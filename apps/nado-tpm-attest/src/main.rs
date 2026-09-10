//! nado-tpm-attest — make a Windows TPM usable for NADO device attestation when Windows Hello will not.
//!
//! WHY THIS EXISTS (doc/windows-tpm-attester.md). Windows Hello is the only way a web page can reach a TPM,
//! and on many PCs it simply refuses: it hands back `fmt: "none"` (or a chainless `packed` self-attestation)
//! because it has no usable Attestation Identity Key for the signed-in user — measured over 202 samples, and
//! reproduced on a machine whose TPM is healthy and whose `certreq -enrollaik` succeeds. Nothing a browser
//! sends can change that. So we go around it: enrol our OWN named AIK the way Microsoft's own sample does
//! (certreq -enrollaik -f -machine -config "" <name>, per their EnrollAik.ps1), create the credential key in
//! the TPM, have the AIK certify it, and emit exactly the `tpm` statement native/attest already verifies.
//!
//! THIS BUILD IS THE PROBE. It is deliberately read-mostly: it reports what the machine can actually do and
//! dumps the shape of NCryptCreateClaim's output, because the claim blob layout is the one piece that is not
//! publicly specified and must not be guessed. Nothing is submitted to the network from this build.
//!
//! Cross-built from Linux: cargo build --release --target x86_64-pc-windows-gnu

mod win;
use win::*;

const AIK_NAME: &str = "NadoAik";
const KEY_NAME: &str = "NadoAttestKey";
const TPM_GENERATED: [u8; 4] = [0xff, 0x54, 0x43, 0x47]; // "\xffTCG" — starts every TPMS_ATTEST

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn dump(label: &str, b: &[u8], max: usize) {
    let n = b.len().min(max);
    println!("  {label}: {} bytes", b.len());
    for (i, c) in b[..n].chunks(32).enumerate() {
        println!("    {:04x}  {}", i * 32, hex(c));
    }
    if b.len() > n {
        println!("    ...   (+{} more)", b.len() - n);
    }
}

fn st(label: &str, rc: SECURITY_STATUS) -> bool {
    if rc == 0 {
        println!("  [ ok ] {label}");
        true
    } else {
        println!("  [FAIL] {label}: 0x{:08x}", rc as u32);
        false
    }
}

/// NCryptGetProperty into a right-sized Vec.
unsafe fn get_prop(h: NCRYPT_HANDLE, prop: &str) -> Option<Vec<u8>> {
    let p = w(prop);
    let mut n = 0u32;
    if NCryptGetProperty(h, p.as_ptr(), std::ptr::null_mut(), 0, &mut n, 0) != 0 || n == 0 {
        return None;
    }
    let mut buf = vec![0u8; n as usize];
    let mut got = 0u32;
    if NCryptGetProperty(h, p.as_ptr(), buf.as_mut_ptr(), n, &mut got, 0) != 0 {
        return None;
    }
    buf.truncate(got as usize);
    Some(buf)
}

unsafe fn export_pub(h: NCRYPT_HANDLE, blob: &str) -> Option<Vec<u8>> {
    let b = w(blob);
    let mut n = 0u32;
    if NCryptExportKey(h, 0, b.as_ptr(), std::ptr::null(), std::ptr::null_mut(), 0, &mut n, 0) != 0 || n == 0 {
        return None;
    }
    let mut buf = vec![0u8; n as usize];
    let mut got = 0u32;
    if NCryptExportKey(h, 0, b.as_ptr(), std::ptr::null(), buf.as_mut_ptr(), n, &mut got, 0) != 0 {
        return None;
    }
    buf.truncate(got as usize);
    Some(buf)
}

fn tpm_present() -> bool {
    let params = [2u32, 1u32]; // TBS_CONTEXT_PARAMS2 { version 2, includeTpm20 }
    let mut ctx: *mut std::ffi::c_void = std::ptr::null_mut();
    let rc = unsafe { Tbsi_Context_Create(params.as_ptr(), &mut ctx) };
    if rc == 0 {
        unsafe { Tbsip_Context_Close(ctx) };
        println!("  [ ok ] TPM reachable through TBS");
        true
    } else {
        println!("  [FAIL] TBS context: 0x{rc:08x} (no TPM, or not permitted)");
        false
    }
}

