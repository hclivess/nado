//! One handle on this machine's TPM, whichever platform it is.
//!
//! The command bytes are identical everywhere — a TPM speaks TCG part 3 whoever hands it the bytes —
//! so the only platform-specific thing here is which transport gets opened. Everything below is the
//! same code on Windows and Linux.
//!
//! PRIMARIES ARE DERIVED, NOT STORED. Both keys come from fixed templates, so this machine recomputes
//! the same endorsement key and the same attestation key on every run, and an enrolment survives a
//! reboot with nothing persisted on disk. It also means the templates are not negotiable: one byte
//! different yields a different key, and for the endorsement key that means the vendor's certificate
//! no longer matches what the machine holds.

use crate::tpm::{self, Tpm};

const RH_ENDORSEMENT: u32 = 0x4000_000B;

/// Certificates placed next to the program: ek.cer, ek1.cer, ek2.cer ... in that order, leaf first.
/// DER or PEM; a PEM file is converted, because "export it with PowerShell" produces one as often as
/// the other and a user should not have to know which they got.
fn ek_chain_from_files() -> Vec<Vec<u8>> {
    let mut out = Vec::new();
    let dir = match std::env::current_exe().ok().and_then(|e| e.parent().map(|p| p.to_path_buf())) {
        Some(d) => d,
        None => return out,
    };
    for name in ["ek.cer", "ek1.cer", "ek2.cer", "ek3.cer", "ek.der", "ek.pem"] {
        let path = dir.join(name);
        if let Ok(bytes) = std::fs::read(&path) {
            if let Some(der) = as_der(&bytes) {
                out.push(der);
            }
        }
    }
    out
}

/// DER as-is, or the first certificate out of a PEM.
fn as_der(bytes: &[u8]) -> Option<Vec<u8>> {
    if bytes.first() == Some(&0x30) {
        return Some(bytes.to_vec());
    }
    let text = String::from_utf8_lossy(bytes);
    let body: String = text
        .lines()
        .skip_while(|l| !l.contains("BEGIN CERTIFICATE"))
        .skip(1)
        .take_while(|l| !l.contains("END CERTIFICATE"))
        .collect::<Vec<_>>()
        .join("");
    if body.is_empty() {
        return None;
    }
    b64_decode(body.trim())
}

fn b64_decode(s: &str) -> Option<Vec<u8>> {
    const T: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut acc: u32 = 0;
    let mut bits = 0u32;
    let mut out = Vec::new();
    for c in s.bytes() {
        if c == b'=' || c.is_ascii_whitespace() {
            continue;
        }
        let v = T.iter().position(|&t| t == c)? as u32;
        acc = (acc << 6) | v;
        bits += 6;
        if bits >= 8 {
            bits -= 8;
            out.push((acc >> bits) as u8);
        }
    }
    if out.is_empty() { None } else { Some(out) }
}

pub struct Chip {
    pub(crate) t: Box<dyn Tpm>,
}

pub fn open() -> Result<Chip, String> {
    #[cfg(windows)]
    {
        let t = crate::win::open_tbs()
            .map_err(|e| format!("cannot reach the TPM through TBS (0x{e:08x})"))?;
        return Ok(Chip { t: Box::new(t) });
    }
    #[cfg(not(windows))]
    {
        if !crate::devtpm::DevTpm::present() {
            return Err("this machine has no TPM device (/dev/tpmrm0)".into());
        }
        let t = crate::devtpm::DevTpm::open()
            .map_err(|e| format!("cannot open /dev/tpmrm0 (0x{e:08x})"))?;
        Ok(Chip { t: Box::new(t) })
    }
}

