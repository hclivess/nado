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

fn tpm_present() -> bool { tbs_tpm_present() }

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


/// Microsoft's claim blob, decoded (measured on a real machine 2026-09-10 — the layout is not documented):
///   KAST header 28 bytes: "KAST", version, claimType, cbHeader=28, _, cbBody, _
///   KADS body:            "KADS", version, cbHeader=24, cbCertifyInfo, cbSignature, cbKeyBlob
///   then certifyInfo (a TPMS_ATTEST), signature, key blob — back to back.
/// Returns (certInfo, signature, keyBlob).

/// Offsets of every TPMS_ATTEST ("\xffTCG") in a blob, whatever wraps them.
fn find_attests(b: &[u8]) -> Vec<usize> {
    b.windows(4).enumerate().filter(|(_, w)| *w == TPM_GENERATED).map(|(i, _)| i).collect()
}

/// (type, qualifiedSigner len, extraData) of the TPMS_ATTEST at `off`.
fn attest_at(b: &[u8], off: usize) -> Option<(u16, usize, Vec<u8>)> {
    let a = b.get(off..)?;
    if a.len() < 10 { return None; }
    let ty = u16::from_be_bytes([a[4], a[5]]);
    let qs = u16::from_be_bytes([a[6], a[7]]) as usize;
    let o = 8 + qs;
    let n = u16::from_be_bytes([*a.get(o)?, *a.get(o + 1)?]) as usize;
    Some((ty, qs, a.get(o + 2..o + 2 + n)?.to_vec()))
}

/// Any extraData in the blob that equals the nonce we asked for.
fn blob_binds(b: &[u8], nonce: &[u8]) -> bool {
    find_attests(b).into_iter().filter_map(|o| attest_at(b, o)).any(|(_, _, ed)| ed == nonce)
}

/// Every 4-byte ASCII tag in the blob, so an unknown container names itself.
fn tags(b: &[u8]) -> Vec<(usize, String)> {
    let mut out = Vec::new();
    for (i, w) in b.windows(4).enumerate() {
        if w.iter().all(|c| c.is_ascii_uppercase() || c.is_ascii_digit()) {
            out.push((i, String::from_utf8_lossy(w).to_string()));
        }
    }
    out.truncate(12);
    out
}

fn split_claim(b: &[u8]) -> Option<(&[u8], &[u8], &[u8])> {
    let u32le = |o: usize| -> usize {
        u32::from_le_bytes([b[o], b[o + 1], b[o + 2], b[o + 3]]) as usize
    };
    if b.len() < 52 || &b[0..4] != b"KAST" || &b[28..32] != b"KADS" { return None; }
    let (ci, sg, kb) = (u32le(40), u32le(44), u32le(48));
    let o = 52;
    if o + ci + sg + kb > b.len() { return None; }
    Some((&b[o..o + ci], &b[o + ci..o + ci + sg], &b[o + ci + sg..o + ci + sg + kb]))
}

/// extraData out of a TPMS_ATTEST: magic(4) type(2) qualifiedSigner(2+n) extraData(2+n) ...
fn attest_extra_data(ci: &[u8]) -> Option<&[u8]> {
    if ci.len() < 10 || ci[0..4] != [0xff, 0x54, 0x43, 0x47] { return None; }
    let qs = u16::from_be_bytes([ci[8], ci[9]]) as usize;
    let o = 10 + qs;
    if ci.len() < o + 2 { return None; }
    let n = u16::from_be_bytes([ci[o], ci[o + 1]]) as usize;
    ci.get(o + 2..o + 2 + n)
}

/// Ask the chip to certify `key` with `aik`, optionally binding `nonce` through the parameter list.
unsafe fn make_claim(key: NCRYPT_HANDLE, aik: NCRYPT_HANDLE, nonce: Option<(&[u8], u32)>) -> Result<Vec<u8>, u32> {
    let mut buf;
    let mut desc;
    let plist: *const std::ffi::c_void = match nonce {
        None => std::ptr::null(),
        Some((n, kind)) => {
            buf = NCryptBuffer { cbBuffer: n.len() as u32, BufferType: kind,
                                 pvBuffer: n.as_ptr() as *mut std::ffi::c_void };
            desc = NCryptBufferDesc { ulVersion: NCRYPTBUFFER_VERSION, cBuffers: 1, pBuffers: &mut buf };
            &mut desc as *mut NCryptBufferDesc as *const std::ffi::c_void
        }
    };
    let mut n = 0u32;
    let rc = NCryptCreateClaim(key, aik, NCRYPT_CLAIM_AUTHORITY_AND_SUBJECT, plist,
                               std::ptr::null_mut(), 0, &mut n, 0);
    if rc != 0 { return Err(rc as u32); }
    let mut out = vec![0u8; n as usize];
    let mut got = 0u32;
    let rc = NCryptCreateClaim(key, aik, NCRYPT_CLAIM_AUTHORITY_AND_SUBJECT, plist,
                               out.as_mut_ptr(), n, &mut got, 0);
    if rc != 0 { return Err(rc as u32); }
    out.truncate(got as usize);
    Ok(out)
}

