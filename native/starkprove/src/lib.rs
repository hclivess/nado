// NADO holistic native STARK prover — the PERSISTENT LDE ARENA (step 1 of the end-to-end Rust prover).
//
// The Python prover (execnode/stark/stark.py) computes every low-degree-extension column with the shared-buffer
// native NTT (wasm/goldilocks) but MARSHALS each result back into a Python list — so W column-LDEs + the
// periodic LDEs + the composition all live simultaneously as Python int lists (~28 bytes/element × N). For a
// wide/deep RECURSION proof (comp-over-fold: W≈21, N≈10^5) that is the memory wall.
//
// This crate keeps the LDE columns in Rust Vec<u64> ARENA across the prove, so Python holds only handles. It is
// native-only (std — the browser keeps the per-kernel wasm path) and BIT-IDENTICAL to stark.py: sp_lde_column
// reproduces `_coset_evaluate(F.interpolate(col), N, OFF)` exactly (interpolate = inverse NTT over the T-domain;
// coset-eval = zero-pad to N, scale coeff j by OFF^j, forward NTT). Verified field-for-field by
// tests/test_starkprove.py before anything depends on it.
//
// ROADMAP (each stage bit-identity-gated by tests/test_starkprove.py before anything depends on it):
//   [DONE] step 1  persistent LDE arena + fused native interpolate→coset-eval (sp_lde_column / sp_read).
//   [DONE] step 2  Merkle commit + open from the arena, RECURSION backend rleaf/rnode (sp_commit_col / sp_open).
//   [TODO] step 3  composition from the arena: compute invZ + boundary denominators + x_lde in Rust, evaluate
//                  the air_ir constraint program over the retained col/periodic LDEs, retain cp — so col_lde /
//                  per_lde never become Python lists (the linchpin: this is what actually lowers PEAK memory).
//   [TODO] step 4  FRI (fold layers + commit + query) over the retained cp.
//   [TODO] step 5  openings straight from the retained trees at the FRI query positions.
//   [TODO] step 6  an opt-in orchestrator (execnode/stark) that runs the whole prove via the arena — transcript
//                  stays in Python (a few hashes) — and an END-TO-END bit-identity test vs stark.prove, then
//                  row-commit + two-phase. Only when that passes does the default prover switch over.
// Default stark.prove is untouched until the whole path is proven byte-for-byte.

use std::sync::Mutex;

const P: u128 = 0xFFFFFFFF00000001;
const PU64: u64 = 0xFFFFFFFF00000001;
const EPSILON: u64 = 0xFFFFFFFF; // 2^32 - 1 ( = 2^64 mod p )
const GENERATOR: u64 = 7; // matches field.py primitive_root_of_unity (7^((p-1)/n))

// Fast Goldilocks reduction of a 128-bit product to [0, p), no division. Copied verbatim from wasm/goldilocks
// so the field multiply is byte-identical to the NTT the rest of the stack already uses.
#[inline(always)]
fn reduce128(x: u128) -> u64 {
    let x_lo = x as u64;
    let x_hi = (x >> 64) as u64;
    let x_hi_hi = x_hi >> 32;
    let x_hi_lo = x_hi & 0xFFFFFFFF;
    let (mut t0, borrow) = x_lo.overflowing_sub(x_hi_hi);
    if borrow {
        t0 = t0.wrapping_sub(EPSILON);
    }
    let t1 = x_hi_lo.wrapping_mul(EPSILON);
    let (res, carry) = t0.overflowing_add(t1);
    let mut r = res.wrapping_add(EPSILON * (carry as u64));
    if r >= PU64 {
        r -= PU64;
    }
    r
}

#[inline(always)]
fn mulf(a: u64, b: u64) -> u64 {
    reduce128((a as u128) * (b as u128))
}
#[inline(always)]
fn addf(a: u64, b: u64) -> u64 {
    (((a as u128) + (b as u128)) % P) as u64
}
#[inline(always)]
fn subf(a: u64, b: u64) -> u64 {
    (((a as u128) + P - (b as u128)) % P) as u64
}

