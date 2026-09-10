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

/// The command framing is the part a chip rejects wordlessly if it is wrong, so pin it on a host with no TPM.
/// Sizes and offsets here are TCG Part 3: header is tag(2) size(4) code(4), and a TPM2B is a 16-bit length.
#[test]
fn command_framing_matches_the_spec() {
    use nado_tpm_attest::tpm::*;

    let mut c = Cmd::new(ST_NO_SESSIONS, CC_READ_PUBLIC);
    c.u32(0x8100_0001);
    let b = c.finish();
    assert_eq!(&b[0..2], &[0x80, 0x01], "tag ST_NO_SESSIONS");
    assert_eq!(u32::from_be_bytes([b[2], b[3], b[4], b[5]]) as usize, b.len(), "size is patched to the whole command");
    assert_eq!(&b[6..10], &[0x00, 0x00, 0x01, 0x73], "TPM2_CC_ReadPublic");
    assert_eq!(b.len(), 14, "header 10 + one handle");

    // An empty-password authorization area is 9 bytes: handle(4) nonce(2) attrs(1) hmac(2).
    let mut c = Cmd::new(ST_SESSIONS, CC_CREATE_PRIMARY);
    c.u32(RH_ENDORSEMENT);
    c.pw_auth();
    let b = c.finish();
    assert_eq!(&b[0..2], &[0x80, 0x02], "tag ST_SESSIONS");
    assert_eq!(u32::from_be_bytes([b[14], b[15], b[16], b[17]]), 9, "authorizationSize");

    // The EK template is derived, not chosen: a byte wrong here yields a different key and the vendor's
    // endorsement certificate then belongs to a key we do not hold.
    let ek = ek_template();
    assert_eq!(u16::from_be_bytes([ek[0], ek[1]]), ALG_RSA);
    assert_eq!(u16::from_be_bytes([ek[2], ek[3]]), ALG_SHA256, "nameAlg");
    assert_eq!(u32::from_be_bytes([ek[4], ek[5], ek[6], ek[7]]), 0x0003_00B2, "TCG EK profile L-1 attributes");
    assert_eq!(u16::from_be_bytes([ek[8], ek[9]]) as usize, 32, "authPolicy is a SHA-256 digest");
    // 4 type+nameAlg, 4 attrs, 2+32 authPolicy, 14 parameters, 2+256 unique. The parameters are 14 and not
    // 12: TPMT_SYM_DEF_OBJECT is alg+keyBits+mode = 6 bytes, then scheme 2, keyBits 2, exponent 4.
    assert_eq!(ek.len(), 4 + 4 + 34 + 14 + 258, "EK template length");
    assert_eq!(ek.len(), 314);

    // THE SAME DIGESTS ARE PINNED IN tests/test_tpm_linux.py. There are two clients — this one for the
    // sideloaded executables, and a Python one inside the node — and they MUST derive the same keys. A
    // primary is derived from its template, so a byte of drift between them yields a different key on the
    // same chip, and the vendor's endorsement certificate would then belong to a key that client cannot use.
    let d = |b: &[u8]| nado_tpm_attest::sha::sha256_hex(b);
    assert_eq!(d(&ek_template()), "32503929a1287eedaa3e89d932f9b51a6f92abd0fa57721ffa6fc041e04f7498",
               "EK template drifted from the Python node client");
    assert_eq!(d(&aik_template()), "6cb5284d3e55fbf1ba82e683294e1c319320bc7e6897a60b90f1497d09d55033",
               "AIK template drifted from the Python node client");

    // Our AIK is restricted+sign and declares RSASSA/SHA-256, which is what makes the statement COSE -257.
    let aik = aik_template();
    assert_eq!(u32::from_be_bytes([aik[4], aik[5], aik[6], aik[7]]), 0x0005_0472, "restricted signing key");
    assert_eq!(u16::from_be_bytes([aik[12], aik[13]]), ALG_RSASSA, "scheme");
    assert_eq!(u16::from_be_bytes([aik[14], aik[15]]), ALG_SHA256, "scheme hash — NOT SHA-1");

    // A response must be read defensively: it comes from a device.
    assert!(Rsp::parse(&[0x80, 0x01, 0x00, 0x00]).is_none(), "a truncated response is not parsed");
    let good = [0x80u8, 0x01, 0, 0, 0, 12, 0, 0, 0, 0, 0xAB, 0xCD];
    let mut r = Rsp::parse(&good).expect("well-formed");
    assert!(r.ok());
    assert_eq!(r.u16(), Some(0xABCD));
    assert_eq!(r.u16(), None, "reading past the end yields None rather than panicking");
}
