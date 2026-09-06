//! Android Key Attestation (`android-key`): attStmt.sig by the leaf key over authData || sha256(cdj); the
//! key-description extension (1.3.6.1.4.1.11129.2.1.17) carries clientDataHash as the attestation challenge
//! and TrustedEnvironment/StrongBox security levels for both the attestation and the keymaster.

use super::{cbor_bytes, signed_message, Ctx};
use crate::authdata::cose_p256_matches;
use crate::chain::{ext_value, verify_with_cert, Hash};
use crate::Out;

const KEYDESC_OID: &str = "1.3.6.1.4.1.11129.2.1.17";

/// KeyDescription: SEQUENCE { attestationVersion INT, attestationSecurityLevel ENUM, keymasterVersion INT,
/// keymasterSecurityLevel ENUM, attestationChallenge OCTET STRING, ... } -> (attSecLevel, kmSecLevel, challenge)
pub fn key_description(ext: &[u8]) -> Option<(i64, i64, Vec<u8>)> {
    use der_parser::ber::*;
    let (_, seq) = parse_ber_sequence(ext).ok()?;
    let items = seq.as_sequence().ok()?;
    if items.len() < 5 {
        return None;
    }
    let as_int = |o: &BerObject| -> Option<i64> { o.as_i64().ok().or_else(|| o.as_u64().ok().map(|u| u as i64)) };
    Some((as_int(&items[1])?, as_int(&items[3])?, items[4].as_slice().ok()?.to_vec()))
}

pub fn verify(c: &Ctx, out: &mut Out) -> Result<(), String> {
    let sig = cbor_bytes(c.st, "sig").ok_or("android-key: no sig")?;
    if !verify_with_cert(c.leaf, &signed_message(c), &sig, Hash::S256) {
        return Err("android-key: signature does not verify".into());
    }
    if !cose_p256_matches(&c.a.cred_pubkey_cose, c.leaf) {
        return Err("credential key != leaf certificate key".into());
    }
    let (att_level, km_level, chal) = ext_value(c.leaf, KEYDESC_OID)
        .and_then(key_description)
        .ok_or("android-key: no key description extension")?;
    if chal != c.cdj_hash {
        return Err("android-key: attestationChallenge != clientDataHash".into());
    }
    if att_level < 1 || km_level < 1 {
        return Err("android-key: software security level".into()); // 0 Software, 1 TrustedEnvironment, 2 StrongBox
    }
    out.security_level = att_level.min(km_level);
    Ok(())
}