impl Chip {
    /// The endorsement chain: from the chip's own NV first, and on Windows from the certificate store
    /// Windows caches into when the chip does not carry one.
    ///
    /// AN AMD FIRMWARE TPM COMMONLY HAS NOTHING IN NV. Measured on a real machine: all four NCrypt
    /// EK-certificate properties returned empty and both NV indices were unpopulated, on a chip whose
    /// certificate PowerShell displays without difficulty — because Windows fetched it once and kept
    /// it. Reading only NV would refuse those machines for a reason that has nothing to do with their
    /// hardware, which is the whole failure mode this path exists to fix.
    pub fn ek_chain(&mut self) -> Result<Vec<Vec<u8>>, String> {
        // A CERTIFICATE PUT BESIDE THE EXE WINS, because it is the escape hatch that needs no new code
        // when a machine keeps its certificate somewhere nobody predicted. Vendors deliver these four
        // different ways already; supplying the file directly is always available and always works, and
        // it is not a weakening — the certificate is public, it is verified to a pinned vendor root,
        // and a certificate belonging to some other chip cannot open credentials sealed to it.
        let from_file = ek_chain_from_files();
        if !from_file.is_empty() {
            println!("  chip       endorsement chain supplied beside the program ({} file(s))",
                     from_file.len());
            return Ok(from_file);
        }
        // FINDING THE LEAF AND FINDING THE LINKS ARE TWO SEPARATE QUESTIONS, and conflating them is what
        // hid an entire class of machine. A chip may hold no endorsement certificate while holding the
        // intermediates that certificate needs, and vice versa, so ask for both independently.
        let mut chain = tpm::ek_chain(self.t.as_ref());
        #[cfg(windows)]
        if chain.is_empty() {
            chain = crate::win::ek_certificates_from_registry();
            if !chain.is_empty() {
                println!("  chip       endorsement certificate came from the Windows certificate store");
                println!("             (this chip holds none in its own NV — normal for an AMD fTPM)");
            }
        }
        // The EK certificate CHAIN NV range, always — an Intel CSME part keeps its leaf in an
        // operating-system store while the ROM / Kernel / PTT intermediates sit in the chip, and those
        // intermediates exist in no other place on earth: the vendor does not publish them and no
        // certificate points down at them.
        let nv_links = tpm::ek_chain_extra(self.t.as_ref());
        if !nv_links.is_empty() {
            println!("  chip       {} intermediate(s) read from the chip's EK certificate chain",
                     nv_links.len());
        }
        // A STORE HOLDS A SET OF CERTIFICATES, NOT A PATH. This completed the chain only when exactly ONE
        // certificate was found, on the assumption that more than one already meant a chain. It does not:
        // a Windows EKCertStore with two entries handed over a leaf and a certificate that was not its
        // issuer, in that order, and the verifier refused it with "x5c[0] signature does not verify
        // against its issuer" — a true statement about a bag someone had called a chain. The machine was
        // an Alder Lake PTT whose root we already pinned, so nothing about the hardware was wrong.
        //
        // So: order whatever we hold into a real path from the leaf up, then extend it from the TOP by
        // AIA. Walking from the top matters — an Intel OnDie leaf carries no AIA extension at all, and a
        // walk that starts at the leaf gives up immediately while the certificate above it points the
        // rest of the way.
        // BUILD A PATH OUT OF A POOL. A platform scatters the pieces of an endorsement chain across
        // wherever it chose to put them, and the pieces are not all in one place: an Intel CSME machine
        // kept its leaf in the TPM's EKCertStore while the certificate that ISSUED that leaf was in
        // neither that store nor anywhere the chain points at, since no certificate points DOWNWARD. So
        // gather from everywhere the machine might hold one, then link a path through the pool, and fall
        // back to fetching an issuer only where the pool cannot supply it.
        let mut pool: Vec<Vec<u8>> = chain.clone();
        for der in nv_links {
            if !pool.iter().any(|c| *c == der) {
                pool.push(der);
            }
        }
        #[cfg(windows)]
        {
            let sys = crate::win::certificates_from_system_stores();
            if !sys.is_empty() {
                println!("  chip       {} certificate(s) available from this machine's stores to link with",
                         sys.len());
                for der in sys {
                    if !pool.iter().any(|c| *c == der) {
                        pool.push(der);
                    }
                }
            }
        }
        let path = build_path(&chain, &mut pool);
        println!("  chip       endorsement chain is {} certificate(s)", path.len());
        Ok(path)
    }

    pub fn ek_public(&mut self) -> Result<Vec<u8>, String> {
        let (h, pubarea, _) = tpm::create_primary(self.t.as_ref(), RH_ENDORSEMENT, &tpm::ek_template())
            .map_err(|e| format!("could not derive the endorsement key (0x{e:08x})"))?;
        tpm::flush(self.t.as_ref(), h).ok();
        Ok(pubarea)
    }

    pub fn aik_public(&mut self) -> Result<Vec<u8>, String> {
        self.aik_public_for(0)
    }

