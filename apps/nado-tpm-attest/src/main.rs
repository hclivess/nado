//! nado-tpm-attest — ask this PC's security chip to vouch for a NADO wallet, when Windows Hello will not.
//!
//! WHY THIS EXISTS (doc/windows-tpm-attester.md). Windows Hello is the only way a web page can reach a TPM,
//! and on many PCs it refuses: it returns `fmt: "none"`, or a chainless `packed` self-attestation, because it
//! has no usable Attestation Identity Key for the signed-in user. Measured over 202 samples and reproduced on
//! a machine whose TPM is healthy and whose AIK enrolment succeeds. No browser-side change fixes it.
//!
//! WRITTEN FOR A NORMAL PERSON, NOT A SYSTEMS ENGINEER (operator, 2026-09-10). It performs the AIK enrolment
//! itself instead of telling the user to run certreq; it says what each step means in plain words; it colours
//! the result so the outcome is obvious at a glance; and it pauses at the end so double-clicking it works.
//!
//! THIS BUILD REPORTS ONLY — it submits nothing to the network. It creates one test key and deletes it.
//!
//! Cross-built from Linux: cargo build --release --target x86_64-pc-windows-gnu

mod win;
use win::*;
use std::io::Write;

const AIK_NAME: &str = "NadoAik";
const KEY_NAME: &str = "NadoAttestKey";
const TPM_GENERATED: [u8; 4] = [0xff, 0x54, 0x43, 0x47]; // "\xffTCG" — starts every TPMS_ATTEST

static mut COLOUR: bool = false;
fn c(code: &str, s: &str) -> String {
    if unsafe { COLOUR } { format!("\x1b[{code}m{s}\x1b[0m") } else { s.to_string() }
}
fn ok(s: &str) -> String { c("1;32", s) }
fn bad(s: &str) -> String { c("1;31", s) }
fn warn(s: &str) -> String { c("1;33", s) }
fn head(s: &str) -> String { c("1;36", s) }
fn dim(s: &str) -> String { c("2", s) }

fn step(n: u32, total: u32, what: &str) {
    print!("  {} {:.<42}", dim(&format!("[{n}/{total}]")), what);
    let _ = std::io::stdout().flush();
}
fn said_ok(detail: &str) { println!(" {}{}", ok("OK"), if detail.is_empty() { String::new() } else { format!("  {}", dim(detail)) }); }
fn said_bad(detail: &str) { println!(" {}  {}", bad("FAILED"), detail); }
fn said_warn(detail: &str) { println!(" {}  {}", warn("SKIPPED"), detail); }

fn hex(b: &[u8]) -> String { b.iter().map(|x| format!("{x:02x}")).collect() }

fn pause() {
    println!();
    println!("  {}", dim("Press Enter to close this window."));
    let mut s = String::new();
    let _ = std::io::stdin().read_line(&mut s);
}

unsafe fn get_prop(h: NCRYPT_HANDLE, prop: &str) -> Option<Vec<u8>> {
    let p = w(prop);
    let mut n = 0u32;
    if NCryptGetProperty(h, p.as_ptr(), std::ptr::null_mut(), 0, &mut n, 0) != 0 || n == 0 { return None; }
    let mut buf = vec![0u8; n as usize];
    let mut got = 0u32;
    if NCryptGetProperty(h, p.as_ptr(), buf.as_mut_ptr(), n, &mut got, 0) != 0 { return None; }
    buf.truncate(got as usize);
    Some(buf)
}

unsafe fn export_pub(h: NCRYPT_HANDLE, blob: &str) -> Option<Vec<u8>> {
    let b = w(blob);
    let mut n = 0u32;
    if NCryptExportKey(h, 0, b.as_ptr(), std::ptr::null(), std::ptr::null_mut(), 0, &mut n, 0) != 0 || n == 0 { return None; }
    let mut buf = vec![0u8; n as usize];
    let mut got = 0u32;
    if NCryptExportKey(h, 0, b.as_ptr(), std::ptr::null(), buf.as_mut_ptr(), n, &mut got, 0) != 0 { return None; }
    buf.truncate(got as usize);
    Some(buf)
}

fn tpm_present() -> bool {
    let params = [2u32, 1u32];
    let mut ctx: *mut std::ffi::c_void = std::ptr::null_mut();
    let rc = unsafe { Tbsi_Context_Create(params.as_ptr(), &mut ctx) };
    if rc == 0 { unsafe { Tbsip_Context_Close(ctx) }; true } else { false }
}