fn main() {
    // SAY SOMETHING BEFORE TOUCHING ANYTHING (2026-09-10: first run "just crashes, no log"). This line proves
    // the binary started, and the panic hook below turns any later fault into a readable message plus a pause
    // instead of a window that vanishes.
    println!("nado-tpm-attest 0.7 starting...");
    std::panic::set_hook(Box::new(|info| {
        println!();
        println!("  SOMETHING WENT WRONG: {info}");
        println!("  Please send this text back.");
        println!();
        println!("  Press Enter to close this window.");
        let mut s = String::new();
        let _ = std::io::stdin().read_line(&mut s);
    }));
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
        // the AIK is a MACHINE key; the key being attested is a USER key — same split as Microsoft's sample
        NCryptCreatePersistedKey(prov, &mut key, alg.as_ptr(), kn.as_ptr(), 0,
                                 NCRYPT_OVERWRITE_KEY_FLAG) == 0
    };
    if have_key {
        let len: u32 = 2048;
        let lp = w(NCRYPT_LENGTH_PROPERTY);
        unsafe { NCryptSetProperty(key, lp.as_ptr(), &len as *const u32 as *const u8, 4, 0) };
        have_key = unsafe { NCryptFinalizeKey(key, 0) } == 0;
    }
    if have_key { said_ok(""); } else { said_bad("the chip would not create a key"); }

    step(6, total, "Chip signing a proof for that key");
    // THE WHOLE POINT OF THIS ROUND: a claim with no parameter list comes back with extraData EMPTY, and
    // native/attest requires certInfo.extraData == hash(authData || clientDataHash). So bind a nonce. The
    // buffer-type constant for it is the one thing not settled, so try each and let the chip decide.
    let probe_nonce: [u8; 32] = *b"NADO-nonce-probe-0123456789abcde";
    // The PCP key blob carries the credential key's TPM2B_PUBLIC — the `pubArea` a WebAuthn tpm statement
    // needs. Layout measured from a real claim: "PCPM", cbHeader=56, pcpType, flags, cbPublic, cbPrivate, ...
    fn pcp_public(kb: &[u8]) -> Option<&[u8]> {
        if kb.len() < 24 || &kb[0..4] != b"PCPM" { return None; }
        let u = |o: usize| u32::from_le_bytes([kb[o], kb[o+1], kb[o+2], kb[o+3]]) as usize;
        let (hdr, pubn) = (u(4), u(16));
        kb.get(hdr..hdr + pubn)
    }
    let mut proof: Option<Vec<u8>> = None;
    let mut winner: Option<u32> = None;
    if have_aik && have_key {
        match unsafe { make_claim(key, aik, None) } {
            Ok(b) => { said_ok(&format!("{} bytes", b.len())); proof = Some(b); }
            Err(rc) => said_bad(&format!("the chip refused to sign (0x{rc:08x})")),
        }
        for (kind, label) in [(NCRYPTBUFFER_CLAIM_KEYATTESTATION_NONCE, "KEYATTESTATION_NONCE(49)"),
                              (NCRYPTBUFFER_CLAIM_IDBINDING_NONCE, "IDBINDING_NONCE(48)")] {
            print!("        {:.<40}", format!("nonce via {label}"));
            let _ = std::io::stdout().flush();
            match unsafe { make_claim(key, aik, Some((&probe_nonce, kind))) } {
                Err(rc) => println!(" {}  0x{rc:08x}", bad("no")),
                Ok(b) => {
                    let table: Vec<String> = find_attests(&b).into_iter()
                        .filter_map(|o| attest_at(&b, o).map(|(t, _, e)| {
                            let mine = if e == probe_nonce { "<-NONCE" } else { "" };
                            format!("@{o}/0x{t:04x}/extra{}{}", e.len(), mine)
                        })).collect();
                    let certify_bound = find_attests(&b).into_iter()
                        .filter_map(|o| attest_at(&b, o))
                        .any(|(t, _, e)| t == 0x8017 && e == probe_nonce);
                    if certify_bound {
                        println!(" {}  nonce is in the CERTIFY attest ({} bytes)", ok("YES"), b.len());
                        winner = Some(kind); proof = Some(b);
                    } else if blob_binds(&b, &probe_nonce) {
                        println!(" {}  nonce present but NOT in 0x8017 [{}]", warn("wrong attest"), table.join(" "));
                        if proof.is_none() { proof = Some(b); }
                    } else {
                        println!(" {}  {} bytes [{}]", warn("no"), b.len(), table.join(" "));
                    }
                }
            }
        }
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
        println!("  head={}", hex(&blob[..blob.len().min(160)]));
        println!("  tags={:?}", tags(blob));
        for o in find_attests(blob) {
            if let Some((t, qs, ed)) = attest_at(blob, o) {
                println!("  attest@{o} type=0x{t:04x} qs={qs} extra={} {}", ed.len(), hex(&ed));
            }
        }
        match split_claim(blob) {
            Some((ci, sg, kb)) => {
                println!("  certInfo={} sig={} keyblob={}", ci.len(), sg.len(), kb.len());
                println!("  certInfo.hex={}", hex(&ci[..ci.len().min(64)]));
                match attest_extra_data(ci) {
                    Some(e) if !e.is_empty() => println!("  extraData={} {}", e.len(), hex(e)),
                    _ => println!("  extraData=0  (NOT BOUND — this proof cannot be used yet)"),
                }
                match pcp_public(kb) {
                    Some(pa) => println!("  pubArea={} {}", pa.len(), hex(&pa[..pa.len().min(24)])),
                    None => println!("  pubArea=?  keyblob.hex={}", hex(&kb[..kb.len().min(48)])),
                }
            }
            None => println!("  claim did not parse as KAST/KADS"),
        }
        println!("  nonce_buffer_type={}", winner.map(|k| k.to_string()).unwrap_or_else(|| "none worked".into()));
        if let Some(pb) = unsafe { export_pub(key, BCRYPT_RSAPUBLIC_BLOB) } {
            println!("  pub={} {}", pb.len(), hex(&pb[..pb.len().min(24)]));
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

    // PHASE 2 GROUNDWORK: the endorsement key certificate straight from the provider. It is the per-device,
    // vendor-signed anchor an AMD/Intel chip carries even when Microsoft refuses to certify an AIK for it,
    // so reading it here means the eventual EK -> AIK handshake needs no PowerShell and no user typing.
    println!();
    println!("  {}", head("raw-TPM fallback groundwork"));
    for (h, label) in [(key, "credential key"), (aik, "AIK")] {
        match unsafe { get_prop(h, NCRYPT_PCP_PLATFORMHANDLE_PROPERTY) } {
            Some(v) if v.len() == 4 => println!("  {label} TPM handle = 0x{:08x}",
                                                u32::from_le_bytes([v[0], v[1], v[2], v[3]])),
            Some(v) => println!("  {label} PCP_PLATFORMHANDLE = {} {}", v.len(), hex(&v)),
            None => println!("  {label} PCP_PLATFORMHANDLE = none"),
        }
    }

    println!();
    println!("  {}", head("endorsement key (for the Microsoft-free path)"));
    for (prop, label) in [(NCRYPT_PCP_EKCERT_PROPERTY, "PCP_EKCERT"),
                          (NCRYPT_PCP_RSA_EKCERT_PROPERTY, "PCP_RSA_EKCERT"),
                          ("PCP_EKNVCERT", "PCP_EKNVCERT"),
                          ("PCP_RSA_EKNVCERT", "PCP_RSA_EKNVCERT"),
                          (NCRYPT_PCP_EKPUB_PROPERTY, "PCP_EKPUB")] {
        let on_prov = unsafe { get_prop(prov, prop) };
        let on_key = if have_aik { unsafe { get_prop(aik, prop) } } else { None };
        let show = |w: &str, v: &Option<Vec<u8>>| match v {
            Some(v) => format!("{w}{} {}", v.len(), hex(&v[..v.len().min(20)])),
            None => format!("{w}none"),
        };
        println!("  {label}: prov={} aik={}", show("", &on_prov), show("", &on_key));
    }

    if have_key { unsafe { NCryptDeleteKey(key, 0) }; }
    if have_aik { unsafe { NCryptFreeObject(aik) }; }
    unsafe { NCryptFreeObject(prov) };
    pause();
}