// base^exp mod p (square-and-multiply) — for root-of-unity + inverse computation.
fn powf(mut base: u64, mut exp: u64) -> u64 {
    base %= PU64;
    let mut r: u64 = 1;
    while exp > 0 {
        if exp & 1 == 1 {
            r = mulf(r, base);
        }
        base = mulf(base, base);
        exp >>= 1;
    }
    r
}

#[inline]
fn inv(x: u64) -> u64 {
    powf(x, PU64 - 2)
}

// Primitive n-th root of unity, n a power of two — identical to field.primitive_root_of_unity.
#[inline]
fn rou(n: usize) -> u64 {
    powf(GENERATOR, ((PU64 as u128 - 1) / (n as u128)) as u64)
}

fn bitrev(a: &mut [u64], n: usize) {
    let mut j = 0usize;
    let mut i = 1usize;
    while i < n {
        let mut bit = n >> 1;
        while j & bit != 0 {
            j ^= bit;
            bit >>= 1;
        }
        j ^= bit;
        if i < j {
            a.swap(i, j);
        }
        i += 1;
    }
}

// In-place iterative NTT on a[0..n] (n = a.len(), a power of two). Same butterfly schedule as wasm/goldilocks
// and field.ntt — twiddles t[j] = root^j, decimation-in-time. inverse ⇒ scale by n^-1 at the end.
fn ntt(a: &mut [u64], inverse: bool) {
    let n = a.len();
    if n <= 1 {
        return;
    }
    let root = if inverse { inv(rou(n)) } else { rou(n) };
    bitrev(a, n);
    let h = n >> 1;
    let mut tw = vec![0u64; h.max(1)];
    tw[0] = 1;
    let mut j = 1;
    while j < h {
        tw[j] = mulf(tw[j - 1], root);
        j += 1;
    }
    let mut length = 2;
    while length <= n {
        let half = length >> 1;
        let stride = n / length;
        let mut i = 0;
        while i < n {
            let mut m = 0;
            while m < half {
                let t = tw[m * stride];
                let k = i + m;
                let u = a[k];
                let v = mulf(a[k + half], t);
                a[k] = addf(u, v);
                a[k + half] = subf(u, v);
                m += 1;
            }
            i += length;
        }
        length <<= 1;
    }
    if inverse {
        let n_inv = inv(n as u64);
        for x in a.iter_mut() {
            *x = mulf(*x, n_inv);
        }
    }
}

// The LDE of one trace column: interpolate (inverse NTT over the size-T domain) → zero-pad to N → scale coeff j
// by offset^j → forward NTT. Byte-identical to `_coset_evaluate(F.interpolate(vals), N, OFF)`.
fn lde_column(vals: &[u64], n: usize, offset: u64) -> Vec<u64> {
    let t = vals.len();
    let mut coeffs: Vec<u64> = vals.iter().map(|v| v % PU64).collect();
    ntt(&mut coeffs, true); // interpolate: coeffs[0..t]
    let mut buf = vec![0u64; n];
    // coset scale in coefficient order: buf[j] = coeffs[j] * offset^j
    let mut s = 1u64;
    for j in 0..t {
        buf[j] = mulf(coeffs[j], s);
        s = mulf(s, offset);
    }
    ntt(&mut buf, false); // forward NTT over the size-N coset
    buf
}

// ---- alghash2 (RECURSION backend) — the Merkle hash ---------------------------------------------------------
// Width-12 wide sponge, RATE 8, CAPACITY 4, ROUNDS 8, x^7 S-box. The round constants / IV / MDS are the
// nothing-up-my-sleeve values Python computes (blake2b of labels) and hands in via sp_init — the SAME ones it
// hands to native/alghash2 — so this permute is byte-identical to alghash2.py.permute. rleaf/rnode reproduce
// alghash2.py exactly (guarded by tests/test_starkprove.py against merkle.commit over the RECURSION backend).
const HW: usize = 12;
const HR: usize = 8;
const RATE: usize = 8;
const CAP: usize = 4;
static mut RC: [[u64; HW]; HR] = [[0; HW]; HR];
static mut IVH: [u64; CAP] = [0; CAP];
static mut MDS: [[u64; HW]; HW] = [[0; HW]; HW];
static mut HASH_READY: bool = false;

