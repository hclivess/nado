//! `ledger` — Ledger device genuineness (Nano S / S Plus / X / Stax / Flex), doc/device-attestation.md §Hardware.
//!
//! Every Ledger holds a per-device secp256k1 key whose public key was signed at the factory by Ledger's ISSUER key
//! (the "Issuer certificate"). The secure-channel handshake (ledgerblue.deployed.getDeployedSecretV2 /
//! ledgerblue.checkGenuine) makes the device prove possession of that key: after the host presents its own
//! (self-signed, "unsafe manager" — the user confirms ON THE DEVICE, that is the tap) certificate, the device
//! returns two certificates over APDU E0 52:
//!   cert0: [hdrLen][header][pubLen][devicePub][sigLen][sig]  sig = ECDSA_secp256k1(SHA-256(0x02 || header || devicePub)) by the ISSUER
//!   cert1: [hdrLen][header][pubLen][ephPub][sigLen][sig]     sig = ECDSA_secp256k1(SHA-256(0x12 || deviceNonce || hostNonce || ephPub)) by devicePub
//! The wallet sets hostNonce = challenge[..8] (INITIALIZE_AUTHENTICATION E0 50), so cert1 binds the device key to
//! this registration's challenge; cert0 binds the device key to Ledger. The issuer key is pinned in protocol
//! (ledgerblue's DEFAULT_ISSUER_KEY) and passed as a `0x02 || SEC1(65)` entry of the roots blob.
//!
//! attStmt: { target_id: 4 bytes, batch: 4 bytes, host_nonce: 8, device_nonce: 8, cert0: bytes, cert1: bytes }.
//! Per-device binding key: sha256(devicePub) — permanent for the life of the device.

use crate::formats::cbor_bytes;
use crate::Out;
use ciborium::value::Value;
use k256::ecdsa::{Signature as KSig, VerifyingKey as KKey};
use sha2::{Digest, Sha256};

pub struct Cert {
    pub header: Vec<u8>,
    pub pubkey: Vec<u8>,
    pub sig: Vec<u8>,
}

/// The device's certificate layout: length-prefixed header, public key and signature.
pub fn parse_cert(b: &[u8]) -> Result<Cert, String> {
    let mut o = 0usize;
    let mut take = |what: &str| -> Result<Vec<u8>, String> {
        let n = *b.get(o).ok_or_else(|| format!("ledger: certificate truncated at {what} length"))? as usize;
        o += 1;
        let v = b.get(o..o + n).ok_or_else(|| format!("ledger: certificate truncated in {what}"))?.to_vec();
        o += n;
        Ok(v)
    };
    let header = take("header")?;
    let pubkey = take("public key")?;
    let sig = take("signature")?;
    if o != b.len() {
        return Err("ledger: trailing bytes after certificate".into());
    }
    if pubkey.len() != 65 || pubkey[0] != 0x04 {
        return Err("ledger: certificate public key is not an uncompressed secp256k1 point".into());
    }
    Ok(Cert { header, pubkey, sig })
}

fn verify_k256(pub_sec1: &[u8], msg: &[u8], sig_der: &[u8]) -> bool {
    use ecdsa::signature::hazmat::PrehashVerifier;
    let k = match KKey::from_sec1_bytes(pub_sec1) {
        Ok(k) => k,
        Err(_) => return false,
    };
    let s = match KSig::from_der(sig_der) {
        Ok(s) => s,
        Err(_) => return false,
    };
    // libsecp256k1 emits low-S; accept either form by normalising (verification semantics are unchanged)
    let s = s.normalize_s().unwrap_or(s);
    k.verify_prehash(&Sha256::digest(msg), &s).is_ok()
}

pub fn verify(st: &[(Value, Value)], challenge: &[u8], roots: &[Vec<u8>], out: &mut Out) -> Result<(), String> {
    let target_id = cbor_bytes(st, "target_id").ok_or("ledger: no target_id")?;
    let batch = cbor_bytes(st, "batch").unwrap_or_default();
    let host_nonce = cbor_bytes(st, "host_nonce").ok_or("ledger: no host_nonce")?;
    let device_nonce = cbor_bytes(st, "device_nonce").ok_or("ledger: no device_nonce")?;
    let c0 = cbor_bytes(st, "cert0").ok_or("ledger: no cert0")?;
    let c1 = cbor_bytes(st, "cert1").ok_or("ledger: no cert1")?;
    if target_id.len() != 4 || host_nonce.len() != 8 || device_nonce.len() != 8 {
        return Err("ledger: target_id/host_nonce/device_nonce have the wrong length".into());
    }
    if challenge.len() < 8 || host_nonce[..] != challenge[..8] {
        return Err("ledger: host nonce is not the registration challenge".into());
    }
    let cert0 = parse_cert(&c0)?;
    let cert1 = parse_cert(&c1)?;
    // 1. cert0: the device key is certified by Ledger's issuer key
    let issuers: Vec<&[u8]> = roots.iter().filter(|r| r.len() == 66 && r[0] == 0x02).map(|r| &r[1..]).collect();
    if issuers.is_empty() {
        return Err("ledger: no Ledger issuer key pinned".into());
    }
    let mut m0 = vec![0x02u8];
    m0.extend_from_slice(&cert0.header);
    m0.extend_from_slice(&cert0.pubkey);
    let issuer = issuers.iter().find(|k| verify_k256(k, &m0, &cert0.sig)).ok_or("ledger: device certificate is not signed by a pinned Ledger issuer key")?;
    // 2. cert1: the device key signed the ephemeral key together with BOTH nonces (ours is the challenge)
    let mut m1 = vec![0x12u8];
    m1.extend_from_slice(&device_nonce);
    m1.extend_from_slice(&host_nonce);
    m1.extend_from_slice(&cert1.pubkey);
    if !verify_k256(&cert0.pubkey, &m1, &cert1.sig) {
        return Err("ledger: ephemeral certificate is not signed by the device key over the nonces".into());
    }
    out.root_sha256 = crate::hex(&Sha256::digest(issuer));
    out.aaguid = crate::hex(&target_id);
    out.cred_id = crate::hex(&Sha256::digest(&cert0.pubkey));
    out.tpm_manufacturer = crate::hex(&batch);
    out.chain.push(format!("ledger device {} (target {})", crate::hex(&cert0.pubkey[1..9]), crate::hex(&target_id)));
    out.security_level = 2;
    Ok(())
}
