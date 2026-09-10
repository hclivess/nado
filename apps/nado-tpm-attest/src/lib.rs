//! The parts of the attester that are pure logic — no Windows, no TPM — so they can be built and tested on
//! the Linux fleet host instead of only on the target machine. The CBOR encoding, authData layout and digests
//! are exactly where a silent mistake would produce a statement the chain rejects for reasons that look like
//! a hardware problem, so they get tested where testing is cheap.
pub mod sha;
pub mod tpm;
pub mod webauthn;