    /// The attestation key for one ATTEMPT — see tpm::aik_template_for. A stalled enrolment is escaped
    /// by deriving the next one, which yields a fresh challenger draw immediately.
    pub fn aik_public_for(&mut self, attempt: u32) -> Result<Vec<u8>, String> {
        let (h, pubarea, _) = tpm::create_primary(self.t.as_ref(), RH_ENDORSEMENT,
                                                  &tpm::aik_template_for(attempt))
            .map_err(|e| format!("could not derive the attestation key (0x{e:08x})"))?;
        tpm::flush(self.t.as_ref(), h).ok();
        Ok(pubarea)
    }

    /// Open one challenger's credential. The chip returns the secret ONLY because both the endorsement
    /// key and the attestation key are objects inside it — that is the entire proof.
    pub fn activate_credential(&mut self, blob: &[u8], enc_seed: &[u8]) -> Result<Vec<u8>, String> {
        self.activate_credential_for(0, blob, enc_seed)
    }

    pub fn activate_credential_for(&mut self, attempt: u32, blob: &[u8], enc_seed: &[u8])
            -> Result<Vec<u8>, String> {
        let t = self.t.as_ref();
        let (ek, _, _) = tpm::create_primary(t, RH_ENDORSEMENT, &tpm::ek_template())
            .map_err(|e| format!("endorsement key (0x{e:08x})"))?;
        let (aik, _, _) = match tpm::create_primary(t, RH_ENDORSEMENT, &tpm::aik_template_for(attempt)) {
            Ok(v) => v,
            Err(e) => {
                tpm::flush(t, ek).ok();
                return Err(format!("attestation key (0x{e:08x})"));
            }
        };
        let result = (|| -> Result<Vec<u8>, String> {
            // The endorsement key is adminWithPolicy, so a plain password authorisation is refused
            // however empty the endorsement auth happens to be. This is what satisfies its policy.
            let session = tpm::start_policy_session(t)
                .map_err(|e| format!("policy session (0x{e:08x})"))?;
            let out = (|| {
                tpm::policy_secret_endorsement(t, session)
                    .map_err(|e| format!("PolicySecret (0x{e:08x})"))?;
                tpm::activate_credential(t, aik, ek, session, blob, enc_seed)
                    .map_err(|e| format!("ActivateCredential (0x{e:08x})"))
            })();
            tpm::flush(t, session).ok();
            out
        })();
        // A LEAKED TRANSIENT HANDLE WEDGES THE NEXT ATTEMPT with TPM_RC_OBJECT_MEMORY, which then looks
        // like a fault in whatever that attempt is doing rather than in what this one failed to clean up.
        tpm::flush(t, aik).ok();
        tpm::flush(t, ek).ok();
        result
    }

    /// A fresh certify over this registration's challenge, under the enrolled attestation key.
    pub fn certify(&mut self, challenge: &[u8]) -> Result<(Vec<u8>, Vec<u8>), String> {
        self.certify_for(0, challenge)
    }

    pub fn certify_for(&mut self, attempt: u32, challenge: &[u8])
            -> Result<(Vec<u8>, Vec<u8>), String> {
        let t = self.t.as_ref();
        let (aik, _, _) = tpm::create_primary(t, RH_ENDORSEMENT, &tpm::aik_template_for(attempt))
            .map_err(|e| format!("attestation key (0x{e:08x})"))?;
        let out = tpm::certify(t, aik, aik, challenge)
            .map_err(|e| format!("Certify (0x{e:08x})"));
        tpm::flush(t, aik).ok();
        out
    }
}

/// Assemble and report a chain from a certificate on disk, touching no TPM.
///
/// A SAFE THING TO RUN. It reads one file, fetches the issuers its own AIA extension points at, and
/// prints what it found. No chip, no keys, no transactions — so it can be used to answer "will my
/// certificate verify" separately from "does the enrolment work", which are the two questions that
/// otherwise fail together and look like one problem.
pub fn selftest_chain(path: &str) -> Result<(), String> {
    let bytes = std::fs::read(path).map_err(|e| format!("cannot read {path}: {e}"))?;
    let leaf = as_der(&bytes).ok_or("that file is neither DER nor PEM")?;
    println!("  leaf        {} bytes, sha256 {}", leaf.len(), crate::tx::blake2b_free_sha256(&leaf));
    let issuers = fetch_issuers(&leaf, false);
    if issuers.is_empty() {
        println!("  issuers     none fetched — the chain is just the leaf");
        for u in urls_in(&leaf) {
            println!("              (leaf points at {u})");
        }
    }
    for (i, c) in issuers.iter().enumerate() {
        println!("  issuer {}    {} bytes, sha256 {}", i + 1, c.len(),
                 crate::tx::blake2b_free_sha256(c));
    }
    println!();
    println!("  Send the sha256 values above; the last one must be a pinned vendor root.");
    Ok(())
}

