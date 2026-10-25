//! Endorsement-key certificates: the vendor's word that a chip is genuine.
//!
//! WHY THIS IS IN THE KERNEL AND NOT IN PYTHON. Real vendor EK certificates are not strictly DER — AMD encodes
//! `critical: FALSE` explicitly where DER requires the default omitted, and python `cryptography` refuses the
//! certificate outright with `EncodedDefault`. openssl and x509-parser accept it. Since consensus will have to
//! read these certificates anyway, and consensus parsing must be one deterministic implementation rather than
//! whatever library each caller happens to have, it lives here.
//!
//! WHAT THE VENDOR SIGNATURE BUYS. Everything in doc/tpm-attestation-without-a-ca.md proves "the attestation
//! key is in the same chip as this endorsement key". That is worth nothing unless the endorsement key is one a
//! silicon vendor certified: AMD and Intel are the parties asserting the part is real, and we verify their
//! signature instead of auditing their factories. Skip this and the design degrades to "some TPM somewhere
//! said yes", which a software TPM says just as convincingly.

use crate::chain::{ext_value, verify_chain};
use crate::tpm::manufacturer_from_san;
use crate::Out;
use sha2::{Digest, Sha256};
use x509_parser::prelude::*;

const EK_EKU_OID: &str = "2.23.133.8.1"; // tcg-kp-EKCertificate
const SAN_OID: &str = "2.5.29.17";

pub struct Ek {
    /// sha256 of the endorsement key's SubjectPublicKeyInfo. THE identity handle: burned in at manufacture,
    /// one per chip, and unlike an attestation key it cannot be re-minted, so binding on it is what stops one
    /// machine claiming an identity per enrolment.
    pub identity: String,
    pub manufacturer: String,
    pub root_sha256: String,
}

/// Verify `chain[0]` is a genuine endorsement certificate and that it reaches one of `roots`.
///
/// `chain[1..]` are the client's intermediates. They are only a routing hint — every link's signature is
/// checked and only a pinned root is trust input, so a hostile client can supply whatever it likes here and
/// gain nothing.
pub fn verify_ek(chain: &[Vec<u8>], roots: &[Vec<u8>], now: i64) -> Result<Ek, String> {
    if chain.is_empty() {
        return Err("no endorsement certificate".into());
    }
    let mut out = Out::default();
    verify_chain(chain, roots, now, &mut out)?;

    let (_, leaf) = X509Certificate::from_der(&chain[0]).map_err(|e| format!("ek parse: {e}"))?;

    // It must be an ENDORSEMENT certificate, not some other certificate the same vendor happens to sign.
    let eku_ok = leaf
        .extended_key_usage()
        .ok()
        .flatten()
        .map(|e| e.value.other.iter().any(|o| o.to_id_string() == EK_EKU_OID))
        .unwrap_or(false);
    if !eku_ok {
        return Err("certificate is not marked tcg-kp-EKCertificate".into());
    }
    if leaf.is_ca() {
        return Err("an endorsement certificate must not be a CA".into());
    }

    // THE ENDORSEMENT KEY CANNOT SIGN, BY DEFINITION. It is a restricted decryption key, which is precisely
    // why proving possession of it requires a decrypt challenge rather than a signature. A certificate that
    // claims signing capability is not an EK, and treating one as such would undermine the reason the
    // handshake exists at all.
    match leaf.key_usage().ok().flatten() {
        Some(ku) if ku.value.key_encipherment() && !ku.value.digital_signature() => {}
        Some(_) => return Err("endorsement key must be encipherment-only".into()),
        None => return Err("endorsement certificate has no key usage".into()),
    }

    // The TPM maker, from the SAN's directoryName. The caller refuses virtual TPMs by this value.
    let manufacturer = ext_value(&leaf, SAN_OID)
        .and_then(manufacturer_from_san)
        .ok_or("endorsement certificate names no TPM manufacturer")?;

    Ok(Ek {
        identity: crate::hex(&Sha256::digest(leaf.public_key().raw)),
        manufacturer,
        root_sha256: out.root_sha256,
    })
}