#[inline(always)]
fn pow7(x: u64) -> u64 {
    let x2 = mulf(x, x);
    let x3 = mulf(x2, x);
    let x6 = mulf(x3, x3);
    mulf(x6, x)
}

#[inline(always)]
fn permute(s: &mut [u64; HW]) {
    unsafe {
        for r in 0..HR {
            let mut t = [0u64; HW];
            for i in 0..HW {
                t[i] = pow7(addf(s[i], RC[r][i]));
            }
            for i in 0..HW {
                let mut acc: u128 = 0;
                for j in 0..HW {
                    acc += mulf(MDS[i][j], t[j]) as u128;
                }
                s[i] = (acc % P) as u64;
            }
        }
    }
}

// rleaf(x) = permute([DOM_LEAF=1, x, 0×6, IV])[:CAP]; rnode(a,b) = permute([a(4)|b(4)|IV])[:CAP].
#[inline]
fn rleaf(x: u64) -> [u64; CAP] {
    let mut s = [0u64; HW];
    s[0] = 1;
    s[1] = x % PU64;
    unsafe {
        for k in 0..CAP {
            s[RATE + k] = IVH[k];
        }
    }
    permute(&mut s);
    [s[0], s[1], s[2], s[3]]
}

#[inline]
fn rnode(a: &[u64; CAP], b: &[u64; CAP]) -> [u64; CAP] {
    let mut s = [0u64; HW];
    unsafe {
        for k in 0..CAP {
            s[k] = a[k];
            s[CAP + k] = b[k];
            s[RATE + k] = IVH[k];
        }
    }
    permute(&mut s);
    [s[0], s[1], s[2], s[3]]
}

/// Install the alghash2 round constants / IV / MDS (Python passes the SAME arrays it passes to native/alghash2).
///
/// # Safety
/// `rc` must point to HR*HW u64, `iv` to CAP u64, `mds` to HW*HW u64.
#[no_mangle]
pub unsafe extern "C" fn sp_init(rc: *const u64, iv: *const u64, mds: *const u64) {
    for r in 0..HR {
        for i in 0..HW {
            RC[r][i] = *rc.add(r * HW + i);
        }
    }
    for i in 0..CAP {
        IVH[i] = *iv.add(i);
    }
    for i in 0..HW {
        for j in 0..HW {
            MDS[i][j] = *mds.add(i * HW + j);
        }
    }
    HASH_READY = true;
}

// A retained Merkle tree: n leaves + all bottom-up layer digests concatenated (2n-1 digests, CAP lanes each),
// the same flat layout native/alghash2::rmerkle_commit produces, so open walks it identically.
struct Tree {
    n: usize,
    digs: Vec<[u64; CAP]>, // len 2n-1
}

// ---- persistent arena --------------------------------------------------------------------------------------
struct Arena {
    t: usize,
    n: usize,
    offset: u64,
    cols: Vec<Vec<u64>>, // each an LDE column of length n
    trees: Vec<Tree>,    // Merkle trees committed from those columns
}

static ARENA: Mutex<Option<Arena>> = Mutex::new(None);

/// Start a new proof: record geometry and clear any retained columns.
#[no_mangle]
pub extern "C" fn sp_reset(t: usize, n: usize, offset: u64) {
    let mut g = ARENA.lock().unwrap();
    *g = Some(Arena {
        t,
        n,
        offset,
        cols: Vec::new(),
        trees: Vec::new(),
    });
}

/// Compute the LDE of one trace column (T values at `in_ptr`), RETAIN it in the arena, and (if `out_ptr` is
/// non-null) also write the N-length result there. Returns the column index, or -1 on error.
///
/// # Safety
/// `in_ptr` must point to at least T readable u64; `out_ptr`, if non-null, to at least N writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_lde_column(in_ptr: *const u64, out_ptr: *mut u64) -> i64 {
    let mut g = ARENA.lock().unwrap();
    let arena = match g.as_mut() {
        Some(a) => a,
        None => return -1,
    };
    let (t, n, offset) = (arena.t, arena.n, arena.offset);
    if in_ptr.is_null() || t == 0 || n == 0 {
        return -1;
    }
    let vals = std::slice::from_raw_parts(in_ptr, t);
    let lde = lde_column(vals, n, offset);
    if !out_ptr.is_null() {
        std::ptr::copy_nonoverlapping(lde.as_ptr(), out_ptr, n);
    }
    arena.cols.push(lde);
    (arena.cols.len() - 1) as i64
}

