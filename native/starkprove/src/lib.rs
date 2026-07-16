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
//   [DONE] step 3  composition from the arena (sp_compose): invZ + boundary denominators + coset domain in
//                  Rust, air_ir SSA program over the retained col/periodic LDEs, cp retained — the linchpin.
//   [DONE] step 4  FRI over the retained cp (sp_fold + sp_commit_col + sp_open; transcript stays in Python).
//   [DONE] step 5  openings straight from the retained columns/trees (sp_read / sp_open).
//   [DONE] step 6  stark_native.prove — the whole prove via the arena, ALL modes (column + row-commit
//                  sp_commit_rows/rrow, single- + two-phase), byte-identical end-to-end vs stark.prove and the
//                  proofs verify (tests/test_starkprove.py). Wired into stark.prove for the RECURSION backend.
// COMPLETE: every stage bit-identical, gated by tests/test_starkprove.py.

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

// hashn(els) — the sponge with els already carrying its length prefix as els[0] (matches alghash2.py: els =
// [len] + elements). State = [0;RATE] ++ IV; absorb RATE lanes at a time (add into rate, permute); squeeze
// the first CAP lanes. Used by rrow (whole-row leaf) = hashn([len, DOM_LEAF, *row]).
fn hashn(els: &[u64]) -> [u64; CAP] {
    let mut state = [0u64; HW];
    unsafe {
        for k in 0..CAP {
            state[RATE + k] = IVH[k];
        }
    }
    let mut off = 0usize;
    while off < els.len() {
        let end = core::cmp::min(off + RATE, els.len());
        for i in 0..(end - off) {
            state[i] = addf(state[i], els[off + i]);
        }
        permute(&mut state);
        off += RATE;
    }
    [state[0], state[1], state[2], state[3]]
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

/// Load `len` values as a new arena column verbatim (no LDE) — e.g. a composition/evals vector computed
/// elsewhere, so FRI can fold it from the arena. Returns the column id.
///
/// # Safety
/// `in_ptr` must point to at least `len` readable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_load_col(in_ptr: *const u64, len: usize) -> i64 {
    let mut g = ARENA.lock().unwrap();
    let arena = match g.as_mut() {
        Some(a) => a,
        None => return -1,
    };
    if in_ptr.is_null() || len == 0 {
        return -1;
    }
    let vals = std::slice::from_raw_parts(in_ptr, len);
    arena.cols.push(vals.iter().map(|v| v % PU64).collect());
    (arena.cols.len() - 1) as i64
}

/// Number of columns retained.
#[no_mangle]
pub extern "C" fn sp_num_cols() -> i64 {
    let g = ARENA.lock().unwrap();
    g.as_ref().map(|a| a.cols.len() as i64).unwrap_or(-1)
}

/// One retained value ARENA[col][pos] (for openings + byte-identity checks). Uses the COLUMN's own length
/// (FRI fold layers are shorter than N). u64::MAX on out-of-range.
#[no_mangle]
pub extern "C" fn sp_read(col: usize, pos: usize) -> u64 {
    let g = ARENA.lock().unwrap();
    match g.as_ref() {
        Some(a) if col < a.cols.len() && pos < a.cols[col].len() => a.cols[col][pos],
        _ => u64::MAX,
    }
}

/// Length of a retained column (FRI layers shrink by half each fold). -1 on out-of-range.
#[no_mangle]
pub extern "C" fn sp_col_len(col: usize) -> i64 {
    let g = ARENA.lock().unwrap();
    match g.as_ref() {
        Some(a) if col < a.cols.len() => a.cols[col].len() as i64,
        _ => -1,
    }
}

