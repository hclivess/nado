// Native STARK composition (doc/zk-recursion.md §3.2 — the native prover). Evaluates the constraint-IR built
// by execnode/stark/air_ir.py over the whole size-N LDE domain and forms the composition polynomial, EXACTLY
// as stark._composition does — the same field arithmetic (Goldilocks, reduce mod P at every op), just off the
// Python interpreter. Purely functional: every input is passed by pointer, all scratch is a reused Vec, no
// static state → reentrant, no lock needed (unlike the static-buffer goldilocks NTT lib).
//
// The IR is SSA: ops[i] = (op, a, b). Leaves load a trace column / periodic column / challenge / constant;
// binary ops reference earlier temps; POW's b is a small immediate exponent. temp[i] holds op i's value.
// cp[j] = ( Σ_t alphas[t]·con_t(j) )·invZ[j]  +  Σ_b alphas[nt+b]·(col_{cb}[j] − val_b)·invden_b[j].

const P: u128 = 0xFFFFFFFF00000001; // 2^64 - 2^32 + 1

#[inline(always)]
fn mulf(a: u64, b: u64) -> u64 {
    (((a as u128) * (b as u128)) % P) as u64
}
#[inline(always)]
fn addf(a: u64, b: u64) -> u64 {
    (((a as u128) + (b as u128)) % P) as u64
}
#[inline(always)]
fn subf(a: u64, b: u64) -> u64 {
    (((a as u128) + P - (b as u128)) % P) as u64
}
// base^exp mod P — square-and-multiply, bit-identical to Python pow(base, exp, P).
#[inline(always)]
fn powf(mut base: u64, mut exp: u64) -> u64 {
    let mut acc: u64 = 1;
    base %= P as u64;
    while exp > 0 {
        if exp & 1 == 1 {
            acc = mulf(acc, base);
        }
        base = mulf(base, base);
        exp >>= 1;
    }
    acc
}

// opcodes — MUST match execnode/stark/air_ir.py
const CUR: u32 = 0;
const NXT: u32 = 1;
const PER: u32 = 2;
const CHAL: u32 = 3;
const CONST: u32 = 4;
const ADD: u32 = 5;
const SUB: u32 = 6;
const MUL: u32 = 7;
const POW: u32 = 8;

/// Evaluate the composition. All arrays are borrowed from Python (ctypes); `out` (len n) is written.
/// Returns 0 on success, a nonzero code on a malformed program (so Python can fall back rather than trust
/// garbage). See air_ir.compose_native for the exact argument packing.
#[no_mangle]
pub unsafe extern "C" fn compose(
    n_ops: usize,
    ops: *const u32,        // n_ops * 3  (op, a, b)
    n_consts: usize,
    consts: *const u64,     // n_consts
    n_out: usize,
    outputs: *const u32,    // n_out  (temp indices)
    w: usize,
    nper: usize,
    nchal: usize,
    n: usize,               // N (LDE size)
    blowup: usize,
    cols: *const u64,       // w * n
    per: *const u64,        // nper * n
    chals: *const u64,      // nchal
    alphas: *const u64,     // n_out + n_bnd
    inv_z: *const u64,      // n
    n_bnd: usize,
    bnd_col: *const u32,    // n_bnd
    bnd_val: *const u64,    // n_bnd
    bnd_invden: *const u64, // n_bnd * n
    out: *mut u64,          // n
) -> i32 {
    let ops = core::slice::from_raw_parts(ops, n_ops * 3);
    let consts = core::slice::from_raw_parts(consts, n_consts);
    let outputs = core::slice::from_raw_parts(outputs, n_out);
    let cols = core::slice::from_raw_parts(cols, w * n);
    let per = core::slice::from_raw_parts(per, nper * n);
    let chals = core::slice::from_raw_parts(chals, nchal);
    let alphas = core::slice::from_raw_parts(alphas, n_out + n_bnd);
    let inv_z = core::slice::from_raw_parts(inv_z, n);
    let bnd_col = core::slice::from_raw_parts(bnd_col, n_bnd);
    let bnd_val = core::slice::from_raw_parts(bnd_val, n_bnd);
    let bnd_invden = core::slice::from_raw_parts(bnd_invden, n_bnd * n);
    let out = core::slice::from_raw_parts_mut(out, n);

    // validate operand bounds ONCE (a leaf index out of range would be UB / wrong field values)
    for i in 0..n_ops {
        let op = ops[i * 3];
        let a = ops[i * 3 + 1] as usize;
        let b = ops[i * 3 + 2] as usize;
        let bad = match op {
            CUR | NXT => a >= w,
            PER => a >= nper,
            CHAL => a >= nchal,
            CONST => a >= n_consts,
            ADD | SUB | MUL => a >= i || b >= i, // SSA: operands precede
            POW => a >= i,
            _ => true,
        };
        if bad {
            return 1;
        }
    }
    for &o in outputs {
        if (o as usize) >= n_ops {
            return 2;
        }
    }
    for bi in 0..n_bnd {
        if (bnd_col[bi] as usize) >= w {
            return 3;
        }
    }

    let mut temp = vec![0u64; n_ops];
    for j in 0..n {
        let jn = if blowup == 0 { j } else { (j + blowup) % n };
        for i in 0..n_ops {
            let op = ops[i * 3];
            let a = ops[i * 3 + 1] as usize;
            let b = ops[i * 3 + 2] as usize;
            temp[i] = match op {
                CUR => cols[a * n + j],
                NXT => cols[a * n + jn],
                PER => per[a * n + j],
                CHAL => chals[a],
                CONST => consts[a],
                ADD => addf(temp[a], temp[b]),
                SUB => subf(temp[a], temp[b]),
                MUL => mulf(temp[a], temp[b]),
                POW => powf(temp[a], b as u64),
                _ => 0,
            };
        }
        let mut acc: u64 = 0;
        for t in 0..n_out {
            acc = addf(acc, mulf(alphas[t], temp[outputs[t] as usize]));
        }
        let mut v = mulf(acc, inv_z[j]);
        for bi in 0..n_bnd {
            let col = bnd_col[bi] as usize;
            let diff = subf(cols[col * n + j], bnd_val[bi]);
            v = addf(v, mulf(mulf(alphas[n_out + bi], diff), bnd_invden[bi * n + j]));
        }
        out[j] = v;
    }
    0
}