/// Number of columns retained.
#[no_mangle]
pub extern "C" fn sp_num_cols() -> i64 {
    let g = ARENA.lock().unwrap();
    g.as_ref().map(|a| a.cols.len() as i64).unwrap_or(-1)
}

/// One retained LDE value ARENA[col][pos] (for openings + byte-identity checks). u64::MAX on out-of-range.
#[no_mangle]
pub extern "C" fn sp_read(col: usize, pos: usize) -> u64 {
    let g = ARENA.lock().unwrap();
    match g.as_ref() {
        Some(a) if col < a.cols.len() && pos < a.n => a.cols[col][pos],
        _ => u64::MAX,
    }
}

/// Merkle-commit a RETAINED LDE column (RECURSION backend: leaf = rleaf(value), inner = rnode(l,r)). Retains
/// the whole tree for opening, writes the CAP-lane root to `root_ptr`, returns the tree id (or -1 on error).
/// Byte-identical to merkle.commit(col_lde[col], backend.RECURSION).
///
/// # Safety
/// `root_ptr`, if non-null, must point to at least CAP writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_commit_col(col: usize, root_ptr: *mut u64) -> i64 {
    let mut g = ARENA.lock().unwrap();
    let arena = match g.as_mut() {
        Some(a) => a,
        None => return -1,
    };
    if !HASH_READY || col >= arena.cols.len() {
        return -1;
    }
    let n = arena.cols[col].len();
    if n < 1 || (n & (n - 1)) != 0 {
        return -1;
    }
    let mut digs: Vec<[u64; CAP]> = Vec::with_capacity(2 * n - 1);
    for i in 0..n {
        digs.push(rleaf(arena.cols[col][i]));
    }
    // inner layers, bottom-up, appended after the leaves (same flat layout as native rmerkle_commit)
    let mut layer_start = 0usize;
    let mut layer_len = n;
    while layer_len > 1 {
        let half = layer_len / 2;
        for i in 0..half {
            let a = digs[layer_start + 2 * i];
            let b = digs[layer_start + 2 * i + 1];
            digs.push(rnode(&a, &b));
        }
        layer_start += layer_len;
        layer_len = half;
    }
    let root = digs[digs.len() - 1];
    if !root_ptr.is_null() {
        for k in 0..CAP {
            *root_ptr.add(k) = root[k];
        }
    }
    arena.trees.push(Tree { n, digs });
    (arena.trees.len() - 1) as i64
}

/// Authentication path (sibling digests, bottom-up) for leaf `pos` of retained tree `tree`. Writes
/// path_len·CAP u64 to `out_ptr` and returns path_len (= log2 n), or -1 on error. Byte-identical to
/// merkle.open_at(layers, pos).
///
/// # Safety
/// `out_ptr` must point to at least log2(n)·CAP writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_open(tree: usize, pos: usize, out_ptr: *mut u64) -> i64 {
    let g = ARENA.lock().unwrap();
    let arena = match g.as_ref() {
        Some(a) => a,
        None => return -1,
    };
    if tree >= arena.trees.len() {
        return -1;
    }
    let t = &arena.trees[tree];
    if pos >= t.n {
        return -1;
    }
    let mut layer_start = 0usize;
    let mut layer_len = t.n;
    let mut idx = pos;
    let mut written = 0i64;
    while layer_len > 1 {
        let sib = t.digs[layer_start + (idx ^ 1)];
        for k in 0..CAP {
            *out_ptr.add((written as usize) * CAP + k) = sib[k];
        }
        written += 1;
        layer_start += layer_len;
        layer_len /= 2;
        idx /= 2;
    }
    written
}

/// Release the arena (free retained columns + trees).
#[no_mangle]
pub extern "C" fn sp_free() {
    let mut g = ARENA.lock().unwrap();
    *g = None;
}