/// HARDWARE CAPABILITY PROBE: can this chip use its endorsement key as a storage parent, create a key
/// under it, and have that key certify its own creation?
///
/// THIS IS NOT A PROOF AND MUST NOT BE PRESENTED AS ONE. An architecture built on these commands was
/// proposed and retracted the same day — it is forgeable in software, because nothing vendor-signed
/// reaches the key doing the signing (tests/test_certify_creation_is_forgeable.py builds a message that
/// passes every check with no TPM at all). What this answers is narrower and still worth knowing: a
/// constrained firmware TPM may refuse the endorsement key as a parent entirely, and nobody has asked
/// one. Touches no keys you own and publishes nothing.
pub fn check_creation() -> Result<(), String> {
    let mut c = open()?;
    let t = c.t.as_ref();
    println!();
    println!("  Probing whether this chip will parent a key under its endorsement key.");
    println!("  This proves a CAPABILITY, not a design — the architecture built on it was retracted");
    println!("  as forgeable. Nothing is published and no key of yours is touched.");
    println!();

    let (ek, ek_pub, ek_name) = tpm::create_primary(t, RH_ENDORSEMENT, &tpm::ek_template())
        .map_err(|e| format!("endorsement key (0x{e:08x})"))?;
    println!("  [1/5] endorsement key derives ............ OK  {} byte public area", ek_pub.len());
    let derived = {
        let mut v = vec![0x00u8, 0x0bu8];
        v.extend_from_slice(&crate::sha::sha256(&ek_pub));
        v
    };
    println!("  [2/5] its name is derivable .............. {}",
             if derived == ek_name { "OK  a verifier can recompute it" } else { "MISMATCH" });

    let session = match tpm::start_policy_session(t) {
        Ok(s) => s,
        Err(e) => { tpm::flush(t, ek).ok(); return Err(format!("policy session (0x{e:08x})")); }
    };
    let out = (|| -> Result<(), String> {
        tpm::policy_secret_endorsement(t, session)
            .map_err(|e| format!("PolicySecret (0x{e:08x})"))?;
        let (priv_, pub_, cdata, chash, ticket) =
            tpm::create_under(t, ek, session, &tpm::aik_template())
                .map_err(|e| format!("[3/5] TPM2_Create under the endorsement key FAILED (0x{e:08x})                                       — this chip will not parent a key there"))?;
        println!("  [3/5] TPM2_Create under the EK ........... OK  priv {} pub {}", priv_.len(), pub_.len());

        let session2 = tpm::start_policy_session(t).map_err(|e| format!("second session (0x{e:08x})"))?;
        tpm::policy_secret_endorsement(t, session2)
            .map_err(|e| format!("PolicySecret (0x{e:08x})"))?;
        let child = tpm::load_under(t, ek, session2, &priv_, &pub_)
            .map_err(|e| format!("[4/5] TPM2_Load FAILED (0x{e:08x})"));
        tpm::flush(t, session2).ok();
        let child = child?;
        println!("  [4/5] the child loads .................... OK  handle 0x{child:08x}");

        let mut qual = [0u8; 32];
        crate::rand_bytes(&mut qual);
        let r = tpm::certify_creation(t, child, child, &qual, &chash, &ticket)
            .map_err(|e| format!("[5/5] TPM2_CertifyCreation FAILED (0x{e:08x})"));
        tpm::flush(t, child).ok();
        let (info, sig) = r?;
        println!("  [5/5] TPM2_CertifyCreation ............... OK  attest {} sig {}", info.len(), sig.len());
        let magic = u32::from_be_bytes([info[0], info[1], info[2], info[3]]);
        let typ = u16::from_be_bytes([info[4], info[5]]);
        println!("        TPM_GENERATED 0x{magic:08x}, type 0x{typ:04x} (want 0xff544347 / 0x801a)");
        println!("        creationData {} bytes; parent named inside it", cdata.len());
        Ok(())
    })();
    tpm::flush(t, session).ok();
    tpm::flush(t, ek).ok();
    println!();
    match &out {
        Ok(()) => println!("  RESULT: this chip CAN parent a key under its endorsement key."),
        Err(e) => println!("  RESULT: {e}"),
    }
    println!("  Either way the four-message enrolment stays — see the retraction note.");
    out
}

