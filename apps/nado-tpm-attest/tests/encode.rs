//! Does our attestationObject actually decode as the chain expects? The encoder is hand-written CBOR, and a
//! wrong header byte would surface on a user's PC as an unexplainable rejection. Emit one here instead, where
//! ops/device_attest.py can parse it in the same breath.
use nado_tpm_attest::sha::sha256;
use nado_tpm_attest::webauthn::*;

#[test]
fn emit_sample_attestation_object() {
    let modulus = vec![0xC5u8; 256];
    let cose = cose_rsa(&modulus, 65537);
    let cred_id = sha256(b"credential");
    let rp_hash = sha256(b"get.nadochain.com");
    let ad = auth_data(&rp_hash, &cred_id, &cose);
    let att = attestation_object(-257, &[vec![0x30, 0x82, 0x01, 0x00]], &[0xAA; 256], &[0xBB; 173],
                                 &[0xCC; 310], &ad);
    println!("AUTHDATA_LEN={}", ad.len());
    println!("ATT_B64={}", b64(&att));
    println!("COSE_B64={}", b64(&cose));
}
