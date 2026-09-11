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
    t: Box<dyn Tpm>,
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
        let mut chain = tpm::ek_chain(self.t.as_ref());
        #[cfg(windows)]
        if chain.is_empty() {
            chain = crate::win::ek_certificates_from_registry();
            if !chain.is_empty() {
                println!("  chip       endorsement certificate came from the Windows certificate store");
                println!("             (this chip holds none in its own NV — normal for an AMD fTPM)");
            }
        }
        if chain.len() == 1 {
            // A LEAF ON ITS OWN IS AN INCOMPLETE CHAIN. AMD's endorsement certificate reaches its root
            // through an intermediate that is on neither the chip nor the machine, so without this the
            // verifier is handed a path it cannot close and the machine is refused for a reason that has
            // nothing to do with its hardware.
            let extra = fetch_issuers(&chain[0], true);
            if !extra.is_empty() {
                println!("  chip       fetched {} issuing certificate(s) from the vendor", extra.len());
                chain.extend(extra);
            }
        }
        Ok(chain)
    }

    pub fn ek_public(&mut self) -> Result<Vec<u8>, String> {
        let (h, pubarea, _) = tpm::create_primary(self.t.as_ref(), RH_ENDORSEMENT, &tpm::ek_template())
            .map_err(|e| format!("could not derive the endorsement key (0x{e:08x})"))?;
        tpm::flush(self.t.as_ref(), h).ok();
        Ok(pubarea)
    }

    pub fn aik_public(&mut self) -> Result<Vec<u8>, String> {
        let (h, pubarea, _) = tpm::create_primary(self.t.as_ref(), RH_ENDORSEMENT, &tpm::aik_template())
            .map_err(|e| format!("could not derive the attestation key (0x{e:08x})"))?;
        tpm::flush(self.t.as_ref(), h).ok();
        Ok(pubarea)
    }

    /// Open one challenger's credential. The chip returns the secret ONLY because both the endorsement
    /// key and the attestation key are objects inside it — that is the entire proof.
    pub fn activate_credential(&mut self, blob: &[u8], enc_seed: &[u8]) -> Result<Vec<u8>, String> {
        let t = self.t.as_ref();
        let (ek, _, _) = tpm::create_primary(t, RH_ENDORSEMENT, &tpm::ek_template())
            .map_err(|e| format!("endorsement key (0x{e:08x})"))?;
        let (aik, _, _) = match tpm::create_primary(t, RH_ENDORSEMENT, &tpm::aik_template()) {
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
        let t = self.t.as_ref();
        let (aik, _, _) = tpm::create_primary(t, RH_ENDORSEMENT, &tpm::aik_template())
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
fn fetch_issuers(leaf: &[u8], relay_hint: bool) -> Vec<Vec<u8>> {
    let _ = relay_hint;
    let mut out: Vec<Vec<u8>> = Vec::new();
    let mut current = leaf.to_vec();
    for _ in 0..4 {
        let mut got: Option<Vec<u8>> = None;
        for url in urls_in(&current) {
            if let Some(der) = http_get_der(&url) {
                // Do not walk into a certificate we already hold, and stop at a self-signed root.
                if out.iter().any(|c| *c == der) || der == leaf {
                    continue;
                }
                got = Some(der);
                break;
            }
        }
        match got {
            Some(der) => {
                current = der.clone();
                out.push(der);
            }
            None => break,
        }
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
    let needle = b"http://";
    let mut out: Vec<String> = Vec::new();
    let mut i = 0usize;
    while i + needle.len() < der.len() {
        if &der[i..i + needle.len()] != needle {
            i += 1;
            continue;
        }
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
    let rest = url.strip_prefix("http://")?;
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