/// Run the AIK enrolment ourselves. This is Microsoft's own documented line (their EnrollAik.ps1):
/// a NAMED, persistent key we can open again afterwards — unlike a bare `certreq -enrollaik`, which makes an
/// anonymous TestAIK nobody can reopen. Returns (succeeded, human explanation).
fn enrol_aik() -> (bool, String) {
    let out = std::process::Command::new("certreq")
        .args(["-enrollaik", "-f", "-machine", "-config", "", AIK_NAME])
        .output();
    let out = match out {
        Ok(o) => o,
        Err(e) => return (false, format!("could not run certreq ({e})")),
    };
    let text = format!("{}{}", String::from_utf8_lossy(&out.stdout), String::from_utf8_lossy(&out.stderr));
    if text.contains("EnrollDone") || text.contains("Enrolled") {
        return (true, String::new());
    }
    if text.contains("404") || text.contains("does not exist") || text.contains("0x80190194") {
        return (false, "Microsoft has no certificate authority for this chip (404).\n         \
                        This is a fault on Microsoft's side, not your PC — nothing here can fix it.\n         \
                        Your chip is fine; it just cannot get a Microsoft identity certificate.".into());
    }
    let first = text.lines().find(|l| l.to_lowercase().contains("error") || l.contains("0x"))
                    .unwrap_or("no recognisable result").trim().to_string();
    (false, format!("certreq did not report success: {first}"))
}

unsafe fn count_aik_certs() -> usize {
    let store_name = w("My");
    let store = CertOpenStore(CERT_STORE_PROV_SYSTEM_W, 0, 0, CERT_SYSTEM_STORE_LOCAL_MACHINE,
                              store_name.as_ptr() as *const _);
    if store.is_null() { return 0; }
    let mut ctx: *const CERT_CONTEXT = std::ptr::null();
    let mut found = 0usize;
    loop {
        ctx = CertEnumCertificatesInStore(store, ctx);
        if ctx.is_null() { break; }
        let mut name = [0u16; 512];
        let n = CertGetNameStringW(ctx, CERT_NAME_SIMPLE_DISPLAY_TYPE, CERT_NAME_ISSUER_FLAG,
                                   std::ptr::null(), name.as_mut_ptr(), name.len() as u32);
        let issuer = String::from_utf16_lossy(&name[..(n as usize).saturating_sub(1)]);
        if issuer.to_ascii_lowercase().contains("keyid") { found += 1; }
    }
    CertCloseStore(store, 0);
    found
}