/// Follow a certificate's Authority Information Access pointers and collect the issuers above it.
///
/// WHY THE CLIENT DOES THIS AND THE VERIFIER NEVER COULD. An AMD firmware TPM's endorsement leaf does
/// not chain straight to CN=AMDTPM — it goes through an intermediate that lives on neither the chip nor
/// the machine. Windows fetches it over AIA at validation time and caches it somewhere the registry
/// does not expose. So the leaf alone is an incomplete chain, and a verifier cannot go and get the rest
/// itself: a consensus rule that made a network call would give different answers on different nodes,
/// and on the same node at different times.
///
/// Fetching it HERE is safe precisely because it changes nothing about trust. Intermediates are a
/// routing hint; every link is verified and only the pinned root is trust input, so a hostile or
/// broken response produces a chain that fails verification rather than one that wrongly passes. The
/// transport is plain HTTP for the same reason — there is nothing here worth encrypting and nothing
/// worth authenticating, because the answer is checked against a root we already hold.
///
/// URLs are found by scanning for "http://" rather than by decoding the AIA extension, which keeps an
/// X.509 parser out of a program that does not otherwise need one. CRL and OCSP endpoints get tried
/// too and simply do not return certificates, so they filter themselves out.
/// The path from the leaf upward: each certificate issued by the next, taking links from `pool` where the
/// machine already has them and fetching an issuer only where it does not.
///
/// SHIP THE PATH, NOT THE POOL. A machine's trust store holds thousands of certificates that are nothing
/// to do with this chip; handing all of them to a verifier would be enormous and wrong. The pool exists
/// to supply MISSING LINKS, and only the certificates that actually link are sent.
fn build_path(primary: &[Vec<u8>], pool: &mut Vec<Vec<u8>>) -> Vec<Vec<u8>> {
    if primary.is_empty() {
        return Vec::new();
    }
    // The leaf is the certificate in `primary` that issued nothing else in `primary` — no name parsing,
    // no assumption about the order a store happened to return things in.
    let subj: Vec<Vec<u8>> = primary.iter().map(|c| subject_der(c)).collect();
    let leaf_idx = (0..primary.len())
        .find(|&i| !subj[i].is_empty()
              && !primary.iter().enumerate().any(|(j, c)| j != i && issuer_der(c) == subj[i]))
        .unwrap_or(0);

    let mut path: Vec<Vec<u8>> = vec![primary[leaf_idx].clone()];
    for _ in 0..10 {
        let cur = path.last().unwrap().clone();
        let (cs, ci) = (subject_der(&cur), issuer_der(&cur));
        if ci.is_empty() || ci == cs {
            break;                                          // self-signed: the top
        }
        // already in the pool?
        if let Some(next) = pool.iter().find(|c| subject_der(c) == ci && **c != cur).cloned() {
            path.push(next);
            continue;
        }
        // not held anywhere: ask the network, from this certificate AND from everything we hold, because
        // the pointer to the next link is not always on the certificate that needs it.
        let mut found: Option<Vec<u8>> = None;
        let mut sources = vec![cur.clone()];
        sources.extend(path.iter().cloned());
        for src in sources {
            for der in fetch_issuers(&src, true) {
                if !pool.iter().any(|c| *c == der) {
                    pool.push(der.clone());
                }
                if subject_der(&der) == ci {
                    found = Some(der);
                }
            }
            if found.is_some() {
                break;
            }
        }
        match found {
            Some(der) => path.push(der),
            None => break,                                  // the link genuinely does not exist anywhere
        }
    }
    path
}