/// Certificates in LocalMachine\My whose issuer names a TPM-vendor KeyId — i.e. AIK certificates.
unsafe fn list_aik_certs() {
    let store_name = w("My");
    let store = CertOpenStore(
        CERT_STORE_PROV_SYSTEM_W,
        0,
        0,
        CERT_SYSTEM_STORE_LOCAL_MACHINE,
        store_name.as_ptr() as *const _,
    );
    if store.is_null() {
        println!("  [FAIL] could not open LocalMachine\\My");
        return;
    }
    let mut ctx: *const CERT_CONTEXT = std::ptr::null();
    let mut found = 0;
    loop {
        ctx = CertEnumCertificatesInStore(store, ctx);
        if ctx.is_null() {
            break;
        }
        let mut name = [0u16; 512];
        let n = CertGetNameStringW(ctx, CERT_NAME_SIMPLE_DISPLAY_TYPE, CERT_NAME_ISSUER_FLAG,
                                   std::ptr::null(), name.as_mut_ptr(), name.len() as u32);
        let issuer = String::from_utf16_lossy(&name[..(n as usize).saturating_sub(1)]);
        if issuer.to_ascii_lowercase().contains("keyid") {
            let der = std::slice::from_raw_parts((*ctx).pbCertEncoded, (*ctx).cbCertEncoded as usize);
            found += 1;
            println!("  [ ok ] AIK certificate #{found}: issuer {issuer}");
            println!("         der {} bytes, sha256-of-der {}", der.len(), sha256_hex(der));
        }
    }
    if found == 0 {
        println!("  [WARN] no AIK certificate in LocalMachine\\My — run the certreq line above first");
    }
    CertCloseStore(store, 0);
}