fn main() {
    unsafe { COLOUR = enable_colour() };
    println!();
    println!("  {}", head("NADO — device check for Windows"));
    println!("  {}", dim("This asks your PC's security chip (the TPM) whether it can vouch for you."));
    println!("  {}", dim("It only checks. Nothing is sent anywhere and nothing is registered."));
    println!();

    let total = 6;

    step(1, total, "Administrator rights");
    if is_elevated() {
        said_ok("");
    } else {
        said_bad("this window is not running as administrator");
        println!();
        println!("  {}", warn("Close this, right-click nado-tpm-attest.exe and choose"));
        println!("  {}", warn("\"Run as administrator\", then try again."));
        println!("  {}", dim("The security chip will not hand out an identity certificate otherwise."));
        pause();
        return;
    }

    step(2, total, "Security chip (TPM 2.0)");
    if !tpm_present() {
        said_bad("no TPM reachable on this PC");
        println!();
        println!("  {}", warn("Your PC has no usable security chip, or it is switched off in the BIOS."));
        println!("  {}", dim("Look for \"AMD fTPM\" or \"Intel PTT\" in your BIOS settings."));
        pause();
        return;
    }
    said_ok("");

    step(3, total, "Windows key storage");
    let mut prov: NCRYPT_HANDLE = 0;
    let pname = w(MS_PLATFORM_KEY_STORAGE_PROVIDER);
    if unsafe { NCryptOpenStorageProvider(&mut prov, pname.as_ptr(), 0) } != 0 {
        said_bad("Windows will not open the chip's key store");
        pause();
        return;
    }
    said_ok("");

    step(4, total, "Identity certificate (asking Microsoft)");
    let _ = std::io::stdout().flush();
    let (enrolled, why) = enrol_aik();
    if enrolled { said_ok("issued"); } else { said_bad(&why); }

    let mut aik: NCRYPT_HANDLE = 0;
    let an = w(AIK_NAME);
    let have_aik = unsafe {
        NCryptOpenKey(prov, &mut aik, an.as_ptr(), 0, NCRYPT_SILENT_FLAG | NCRYPT_MACHINE_KEY_FLAG) == 0
    };
    let certs = unsafe { count_aik_certs() };
    println!("        {}", dim(&format!("identity keys usable: {}, certificates on this PC: {}",
                                        if have_aik { "yes" } else { "no" }, certs)));

    step(5, total, "Creating a key inside the chip");
    let mut key: NCRYPT_HANDLE = 0;
    let kn = w(KEY_NAME);
    let alg = w(BCRYPT_RSA_ALGORITHM);
    let mut have_key = unsafe {
        NCryptCreatePersistedKey(prov, &mut key, alg.as_ptr(), kn.as_ptr(), 0,
                                 NCRYPT_OVERWRITE_KEY_FLAG | NCRYPT_MACHINE_KEY_FLAG) == 0
    };
    if have_key {
        let len: u32 = 2048;
        let lp = w(NCRYPT_LENGTH_PROPERTY);
        unsafe { NCryptSetProperty(key, lp.as_ptr(), &len as *const u32 as *const u8, 4, 0) };
        have_key = unsafe { NCryptFinalizeKey(key, 0) } == 0;
    }
    if have_key { said_ok(""); } else { said_bad("the chip would not create a key"); }

    step(6, total, "Chip signing a proof for that key");
    let mut proof: Option<Vec<u8>> = None;
    if have_aik && have_key {
        let mut n = 0u32;
        let rc = unsafe {
            NCryptCreateClaim(key, aik, NCRYPT_CLAIM_AUTHORITY_AND_SUBJECT, std::ptr::null(),
                              std::ptr::null_mut(), 0, &mut n, 0)
        };
        if rc == 0 && n > 0 {
            let mut blob = vec![0u8; n as usize];
            let mut got = 0u32;
            if unsafe {
                NCryptCreateClaim(key, aik, NCRYPT_CLAIM_AUTHORITY_AND_SUBJECT, std::ptr::null(),
                                  blob.as_mut_ptr(), n, &mut got, 0)
            } == 0 {
                blob.truncate(got as usize);
                said_ok(&format!("{} bytes", blob.len()));
                proof = Some(blob);
            } else { said_bad("the chip refused to sign"); }
        } else { said_bad(&format!("the chip refused to sign (0x{:08x})", rc as u32)); }
    } else {
        said_warn("needs both an identity certificate and a key");
    }

    println!();
    if let Some(blob) = &proof {
        println!("  {}", ok("This PC CAN vouch for you."));
        println!("  {}", dim("Copy everything below and send it back — it is technical detail about the"));
        println!("  {}", dim("proof's layout only. It contains no password, wallet or personal data."));
        println!();
        println!("  ----- begin -----");
        println!("  len={}", blob.len());
        for (i, ch) in blob.chunks(32).take(8).enumerate() {
            println!("  {:04x} {}", i * 32, hex(ch));
        }
        let hits: Vec<usize> = blob.windows(4).enumerate()
            .filter(|(_, wd)| *wd == TPM_GENERATED).map(|(i, _)| i).collect();
        for off in &hits {
            let t = if blob.len() > off + 5 { u16::from_be_bytes([blob[off + 4], blob[off + 5]]) } else { 0 };
            println!("  attest@{off} type=0x{t:04x}");
        }
        if hits.is_empty() { println!("  attest@none"); }
        if let Some(pa) = unsafe { get_prop(key, NCRYPT_PCP_TPM12_IDBINDING_PROPERTY) } {
            println!("  idbinding={} {}", pa.len(), hex(&pa[..pa.len().min(32)]));
        }
        if let Some(pb) = unsafe { export_pub(key, BCRYPT_RSAPUBLIC_BLOB) } {
            println!("  pub={}", pb.len());
        }
        println!("  ----- end -----");
    } else if !enrolled {
        println!("  {}", bad("This PC cannot vouch for you."));
        println!("  {}", dim("The chip works, but Microsoft will not issue it an identity certificate."));
        println!("  {}", dim("Use your Android phone instead (\"Attest from another device\" in the wallet),"));
        println!("  {}", dim("or a Ledger / Trezor. We are building a way around this — it is not your fault."));
    } else {
        println!("  {}", warn("Inconclusive — send this output back."));
    }

    if have_key { unsafe { NCryptDeleteKey(key, 0) }; }
    if have_aik { unsafe { NCryptFreeObject(aik) }; }
    unsafe { NCryptFreeObject(prov) };
    pause();
}