/// Order a bag of certificates into a path: the leaf first, then each certificate that ISSUED the one
/// before it. Anything we cannot place is appended, because a verifier that can use it should still get
/// it and one we cannot place is not evidence of a bad chip.
///
/// The leaf is the certificate no other certificate in the bag is issued BY — a definition that needs no
/// name parsing and no assumption about store ordering, which is what made the previous version wrong.
fn order_chain(certs: Vec<Vec<u8>>) -> Vec<Vec<u8>> {
    if certs.len() < 2 {
        return certs;
    }
    let subj: Vec<Vec<u8>> = certs.iter().map(|c| subject_der(c)).collect();
    let issu: Vec<Vec<u8>> = certs.iter().map(|c| issuer_der(c)).collect();
    // a leaf issues nothing else in the bag
    let leaf = (0..certs.len())
        .find(|&i| !subj[i].is_empty() && !issu.iter().enumerate().any(|(j, is)| j != i && *is == subj[i]))
        .unwrap_or(0);
    let mut used = vec![false; certs.len()];
    let mut out = Vec::with_capacity(certs.len());
    let mut cur = leaf;
    loop {
        used[cur] = true;
        out.push(certs[cur].clone());
        if issu[cur].is_empty() || issu[cur] == subj[cur] {
            break;                                    // self-signed: the top of the path
        }
        match (0..certs.len()).find(|&j| !used[j] && !subj[j].is_empty() && subj[j] == issu[cur]) {
            Some(next) => cur = next,
            None => break,                            // the issuer is not in the bag; AIA continues from here
        }
    }
    for (i, c) in certs.into_iter().enumerate() {
        if !used[i] {
            out.push(c);
        }
    }
    out
}

/// The raw DER of a certificate's subject / issuer Name, compared as bytes so no name-string parsing or
/// normalisation can make two different names look equal.
fn issuer_der(der: &[u8]) -> Vec<u8> { tbs_name(der, 0) }
fn subject_der(der: &[u8]) -> Vec<u8> { tbs_name(der, 1) }

/// Pull issuer (which = 0) or subject (which = 1) out of a certificate's TBS, by walking the DER rather
/// than by decoding it: TBSCertificate is [version] serial, sigAlg, issuer, validity, subject, ...
fn tbs_name(der: &[u8], which: usize) -> Vec<u8> {
    fn hdr(b: &[u8], o: usize) -> Option<(usize, usize)> {
        if o + 1 >= b.len() { return None; }
        let first = b[o + 1] as usize;
        if first < 0x80 { return Some((o + 2, first)); }
        let n = first & 0x7f;
        if n == 0 || n > 4 || o + 2 + n > b.len() { return None; }
        let mut len = 0usize;
        for i in 0..n { len = (len << 8) | b[o + 2 + i] as usize; }
        Some((o + 2 + n, len))
    }
    let (cert_body, _) = match hdr(der, 0) { Some(v) => v, None => return Vec::new() };
    let (tbs_body, _) = match hdr(der, cert_body) { Some(v) => v, None => return Vec::new() };
    let mut o = tbs_body;
    if o < der.len() && der[o] == 0xA0 {                       // optional explicit version
        let (b, l) = match hdr(der, o) { Some(v) => v, None => return Vec::new() };
        o = b + l;
    }
    let mut seen = 0usize;
    while o < der.len() {
        let (b, l) = match hdr(der, o) { Some(v) => v, None => return Vec::new() };
        let end = b + l;
        if end > der.len() { return Vec::new(); }
        // serial (INTEGER), sigAlg (SEQUENCE), issuer (SEQUENCE), validity (SEQUENCE), subject (SEQUENCE)
        if der[o] == 0x30 {
            seen += 1;
            if (which == 0 && seen == 2) || (which == 1 && seen == 4) {
                return der[o..end].to_vec();
            }
        }
        o = end;
    }
    Vec::new()
}

