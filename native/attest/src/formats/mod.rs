//! One module per accepted attestation format. Each `verify` runs AFTER the common checks (CBOR shape,
//! authenticator data, rp id, challenge) and after the x5c chain reached a pinned root; it returns Ok(()) or
//! the reason to refuse, and may fill format-specific verdict fields on `out`.

pub mod android_key;
pub mod apple;
pub mod packed;
pub mod tpm;

use crate::authdata::AuthData;
use ciborium::value::Value;
use x509_parser::prelude::*;

/// What every format gets: the attStmt map, authData bytes, sha256(clientDataJSON), the parsed authData and
/// the leaf certificate (x5c[0]).
pub struct Ctx<'a> {
    pub st: &'a [(Value, Value)],
    pub ad: &'a [u8],
    pub cdj_hash: [u8; 32],
    pub a: &'a AuthData,
    pub leaf: &'a X509Certificate<'a>,
}

pub fn cbor_get<'a>(m: &'a [(Value, Value)], key: &str) -> Option<&'a Value> {
    m.iter().find(|(k, _)| matches!(k, Value::Text(t) if t == key)).map(|(_, v)| v)
}

pub fn cbor_bytes(m: &[(Value, Value)], key: &str) -> Option<Vec<u8>> {
    match cbor_get(m, key) {
        Some(Value::Bytes(b)) => Some(b.clone()),
        _ => None,
    }
}

pub fn cbor_int(m: &[(Value, Value)], key: &str) -> Option<i128> {
    match cbor_get(m, key) {
        Some(Value::Integer(i)) => Some(i128::from(*i)),
        _ => None,
    }
}

/// authData || sha256(clientDataJSON): the message every attestation signature covers.
pub fn signed_message(c: &Ctx) -> Vec<u8> {
    let mut msg = c.ad.to_vec();
    msg.extend_from_slice(&c.cdj_hash);
    msg
}
