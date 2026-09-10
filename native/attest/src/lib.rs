//! Device attestation verifier — doc/device-attestation.md.
//!
//! verify(attestationObject, clientDataJSON, expected_challenge, pinned_roots_der, rp_ids, now_unix)
//!   -> JSON {"ok", "fmt", "aaguid", "cred_id", "reason", "chain", "security_level", "root_sha256", "tpm_manufacturer"}
//! Deterministic: same bytes + same roots + same time -> same answer on every node. No network, no clock other
//! than the caller's (the block timestamp), no revocation fetch.
//!
//! Layout: `chain` (certificate chain + signatures), `authdata` (authenticator data + COSE keys), `tpm`
//! (TPM 2.0 structures), `formats::*` (one module per accepted statement format), and this file: the
//! attestation-object parse, the checks every format shares, the dispatch, and the C ABI.

mod authdata;
mod chain;
mod ek;
mod formats;
mod tpm;

use authdata::parse_auth_data;
use base64::Engine;
use chain::verify_chain;
use ciborium::value::Value;
use formats::{cbor_bytes, cbor_get};
use sha2::{Digest, Sha256};
use std::os::raw::c_char;
use x509_parser::prelude::*;

#[derive(serde::Serialize, Default)]
pub struct Out {
    pub ok: bool,
    pub fmt: String,
    pub aaguid: String,
    pub cred_id: String,
    pub reason: String,
    pub chain: Vec<String>,
    pub security_level: i64,
    pub root_sha256: String,
    pub tpm_manufacturer: String,
}

pub fn fail(mut o: Out, why: &str) -> Out {
    o.ok = false;
    o.reason = why.to_string();
    o
}

pub fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
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
    // HARDWARE WALLETS (trezor / ledger): no WebAuthn authenticator data, no rp id — the statement is the vendor's
    // own genuineness protocol carried in attStmt, bound to OUR challenge; clientData.type is "nado.hw".
    if fmt == "trezor" || fmt == "ledger" {
        let st = match cbor_get(&m, "attStmt") {
            Some(Value::Map(s)) => s.clone(),
            _ => return fail(out, "no attStmt"),
        };
        let cd: serde_json::Value = match serde_json::from_slice(cdj) {
            Ok(v) => v,
            Err(_) => return fail(out, "clientDataJSON is not JSON"),
        };
        if cd.get("type").and_then(|t| t.as_str()) != Some("nado.hw") {
            return fail(out, "clientData.type is not nado.hw");
        }
        let chal_b64 = cd.get("challenge").and_then(|c| c.as_str()).unwrap_or("");
        let chal = match base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(chal_b64) {
            Ok(c) => c,
            Err(_) => return fail(out, "challenge is not base64url"),
        };
        if chal != challenge {
            return fail(out, "challenge mismatch");
        }
        let res = match fmt.as_str() {
            "trezor" => formats::trezor::verify(&st, challenge, roots, now, &mut out),
            _ => formats::ledger::verify(&st, challenge, roots, &mut out),
        };
        if let Err(why) = res {
            return fail(out, &why);
        }
        out.ok = true;
        out.reason = "ok".into();
        return out;
    }
    let ad = match cbor_bytes(&m, "authData") {
        Some(b) => b,
        None => return fail(out, "no authData"),
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
    // certificate chain to a pinned root (every format we accept carries one; self-attestation has none)
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
    let ctx = formats::Ctx { st: &st, ad: &ad, cdj_hash, a: &a, leaf: &leaf };
    let res = match fmt.as_str() {
        "apple" => formats::apple::verify(&ctx, &mut out),
        "android-key" => formats::android_key::verify(&ctx, &mut out),
        "packed" => formats::packed::verify(&ctx, &mut out),
        "tpm" => formats::tpm::verify(&ctx, &mut out),
        _ => Err("unsupported attestation format".into()),
    };
    if let Err(why) = res {
        return fail(out, &why);
    }
    out.ok = true;
    out.reason = "ok".into();
    out
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

/// C ABI for endorsement-certificate verification — the vendor's word that a chip is genuine, which is the
/// whole basis of the CA-free attestation path (doc/tpm-attestation-without-a-ca.md). Separate entry point
/// from nado_attest_verify because it answers a different question: not "is this statement valid" but "is this
/// endorsement key one a silicon vendor certified".
///
/// `chain` and `roots` are both concatenations of (u32 big-endian length || DER) entries.
#[no_mangle]
pub extern "C" fn nado_ek_verify(
    chain: *const u8, chain_len: usize, roots: *const u8, roots_len: usize, now_unix: i64,
    out: *mut u8, out_cap: usize,
) -> i64 {
    if out.is_null() {
        return -1;
    }
    let unpack = |p: *const u8, n: usize| -> Vec<Vec<u8>> {
        let raw = if p.is_null() { &[][..] } else { unsafe { std::slice::from_raw_parts(p, n) } };
        let mut v = Vec::new();
        let mut i = 0usize;
        while i + 4 <= raw.len() {
            let l = u32::from_be_bytes([raw[i], raw[i + 1], raw[i + 2], raw[i + 3]]) as usize;
            i += 4;
            if i + l > raw.len() { break; }
            v.push(raw[i..i + l].to_vec());
            i += l;
        }
        v
    };
    let js = match ek::verify_ek(&unpack(chain, chain_len), &unpack(roots, roots_len), now_unix) {
        Ok(e) => serde_json::json!({"ok": true, "ek_identity": e.identity,
                                    "manufacturer": e.manufacturer, "root_sha256": e.root_sha256}),
        Err(why) => serde_json::json!({"ok": false, "reason": why}),
    };
    let js = serde_json::to_vec(&js).unwrap_or_else(|_| b"{\"ok\":false,\"reason\":\"serialize\"}".to_vec());
    let n = js.len().min(out_cap);
    unsafe { std::ptr::copy_nonoverlapping(js.as_ptr(), out, n) };
    n as i64
}

/// Test-only view of ek::verify_ek so integration tests can exercise it without the C ABI.
pub fn ek_verify_for_test(chain: &[Vec<u8>], roots: &[Vec<u8>], now: i64) -> Result<(String, String, String), String> {
    ek::verify_ek(chain, roots, now).map(|e| (e.identity, e.manufacturer, e.root_sha256))
}

/// The endorsement key's SubjectPublicKeyInfo, in DER. The relay needs it to seal a credential and cannot
/// parse the certificate itself — real vendor certificates are not strictly DER.
#[no_mangle]
pub extern "C" fn nado_ek_public(cert: *const u8, cert_len: usize, out: *mut u8, out_cap: usize) -> i64 {
    if cert.is_null() || out.is_null() {
        return -1;
    }
    let der = unsafe { std::slice::from_raw_parts(cert, cert_len) };
    let spki = match X509Certificate::from_der(der) {
        Ok((_, c)) => c.public_key().raw.to_vec(),
        Err(_) => return -1,
    };
    if spki.len() > out_cap {
        return -1;
    }
    unsafe { std::ptr::copy_nonoverlapping(spki.as_ptr(), out, spki.len()) };
    spki.len() as i64
}
