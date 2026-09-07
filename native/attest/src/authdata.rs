//! WebAuthn authenticator data (rpIdHash | flags | signCount | AAGUID | credentialId | COSE key) and the
//! COSE-key comparison that binds the credential to the attested certificate.

use ciborium::value::Value;
use p256::ecdsa::VerifyingKey as P256Key;
use rsa::pkcs8::DecodePublicKey;
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
