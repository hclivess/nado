//! Linux transport: the TPM character device.
//!
//! Every command byte is identical to the Windows path — a TPM speaks TCG Part 3 regardless of who hands it
//! the bytes — so this file is the entire Linux port. `src/tpm.rs` holds the commands and knows nothing about
//! either platform.
//!
//! PREFER /dev/tpmrm0. That is the kernel's resource manager: it virtualises transient handles, so our
//! primaries and policy sessions cannot collide with another process's, and it flushes what we leak if we
//! crash. /dev/tpm0 is the raw device — exclusive-open, no virtualisation, and a leaked transient handle there
//! wedges the chip for everything else on the machine until reboot. We fall back to it only when the resource
//! manager is absent (older kernels), and then FlushContext discipline is not optional.
#![allow(dead_code)]

use nado_tpm_attest::tpm::Tpm;
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::sync::Mutex;

/// Errors are reported in the same u32 space as the Windows transport so callers stay platform-blind. These
/// are ours, not the TPM's — a TPM response code is a value the chip returned, which means it was reached.
pub const ERR_NO_DEVICE: u32 = 0xFFFF_FF01;
pub const ERR_WRITE: u32 = 0xFFFF_FF02;
pub const ERR_READ: u32 = 0xFFFF_FF03;

pub struct DevTpm {
    /// One command in flight at a time: the device is a request/response channel, and interleaving two
    /// commands on one descriptor mixes their replies.
    dev: Mutex<File>,
    pub path: &'static str,
}

impl DevTpm {
    /// Open the resource manager, falling back to the raw device.
    pub fn open() -> Result<DevTpm, u32> {
        for path in ["/dev/tpmrm0", "/dev/tpm0"] {
            if let Ok(f) = OpenOptions::new().read(true).write(true).custom_flags(0).open(path) {
                return Ok(DevTpm { dev: Mutex::new(f), path });
            }
        }
        Err(ERR_NO_DEVICE)
    }

    /// True when a TPM is reachable at all — used to say "no TPM" rather than to fail obscurely later.
    pub fn present() -> bool {
        std::path::Path::new("/dev/tpmrm0").exists() || std::path::Path::new("/dev/tpm0").exists()
    }
}

impl Tpm for DevTpm {
    fn transmit(&self, cmd: &[u8]) -> Result<Vec<u8>, u32> {
        let mut dev = self.dev.lock().map_err(|_| ERR_WRITE)?;
        // The kernel takes ONE command per write() and returns ONE response per read(); a short write is a
        // failure rather than something to loop over, because a partial command is not a command.
        match dev.write(cmd) {
            Ok(n) if n == cmd.len() => {}
            _ => return Err(ERR_WRITE),
        }
        let mut buf = vec![0u8; 4096];
        let n = dev.read(&mut buf).map_err(|_| ERR_READ)?;
        buf.truncate(n);
        Ok(buf)
    }
}
