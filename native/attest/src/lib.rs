//! Device attestation verifier — doc/device-attestation.md.
//!
//! verify(attestationObject, clientDataJSON, expected_challenge, pinned_roots_der, now_unix)
//!   -> JSON {"ok": bool, "fmt": str, "aaguid": hex, "cred_id": hex, "reason": str, "chain": [subjects]}
//! Deterministic: same bytes + same roots + same time -> same answer on every node. No network, no clock
//! other than the caller's (the block timestamp), no revocation fetch.

use base64::Engine;
use ciborium::value::Value;
use p256::ecdsa::{Signature as P256Sig, VerifyingKey as P256Key};
use rsa::pkcs1v15::{Signature as RsaSig, VerifyingKey as RsaKey};
use rsa::pkcs8::DecodePublicKey;
use rsa::signature::Verifier as _;
use p384::pkcs8::DecodePublicKey as _;
use sha2::{Digest, Sha256};
use std::os::raw::c_char;
use x509_parser::prelude::*;

const OID_APPLE_NONCE: &str = "1.2.840.113635.100.8.2";
const OID_ANDROID_KEYDESC: &str = "1.3.6.1.4.1.11129.2.1.17";

#[derive(serde::Serialize, Default)]
struct Out {
    ok: bool,
    fmt: String,
    aaguid: String,
    cred_id: String,
    reason: String,
    chain: Vec<String>,
    security_level: i64,
}

fn fail(mut o: Out, why: &str) -> Out {
    o.ok = false;
    o.reason = why.to_string();
    o
}

fn cbor_get<'a>(m: &'a [(Value, Value)], key: &str) -> Option<&'a Value> {
    m.iter().find(|(k, _)| matches!(k, Value::Text(t) if t == key)).map(|(_, v)| v)
}

struct AuthData {
    rp_id_hash: Vec<u8>,
    flags: u8,
    aaguid: Vec<u8>,
    cred_id: Vec<u8>,
    cred_pubkey_cose: Vec<u8>,
}

fn parse_auth_data(ad: &[u8]) -> Result<AuthData, &'static str> {
    if ad.len() < 37 {
        return Err("authData too short");
    }
    let flags = ad[32];
    if flags & 0x40 == 0 {
        return Err("no attested credential data");
    }
    if ad.len() < 55 {
        return Err("authData truncated before credential");
    }
    let n = u16::from_be_bytes([ad[53], ad[54]]) as usize;
    if ad.len() < 55 + n {
        return Err("credential id truncated");
    }
    Ok(AuthData {
        rp_id_hash: ad[..32].to_vec(),
        flags,
        aaguid: ad[37..53].to_vec(),
        cred_id: ad[55..55 + n].to_vec(),
        cred_pubkey_cose: ad[55 + n..].to_vec(),
    })
}

#[derive(Clone, Copy, PartialEq)]
enum Hash { S256, S384, S512 }

/// The hash named by a certificate's signatureAlgorithm OID (ecdsa-with-SHA2xx / sha2xxWithRSAEncryption).
fn sig_hash_of(cert: &X509Certificate) -> Option<Hash> {
    match cert.signature_algorithm.algorithm.to_id_string().as_str() {
        "1.2.840.10045.4.3.2" | "1.2.840.113549.1.1.11" => Some(Hash::S256),
        "1.2.840.10045.4.3.3" | "1.2.840.113549.1.1.12" => Some(Hash::S384),
        "1.2.840.10045.4.3.4" | "1.2.840.113549.1.1.13" => Some(Hash::S512),
        _ => None,
    }
}

fn digest(h: Hash, msg: &[u8]) -> Vec<u8> {
    match h {
        Hash::S256 => Sha256::digest(msg).to_vec(),
        Hash::S384 => sha2::Sha384::digest(msg).to_vec(),
        Hash::S512 => sha2::Sha512::digest(msg).to_vec(),
    }
}