/// One FRI fold of a retained column (step 4): evals of f on the coset {offset·ω^i} (size m) → evals of g on
/// the squared coset (size m/2), g(x²) = (f(x)+f(-x))/2 + α·(f(x)-f(-x))/(2x), the pair (x,−x) at (i, i+m/2).
/// Retains the folded column, returns its id. Byte-identical to fri._fold(evals, F.domain(m, offset), alpha).
#[no_mangle]
pub extern "C" fn sp_fold(col: usize, offset: u64, alpha: u64) -> i64 {
    let mut g = ARENA.lock().unwrap();
    let arena = match g.as_mut() {
        Some(a) => a,
        None => return -1,
    };
    if col >= arena.cols.len() {
        return -1;
    }
    let m = arena.cols[col].len();
    if m < 2 || (m & (m - 1)) != 0 {
        return -1;
    }
    let half = m / 2;
    let inv2 = inv(2);
    let omega = rou(m);
    let mut x = offset % PU64;
    let mut out = vec![0u64; half];
    for i in 0..half {
        let fx = arena.cols[col][i];
        let fmx = arena.cols[col][i + half];
        let fe = mulf(addf(fx, fmx), inv2);
        let fo = mulf(subf(fx, fmx), mulf(inv2, inv(x)));
        out[i] = addf(fe, mulf(alpha, fo));
        x = mulf(x, omega);
    }
    arena.cols.push(out);
    (arena.cols.len() - 1) as i64
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

/// ROW-commit: build ONE Merkle tree whose leaf j = rrow(row j) = hashn([1+w, DOM_LEAF, cols[ids[0]][j], …,
/// cols[ids[w-1]][j]]) across the given column group, inner nodes = rnode — the wide-trace enabler (one path
/// authenticates a whole opened row). Retains the tree, writes the CAP-lane root, returns the tree id (or -1).
/// Byte-identical to stark._row_tree(group, N) → merkle.commit_digests over RECURSION.
///
/// # Safety
/// `col_ids` must point to `w` usize; each must index a retained column of length arena.n; `root_ptr`, if
/// non-null, to CAP writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_commit_rows(col_ids: *const usize, w: usize, root_ptr: *mut u64) -> i64 {
    let mut g = ARENA.lock().unwrap();
    let arena = match g.as_mut() {
        Some(a) => a,
        None => return -1,
    };
    if !HASH_READY || w == 0 {
        return -1;
    }
    let ids = std::slice::from_raw_parts(col_ids, w);
    for &c in ids {
        if c >= arena.cols.len() {
            return -1;
        }
    }
    let n = arena.cols[ids[0]].len();
    if n < 1 || (n & (n - 1)) != 0 {
        return -1;
    }
    let mut digs: Vec<[u64; CAP]> = Vec::with_capacity(2 * n - 1);
    let mut els = vec![0u64; w + 2];
    els[0] = (w as u64) + 1; // len([DOM_LEAF, *row]) = 1 + w
    els[1] = 1; // DOM_LEAF
    for j in 0..n {
        for (k, &c) in ids.iter().enumerate() {
            els[2 + k] = arena.cols[c][j];
        }
        digs.push(hashn(&els));
    }
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

// air_ir SSA opcodes — MUST match execnode/stark/air_ir.py (and native/starkcompose).
const OP_CUR: u32 = 0;
const OP_NXT: u32 = 1;
const OP_PER: u32 = 2;
const OP_CHAL: u32 = 3;
const OP_CONST: u32 = 4;
const OP_ADD: u32 = 5;
const OP_SUB: u32 = 6;
const OP_MUL: u32 = 7;
const OP_POW: u32 = 8;

/// Composition polynomial straight from the arena (step 3). Reads the retained LDE columns (trace/aux at arena
/// indices 0..w, periodic at w..w+nper), computes invZ + boundary denominators + the coset domain IN RUST, runs
/// the air_ir SSA program over the size-N domain, and RETAINS cp as a new arena column (returns its id; also
/// writes it to `out_ptr` if non-null). Byte-identical to stark._composition → air_ir.compose_native: the field
/// inverses are unique so invZ/denominators match regardless of method, and the SSA loop mirrors starkcompose.
///
/// # Safety
/// All pointers must reference the stated element counts; the arena must already hold ≥ w+nper columns.
#[no_mangle]
pub unsafe extern "C" fn sp_compose(
    n_ops: usize, ops: *const u32,
    n_consts: usize, consts: *const u64,
    n_out: usize, outputs: *const u32,
    w: usize, nper: usize, nchal: usize,
    chals: *const u64,
    alphas: *const u64,          // n_out + n_bnd
    n_bnd: usize,
    bnd_col: *const u32,         // n_bnd
    bnd_val: *const u64,         // n_bnd
    bnd_row: *const u64,         // n_bnd (trace-domain row index of each boundary)
    t: usize, blowup: usize, offset: u64,
    out_ptr: *mut u64,
) -> i64 {
    let mut g = ARENA.lock().unwrap();
    let arena = match g.as_mut() {
        Some(a) => a,
        None => return -1,
    };
    let n = arena.n;
    if n == 0 || t == 0 || w + nper > arena.cols.len() {
        return -1;
    }
    let ops = std::slice::from_raw_parts(ops, n_ops * 3);
    let consts = std::slice::from_raw_parts(consts, n_consts.max(1));
    let outputs = std::slice::from_raw_parts(outputs, n_out.max(1));
    let chals = std::slice::from_raw_parts(chals, nchal.max(1));
    let alphas = std::slice::from_raw_parts(alphas, n_out + n_bnd);
    let bnd_col = std::slice::from_raw_parts(bnd_col, n_bnd.max(1));
    let bnd_val = std::slice::from_raw_parts(bnd_val, n_bnd.max(1));
    let bnd_row = std::slice::from_raw_parts(bnd_row, n_bnd.max(1));

    // operand-bounds validation (same codes as native/starkcompose)
    for i in 0..n_ops {
        let (op, a, b) = (ops[i * 3], ops[i * 3 + 1] as usize, ops[i * 3 + 2] as usize);
        let bad = match op {
            OP_CUR | OP_NXT => a >= w,
            OP_PER => a >= nper,
            OP_CHAL => a >= nchal,
            OP_CONST => a >= n_consts,
            OP_ADD | OP_SUB | OP_MUL => a >= i || b >= i,
            OP_POW => a >= i,
            _ => true,
        };
        if bad {
            return 2;
        }
    }
    for &o in outputs.iter().take(n_out) {
        if (o as usize) >= n_ops {
            return 3;
        }
    }
    for bi in 0..n_bnd {
        if (bnd_col[bi] as usize) >= w {
            return 4;
        }
    }

    let omega = rou(n);
    let g_t = rou(t);
    let last = powf(g_t, (t - 1) as u64);
    // g_t^row per boundary (small; dedup would help but the value is what matters, not the count)
    let grow: Vec<u64> = (0..n_bnd).map(|bi| powf(g_t, bnd_row[bi])).collect();

    let mut cp = vec![0u64; n];
    let mut temp = vec![0u64; n_ops];
    let mut x = offset % PU64;
    for j in 0..n {
        let jn = (j + blowup) % n;
        for i in 0..n_ops {
            let (op, a, b) = (ops[i * 3], ops[i * 3 + 1] as usize, ops[i * 3 + 2] as usize);
            temp[i] = match op {
                OP_CUR => arena.cols[a][j],
                OP_NXT => arena.cols[a][jn],
                OP_PER => arena.cols[w + a][j],
                OP_CHAL => chals[a],
                OP_CONST => consts[a],
                OP_ADD => addf(temp[a], temp[b]),
                OP_SUB => subf(temp[a], temp[b]),
                OP_MUL => mulf(temp[a], temp[b]),
                OP_POW => powf(temp[a], b as u64),
                _ => 0,
            };
        }
        // transition part: (Σ_t alpha_t · con_t) · invZ,  invZ = (x - last)/(x^T - 1)
        let mut acc = 0u64;
        for k in 0..n_out {
            acc = addf(acc, mulf(alphas[k], temp[outputs[k] as usize]));
        }
        let xt = powf(x, t as u64);
        let inv_z = mulf(subf(x, last), inv(subf(xt, 1)));
        let mut v = mulf(acc, inv_z);
        // boundary part: Σ_b alpha_{nout+b} · (col_b[j] - val_b) / (x - g_t^row_b)
        for bi in 0..n_bnd {
            let col = bnd_col[bi] as usize;
            let diff = subf(arena.cols[col][j], bnd_val[bi]);
            let invden = inv(subf(x, grow[bi]));
            v = addf(v, mulf(mulf(alphas[n_out + bi], diff), invden));
        }
        cp[j] = v;
        x = mulf(x, omega);
    }
    if !out_ptr.is_null() {
        std::ptr::copy_nonoverlapping(cp.as_ptr(), out_ptr, n);
    }
    arena.cols.push(cp);
    (arena.cols.len() - 1) as i64
}

/// Release the arena (free retained columns + trees).
#[no_mangle]
pub extern "C" fn sp_free() {
    let mut g = ARENA.lock().unwrap();
    *g = None;
}
