//! Certificate-chain verification against the pinned roots, and the per-link signature check:
//! ECDSA P-256 / P-384 or RSA PKCS#1 v1.5, with the hash the SIGNED certificate names (SHA-1/256/384/512).

use crate::Out;
use p256::ecdsa::{Signature as P256Sig, VerifyingKey as P256Key};
use rsa::pkcs1v15::{Signature as RsaSig, VerifyingKey as RsaKey};
use rsa::pkcs8::DecodePublicKey;
use rsa::signature::Verifier as _;
use sha2::{Digest, Sha256};
use x509_parser::prelude::*;

#[derive(Clone, Copy, PartialEq)]
pub enum Hash {
    S1,
    S256,
    S384,
    S512,
}

/// The hash named by a certificate's signatureAlgorithm OID (ecdsa-with-SHA2xx / sha2xxWithRSAEncryption).
pub fn sig_hash_of(cert: &X509Certificate) -> Option<Hash> {
    match cert.signature_algorithm.algorithm.to_id_string().as_str() {
        "1.2.840.10045.4.3.2" | "1.2.840.113549.1.1.11" => Some(Hash::S256),
        "1.2.840.10045.4.3.3" | "1.2.840.113549.1.1.12" => Some(Hash::S384),
        "1.2.840.10045.4.3.4" | "1.2.840.113549.1.1.13" => Some(Hash::S512),
        "1.2.840.113549.1.1.5" => Some(Hash::S1),
        _ => None,
    }
}

/// The hash a COSE algorithm identifier implies (ES256/RS256 = -7/-257, ES384/RS384 = -35/-258, ES512/RS512 = -36/-259, RS1 = -65535).
pub fn hash_of_cose_alg(alg: i128) -> Option<Hash> {
    match alg {
        -7 | -257 => Some(Hash::S256),
        -35 | -258 => Some(Hash::S384),
        -36 | -259 => Some(Hash::S512),
        -65535 => Some(Hash::S1),
        _ => None,
    }
}

pub fn digest(h: Hash, msg: &[u8]) -> Vec<u8> {
    match h {
        Hash::S1 => sha1::Sha1::digest(msg).to_vec(),
        Hash::S256 => Sha256::digest(msg).to_vec(),
        Hash::S384 => sha2::Sha384::digest(msg).to_vec(),
        Hash::S512 => sha2::Sha512::digest(msg).to_vec(),
    }
}

/// Verify `sig` over `msg` with the SubjectPublicKeyInfo of `signer`. Real Google chains mix P-256/SHA-256
/// leaves with P-384/SHA-384 intermediates; Microsoft AIK chains are RSA; some TPMs sign with RS1.
pub fn verify_with_cert(signer: &X509Certificate, msg: &[u8], sig: &[u8], hash: Hash) -> bool {
    use ecdsa::signature::hazmat::PrehashVerifier;
    let spki_der = signer.public_key().raw;
    let d = digest(hash, msg);
    if let Ok(k) = P256Key::from_public_key_der(spki_der) {
        return match P256Sig::from_der(sig) {
            Ok(s) => k.verify_prehash(&d, &s).is_ok(),
            Err(_) => false,
        };
    }
    if let Ok(k) = p384::ecdsa::VerifyingKey::from_public_key_der(spki_der) {
        return match p384::ecdsa::Signature::from_der(sig) {
            Ok(s) => k.verify_prehash(&d, &s).is_ok(),
            Err(_) => false,
        };
    }
    if let Ok(k) = rsa::RsaPublicKey::from_public_key_der(spki_der) {
        let s = match RsaSig::try_from(sig) {
            Ok(s) => s,
            Err(_) => return false,
        };
        return match hash {
            Hash::S1 => RsaKey::<sha1::Sha1>::new(k).verify(msg, &s).is_ok(),
            Hash::S256 => RsaKey::<Sha256>::new(k).verify(msg, &s).is_ok(),
            Hash::S384 => RsaKey::<sha2::Sha384>::new(k).verify(msg, &s).is_ok(),
            Hash::S512 => RsaKey::<sha2::Sha512>::new(k).verify(msg, &s).is_ok(),
        };
    }
    false
}

/// ECDSA P-256 over a PREHASHED message with a bare SEC1 public key (65-byte uncompressed point) — the Trezor
/// roots are keys, not certificates.
pub fn verify_with_p256_key(key_sec1: &[u8], prehash: &[u8], sig_der: &[u8]) -> bool {
    use ecdsa::signature::hazmat::PrehashVerifier;
    match (P256Key::from_sec1_bytes(key_sec1), P256Sig::from_der(sig_der)) {
        (Ok(k), Ok(s)) => k.verify_prehash(prehash, &s).is_ok(),
        _ => false,
    }
}

/// The roots blob carries three kinds of entries: DER certificates (first byte 0x30), `0x01 || SEC1` P-256 keys
/// (Trezor roots) and `0x02 || SEC1` secp256k1 keys (Ledger issuer). Certificate walks must only see the first.
pub fn cert_roots(roots: &[Vec<u8>]) -> Vec<Vec<u8>> {
    roots.iter().filter(|r| r.first() == Some(&0x30)).cloned().collect()
}

/// Walk x5c[0] (leaf) up to a pinned root. Every link's signature is checked; the chain ends when a
/// certificate's DER SHA-256 is a pinned root, OR when the last certificate is signed by a pinned root
/// (Apple omits the root). Records the root reached in `out.root_sha256`.
pub fn verify_chain(x5c: &[Vec<u8>], roots: &[Vec<u8>], now: i64, out: &mut Out) -> Result<(), String> {
    if x5c.is_empty() {
        return Err("empty x5c".into());
    }
    let roots = cert_roots(roots);           // bare vendor KEYS ride in the same blob; they are not certificates
    let roots = &roots[..];
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
            out.root_sha256 = crate::hex(&fp);
            return Ok(()); // reached a pinned root; the links below it were already verified
        }
        let tbs = c.tbs_certificate.as_ref();
        let sig = c.signature_value.as_ref();
        let hash = sig_hash_of(c).ok_or_else(|| format!("x5c[{i}] unsupported signature algorithm"))?;
        if i + 1 < parsed.len() {
            if !verify_with_cert(&parsed[i + 1], tbs, sig, hash) {
                return Err(format!("x5c[{i}] signature does not verify against its issuer"));
            }
        } else {
            match roots.iter().zip(root_certs.iter()).find(|(_, r)| verify_with_cert(r, tbs, sig, hash)) {
                Some((rd, _)) => {
                    out.root_sha256 = crate::hex(&Sha256::digest(rd));
                    return Ok(()); // last link signed by a pinned root
                }
                None => return Err(format!("x5c[{i}] signature does not verify against its issuer")),
            }
        }
    }
    Ok(())
}

/// Raw value of the certificate extension with dotted `oid`, if present.
pub fn ext_value<'a>(cert: &'a X509Certificate, oid: &str) -> Option<&'a [u8]> {
    let parts: Vec<u64> = oid.split('.').filter_map(|p| p.parse().ok()).collect();
    let want = oid_registry::Oid::from(&parts[..]).ok()?;
    cert.extensions().iter().find(|e| e.oid == want).map(|e| e.value)
}
