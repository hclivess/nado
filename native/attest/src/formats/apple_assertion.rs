//! Apple App Attest ASSERTION (`apple-assertion`, doc/apple-app-attest.md): a later statement by an ALREADY-ATTESTED
//! App Attest key (renewal with proof of presence, or a rebind to another account). No certificate chain — the key's
//! genuineness was proven by its attestation, and the caller (consensus) requires the key's devbind row to exist.
//! attStmt = {sig: DER ECDSA-P256-SHA256, authData: rpIdHash(32) || flags(1) || counter(4), pub: X9.62 point(65)}.
//! Apple: nonce = sha256(authenticatorData || clientDataHash); the signature is over `nonce` (ECDSA hashes it again).
//! clientDataHash = sha256(clientDataJSON) — the app passes exactly that hash to generateAssertion.

use super::cbor_bytes;
use crate::{hex, Out};
use base64::Engine;
use ciborium::value::Value;
use p256::ecdsa::{signature::Verifier, Signature, VerifyingKey};
use sha2::{Digest, Sha256};

pub fn verify(st: &[(Value, Value)], cdj: &[u8], challenge: &[u8], rp_ids: &[String], out: &mut Out) -> Result<(), String> {
    let sig = cbor_bytes(st, "sig").ok_or("assertion has no sig")?;
    let ad = cbor_bytes(st, "authData").ok_or("assertion has no authData")?;
    let pubp = cbor_bytes(st, "pub").ok_or("assertion has no pub")?;
    if ad.len() < 37 {
        return Err("assertion authData too short".into());
    }
    if pubp.len() != 65 || pubp[0] != 0x04 {
        return Err("assertion pub is not an uncompressed P-256 point".into());
    }
    if !rp_ids.iter().any(|r| Sha256::digest(r.as_bytes()).as_slice() == &ad[..32]) {
        return Err("assertion rpIdHash does not match an accepted App ID".into());
    }
    let cd: serde_json::Value = serde_json::from_slice(cdj).map_err(|_| "clientDataJSON is not JSON".to_string())?;
    if cd.get("type").and_then(|t| t.as_str()) != Some("nado.app") {
        return Err("clientData.type is not nado.app".into());
    }
    let chal_b64 = cd.get("challenge").and_then(|c| c.as_str()).unwrap_or("");
    let chal = base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(chal_b64).map_err(|_| "challenge is not base64url".to_string())?;
    if chal != challenge {
        return Err("challenge mismatch".into());
    }
    let cdh: [u8; 32] = Sha256::digest(cdj).into();
    let mut msg = ad.clone();
    msg.extend_from_slice(&cdh);
    let nonce: [u8; 32] = Sha256::digest(&msg).into();
    let key = VerifyingKey::from_sec1_bytes(&pubp).map_err(|_| "assertion pub is not a valid P-256 key".to_string())?;
    let sig = Signature::from_der(&sig).map_err(|_| "assertion signature is not DER".to_string())?;
    key.verify(&nonce, &sig).map_err(|_| "assertion signature invalid".to_string())?;
    let kid: [u8; 32] = Sha256::digest(&pubp).into();
    out.cred_id = hex(&kid);
    out.aaguid = hex(&ad[32..37]);   // flags || counter, for the record
    Ok(())
}
