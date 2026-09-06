//! Windows Hello on a TPM (`tpm`, ver "2.0"): attStmt {alg, x5c: [AIK, ...], sig, certInfo, pubArea}.
//! pubArea's key must be the credential key; certInfo must be a TPM_ST_ATTEST_CERTIFY whose extraData is
//! hash(authData || cdjHash) and whose attested name is nameAlg(pubArea); sig over certInfo by the AIK
//! certificate; the AIK certificate is v3, has an empty subject, is not a CA, carries the AIK extended key
//! usage (2.23.133.8.3) and names the TPM manufacturer in its SAN (returned as `tpm_manufacturer` so the
//! caller can refuse virtual TPMs).

use super::{cbor_bytes, cbor_get, cbor_int, signed_message, Ctx};
use crate::chain::{digest, ext_value, hash_of_cose_alg, verify_with_cert, Hash};
use crate::tpm::{cose_matches_pub_area, manufacturer_from_san, parse_cert_info, parse_pub_area};
use crate::Out;
use ciborium::value::Value;

const AIK_EKU_OID: &str = "2.23.133.8.3";
const SAN_OID: &str = "2.5.29.17";

fn hash_of_tpm_alg(alg: u16) -> Option<Hash> {
    match alg {
        0x0004 => Some(Hash::S1),
        0x000b => Some(Hash::S256),
        0x000c => Some(Hash::S384),
        0x000d => Some(Hash::S512),
        _ => None,
    }
}

pub fn verify(c: &Ctx, out: &mut Out) -> Result<(), String> {
    match cbor_get(c.st, "ver") {
        Some(Value::Text(v)) if v == "2.0" => {}
        _ => return Err("tpm: ver != 2.0".into()),
    }
    let alg = cbor_int(c.st, "alg").ok_or("tpm: no alg")?;
    let sig = cbor_bytes(c.st, "sig").ok_or("tpm: no sig")?;
    let cert_info = cbor_bytes(c.st, "certInfo").ok_or("tpm: no certInfo")?;
    let pub_area = cbor_bytes(c.st, "pubArea").ok_or("tpm: no pubArea")?;
    let hash = hash_of_cose_alg(alg).ok_or("tpm: unsupported alg")?;

    let pa = parse_pub_area(&pub_area).ok_or("tpm: malformed pubArea")?;
    if !cose_matches_pub_area(&c.a.cred_pubkey_cose, &pa) {
        return Err("tpm: credential key != pubArea key".into());
    }
    let ci = parse_cert_info(&cert_info).ok_or("tpm: malformed certInfo")?;
    if ci.extra_data != digest(hash, &signed_message(c)) {
        return Err("tpm: certInfo.extraData != hash(authData || clientDataHash)".into());
    }
    let name_hash = hash_of_tpm_alg(pa.name_alg).ok_or("tpm: unsupported nameAlg")?;
    let mut expect_name = pa.name_alg.to_be_bytes().to_vec();
    expect_name.extend_from_slice(&digest(name_hash, &pub_area));
    if ci.attested_name != expect_name {
        return Err("tpm: certInfo.attested.name != name(pubArea)".into());
    }
    if !verify_with_cert(c.leaf, &cert_info, &sig, hash) {
        return Err("tpm: signature over certInfo does not verify".into());
    }
    // AIK certificate requirements (WebAuthn §8.3)
    if c.leaf.version().0 != 2 {
        return Err("tpm: AIK cert is not v3".into());
    }
    if c.leaf.subject().iter().count() != 0 {
        return Err("tpm: AIK cert subject must be empty".into());
    }
    if c.leaf.is_ca() {
        return Err("tpm: AIK cert is a CA".into());
    }
    let eku_ok = c
        .leaf
        .extended_key_usage()
        .ok()
        .flatten()
        .map(|e| e.value.other.iter().any(|o| o.to_id_string() == AIK_EKU_OID))
        .unwrap_or(false);
    if !eku_ok {
        return Err("tpm: AIK cert lacks the AIK extended key usage".into());
    }
    out.tpm_manufacturer = ext_value(c.leaf, SAN_OID)
        .and_then(manufacturer_from_san)
        .ok_or("tpm: AIK cert has no TPM manufacturer in its SAN")?;
    Ok(())
}
