//! FIDO2 security keys (`packed` with a vendor chain — self-attestation has no x5c and is refused before
//! this): attStmt.sig by the leaf key over authData || sha256(cdj); leaf X.509 v3, subject OU
//! "Authenticator Attestation", not a CA, and its AAGUID extension (1.3.6.1.4.1.45724.1.1.4), when present,
//! equal to the authenticator data's AAGUID. Binding the AAGUID to the vendor's OWN root set is done by the
//! caller (protocol_roots/fido_mds_roots.json), using `root_sha256` from the chain walk.

use super::{cbor_bytes, cbor_int, signed_message, Ctx};
use crate::chain::{ext_value, hash_of_cose_alg, verify_with_cert};
use crate::Out;

const AAGUID_OID: &str = "1.3.6.1.4.1.45724.1.1.4";

pub fn verify(c: &Ctx, _out: &mut Out) -> Result<(), String> {
    let alg = cbor_int(c.st, "alg").ok_or("packed: no alg")?;
    let sig = cbor_bytes(c.st, "sig").ok_or("packed: no sig")?;
    let hash = hash_of_cose_alg(alg).ok_or("packed: unsupported alg")?;
    if !verify_with_cert(c.leaf, &signed_message(c), &sig, hash) {
        return Err("packed: signature does not verify".into());
    }
    if c.leaf.is_ca() {
        return Err("packed: leaf is a CA".into());
    }
    if c.leaf.version().0 != 2 {
        return Err("packed: leaf is not an X.509 v3 certificate".into());
    }
    let ou_ok = c
        .leaf
        .subject()
        .iter_organizational_unit()
        .any(|ou| ou.as_str().map(|v| v == "Authenticator Attestation").unwrap_or(false));
    if !ou_ok {
        return Err("packed: leaf subject OU is not 'Authenticator Attestation'".into());
    }
    if let Some(ext) = ext_value(c.leaf, AAGUID_OID) {
        match der_parser::ber::parse_ber_octetstring(ext) {
            Ok((_, os)) => {
                if os.as_slice().map(|v| v != c.a.aaguid.as_slice()).unwrap_or(true) {
                    return Err("packed: certificate AAGUID != authData AAGUID".into());
                }
            }
            Err(_) => return Err("packed: malformed AAGUID extension".into()),
        }
    }
    Ok(())
}
