//! Apple Anonymous Attestation (`apple`): the leaf certificate's nonce extension (1.2.840.113635.100.8.2)
//! must equal sha256(authData || sha256(clientDataJSON)), and the leaf's key IS the credential key.

use super::{signed_message, Ctx};
use crate::authdata::cose_p256_matches;
use crate::chain::ext_value;
use crate::Out;
use sha2::{Digest, Sha256};

const NONCE_OID: &str = "1.2.840.113635.100.8.2";

/// SEQUENCE { [1] EXPLICIT OCTET STRING nonce }
pub fn nonce_from_ext(ext: &[u8]) -> Option<Vec<u8>> {
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

pub fn verify(c: &Ctx, _out: &mut Out) -> Result<(), String> {
    let expect: [u8; 32] = Sha256::digest(signed_message(c)).into();
    let got = ext_value(c.leaf, NONCE_OID).and_then(nonce_from_ext);
    if got.as_deref() != Some(&expect[..]) {
        return Err("apple nonce mismatch".into());
    }
    if !cose_p256_matches(&c.a.cred_pubkey_cose, c.leaf) {
        return Err("credential key != leaf certificate key".into());
    }
    Ok(())
}
