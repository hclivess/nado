//! NADO native ML-DSA-44 backend (matches the Rust prover pattern in wasm/goldilocks).
//!
//! A cdylib exposing exactly the three FIPS 204 *INTERNAL*-mode primitives signatures.py's
//! native-backend seam expects, over a plain C ABI (bound by nado_pq_native.py via ctypes,
//! stdlib-only — no pyo3). "Internal" = NO context/domain wrapping (empty message-prefix), the
//! convention dilithium-py and the browser's @noble/post-quantum sign in, so signatures
//! cross-verify with every existing on-chain signature. The Python startup interop self-test
//! cross-checks this both ways before the backend is ever adopted; a mismatch falls back to
//! pure-Python and can never split consensus.
//!
//! Built via scripts/build_pq_native.sh (`cargo build --release`), same as the Goldilocks lib.

use ml_dsa::{MlDsa44, Signature, SigningKey, ExpandedSigningKey, VerifyingKey, B32,
              EncodedVerifyingKey, EncodedSignature, ExpandedSigningKeyBytes};
use ml_dsa::common::KeyExport;   // brings `.encode()` on VerifyingKey into scope
use ml_dsa::Keypair;             // brings `.verifying_key()` on SigningKey into scope

// ML-DSA-44 (FIPS 204) sizes — asserted against the buffers Python passes.
const SEED: usize = 32;
const PK: usize = 1312;
const SK: usize = 2560;   // Algorithm 24 skEncode (standard) — byte-identical to dilithium-py
const SIG: usize = 2420;
const RND: usize = 32;

/// FIPS 204 KeyGen_internal(seed) -> writes 1312-byte pk and 2560-byte standard-encoded sk.
/// Byte-identical to dilithium-py's _keygen_internal for the same seed (addresses derive from pk).
/// Returns 0 on success, non-zero on a bad pointer/size.
#[no_mangle]
pub extern "C" fn nado_keygen_internal(pk_out: *mut u8, sk_out: *mut u8, seed_in: *const u8) -> i32 {
    if pk_out.is_null() || sk_out.is_null() || seed_in.is_null() {
        return 1;
    }
    let seed_slice = unsafe { std::slice::from_raw_parts(seed_in, SEED) };
    let seed = match B32::try_from(seed_slice) {
        Ok(s) => s,
        Err(_) => return 2,
    };
    let sk = SigningKey::<MlDsa44>::from_seed(&seed);
    let pk_bytes = sk.verifying_key().encode();
    #[allow(deprecated)]
    let sk_bytes = sk.expanded_key().to_expanded();   // Algorithm 24 skEncode (standard FIPS 204)
    unsafe {
        std::ptr::copy_nonoverlapping(pk_bytes.as_ptr(), pk_out, PK);
        std::ptr::copy_nonoverlapping(sk_bytes.as_ptr(), sk_out, SK);
    }
    0
}

/// FIPS 204 Sign_internal (empty prefix) with the caller's 32-byte hedge `rnd`. Writes a 2420-byte
/// signature; sets *siglen. Returns 0 on success.
#[no_mangle]
pub extern "C" fn nado_sign_internal(sig_out: *mut u8, siglen_out: *mut usize,
                                     m_in: *const u8, mlen: usize,
                                     rnd_in: *const u8, sk_in: *const u8) -> i32 {
    if sig_out.is_null() || siglen_out.is_null() || rnd_in.is_null() || sk_in.is_null() {
        return 1;
    }
    let sk_slice = unsafe { std::slice::from_raw_parts(sk_in, SK) };
    let sk_bytes = match ExpandedSigningKeyBytes::<MlDsa44>::try_from(sk_slice) {
        Ok(s) => s,
        Err(_) => return 2,
    };
    #[allow(deprecated)]
    let esk = ExpandedSigningKey::<MlDsa44>::from_expanded(&sk_bytes);
    let rnd_slice = unsafe { std::slice::from_raw_parts(rnd_in, RND) };
    let rnd = match B32::try_from(rnd_slice) {
        Ok(r) => r,
        Err(_) => return 3,
    };
    let msg = if mlen == 0 { &[][..] } else { unsafe { std::slice::from_raw_parts(m_in, mlen) } };
    // sign_internal takes message PARTS that get concatenated; one part == the whole message,
    // matching dilithium-py's single-message _sign_internal.
    let sig = esk.sign_internal(&[msg], &rnd);
    let enc = sig.encode();
    unsafe {
        std::ptr::copy_nonoverlapping(enc.as_ptr(), sig_out, SIG);
        *siglen_out = SIG;
    }
    0
}

/// FIPS 204 Verify_internal (empty prefix). Returns 0 iff the signature is valid, non-zero otherwise
/// (mirrors the pq-crystals C convention nado_pq_native.py checks: `== 0` means valid).
#[no_mangle]
pub extern "C" fn nado_verify_internal(sig_in: *const u8, siglen: usize,
                                       m_in: *const u8, mlen: usize, pk_in: *const u8) -> i32 {
    if sig_in.is_null() || pk_in.is_null() || siglen != SIG {
        return 1;
    }
    let pk_slice = unsafe { std::slice::from_raw_parts(pk_in, PK) };
    let pk_bytes = match EncodedVerifyingKey::<MlDsa44>::try_from(pk_slice) {
        Ok(p) => p,
        Err(_) => return 2,
    };
    let vk = VerifyingKey::<MlDsa44>::decode(&pk_bytes);
    let sig_slice = unsafe { std::slice::from_raw_parts(sig_in, SIG) };
    let sig = match Signature::<MlDsa44>::try_from(sig_slice) {
        Ok(s) => s,
        Err(_) => return 3,   // malformed signature -> invalid, never a panic
    };
    let msg = if mlen == 0 { &[][..] } else { unsafe { std::slice::from_raw_parts(m_in, mlen) } };
    if vk.verify_internal(msg, &sig) { 0 } else { 4 }
}
