//! Apple App Attest (`apple-appattest`, doc/apple-app-attest.md): the NADO iOS/macOS app's Secure-Enclave key,
//! attested by Apple's App Attest service. Same nonce extension as the WebAuthn `apple` format — the app passes
//! clientDataHash = sha256(clientDataJSON), so nonce = sha256(authData || sha256(cdj)) exactly like WebAuthn — plus
//! Apple's own rules: production aaguid, counter 0, credentialId == sha256(leaf public key, X9.62 uncompressed),
//! and the leaf key IS the credential key. The rpIdHash is the APP ID hash (checked by the caller's rp id list,
//! which for this format is the protocol's pinned App IDs only — any developer's app chains to the same Apple root).
//! The chain (credCert -> Apple App Attestation CA 1) was walked to the pinned App Attest root before this runs.

use super::{signed_message, Ctx};
use crate::authdata::cose_p256_matches;
use crate::chain::ext_value;
use crate::formats::apple::nonce_from_ext;
use crate::Out;
use p256::ecdsa::VerifyingKey as P256Key;
use rsa::pkcs8::DecodePublicKey;
use sha2::{Digest, Sha256};

const NONCE_OID: &str = "1.2.840.113635.100.8.2";
pub const AAGUID_PRODUCTION: &[u8; 16] = b"appattest\0\0\0\0\0\0\0";

/// The leaf certificate's P-256 public key as an X9.62 uncompressed point (65 bytes).
pub fn leaf_point(c: &Ctx) -> Result<Vec<u8>, String> {
    let k = P256Key::from_public_key_der(c.leaf.public_key().raw).map_err(|_| "leaf key is not P-256".to_string())?;
    Ok(k.to_encoded_point(false).as_bytes().to_vec())
}

pub fn verify(c: &Ctx, _out: &mut Out) -> Result<(), String> {
    let expect: [u8; 32] = Sha256::digest(signed_message(c)).into();
    let got = ext_value(c.leaf, NONCE_OID).and_then(nonce_from_ext);
    if got.as_deref() != Some(&expect[..]) {
        return Err("app attest nonce mismatch".into());
    }
    if c.a.aaguid.as_slice() != &AAGUID_PRODUCTION[..] {
        return Err("app attest aaguid is not the production environment".into());
    }
    if c.a.counter != 0 {
        return Err("app attest counter is not 0".into());
    }
    let point = leaf_point(c)?;
    let kid: [u8; 32] = Sha256::digest(&point).into();
    if c.a.cred_id.as_slice() != &kid[..] {
        return Err("app attest credentialId != sha256(leaf public key)".into());
    }
    if !cose_p256_matches(&c.a.cred_pubkey_cose, c.leaf) {
        return Err("credential key != leaf certificate key".into());
    }
    Ok(())
}