/// Verify `sig` over `msg` with the SubjectPublicKeyInfo of `signer`: ECDSA on P-256 or P-384, or RSA PKCS#1 v1.5,
/// each with the hash the SIGNED object names (`hash`). Real Google chains mix P-256/SHA-256 leaves with
/// P-384/SHA-384 intermediates (measured on a live sample 2026-09-07).
fn verify_with_cert(signer: &X509Certificate, msg: &[u8], sig: &[u8], hash: Hash) -> bool {
    use ecdsa::signature::hazmat::PrehashVerifier;
    let spki_der = signer.public_key().raw;
    let d = digest(hash, msg);
    if let Ok(k) = P256Key::from_public_key_der(spki_der) {
        return match P256Sig::from_der(sig) { Ok(s) => k.verify_prehash(&d, &s).is_ok(), Err(_) => false };
    }
    if let Ok(k) = p384::ecdsa::VerifyingKey::from_public_key_der(spki_der) {
        return match p384::ecdsa::Signature::from_der(sig) { Ok(s) => k.verify_prehash(&d, &s).is_ok(), Err(_) => false };
    }
    if let Ok(k) = rsa::RsaPublicKey::from_public_key_der(spki_der) {
        let s = match RsaSig::try_from(sig) { Ok(s) => s, Err(_) => return false };
        return match hash {
            Hash::S256 => RsaKey::<Sha256>::new(k).verify(msg, &s).is_ok(),
            Hash::S384 => RsaKey::<sha2::Sha384>::new(k).verify(msg, &s).is_ok(),
            Hash::S512 => RsaKey::<sha2::Sha512>::new(k).verify(msg, &s).is_ok(),
        };
    }
    false
}

/// Walk x5c[0] (leaf) up to a pinned root. Every link's signature is checked; the chain ends when a certificate's
/// DER SHA-256 is a pinned root, OR when the last certificate is signed by a pinned root (Apple omits the root).
fn verify_chain(x5c: &[Vec<u8>], roots: &[Vec<u8>], now: i64, out: &mut Out) -> Result<(), String> {
    if x5c.is_empty() {
        return Err("empty x5c".into());
    }
    let root_fps: Vec<[u8; 32]> = roots.iter().map(|r| Sha256::digest(r).into()).collect();
    let parsed: Vec<X509Certificate> = x5c
        .iter()
        .map(|d| X509Certificate::from_der(d).map(|(_, c)| c).map_err(|e| format!("x5c parse: {e}")))
        .collect::<Result<_, _>>()?;
    let root_certs: Vec<X509Certificate> = roots
        .iter()
        .map(|d| X509Certificate::from_der(d).map(|(_, c)| c).map_err(|e| format!("root parse: {e}")))
        .collect::<Result<_, _>>()?;
    for (i, c) in parsed.iter().enumerate() {
        out.chain.push(c.subject().to_string());
        let nb = c.validity().not_before.timestamp();
        let na = c.validity().not_after.timestamp();
        if now < nb || now > na {
            return Err(format!("x5c[{i}] outside validity"));
        }
        if i > 0 && !c.is_ca() {
            return Err(format!("x5c[{i}] is not a CA"));
        }
        let fp: [u8; 32] = Sha256::digest(&x5c[i]).into();
        if root_fps.contains(&fp) {
            return Ok(()); // reached a pinned root; the links below it were already verified
        }
        let tbs = c.tbs_certificate.as_ref();
        let sig = c.signature_value.as_ref();
        let hash = match sig_hash_of(c) {
            Some(h) => h,
            None => return Err(format!("x5c[{i}] unsupported signature algorithm")),
        };
        let signer_ok = if i + 1 < parsed.len() {
            verify_with_cert(&parsed[i + 1], tbs, sig, hash)
        } else {
            root_certs.iter().any(|r| verify_with_cert(r, tbs, sig, hash))
        };
        if !signer_ok {
            return Err(format!("x5c[{i}] signature does not verify against its issuer"));
        }
        if i + 1 == parsed.len() {
            return Ok(()); // last link signed by a pinned root
        }
    }
    Ok(())
}

fn ext_value<'a>(cert: &'a X509Certificate, oid: &str) -> Option<&'a [u8]> {
    let want = oid_registry::Oid::from(&oid.split('.').map(|p| p.parse::<u64>().unwrap()).collect::<Vec<_>>()[..]).ok()?;
    cert.extensions().iter().find(|e| e.oid == want).map(|e| e.value)
}

/// Apple: SEQUENCE { [1] EXPLICIT OCTET STRING nonce }
fn apple_nonce(ext: &[u8]) -> Option<Vec<u8>> {
    use der_parser::ber::*;
    let (_, seq) = parse_ber_sequence(ext).ok()?;
    let inner = seq.as_sequence().ok()?;
    let tagged = inner.first()?;
    let content = match &tagged.content {
        BerObjectContent::Unknown(any) => any.data,
        _ => return None,
    };
    let (_, os) = parse_ber_octetstring(content).ok()?;
    os.as_slice().ok().map(|s| s.to_vec())
}

