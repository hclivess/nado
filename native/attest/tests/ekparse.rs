//! A REAL vendor endorsement certificate, end to end: parsed, chain-verified to AMD's own root, and its
//! identity extracted. python cryptography refuses this exact certificate (`EncodedDefault` — AMD encodes
//! critical:FALSE where strict DER requires it omitted), which is why this lives in the kernel.
use std::fs;

fn der(p: &str) -> Vec<u8> {
    let b = fs::read(p).unwrap();
    if b.starts_with(b"-----") {
        let s = String::from_utf8_lossy(&b);
        let body: String = s.lines().filter(|l| !l.starts_with("-----")).collect();
        use base64::Engine;
        base64::engine::general_purpose::STANDARD.decode(body).unwrap()
    } else { b }
}

#[test]
fn a_real_amd_endorsement_certificate_verifies_to_amds_root() {
    const S: &str = "/tmp/claude-0/-srv-nado-home-nado/b67ad1ad-d37f-4f80-a1c7-15be171c0956/scratchpad/";
    let ek = der(&format!("{S}ek.der"));
    let inter = der(&format!("{S}amd_inter.pem"));
    let root = der(&format!("{S}amd_root.pem"));
    let now = 1789000000i64;

    let r = nado_attest::ek_verify_for_test(&[ek.clone(), inter.clone()], &[root.clone()], now)
        .expect("a genuine AMD EK certificate must verify");
    println!("manufacturer {}  root {}", r.1, &r.2[..16]);
    assert_eq!(r.1, "414D4400", "AMD");
    assert_eq!(r.0.len(), 64, "ek identity is a sha256 hex digest");

    // NOT asserted: that pinning the intermediate fails. It succeeds, and correctly so — pinning PRG-RN as a
    // root IS a decision to trust PRG-RN, and the EK does chain to it. That is caller policy, not a bug. The
    // property that matters is that only what WE pin is trusted, so a foreign vendor's root must not do:
    let microsoft = der("/srv/nado-home/nado/protocol_roots/microsoft_tpm_root_ca_2014.pem");
    assert!(nado_attest::ek_verify_for_test(&[ek.clone(), inter.clone()], &[microsoft], now).is_err(),
            "an AMD chip must not verify against Microsoft's root");
    assert!(nado_attest::ek_verify_for_test(&[ek.clone(), inter.clone()], &[], now).is_err(),
            "no roots means no trust");
    assert!(nado_attest::ek_verify_for_test(&[ek.clone()], &[root.clone()], now).is_err(),
            "a gap in the chain must not be bridged");
    // The AIK certificate from the same evening is a signing cert, not an EK: it must be refused.
    let aik = der(&format!("{S}aik.pem"));
    assert!(nado_attest::ek_verify_for_test(&[aik], &[root], now).is_err(),
            "a non-EK certificate must be refused");
}
