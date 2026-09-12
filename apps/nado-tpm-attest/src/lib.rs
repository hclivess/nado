//! The parts of the attester that are pure logic — no Windows, no TPM — so they can be built and tested on
//! the Linux fleet host instead of only on the target machine. The CBOR encoding, authData layout and digests
//! are exactly where a silent mistake would produce a statement the chain rejects for reasons that look like
//! a hardware problem, so they get tested where testing is cheap.
pub mod chip;
pub mod colour;
#[cfg(unix)]
pub mod devtpm;
pub mod enrol;
pub mod http;
pub mod sha;
#[cfg(windows)]
pub mod tbs;
pub mod tpm;
pub mod tx;
pub mod webauthn;
#[cfg(windows)]
pub mod win;

/// Fill `buf` with cryptographic randomness.
///
/// ONE PLACE, BOTH PLATFORMS, NO DEPENDENCY. This feeds the ML-DSA signing hedge, so a weak or
/// predictable source here is a real key-recovery risk rather than a style question — which is why it
/// reads the OS generator directly on each platform instead of anything seeded in-process.
pub fn rand_bytes(buf: &mut [u8]) {
    #[cfg(unix)]
    {
        use std::io::Read;
        let mut f = std::fs::File::open("/dev/urandom").expect("open /dev/urandom");
        f.read_exact(buf).expect("read /dev/urandom");
    }
    #[cfg(windows)]
    {
        // RtlGenRandom, exported from advapi32 under its ordinal name. Present on every supported
        // Windows and needs no CryptoAPI context.
        #[link(name = "advapi32")]
        extern "system" {
            #[link_name = "SystemFunction036"]
            fn rtl_gen_random(buf: *mut u8, len: u32) -> u8;
        }
        let ok = unsafe { rtl_gen_random(buf.as_mut_ptr(), buf.len() as u32) };
        assert!(ok != 0, "RtlGenRandom failed");
    }
}
