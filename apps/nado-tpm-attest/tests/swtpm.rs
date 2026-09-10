//! End-to-end against a real TPM 2.0 implementation (swtpm), driving OUR command bytes and OUR issuer.
//!
//! Everything else in this crate's tests checks construction in isolation. This is the only test that asks a
//! TPM whether it accepts what we build: the TCG L-1 endorsement template, a restricted RSASSA/SHA-256
//! attestation key, the policy session the EK's adminWithPolicy demands, ops/tpm_aik.py's MakeCredential, and
//! finally TPM2_Certify over a challenge we choose.
//!
//! WHAT IT DOES NOT PROVE: that a particular piece of silicon behaves the same. swtpm will accept a template a
//! vendor fTPM may reject and it carries no endorsement certificate at all. A green run here means the
//! construction is right, not that the hardware path is done.
//!
//! Ignored by default because it needs a running simulator. To run it:
//!     swtpm socket --tpm2 --server type=tcp,port=2321,bindaddr=127.0.0.1 \
//!                  --ctrl type=tcp,port=2322,bindaddr=127.0.0.1 \
//!                  --tpmstate dir=<dir> --flags not-need-init,startup-clear --daemon
//!     cargo test --target x86_64-unknown-linux-gnu --test swtpm -- --ignored --nocapture

use nado_tpm_attest::sha::sha256;
use nado_tpm_attest::tpm::*;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::Mutex;

/// The simulator's platform protocol: a command is framed with TPM_SEND_COMMAND, a locality byte and a length;
/// the reply is a length, the response, then an acknowledgement word.
struct MsSim(Mutex<TcpStream>);

impl Tpm for MsSim {
    fn transmit(&self, cmd: &[u8]) -> Result<Vec<u8>, u32> {
        let mut s = self.0.lock().map_err(|_| 1u32)?;
        let mut req = Vec::new();
        req.extend_from_slice(&8u32.to_be_bytes()); // TPM_SEND_COMMAND
        req.push(0); // locality
        req.extend_from_slice(&(cmd.len() as u32).to_be_bytes());
        req.extend_from_slice(cmd);
        s.write_all(&req).map_err(|_| 2u32)?;

        let mut n = [0u8; 4];
        s.read_exact(&mut n).map_err(|_| 3u32)?;
        let mut rsp = vec![0u8; u32::from_be_bytes(n) as usize];
        s.read_exact(&mut rsp).map_err(|_| 4u32)?;
        let mut ack = [0u8; 4];
        s.read_exact(&mut ack).map_err(|_| 5u32)?;
        Ok(rsp)
    }
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

#[test]
#[ignore]
fn end_to_end_against_a_real_tpm() {
    let t = MsSim(Mutex::new(
        TcpStream::connect("127.0.0.1:2321").expect("swtpm not listening on 2321"),
    ));

    // A previous run that died before its cleanup leaves primaries loaded, and a TPM has only a few object
    // slots — the next run then fails with TPM_RC_OBJECT_MEMORY for reasons unrelated to what it tests. Sweep
    // first, so this test never needs the simulator restarted by hand.
    let swept = flush_all_transient(&t);
    if swept > 0 { println!("swept     {swept} leaked handle(s) from an earlier run"); }

    // 1. The endorsement key, from the TCG profile template. If this derives at all, our template is the one
    //    the profile specifies — a byte wrong here silently yields a different key.
    let (ek, ek_pub, ek_name) =
        create_primary(&t, RH_ENDORSEMENT, &ek_template()).expect("CreatePrimary(EK) failed");
    println!("EK        handle 0x{ek:08x}  pubArea {} B  name {}", ek_pub.len(), hex(&ek_name[..4]));
    assert_eq!(u16::from_be_bytes([ek_name[0], ek_name[1]]), ALG_SHA256, "EK name is SHA-256");

    // 2. Our attestation key: restricted, signing, RSASSA over SHA-256.
    let (aik, aik_pub, aik_name) =
        create_primary(&t, RH_ENDORSEMENT, &aik_template()).expect("CreatePrimary(AIK) failed");
    println!("AIK       handle 0x{aik:08x}  pubArea {} B", aik_pub.len());

    // The Name a credential binds to is nameAlg || H(pubArea) — recompute it rather than trust the reply.
    let mut expect = ALG_SHA256.to_be_bytes().to_vec();
    expect.extend_from_slice(&sha256(&aik_pub));
    assert_eq!(aik_name, expect, "the AIK's Name is nameAlg || sha256(pubArea)");

    // 3. Hand the EK's public area and the AIK's Name to OUR issuer and let it seal a secret.
    let out = std::process::Command::new("python3")
        .arg("tests/helpers/make_credential.py")
        .arg(hex(&ek_pub))
        .arg(hex(&aik_name))
        .output()
        .expect("could not run the issuer");
    assert!(out.status.success(), "issuer failed: {}", String::from_utf8_lossy(&out.stderr));
    let text = String::from_utf8_lossy(&out.stdout);
    let mut fields = text.split_whitespace();
    let secret_hex = fields.next().expect("issuer printed no secret");
    let blob = hexdec(fields.next().expect("no credential blob"));
    let enc_secret = hexdec(fields.next().expect("no encrypted secret"));
    println!("issuer    credentialBlob {} B  encryptedSecret {} B", blob.len(), enc_secret.len());

    // 4. The EK is adminWithPolicy, so a password authorization is refused however empty the hierarchy auth
    //    is. A policy session satisfied by PolicySecret(TPM_RH_ENDORSEMENT) is mandatory.
    let session = start_policy_session(&t).expect("StartAuthSession failed");
    policy_secret_endorsement(&t, session).expect("PolicySecret(ENDORSEMENT) failed");

    // 5. The proof: the chip returns the secret only because the EK and the AIK live in the same TPM.
    let recovered = activate_credential(&t, aik, ek, session, &blob, &enc_secret)
        .expect("ActivateCredential failed");
    assert_eq!(hex(&recovered), secret_hex, "the TPM recovered exactly the secret our issuer sealed");
    println!("activate  recovered the sealed secret — EK and AIK proven to share a chip");

    // 6. And the statement itself: certInfo signed by the key whose certificate would go in x5c, over a
    //    challenge we chose. This is what the NCrypt path could never give us.
    let challenge = sha256(b"nado end-to-end challenge");
    let (cert_info, sig) = certify(&t, aik, aik, &challenge).expect("Certify failed");
    println!("certify   certInfo {} B  sig {} B", cert_info.len(), sig.len());
    assert_eq!(&cert_info[0..4], &[0xff, 0x54, 0x43, 0x47], "TPM_GENERATED");
    assert_eq!(u16::from_be_bytes([cert_info[4], cert_info[5]]), 0x8017, "ST_ATTEST_CERTIFY");

    // extraData must carry our challenge, which is where the verifier looks for hash(authData||clientDataHash)
    let qs = u16::from_be_bytes([cert_info[6], cert_info[7]]) as usize;
    let o = 8 + qs;
    let n = u16::from_be_bytes([cert_info[o], cert_info[o + 1]]) as usize;
    assert_eq!(&cert_info[o + 2..o + 2 + n], &challenge[..], "extraData is the challenge we chose");
    println!("certify   extraData carries our challenge — the binding the verifier checks");

    let _ = flush(&t, session);
    let _ = flush(&t, aik);
    let _ = flush(&t, ek);
}

fn hexdec(s: &str) -> Vec<u8> {
    (0..s.len() / 2).map(|i| u8::from_str_radix(&s[i * 2..i * 2 + 2], 16).unwrap()).collect()
}
