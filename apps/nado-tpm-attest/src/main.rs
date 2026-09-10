//! nado-tpm-attest — see src/imp.rs and doc/windows-tpm-attester.md.
//!
//! The Windows implementation is gated so the crate still builds on the Linux fleet host, where the pure
//! parts (CBOR, authData, digests) are unit-tested. A hand-written encoder that is only ever exercised on a
//! user's PC fails there as an unexplainable rejection; tested here it fails as a test.

#[cfg(windows)]
mod imp;
#[cfg(windows)]
mod tpm;
#[cfg(windows)]
mod win;

#[cfg(windows)]
fn main() {
    imp::main();
}

#[cfg(not(windows))]
fn main() {
    eprintln!("nado-tpm-attest runs on Windows: it talks to the TPM through the Platform Crypto Provider.");
}