/// Tiny SHA-256 so the probe stays dependency-free (only used to label certificates in the report).
fn sha256_hex(data: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
    let mut h: [u32; 8] = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
    let mut m = data.to_vec();
    let bits = (data.len() as u64) * 8;
    m.push(0x80);
    while m.len() % 64 != 56 { m.push(0); }
    m.extend_from_slice(&bits.to_be_bytes());
    for blk in m.chunks(64) {
        let mut wds = [0u32; 64];
        for i in 0..16 { wds[i] = u32::from_be_bytes([blk[4*i],blk[4*i+1],blk[4*i+2],blk[4*i+3]]); }
        for i in 16..64 {
            let s0 = wds[i-15].rotate_right(7) ^ wds[i-15].rotate_right(18) ^ (wds[i-15] >> 3);
            let s1 = wds[i-2].rotate_right(17) ^ wds[i-2].rotate_right(19) ^ (wds[i-2] >> 10);
            wds[i] = wds[i-16].wrapping_add(s0).wrapping_add(wds[i-7]).wrapping_add(s1);
        }
        let (mut a,mut b,mut c,mut d,mut e,mut f,mut g,mut hh)=(h[0],h[1],h[2],h[3],h[4],h[5],h[6],h[7]);
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh.wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(wds[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh=g; g=f; f=e; e=d.wrapping_add(t1); d=c; c=b; b=a; a=t1.wrapping_add(t2);
        }
        for (i,v) in [a,b,c,d,e,f,g,hh].iter().enumerate() { h[i]=h[i].wrapping_add(*v); }
    }
    h.iter().map(|x| format!("{x:08x}")).collect()
}

fn main() {
    println!("nado-tpm-attest probe 0.1.0 — reports only, submits nothing\n");

    println!("[1] TPM");
    tpm_present();

    println!("\n[2] Platform Crypto Provider");
    let mut prov: NCRYPT_HANDLE = 0;
    let pname = w(MS_PLATFORM_KEY_STORAGE_PROVIDER);
    let rc = unsafe { NCryptOpenStorageProvider(&mut prov, pname.as_ptr(), 0) };
    if !st("open \"Microsoft Platform Crypto Provider\"", rc) {
        println!("\nThis machine has no TPM key storage provider — stopping.");
        return;
    }

    println!("\n[3] Attestation Identity Key \"{AIK_NAME}\"");
    println!("  if this fails, run ONCE in an elevated Command Prompt:");
    println!("      certreq -enrollaik -f -machine -config \"\" {AIK_NAME}");
    let mut aik: NCRYPT_HANDLE = 0;
    let an = w(AIK_NAME);
    let rc = unsafe {
        NCryptOpenKey(prov, &mut aik, an.as_ptr(), 0, NCRYPT_SILENT_FLAG | NCRYPT_MACHINE_KEY_FLAG)
    };
    let have_aik = st("open the AIK", rc);
    if have_aik {
        unsafe {
            if let Some(a) = get_prop(aik, NCRYPT_ALGORITHM_PROPERTY) {
                println!("         algorithm: {}", String::from_utf16_lossy(
                    &a.chunks(2).map(|c| u16::from_le_bytes([c[0], c[1]])).take_while(|&x| x != 0).collect::<Vec<_>>()));
            }
            if let Some(b) = export_pub(aik, BCRYPT_RSAPUBLIC_BLOB) {
                println!("         public blob: {} bytes", b.len());
            }
        }
    }

    println!("\n[4] AIK certificates in LocalMachine\\My");
    unsafe { list_aik_certs() };

    println!("\n[5] Credential key in the TPM (\"{KEY_NAME}\")");
    let mut key: NCRYPT_HANDLE = 0;
    let kn = w(KEY_NAME);
    let alg = w(BCRYPT_RSA_ALGORITHM);
    let rc = unsafe {
        NCryptCreatePersistedKey(prov, &mut key, alg.as_ptr(), kn.as_ptr(), 0,
                                 NCRYPT_OVERWRITE_KEY_FLAG | NCRYPT_MACHINE_KEY_FLAG)
    };
    let mut have_key = st("create persisted key", rc);
    if have_key {
        let len: u32 = 2048;
        let lp = w(NCRYPT_LENGTH_PROPERTY);
        unsafe { NCryptSetProperty(key, lp.as_ptr(), &len as *const u32 as *const u8, 4, 0) };
        have_key = st("finalize", unsafe { NCryptFinalizeKey(key, 0) });
    }
    if have_key {
        unsafe {
            if let Some(b) = export_pub(key, BCRYPT_RSAPUBLIC_BLOB) {
                println!("         public blob: {} bytes", b.len());
            }
            if let Some(pa) = get_prop(key, NCRYPT_PCP_TPM12_IDBINDING_PROPERTY) {
                dump("PCP_TPM12_IDBINDING", &pa, 64);
            }
        }
    }

    println!("\n[6] NCryptCreateClaim — the TPM certifying the key with the AIK");
    if have_aik && have_key {
        let mut n = 0u32;
        let rc = unsafe {
            NCryptCreateClaim(key, aik, NCRYPT_CLAIM_AUTHORITY_AND_SUBJECT, std::ptr::null(),
                              std::ptr::null_mut(), 0, &mut n, 0)
        };
        if st(&format!("size query (claim would be {n} bytes)"), rc) && n > 0 {
            let mut blob = vec![0u8; n as usize];
            let mut got = 0u32;
            let rc = unsafe {
                NCryptCreateClaim(key, aik, NCRYPT_CLAIM_AUTHORITY_AND_SUBJECT, std::ptr::null(),
                                  blob.as_mut_ptr(), n, &mut got, 0)
            };
            if st("produce claim", rc) {
                blob.truncate(got as usize);
                dump("claim blob", &blob, 256);
                // The one thing we need out of it: the TPMS_ATTEST. It always starts with "\xffTCG".
                let hits: Vec<usize> = blob.windows(4).enumerate()
                    .filter(|(_, wd)| *wd == TPM_GENERATED).map(|(i, _)| i).collect();
                if hits.is_empty() {
                    println!("  [WARN] no TPM_GENERATED magic in the claim — layout needs a closer look");
                } else {
                    for off in &hits {
                        let t = if blob.len() > off + 5 { u16::from_be_bytes([blob[off+4], blob[off+5]]) } else { 0 };
                        println!("  [ ok ] TPMS_ATTEST at offset {off} (type 0x{t:04x}{})",
                                 if t == 0x8017 { ", ST_ATTEST_CERTIFY — this is the certInfo we need" } else { "" });
                    }
                }
            }
        }
    } else {
        println!("  [SKIP] needs both the AIK and the credential key");
    }

    println!("\n[7] cleanup");
    if have_key { st("delete the test credential key", unsafe { NCryptDeleteKey(key, 0) }); }
    if have_aik { unsafe { NCryptFreeObject(aik) }; }
    unsafe { NCryptFreeObject(prov) };
    println!("\nDone. Send this whole output back.");
}
