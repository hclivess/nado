//! WebAuthn authenticator data (rpIdHash | flags | signCount | AAGUID | credentialId | COSE key) and the
//! COSE-key comparison that binds the credential to the attested certificate.

use ciborium::value::Value;
use p256::ecdsa::{Signature as P256Sig, VerifyingKey as P256Key};
use rsa::pkcs1v15::{Signature as RsaSig, VerifyingKey as RsaKey};
use rsa::pkcs8::DecodePublicKey;
use rsa::signature::Verifier as _;
use rsa::{BigUint, RsaPublicKey};
use sha2::{Digest, Sha256};
use x509_parser::prelude::*;

pub struct AuthData {
    pub rp_id_hash: Vec<u8>,
    pub flags: u8,
    pub aaguid: Vec<u8>,
    pub cred_id: Vec<u8>,
    pub cred_pubkey_cose: Vec<u8>,
}

pub fn parse_auth_data(ad: &[u8]) -> Result<AuthData, &'static str> {
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

/// Decoded COSE_Key map (integer labels), or None.
pub fn cose_map(cose: &[u8]) -> Option<Vec<(Value, Value)>> {
    match ciborium::de::from_reader(cose) {
        Ok(Value::Map(m)) => Some(m),
        _ => None,
    }
}

pub fn cose_get<'a>(m: &'a [(Value, Value)], label: i64) -> Option<&'a Value> {
    m.iter()
        .find(|(k, _)| matches!(k, Value::Integer(i) if i128::from(*i) == label as i128))
        .map(|(_, v)| v)
}

/// COSE EC2 P-256 credential key {-2: x, -3: y} equals the certificate's public key.
pub fn cose_p256_matches(cose: &[u8], cert: &X509Certificate) -> bool {
    let m = match cose_map(cose) {
        Some(m) => m,
        None => return false,
    };
    let (x, y) = match (cose_get(&m, -2), cose_get(&m, -3)) {
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


/// Verify `sig` over `msg` with a COSE_Key — the credential a statement bound, signing a later ASSERTION
/// (protocol.LEASE_ASSERT_CLASSES: the signature renewal). ES256 (kty 2 / P-256 / alg -7, DER signature) and RS256
/// (kty 3 / alg -257, PKCS#1 v1.5 over SHA-256) — the two algorithms the wallet offers at create(). Returns the
/// algorithm name it verified with.
pub fn verify_cose_signature(cose: &[u8], msg: &[u8], sig: &[u8]) -> Result<&'static str, String> {
    let m = cose_map(cose).ok_or_else(|| "credential is not a COSE key".to_string())?;
    let int = |label: i64| -> Option<i128> {
        match cose_get(&m, label) { Some(Value::Integer(i)) => Some(i128::from(*i)), _ => None }
    };
    let bytes = |label: i64| -> Option<Vec<u8>> {
        match cose_get(&m, label) { Some(Value::Bytes(b)) => Some(b.clone()), _ => None }
    };
    match (int(1), int(3)) {
        (Some(2), Some(-7)) => {
            use ecdsa::signature::hazmat::PrehashVerifier;
            if int(-1) != Some(1) {
                return Err("ES256 credential is not on P-256".into());
            }
            let (x, y) = match (bytes(-2), bytes(-3)) { (Some(x), Some(y)) => (x, y), _ => return Err("EC2 key lacks x/y".into()) };
            let mut pt = vec![0x04u8];
            pt.extend_from_slice(&x);
            pt.extend_from_slice(&y);
            let k = P256Key::from_sec1_bytes(&pt).map_err(|_| "EC2 key is not a valid P-256 point".to_string())?;
            let s = P256Sig::from_der(sig).map_err(|_| "ES256 signature is not DER".to_string())?;
            let d = Sha256::digest(msg);
            k.verify_prehash(&d, &s).map(|_| "ES256").map_err(|_| "ES256 signature does not verify".to_string())
        }
        (Some(3), Some(-257)) => {
            let (n, e) = match (bytes(-1), bytes(-2)) { (Some(n), Some(e)) => (n, e), _ => return Err("RSA key lacks n/e".into()) };
            let k = RsaPublicKey::new(BigUint::from_bytes_be(&n), BigUint::from_bytes_be(&e))
                .map_err(|_| "RSA key is not valid".to_string())?;
            let s = RsaSig::try_from(sig).map_err(|_| "RS256 signature is malformed".to_string())?;
            RsaKey::<Sha256>::new(k).verify(msg, &s).map(|_| "RS256").map_err(|_| "RS256 signature does not verify".to_string())
        }
        (kty, alg) => Err(format!("unsupported credential algorithm (kty {kty:?}, alg {alg:?})")),
    }
}