fn fetch_issuers(leaf: &[u8], relay_hint: bool) -> Vec<Vec<u8>> {
    let _ = relay_hint;
    // TAKE EVERY CERTIFICATE OFFERED, NOT THE FIRST ONE THAT ANSWERS. This walked a single path and
    // stopped at the first URL that returned anything, which assumes a certificate has exactly one
    // issuer worth fetching and that the first URL is the useful one. Neither holds: a certificate may
    // publish several access locations, a vendor may serve a cross-signed alternative at one of them,
    // and the path that closes to a pinned root may be the one we skipped. Collecting everything costs
    // a few HTTP requests once per enrolment and lets order_chain pick the path that actually links up.
    //
    // Breadth-first over what we have already fetched, bounded in BOTH directions — a certificate that
    // points at itself, or a pair that point at each other, otherwise walks forever.
    const MAX_FETCHES: usize = 16;
    const MAX_DEPTH: usize = 6;
    let mut out: Vec<Vec<u8>> = Vec::new();
    let mut frontier: Vec<Vec<u8>> = vec![leaf.to_vec()];
    let mut fetches = 0usize;
    for _depth in 0..MAX_DEPTH {
        let mut next: Vec<Vec<u8>> = Vec::new();
        for cert in &frontier {
            for url in urls_in(cert) {
                if fetches >= MAX_FETCHES {
                    break;
                }
                fetches += 1;
                if let Some(der) = http_get_der(&url) {
                    // already held, or the leaf itself coming back: nothing new to expand
                    if der == leaf || out.iter().any(|c| *c == der) {
                        continue;
                    }
                    out.push(der.clone());
                    next.push(der);
                }
            }
        }
        if next.is_empty() || fetches >= MAX_FETCHES {
            break;
        }
        frontier = next;
    }
    out
}

/// The http:// URLs a certificate points at.
///
/// AN AIA URL IS A LENGTH-PREFIXED IA5String, tag 0x86, and reading it as "graphic characters until
/// something that looks like a delimiter" walks straight off the end: the DER length and tag bytes that
/// follow are frequently printable, so the URL comes back with rubbish appended and the fetch 404s for
/// a reason invisible in the output. Take the declared length instead, and keep the scan only as a
/// fallback for a certificate whose encoding surprises us.
fn urls_in(der: &[u8]) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut i = 0usize;
    while i < der.len() {
        // BOTH SCHEMES. This looked for the literal "http://" only, so every https AIA was invisible:
        // AMD publishes over plain http and worked, Intel publishes over https and could never have its
        // chain completed at all. An Alder Lake machine was refused for that and for nothing else.
        let needle: &[u8] = if der[i..].starts_with(b"https://") {
            b"https://"
        } else if der[i..].starts_with(b"http://") {
            b"http://"
        } else {
            i += 1;
            continue;
        };
        let mut url: Option<String> = None;
        // 0x86 <len> "http://..."  — the GeneralName form AIA and CRL distribution points use.
        if i >= 2 && der[i - 2] == 0x86 {
            let len = der[i - 1] as usize;
            if len >= needle.len() && i + len <= der.len() {
                if let Ok(s) = std::str::from_utf8(&der[i..i + len]) {
                    url = Some(s.to_string());
                }
            }
        }
        if url.is_none() {
            let mut j = i;
            while j < der.len()
                && der[j].is_ascii_graphic()
                && !matches!(der[j], b',' | b'(' | b')' | b'<' | b'>' | b'"')
            {
                j += 1;
            }
            if let Ok(s) = std::str::from_utf8(&der[i..j]) {
                url = Some(s.trim_end_matches(|c: char| !c.is_ascii_alphanumeric()).to_string());
            }
        }
        if let Some(u) = url {
            let n = u.len();
            if n > 12 && !out.contains(&u) {
                out.push(u);
            }
            i += n.max(1);
        } else {
            i += 1;
        }
    }
    out
}

fn http_get_der(url: &str) -> Option<Vec<u8>> {
    // AN AIA FETCH NEEDS NO TLS, and refusing to make one without TLS is what broke Intel machines. The
    // object retrieved is a CERTIFICATE: it is verified by signature up to a root pinned in this binary,
    // so a tampered or substituted response fails verification exactly as a corrupt one does, and a
    // confidential channel protects nothing — the certificate is public by construction. RFC 5280 names
    // HTTP for this. Verified byte-for-byte: Intel serves the identical DER on port 80 and 443.
    //
    // This also keeps the client free of a TLS stack, which for a program people download and run is a
    // smaller thing to audit, not a corner cut.
    let rest = url.strip_prefix("https://").or_else(|| url.strip_prefix("http://"))?;
    let (hostport, path) = match rest.find('/') {
        Some(k) => (&rest[..k], &rest[k..]),
        None => (rest, "/"),
    };
    let relay = crate::http::Relay::parse_with_default(hostport, 80).ok()?;
    let bytes = relay.get_bytes(path).ok()?;
    // A certificate, not a CRL or an OCSP response: DER SEQUENCE with a long-form length, sane size.
    if bytes.len() > 256 && bytes[0] == 0x30 && bytes[1] == 0x82 {
        Some(bytes)
    } else {
        None
    }
}
