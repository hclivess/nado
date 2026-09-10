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
    pub fn ek_certificate(&mut self) -> Result<Option<Vec<u8>>, String> {
        Ok(tpm::ek_certificate(self.t.as_ref()))
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
