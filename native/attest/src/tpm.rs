//! TPM 2.0 structures a Windows Hello `tpm` statement carries — TPMT_PUBLIC (pubArea) and TPMS_ATTEST
//! (certInfo) — the COSE-vs-pubArea key match, and the AIK certificate's TPM manufacturer from its SAN.

use crate::authdata::{cose_get, cose_map};
use ciborium::value::Value;
use x509_parser::prelude::*;

pub const ALG_RSA: u16 = 0x0001;
pub const ALG_ECC: u16 = 0x0023;
pub const ALG_NULL: u16 = 0x0010;
pub const TPM_GENERATED_VALUE: u32 = 0xff54_4347;
pub const ST_ATTEST_CERTIFY: u16 = 0x8017;

pub struct TpmPub {
    pub key_type: u16,
    pub name_alg: u16,
    pub rsa_n: Vec<u8>,
    pub rsa_e: u32,
    pub ecc_curve: u16,
    pub ecc_x: Vec<u8>,
    pub ecc_y: Vec<u8>,
}

fn rd16(b: &[u8], p: &mut usize) -> Option<u16> {
    if *p + 2 > b.len() { return None; }
    let v = u16::from_be_bytes([b[*p], b[*p + 1]]);
    *p += 2;
    Some(v)
}
fn rd32(b: &[u8], p: &mut usize) -> Option<u32> {
    if *p + 4 > b.len() { return None; }
    let v = u32::from_be_bytes([b[*p], b[*p + 1], b[*p + 2], b[*p + 3]]);
    *p += 4;
    Some(v)
}
fn rd64(b: &[u8], p: &mut usize) -> Option<u64> {
    if *p + 8 > b.len() { return None; }
    let v = u64::from_be_bytes(b[*p..*p + 8].try_into().ok()?);
    *p += 8;
    Some(v)
}
fn rd2b(b: &[u8], p: &mut usize) -> Option<Vec<u8>> {
    let n = rd16(b, p)? as usize;
    if *p + n > b.len() { return None; }
    let v = b[*p..*p + n].to_vec();
    *p += n;
    Some(v)
}
/// A TPMT_SYM_DEF_OBJECT / TPMT_*_SCHEME: an algorithm id, followed by details unless TPM_ALG_NULL.
fn skip_alg_with_details(b: &[u8], p: &mut usize, detail_words: usize) -> Option<()> {
    let alg = rd16(b, p)?;
    if alg != ALG_NULL {
        for _ in 0..detail_words { rd16(b, p)?; }
    }
    Some(())
}

/// TPMT_PUBLIC (TPM 2.0 part 2 §12.2.4): type, nameAlg, objectAttributes, authPolicy, parameters, unique.
pub fn parse_pub_area(b: &[u8]) -> Option<TpmPub> {
    let mut p = 0;
    let key_type = rd16(b, &mut p)?;
    let name_alg = rd16(b, &mut p)?;
    let _attrs = rd32(b, &mut p)?;
    let _policy = rd2b(b, &mut p)?;
    let mut out = TpmPub { key_type, name_alg, rsa_n: vec![], rsa_e: 0, ecc_curve: 0, ecc_x: vec![], ecc_y: vec![] };
    match key_type {
        ALG_RSA => {
            skip_alg_with_details(b, &mut p, 2)?; // symmetric: keyBits + mode
            skip_alg_with_details(b, &mut p, 1)?; // scheme: hashAlg
            let _bits = rd16(b, &mut p)?;
            let e = rd32(b, &mut p)?;
            out.rsa_e = if e == 0 { 65537 } else { e };
            out.rsa_n = rd2b(b, &mut p)?;
        }
        ALG_ECC => {
            skip_alg_with_details(b, &mut p, 2)?;
            skip_alg_with_details(b, &mut p, 1)?;
            out.ecc_curve = rd16(b, &mut p)?;
            skip_alg_with_details(b, &mut p, 1)?; // kdf: hashAlg
            out.ecc_x = rd2b(b, &mut p)?;
            out.ecc_y = rd2b(b, &mut p)?;
        }
        _ => return None,
    }
    if p != b.len() { return None; }
    Some(out)
}

pub struct TpmAttest {
    pub extra_data: Vec<u8>,
    pub attested_name: Vec<u8>,
}

/// TPMS_ATTEST (part 2 §10.12.8) for TPM_ST_ATTEST_CERTIFY: magic, type, qualifiedSigner, extraData,
/// clockInfo {clock, resetCount, restartCount, safe}, firmwareVersion, attested {name, qualifiedName}.
pub fn parse_cert_info(b: &[u8]) -> Option<TpmAttest> {
    let mut p = 0;
    if rd32(b, &mut p)? != TPM_GENERATED_VALUE { return None; }
    if rd16(b, &mut p)? != ST_ATTEST_CERTIFY { return None; }
    let _signer = rd2b(b, &mut p)?;
    let extra_data = rd2b(b, &mut p)?;
    let _clock = rd64(b, &mut p)?;
    let _reset = rd32(b, &mut p)?;
    let _restart = rd32(b, &mut p)?;
    if p >= b.len() { return None; }
    p += 1; // safe: TPMI_YES_NO
    let _fw = rd64(b, &mut p)?;
    let attested_name = rd2b(b, &mut p)?;
    let _qualified = rd2b(b, &mut p)?;
    if p != b.len() { return None; }
    Some(TpmAttest { extra_data, attested_name })
}

/// COSE credential key (RSA kty 3: n = -1, e = -2; EC2 kty 2: x = -2, y = -3) equals the pubArea key.
pub fn cose_matches_pub_area(cose: &[u8], pa: &TpmPub) -> bool {
    let m = match cose_map(cose) { Some(m) => m, None => return false };
    match pa.key_type {
        ALG_RSA => {
            let (n, e) = match (cose_get(&m, -1), cose_get(&m, -2)) {
                (Some(Value::Bytes(n)), Some(Value::Bytes(e))) => (n, e),
                _ => return false,
            };
            let e_val = e.iter().fold(0u64, |acc, b| (acc << 8) | *b as u64);
            n.as_slice() == pa.rsa_n.as_slice() && e_val == pa.rsa_e as u64
        }
        ALG_ECC => {
            let (x, y) = match (cose_get(&m, -2), cose_get(&m, -3)) {
                (Some(Value::Bytes(x)), Some(Value::Bytes(y))) => (x, y),
                _ => return false,
            };
            x.as_slice() == pa.ecc_x.as_slice() && y.as_slice() == pa.ecc_y.as_slice()
        }
        _ => false,
    }
}

/// SAN extension: GeneralNames with a directoryName whose RDNs carry tcg-at-tpmManufacturer (2.23.133.2.1)
/// as "id:XXXXXXXX"; returns the upper-case hex id.
pub fn manufacturer_from_san(ext: &[u8]) -> Option<String> {
    let (_, gn) = x509_parser::extensions::SubjectAlternativeName::from_der(ext).ok()?;
    for name in gn.general_names.iter() {
        if let x509_parser::extensions::GeneralName::DirectoryName(dn) = name {
            for rdn in dn.iter() {
                for attr in rdn.iter() {
                    if attr.attr_type().to_id_string() == "2.23.133.2.1" {
                        let v = attr.as_str().ok()?.to_string();
                        return Some(v.trim_start_matches("id:").to_uppercase());
                    }
                }
            }
        }
    }
    None
}
