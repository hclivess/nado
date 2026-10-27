//! THE NODE'S ENTRY POINT (stable build, no prover): verify a settlement VM proof against a statement. execnode/stark/
//! stwo_settle_native.py binds it with ctypes; the statement is vm::parse_statement's text, which the node's verifier
//! (execnode/settle_b2.py) builds itself from its replay, and the proof is wire::encode's bytes, the prover's.
//!
//! rc 0: the proof verifies. rc 1: refused (the reason in `out`). rc 2: bad arguments or an unparsable statement (a
//! caller error, not a verdict). A panic on adversarial bytes is a refusal (catch_unwind, panic = "unwind" in Cargo.toml's
//! release profile, the default), never a crash of the node.
use std::panic::{AssertUnwindSafe, catch_unwind};

use crate::blake::vm_air::{node_config, verify_vm};
use crate::{vm, wire};

pub const RC_OK: i32 = 0;
pub const RC_REFUSED: i32 = 1;
pub const RC_BAD_ARGS: i32 = 2;

unsafe fn bytes<'a>(p: *const u8, n: usize) -> &'a [u8] {
    if n == 0 { &[] } else { unsafe { std::slice::from_raw_parts(p, n) } }
}

/// The verdict for (statement text, proof bytes), with its reason.
pub fn verify_bytes(stmt: &[u8], proof: &[u8]) -> (i32, String) {
    let Ok(text) = std::str::from_utf8(stmt) else { return (RC_BAD_ARGS, "statement is not UTF-8".into()) };
    let st = match vm::parse_statement(text) {
        Ok(st) => st,
        Err(e) => return (RC_BAD_ARGS, format!("statement: {e}")),
    };
    let p = match wire::decode(proof) {
        Ok(p) => p,
        Err(e) => return (RC_REFUSED, format!("decode {e:?}")),
    };
    match catch_unwind(AssertUnwindSafe(|| verify_vm(&st, p, node_config()))) {
        Ok(Ok(())) => (RC_OK, String::new()),
        Ok(Err(e)) => (RC_REFUSED, format!("{e:?}")),
        Err(_) => (RC_REFUSED, "verifier panicked".into()),
    }
}

/// `out`/`out_cap`: a buffer for the reason (UTF-8, truncated to fit; may be null with cap 0).
#[unsafe(no_mangle)]
pub extern "C" fn nado_stwo_settle_verify(stmt: *const u8, stmt_len: usize, proof: *const u8, proof_len: usize,
                                          out: *mut u8, out_cap: usize) -> i32 {
    if (stmt.is_null() && stmt_len != 0) || (proof.is_null() && proof_len != 0) || (out.is_null() && out_cap != 0) {
        return RC_BAD_ARGS;
    }
    let (rc, why) = match catch_unwind(AssertUnwindSafe(|| verify_bytes(unsafe { bytes(stmt, stmt_len) },
                                                                          unsafe { bytes(proof, proof_len) }))) {
        Ok(r) => r,
        Err(_) => (RC_REFUSED, "verifier panicked".into()),
    };
    let n = why.len().min(out_cap);
    if n > 0 {
        unsafe { std::ptr::copy_nonoverlapping(why.as_ptr(), out, n) };
    }
    rc
}

/// The ABI version: a caller refuses a library whose version it does not know.
#[unsafe(no_mangle)]
pub extern "C" fn nado_stwo_settle_abi() -> u32 {
    1
}