/// Android KeyDescription: SEQUENCE { attestationVersion INT, attestationSecurityLevel ENUM, keymasterVersion INT,
/// keymasterSecurityLevel ENUM, attestationChallenge OCTET STRING, ... }
fn android_keydesc(ext: &[u8]) -> Option<(i64, i64, Vec<u8>)> {
    use der_parser::ber::*;
    let (_, seq) = parse_ber_sequence(ext).ok()?;
    let items = seq.as_sequence().ok()?;
    if items.len() < 5 {
        return None;
    }
    // ENUMERATED (the real extension) or INTEGER (some test generators): accept both
    let as_int = |o: &der_parser::ber::BerObject| -> Option<i64> {
        o.as_i64().ok().or_else(|| o.as_u64().ok().map(|u| u as i64))
    };
    let att_level = as_int(&items[1])?;
    let km_level = as_int(&items[3])?;
    let chal = items[4].as_slice().ok()?.to_vec();
    Some((att_level, km_level, chal))
}

fn cose_p256_matches(cose: &[u8], cert: &X509Certificate) -> bool {
    // COSE_Key EC2: {1:2, 3:-7, -1:1, -2:x, -3:y}
    let v: Value = match ciborium::de::from_reader(cose) {
        Ok(v) => v,
        Err(_) => return false,
    };
    let m = match v {
        Value::Map(m) => m,
        _ => return false,
    };
    let get = |k: i64| m.iter().find(|(kk, _)| matches!(kk, Value::Integer(i) if i128::from(*i) == k as i128)).map(|(_, v)| v);
    let (x, y) = match (get(-2), get(-3)) {
        (Some(Value::Bytes(x)), Some(Value::Bytes(y))) => (x, y),
        _ => return false,
    };
    let mut pt = vec![0x04u8];
    pt.extend_from_slice(x);
    pt.extend_from_slice(y);
    match P256Key::from_public_key_der(cert.public_key().raw) {
        Ok(k) => k.to_encoded_point(false).as_bytes() == pt.as_slice(),
        Err(_) => false,
    }
}

