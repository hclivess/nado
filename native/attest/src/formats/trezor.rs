//! `trezor` — Trezor Safe device authentication (Safe 3 / Safe 5 / Safe 7), doc/device-attestation.md §Hardware.
//!
//! The wallet sends `AuthenticateDevice{challenge}` over USB; the device's secure element (Optiga) signs
//! `compact_size(len("AuthenticateDevice:")) || "AuthenticateDevice:" || compact_size(len(challenge)) || challenge`
//! with its per-device key and returns its X.509 certificate chain: device certificate (subject CN "<model> <serial>",
//! serialNumber) → Trezor CA certificate(s) → signed by a bare P-256 ROOT PUBLIC KEY that Trezor publishes per
//! model (trezorlib.authentication.ROOT_PUBLIC_KEYS). No root certificate exists — the root is a key, pinned in
//! protocol and passed to this kernel as a `0x01 || SEC1(65)` entry of the roots blob.
//!
//! attStmt: { x5c: [device cert DER, CA cert DER, ...], sig: DER ECDSA(P-256, SHA-256) over the message above }.
//! Per-device binding key (ops/device_attest.device_binding_key): sha256(x5c[0]) — the device certificate.

use crate::chain::{digest, sig_hash_of, verify_with_cert, verify_with_p256_key, Hash};
use crate::formats::{cbor_get, cbor_bytes};
use crate::Out;
use ciborium::value::Value;
use sha2::{Digest, Sha256};
use x509_parser::prelude::*;

const HEADER: &[u8] = b"AuthenticateDevice:";
/// Model prefixes of the device certificate's common name (trezorlib checks `internal_name + " "`).
const MODELS: [&str; 4] = ["T2B1", "T3B1", "T3T1", "T3W1"];

pub fn challenge_message(challenge: &[u8]) -> Vec<u8> {
    // compact_size: one byte below 253 — both lengths are far below that (19 and 32)
    let mut m = Vec::with_capacity(2 + HEADER.len() + challenge.len());
    m.push(HEADER.len() as u8);
    m.extend_from_slice(HEADER);
    m.push(challenge.len() as u8);
    m.extend_from_slice(challenge);
    m
}

pub fn verify(st: &[(Value, Value)], challenge: &[u8], roots: &[Vec<u8>], now: i64, out: &mut Out) -> Result<(), String> {
    let x5c: Vec<Vec<u8>> = match cbor_get(st, "x5c") {
        Some(Value::Array(items)) => items.iter().filter_map(|i| if let Value::Bytes(b) = i { Some(b.clone()) } else { None }).collect(),
        _ => return Err("trezor: attStmt has no x5c".into()),
    };
    let sig = cbor_bytes(st, "sig").ok_or("trezor: attStmt has no sig")?;
    if x5c.len() < 2 {
        return Err("trezor: chain needs the device certificate and at least one CA certificate".into());
    }
    if challenge.len() > 200 {
        return Err("trezor: challenge too long".into());
    }
    let parsed: Vec<X509Certificate> = x5c
        .iter()
        .map(|d| X509Certificate::from_der(d).map(|(_, c)| c).map_err(|e| format!("trezor: x5c parse: {e}")))
        .collect::<Result<_, _>>()?;
    // 1. the device key signed OUR challenge (P-256 / SHA-256, DER)
    let msg = challenge_message(challenge);
    if !verify_with_cert(&parsed[0], &msg, &sig, Hash::S256) {
        return Err("trezor: challenge signature does not verify against the device certificate".into());
    }
    // 2. the device certificate names a model and carries a serial number
    let leaf = &parsed[0];
    let cn = leaf.subject().iter_common_name().next().and_then(|a| a.as_str().ok()).unwrap_or("");
    let model = MODELS.iter().find(|m| cn.starts_with(&format!("{m} "))).ok_or_else(|| format!("trezor: device certificate CN '{cn}' names no known model"))?;
    let has_serial = leaf.subject().iter_by_oid(&oid_registry::OID_X509_SERIALNUMBER).next().is_some();
    if !has_serial {
        return Err("trezor: device certificate has no serialNumber".into());
    }
    out.aaguid = model.to_string();
    out.cred_id = crate::hex(&Sha256::digest(&x5c[0]));
    // 3. the chain: each link signed by the next, CA links are CAs, validity at the anchor time, the last link
    //    signed by a pinned Trezor root KEY
    let keys: Vec<&[u8]> = roots.iter().filter(|r| r.len() == 66 && r[0] == 0x01).map(|r| &r[1..]).collect();
    if keys.is_empty() {
        return Err("trezor: no Trezor root keys pinned".into());
    }
    for (i, c) in parsed.iter().enumerate() {
        out.chain.push(c.subject().to_string());
        let nb = c.validity().not_before.timestamp();
        let na = c.validity().not_after.timestamp();
        if now < nb || now > na {
            return Err(format!("trezor: x5c[{i}] outside validity"));
        }
        if i > 0 && !c.is_ca() {
            return Err(format!("trezor: x5c[{i}] is not a CA"));
        }
        let tbs = c.tbs_certificate.as_ref();
        let csig = c.signature_value.as_ref();
        let hash = sig_hash_of(c).ok_or_else(|| format!("trezor: x5c[{i}] unsupported signature algorithm"))?;
        if i + 1 < parsed.len() {
            if c.issuer() != parsed[i + 1].subject() {
                return Err(format!("trezor: x5c[{i}] issuer does not match x5c[{}] subject", i + 1));
            }
            if !verify_with_cert(&parsed[i + 1], tbs, csig, hash) {
                return Err(format!("trezor: x5c[{i}] signature does not verify against its issuer"));
            }
        } else {
            if hash != Hash::S256 {
                return Err("trezor: the CA certificate must be signed with ecdsa-with-SHA256".into());
            }
            let d = digest(Hash::S256, tbs);
            match keys.iter().find(|k| verify_with_p256_key(k, &d, csig)) {
                Some(k) => {
                    out.root_sha256 = crate::hex(&Sha256::digest(k));
                    out.security_level = 2;
                    return Ok(());
                }
                None => return Err("trezor: the CA certificate is not signed by a pinned Trezor root key".into()),
            }
        }
    }
    Err("trezor: chain did not reach a root".into())
}