fn verify_inner(att: &[u8], cdj: &[u8], challenge: &[u8], roots: &[Vec<u8>], rp_ids: &[String], now: i64) -> Out {
    let mut out = Out::default();
    let v: Value = match ciborium::de::from_reader(att) {
        Ok(v) => v,
        Err(e) => return fail(out, &format!("cbor: {e}")),
    };
    let m = match v {
        Value::Map(m) => m,
        _ => return fail(out, "attestationObject is not a map"),
    };
    let fmt = match cbor_get(&m, "fmt") {
        Some(Value::Text(t)) => t.clone(),
        _ => return fail(out, "no fmt"),
    };
    out.fmt = fmt.clone();
    let ad = match cbor_get(&m, "authData") {
        Some(Value::Bytes(b)) => b.clone(),
        _ => return fail(out, "no authData"),
    };
    let st = match cbor_get(&m, "attStmt") {
        Some(Value::Map(s)) => s.clone(),
        _ => return fail(out, "no attStmt"),
    };
    let a = match parse_auth_data(&ad) {
        Ok(a) => a,
        Err(e) => return fail(out, e),
    };
    out.aaguid = hex(&a.aaguid);
    out.cred_id = hex(&a.cred_id);
    if a.flags & 0x01 == 0 {
        return fail(out, "user not present");
    }
    if !rp_ids.iter().any(|r| Sha256::digest(r.as_bytes()).as_slice() == a.rp_id_hash.as_slice()) {
        return fail(out, "rpIdHash does not match an accepted rp id");
    }
    // client data: type + challenge
    let cd: serde_json::Value = match serde_json::from_slice(cdj) {
        Ok(v) => v,
        Err(_) => return fail(out, "clientDataJSON is not JSON"),
    };
    if cd.get("type").and_then(|t| t.as_str()) != Some("webauthn.create") {
        return fail(out, "clientData.type is not webauthn.create");
    }
    let chal_b64 = cd.get("challenge").and_then(|c| c.as_str()).unwrap_or("");
    let chal = match base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(chal_b64) {
        Ok(c) => c,
        Err(_) => return fail(out, "challenge is not base64url"),
    };
    if chal != challenge {
        return fail(out, "challenge mismatch");
    }
    let cdj_hash: [u8; 32] = Sha256::digest(cdj).into();
    let x5c: Vec<Vec<u8>> = match cbor_get(&st, "x5c") {
        Some(Value::Array(items)) => items.iter().filter_map(|i| if let Value::Bytes(b) = i { Some(b.clone()) } else { None }).collect(),
        _ => return fail(out, "attStmt has no x5c"),
    };
    if x5c.is_empty() {
        return fail(out, "x5c empty");
    }
    if let Err(e) = verify_chain(&x5c, roots, now, &mut out) {
        return fail(out, &e);
    }
    let (_, leaf) = match X509Certificate::from_der(&x5c[0]) {
        Ok(c) => c,
        Err(_) => return fail(out, "leaf parse"),
    };
    match fmt.as_str() {
        "apple" => {
            let mut nonce_in = ad.clone();
            nonce_in.extend_from_slice(&cdj_hash);
            let expect: [u8; 32] = Sha256::digest(&nonce_in).into();
            let got = ext_value(&leaf, OID_APPLE_NONCE).and_then(apple_nonce);
            if got.as_deref() != Some(&expect[..]) {
                return fail(out, "apple nonce mismatch");
            }
            if !cose_p256_matches(&a.cred_pubkey_cose, &leaf) {
                return fail(out, "credential key != leaf certificate key");
            }
        }
        "android-key" => {
            let sig = match cbor_get(&st, "sig") {
                Some(Value::Bytes(b)) => b.clone(),
                _ => return fail(out, "android-key: no sig"),
            };
            let mut msg = ad.clone();
            msg.extend_from_slice(&cdj_hash);
            if !verify_with_cert(&leaf, &msg, &sig, Hash::S256) {
                return fail(out, "android-key: signature does not verify");
            }
            if !cose_p256_matches(&a.cred_pubkey_cose, &leaf) {
                return fail(out, "credential key != leaf certificate key");
            }
            let (att_level, km_level, chal_ext) = match ext_value(&leaf, OID_ANDROID_KEYDESC).and_then(android_keydesc) {
                Some(t) => t,
                None => return fail(out, "android-key: no key description extension"),
            };
            if chal_ext != cdj_hash {
                return fail(out, "android-key: attestationChallenge != clientDataHash");
            }
            // 0 = Software, 1 = TrustedEnvironment, 2 = StrongBox
            if att_level < 1 || km_level < 1 {
                return fail(out, "android-key: software security level");
            }
            out.security_level = att_level.min(km_level);
        }
        _ => return fail(out, "unsupported attestation format"),
    }
    out.ok = true;
    out.reason = "ok".into();
    out
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

/// C ABI. roots: concatenation of (u32 big-endian length || DER) entries. rp_ids: NUL-separated UTF-8.
/// Writes JSON into out (up to out_cap bytes) and returns its length, or -1 on a caller error.
#[no_mangle]
pub extern "C" fn nado_attest_verify(
    att: *const u8, att_len: usize, cdj: *const u8, cdj_len: usize, chal: *const u8, chal_len: usize,
    roots: *const u8, roots_len: usize, rp_ids: *const c_char, now_unix: i64, out: *mut u8, out_cap: usize,
) -> i64 {
    if att.is_null() || cdj.is_null() || chal.is_null() || out.is_null() {
        return -1;
    }
    let att = unsafe { std::slice::from_raw_parts(att, att_len) };
    let cdj = unsafe { std::slice::from_raw_parts(cdj, cdj_len) };
    let chal = unsafe { std::slice::from_raw_parts(chal, chal_len) };
    let roots_raw = if roots.is_null() { &[][..] } else { unsafe { std::slice::from_raw_parts(roots, roots_len) } };
    let mut root_list = Vec::new();
    let mut i = 0usize;
    while i + 4 <= roots_raw.len() {
        let n = u32::from_be_bytes([roots_raw[i], roots_raw[i + 1], roots_raw[i + 2], roots_raw[i + 3]]) as usize;
        i += 4;
        if i + n > roots_raw.len() {
            return -1;
        }
        root_list.push(roots_raw[i..i + n].to_vec());
        i += n;
    }
    let rp_str = if rp_ids.is_null() { String::new() } else { unsafe { std::ffi::CStr::from_ptr(rp_ids) }.to_string_lossy().into_owned() };
    let rp_list: Vec<String> = rp_str.split('\0').filter(|s| !s.is_empty()).map(|s| s.to_string()).collect();
    let o = verify_inner(att, cdj, chal, &root_list, &rp_list, now_unix);
    let js = serde_json::to_vec(&o).unwrap_or_else(|_| b"{\"ok\":false,\"reason\":\"serialize\"}".to_vec());
    let n = js.len().min(out_cap);
    unsafe { std::ptr::copy_nonoverlapping(js.as_ptr(), out, n) };
    n as i64
}
