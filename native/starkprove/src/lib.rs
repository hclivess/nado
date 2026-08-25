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

use std::collections::HashMap;
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

// Batch inverse (Montgomery's trick): one field inversion + 3n muls instead of n Fermat inversions. The RESULT
// is the unique inverse of each element, so it is byte-identical to inverting each individually / to
// field.batch_inverse — just far cheaper (the composition's dominant setup cost at recursion scale). Inputs
// must be nonzero (the coset offset guarantees the composition denominators never vanish, exactly as the
// Python path assumes).
fn batch_inverse(vals: &[u64]) -> Vec<u64> {
    let n = vals.len();
    if n == 0 {
        return Vec::new();
    }
    let mut prefix = vec![1u64; n + 1];
    for i in 0..n {
        prefix[i + 1] = mulf(prefix[i], vals[i]);
    }
    let mut acc = inv(prefix[n]);
    let mut out = vec![0u64; n];
    for i in (0..n).rev() {
        out[i] = mulf(prefix[i], acc);
        acc = mulf(acc, vals[i]);
    }
    out
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
// Width-12 wide sponge, RATE 8, CAPACITY 4, ROUNDS 54, x^7 S-box. The round constants / IV / MDS are the
// nothing-up-my-sleeve values Python computes (blake2b of labels) and hands in via sp_init — the SAME ones it
// hands to native/alghash2 — so this permute is byte-identical to alghash2.py.permute. rleaf/rnode reproduce
// alghash2.py exactly (guarded by tests/test_starkprove.py against merkle.commit over the RECURSION backend).
const HW: usize = 12;
const HR: usize = 54;  // alghash2 full rounds — MUST match execnode/stark/alghash2.py ROUNDS (7^54 ≥ 2^128)
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
/// ARENA GENERATION. Column/tree ids are raw positions into the arena, and sp_reset restarts them from 0 —
/// so an id captured by one prove and used after another prove's reset does not fail, it silently aliases a
/// DIFFERENT column (the class of bug the Python-side _LOCK exists to prevent). The generation makes that
/// detectable: sp_reset bumps and returns it, sp_gen reads it, and the Python wrapper refuses to touch the
/// arena when the generation it reset is no longer the live one.
static GEN: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// Start a new proof: record geometry and clear any retained columns. Returns the new arena generation.
#[no_mangle]
pub extern "C" fn sp_reset(t: usize, n: usize, offset: u64) -> u64 {
    let mut g = ARENA.lock().unwrap();
    *g = Some(Arena {
        t,
        n,
        offset,
        cols: Vec::new(),
        trees: Vec::new(),
    });
    GEN.fetch_add(1, std::sync::atomic::Ordering::SeqCst) + 1
}

/// The live arena generation (see GEN).
#[no_mangle]
pub extern "C" fn sp_gen() -> u64 {
    GEN.load(std::sync::atomic::Ordering::SeqCst)
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

// ---- GF(p^D) = F_p[X]/(X^D - NONRESIDUE) ---------------------------------------------------------
// The arena stores columns as Vec<u64>, so an EXTENSION-valued column is carried as D arena columns
// (limb 0 .. limb D-1) meaning c0 + c1*X + ... — the same limb-tuple representation the Python side uses,
// which is what lets a proof move between them unchanged.
//
// This exists because the extension migration otherwise costs the arena entirely: stark_native refuses an
// ext request (it would emit a proof stark.verify could never accept), so every ext proof composed and
// folded in PYTHON. That is 2.8x slower and, far worse, materializes every LDE column as a Python list —
// the K->1 settlement fold OOM-killed at 20.8 GB resident against a ~15 GB budget. Keeping the columns in
// Rust is what makes folding feasible at all, not merely faster.
//
// WRITTEN FOR ARBITRARY D, NOT HAND-EXPANDED. The degree-2 version expanded the product by hand and
// destructured every value as a 2-tuple, so raising the degree meant editing every line that touched an
// extension element — in Python that same shape hid 118 assumptions across 16 files, five of which were
// SILENT (wrong answer, no error). Here the degree is one const and the arithmetic is a generic
// convolution, so a future degree change is a one-line edit that either compiles or does not.
const EXT_DEGREE: usize = 3;
const NONRESIDUE: u64 = 3;      // X^3 - 3 is irreducible over Goldilocks (checked in extf.py at import)

type Ext = [u64; EXT_DEGREE];

const EXT_ZERO: Ext = [0u64; EXT_DEGREE];

/// The extension DEGREE this library was compiled for. The Python side must refuse to use the arena when
/// this disagrees with extf.DEGREE: the symbols existing says nothing about which field they implement, and
/// a degree-mismatched arena does not fail — it composes a perfectly well-formed polynomial over the WRONG
/// field, which then fails verification far from the cause. (Observed exactly this: a degree-2 arena against
/// a degree-3 Python side reported "trace/composition mismatch" with nothing pointing at the field.)
#[no_mangle]
pub extern "C" fn sp_ext_degree() -> i64 {
    EXT_DEGREE as i64
}

/// The NONRESIDUE, exported for the same reason as the degree: two libraries can agree on D and still be
/// different fields. Python checks both before it will touch the arena.
#[no_mangle]
pub extern "C" fn sp_ext_nonresidue() -> u64 {
    NONRESIDUE
}

#[inline]
fn e_add(a: Ext, b: Ext) -> Ext {
    let mut o = EXT_ZERO;
    for i in 0..EXT_DEGREE {
        o[i] = addf(a[i], b[i]);
    }
    o
}

#[inline]
fn e_sub(a: Ext, b: Ext) -> Ext {
    let mut o = EXT_ZERO;
    for i in 0..EXT_DEGREE {
        o[i] = subf(a[i], b[i]);
    }
    o
}

#[inline]
fn e_mul(a: Ext, b: Ext) -> Ext {
    // Polynomial product reduced mod X^D - NONRESIDUE: terms of degree >= D wrap with a NONRESIDUE factor,
    // since X^(D+k) = NONRESIDUE * X^k. Same convolution extf.mul computes, limb for limb.
    let mut acc = [0u64; 2 * EXT_DEGREE - 1];
    for i in 0..EXT_DEGREE {
        if a[i] != 0 {
            for j in 0..EXT_DEGREE {
                acc[i + j] = addf(acc[i + j], mulf(a[i], b[j]));
            }
        }
    }
    let mut o = EXT_ZERO;
    o.copy_from_slice(&acc[..EXT_DEGREE]);
    for k in EXT_DEGREE..(2 * EXT_DEGREE - 1) {
        if acc[k] != 0 {
            o[k - EXT_DEGREE] = addf(o[k - EXT_DEGREE], mulf(NONRESIDUE, acc[k]));
        }
    }
    o
}

#[inline]
fn e_scalar(a: Ext, s: u64) -> Ext {
    // Extension times a BASE scalar — one multiply per limb, no cross terms. This is the per-row hot path
    // (every constraint value scaled by invZ, every fold by 1/2x), so it stays linear in D.
    let mut o = EXT_ZERO;
    for i in 0..EXT_DEGREE {
        o[i] = mulf(a[i], s);
    }
    o
}

/// Read D limbs out of a caller-supplied buffer, reducing each. Returns None if the caller passed a limb
/// count that is not the compiled degree — which means it believes in a different field, and quietly using
/// the first D of them (or zero-padding) would compose over that wrong field without any error.
#[inline]
unsafe fn ext_from_raw(p: *const u64, n: usize) -> Option<Ext> {
    if p.is_null() || n != EXT_DEGREE {
        return None;
    }
    let s = std::slice::from_raw_parts(p, n);
    let mut o = EXT_ZERO;
    for i in 0..EXT_DEGREE {
        o[i] = s[i] % PU64;
    }
    Some(o)
}

/// One FRI fold of an EXTENSION-valued column: the D columns named by `cols` -> the folded D columns,
/// retained in the arena. Returns the LIMB-0 column id; limb k is always at that id + k, so one return
/// value suffices and the caller needs no out-param.
///
/// Identical statement to sp_fold, over GF(p^D): g(x^2) = (f(x)+f(-x))/2 + alpha*(f(x)-f(-x))/(2x), with x
/// a BASE domain point (so the /2x scaling stays a scalar multiply) and alpha the only extension factor.
/// Byte-identical to fri._fold_ext.
///
/// `n_cols` and `n_alpha` are passed and CHECKED rather than assumed: they are how a Python side built for
/// a different degree gets rejected at the call instead of silently folding over the wrong field.
#[no_mangle]
pub unsafe extern "C" fn sp_fold_ext(cols: *const usize, n_cols: usize, offset: u64,
                                     alpha: *const u64, n_alpha: usize) -> i64 {
    if cols.is_null() || n_cols != EXT_DEGREE {
        return -1;
    }
    let alpha = match ext_from_raw(alpha, n_alpha) {
        Some(a) => a,
        None => return -1,
    };
    let ids = std::slice::from_raw_parts(cols, n_cols);
    let mut g = ARENA.lock().unwrap();
    let arena = match g.as_mut() {
        Some(a) => a,
        None => return -1,
    };
    for &c in ids {
        if c >= arena.cols.len() {
            return -1;
        }
    }
    let m = arena.cols[ids[0]].len();
    if m < 2 || (m & (m - 1)) != 0 {
        return -1;
    }
    for &c in ids {
        if arena.cols[c].len() != m {
            return -1;
        }
    }
    let half = m / 2;
    let inv2 = inv(2);
    let omega = rou(m);
    let mut x = offset % PU64;
    let mut out: Vec<Vec<u64>> = (0..EXT_DEGREE).map(|_| vec![0u64; half]).collect();
    for i in 0..half {
        let mut fx = EXT_ZERO;
        let mut fmx = EXT_ZERO;
        for d in 0..EXT_DEGREE {
            fx[d] = arena.cols[ids[d]][i];
            fmx[d] = arena.cols[ids[d]][i + half];
        }
        let fe = e_scalar(e_add(fx, fmx), inv2);
        let fo = e_scalar(e_sub(fx, fmx), mulf(inv2, inv(x)));
        let v = e_add(fe, e_mul(alpha, fo));
        for d in 0..EXT_DEGREE {
            out[d][i] = v[d];
        }
        x = mulf(x, omega);
    }
    let first = arena.cols.len();
    for c in out {
        arena.cols.push(c);
    }
    first as i64
}

/// Everything sp_compose and sp_compose_ext derive from GEOMETRY alone — the coset points, the transition
/// vanishing inverse, and the per-boundary denominators (deduped by row, since recursion AIRs pin many lanes
/// at the same row). Extracted so the two composers share one implementation of it: they differ ONLY in how
/// constraint values are combined with the alphas, and duplicating the setup is how the base and extension
/// paths would silently drift into computing different quotients.
struct ComposeSetup {
    inv_z: Vec<u64>,
    den_vecs: Vec<Vec<u64>>,
    bnd_den_idx: Vec<usize>,
}

fn compose_setup(n: usize, t: usize, offset: u64, n_bnd: usize, bnd_row: &[u64]) -> ComposeSetup {
    let omega = rou(n);
    let g_t = rou(t);
    let last = powf(g_t, (t - 1) as u64);
    let mut xs = vec![0u64; n];
    {
        let mut x = offset % PU64;
        for j in 0..n {
            xs[j] = x;
            x = mulf(x, omega);
        }
    }
    let xtm1: Vec<u64> = xs.iter().map(|&x| subf(powf(x, t as u64), 1)).collect();
    let inv_xtm1 = batch_inverse(&xtm1);
    let inv_z: Vec<u64> = (0..n).map(|j| mulf(subf(xs[j], last), inv_xtm1[j])).collect();

    let mut uniq: Vec<u64> = Vec::new();
    let mut row_to_idx: HashMap<u64, usize> = HashMap::new();
    let mut bnd_den_idx = vec![0usize; n_bnd];
    for bi in 0..n_bnd {
        let r = bnd_row[bi];
        let idx = *row_to_idx.entry(r).or_insert_with(|| {
            uniq.push(r);
            uniq.len() - 1
        });
        bnd_den_idx[bi] = idx;
    }
    let den_vecs: Vec<Vec<u64>> = uniq
        .iter()
        .map(|&r| {
            let grow_r = powf(g_t, r);
            let diffs: Vec<u64> = xs.iter().map(|&x| subf(x, grow_r)).collect();
            batch_inverse(&diffs)
        })
        .collect();
    ComposeSetup { inv_z, den_vecs, bnd_den_idx }
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

// ALGHASH2-backend Merkle (the DEFAULT backend): leaf = hashn([2, DOM_LEAF, x]); inner = hashn([9, DOM_NODE,
// a(4), b(4)]) — byte-identical to alghash2.leaf/node (merkle.commit over backend.ALGHASH2).
#[inline]
fn a2_leaf(x: u64) -> [u64; CAP] {
    hashn(&[2, 1, x % PU64])
}
#[inline]
fn a2_node(a: &[u64; CAP], b: &[u64; CAP]) -> [u64; CAP] {
    hashn(&[9, 2, a[0], a[1], a[2], a[3], b[0], b[1], b[2], b[3]])
}

// ---- PARALLEL Merkle tree building --------------------------------------------------------------------
// Column/row commits dominated fold/composition proving wall-clock (~80% in profiles): single-threaded
// hashing on a multi-core box. Leaf hashing and every inner layer are embarrassingly parallel and PURE
// (permute reads only the init-time constants), so scoped std threads split them into per-thread chunks —
// NO new dependencies, and byte-identical output BY CONSTRUCTION (parallelism changes scheduling, never a
// single hashed value). Threshold-gated so small trees keep the cheaper serial loop. NADO_NATIVE_THREADS
// caps the fan-out (default: all cores).

const PAR_MIN: usize = 2048; // below this many leaves a serial build wins

fn nthreads() -> usize {
    std::env::var("NADO_NATIVE_THREADS")
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or_else(|| std::thread::available_parallelism().map(|v| v.get()).unwrap_or(1))
        .max(1)
}

// BLAKE2B digest <-> CAP lanes. A blake2b digest is 32 raw bytes; the arena carries CAP=4 u64 per digest,
// so lane k holds bytes[8k..8k+8] BIG-ENDIAN. That is a pure bijection, chosen so reconstructing the bytes
// for the next level is exact -- the hash input at every inner node must be the RAW child digests, exactly
// as backend._Blake2b.node does with bytes.fromhex(a).
#[inline(always)]
fn b2b_lanes(d: &[u8; 32]) -> [u64; CAP] {
    let mut o = [0u64; CAP];
    for k in 0..CAP {
        let mut w = [0u8; 8];
        w.copy_from_slice(&d[k * 8..k * 8 + 8]);
        o[k] = u64::from_be_bytes(w);
    }
    o
}
#[inline(always)]
fn b2b_bytes(l: &[u64; CAP]) -> [u8; 32] {
    let mut d = [0u8; 32];
    for k in 0..CAP { d[k * 8..k * 8 + 8].copy_from_slice(&l[k].to_be_bytes()); }
    d
}
// leaf(x) = blake2b32(0x00 || x_le64); node(a,b) = blake2b32(0x01 || a || b). Domain tags match
// execnode/stark/backend.py _Blake2b exactly -- leaf and node spaces must stay disjoint.
#[inline]
fn b2b_leaf(x: u64) -> [u64; CAP] {
    let mut buf = [0u8; 9];
    buf[0] = 0x00;
    buf[1..9].copy_from_slice(&(x % PU64).to_le_bytes());
    b2b_lanes(&blake2b32(&buf))
}
// EXTENSION leaf: its own frame tag (0x02), so a lifted base value and a genuine base value can never share
// a digest -- otherwise one tree's opening could be presented against the other's commitment.
#[inline]
fn b2b_leaf_ext(limbs: &[u64]) -> [u64; CAP] {
    let mut buf = [0u8; 1 + 8 * 8];
    buf[0] = 0x02;
    for (k, v) in limbs.iter().enumerate() {
        buf[1 + k * 8..9 + k * 8].copy_from_slice(&(v % PU64).to_le_bytes());
    }
    b2b_lanes(&blake2b32(&buf[..1 + 8 * limbs.len()]))
}

#[inline]
fn b2b_node(a: &[u64; CAP], b: &[u64; CAP]) -> [u64; CAP] {
    let mut buf = [0u8; 65];
    buf[0] = 0x01;
    buf[1..33].copy_from_slice(&b2b_bytes(a));
    buf[33..65].copy_from_slice(&b2b_bytes(b));
    b2b_lanes(&blake2b32(&buf))
}

// MODE: 0 = RECURSION (rleaf/rnode), 1 = ALGHASH2 (hashn), 2 = BLAKE2B. It was a bool while only the two
// alghash2 flavours existed; the shielded pool proves under BLAKE2B and had no native path at all.
#[inline]
fn node_hash(a: &[u64; CAP], b: &[u64; CAP], mode: u32) -> [u64; CAP] {
    match mode {
        1 => a2_node(a, b),
        2 => b2b_node(a, b),
        _ => rnode(a, b),
    }
}

/// Build the flat 2n-1 digest tree (leaves, then each inner layer bottom-up — the exact layout the serial
/// builder produced, so sp_open walks it identically) from a leaf function. `a2` picks the inner-node hash.
///
/// PARALLEL-SUBTREES: the tree splits into `s` (power of two ≤ cores) complete subtrees of m = n/s leaves;
/// ONE thread scope builds every subtree fully locally (its leaves + all its inner layers — ~(2m−1)/(2n−1)
/// of the total hashing each, no synchronization), then each local layer is memcpy'd into its slot of the
/// global flat layout and the top s−1 nodes finish serially. Near-linear scaling, and every hashed VALUE is
/// identical to the serial build (only the schedule changes).
fn build_tree<F>(n: usize, a2: u32, leaf: F) -> Vec<[u64; CAP]>
where
    F: Fn(usize) -> [u64; CAP] + Sync,
{
    let mut digs = vec![[0u64; CAP]; 2 * n - 1];
    let nt = nthreads();
    let mut s = 1usize;
    while s * 2 <= nt && n / (s * 2) >= 256 {
        s *= 2;
    }
    if n < PAR_MIN || s < 2 {
        for i in 0..n {
            digs[i] = leaf(i);
        }
        let mut layer_start = 0usize;
        let mut layer_len = n;
        while layer_len > 1 {
            let half = layer_len / 2;
            for i in 0..half {
                let a = digs[layer_start + 2 * i];
                let b = digs[layer_start + 2 * i + 1];
                digs[layer_start + layer_len + i] = node_hash(&a, &b, a2);
            }
            layer_start += layer_len;
            layer_len = half;
        }
        return digs;
    }
    let m = n / s; // leaves per subtree (both powers of two ⇒ exact)
    let locals: Vec<Vec<[u64; CAP]>> = std::thread::scope(|scope| {
        let handles: Vec<_> = (0..s)
            .map(|t| {
                let leaf = &leaf;
                scope.spawn(move || {
                    let base = t * m;
                    let mut ld = vec![[0u64; CAP]; 2 * m - 1];
                    for i in 0..m {
                        ld[i] = leaf(base + i);
                    }
                    let mut ls = 0usize;
                    let mut ll = m;
                    while ll > 1 {
                        let half = ll / 2;
                        for i in 0..half {
                            let a = ld[ls + 2 * i];
                            let b = ld[ls + 2 * i + 1];
                            ld[ls + ll + i] = node_hash(&a, &b, a2);
                        }
                        ls += ll;
                        ll = half;
                    }
                    ld
                })
            })
            .collect();
        handles.into_iter().map(|h| h.join().unwrap()).collect()
    });
    // gather: subtree t's local layer j (len m>>j) sits in global layer j at offset t·(m>>j)
    let mut g_start = 0usize; // global start of layer j (global len n>>j)
    let mut l_start = 0usize; // local start of layer j
    let mut ll = m; // local layer len at j
    loop {
        for (t, ld) in locals.iter().enumerate() {
            let dst = g_start + t * ll;
            digs[dst..dst + ll].copy_from_slice(&ld[l_start..l_start + ll]);
        }
        if ll == 1 {
            break;
        }
        g_start += ll * s;
        l_start += ll;
        ll /= 2;
    }
    // top of the tree: from the size-s layer of subtree roots (at g_start) up to the root, serially
    let mut layer_start = g_start;
    let mut layer_len = s;
    while layer_len > 1 {
        let half = layer_len / 2;
        for i in 0..half {
            let a = digs[layer_start + 2 * i];
            let b = digs[layer_start + 2 * i + 1];
            digs[layer_start + layer_len + i] = node_hash(&a, &b, a2);
        }
        layer_start += layer_len;
        layer_len = half;
    }
    digs
}

/// PARALLEL, DETERMINISTIC transcript proof-of-work: the smallest nonce whose
/// hashn([dom, s0..s3, nonce]) digest has `bits` leading zero bits. Scans rounds of nt·CHUNK nonces across
/// scoped threads and returns the MINIMUM valid nonce of the first round with a hit — identical to the
/// sequential 0,1,2,… first-hit (which IS the smallest valid nonce), so proofs stay byte-identical to the
/// serial native/alghash2 grind and the pure-Python loop. hashn is pure after sp_init.
///
/// # Safety
/// `state` must point to CAP readable u64; sp_init must have been called (else u64::MAX is returned).
#[no_mangle]
pub unsafe extern "C" fn sp_grind(state: *const u64, dom: u64, bits: u32) -> u64 {
    if !HASH_READY {
        return u64::MAX;
    }
    let base = [*state, *state.add(1), *state.add(2), *state.add(3)];
    let shift = if bits >= 64 { 0u32 } else { 64 - bits };
    let try_nonce = move |nonce: u64| -> bool {
        let els = [CAP as u64 + 2, dom, base[0], base[1], base[2], base[3], nonce];
        let out = hashn(&els);
        if bits >= 64 {
            out[0] == 0
        } else {
            (out[0] >> shift) == 0
        }
    };
    let nt = nthreads();
    if nt < 2 {
        let mut nonce: u64 = 0;
        loop {
            if try_nonce(nonce) {
                return nonce;
            }
            if nonce == u64::MAX {
                return u64::MAX;
            }
            nonce += 1;
        }
    }
    const CHUNK: u64 = 4096; // per-thread nonces per round
    let mut round_start: u64 = 0;
    loop {
        let found: Vec<Option<u64>> = std::thread::scope(|s| {
            let handles: Vec<_> = (0..nt as u64)
                .map(|t| {
                    let try_nonce = &try_nonce;
                    s.spawn(move || {
                        let lo = round_start.saturating_add(t * CHUNK);
                        let hi = lo.saturating_add(CHUNK);
                        for nonce in lo..hi {
                            if try_nonce(nonce) {
                                return Some(nonce);
                            }
                        }
                        None
                    })
                })
                .collect();
            handles.into_iter().map(|h| h.join().unwrap()).collect()
        });
        if let Some(min) = found.into_iter().flatten().min() {
            return min;
        }
        match round_start.checked_add(nt as u64 * CHUNK) {
            Some(next) => round_start = next,
            None => return u64::MAX,
        }
    }
}

/// Merkle-commit a RETAINED LDE column. `hash_mode` 0 = RECURSION (leaf rleaf, inner rnode), 1 = ALGHASH2
/// (leaf hashn([2,1,x]), inner hashn([9,2,a,b])) — the DEFAULT backend. Retains the whole tree for opening,
/// writes the CAP-lane root, returns the tree id (or -1). Byte-identical to merkle.commit(col_lde[col], b);
/// hashing is PARALLEL across each tree level (build_tree).
///
/// # Safety
/// `root_ptr`, if non-null, must point to at least CAP writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_commit_col(col: usize, root_ptr: *mut u64, hash_mode: u32) -> i64 {
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
    let a2 = hash_mode;
    let digs = {
        let vals: &[u64] = &arena.cols[col];
        build_tree(n, a2, |i| {
            let x = vals[i];
            match a2 {
                1 => a2_leaf(x),
                2 => b2b_leaf(x),
                _ => rleaf(x),
            }
        })
    };
    let root = digs[2 * n - 2];
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
    // row leaves in parallel (each row hashes [1+w, DOM_LEAF, row…]; per-call els buffer keeps threads
    // independent), inner rnode layers via the shared parallel builder — layout + values unchanged.
    let digs = {
        let cols_ref: Vec<&[u64]> = ids.iter().map(|&c| arena.cols[c].as_slice()).collect();
        let w64 = w as u64;
        build_tree(n, 0, |j| {
            let mut els = vec![0u64; w + 2];
            els[0] = w64 + 1; // len([DOM_LEAF, *row]) = 1 + w
            els[1] = 1; // DOM_LEAF
            for (k, c) in cols_ref.iter().enumerate() {
                els[2 + k] = c[j];
            }
            hashn(&els)
        })
    };
    let root = digs[2 * n - 2];
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

    let ComposeSetup { inv_z, den_vecs, bnd_den_idx } = compose_setup(n, t, offset, n_bnd, bnd_row);

    let mut cp = vec![0u64; n];
    let mut temp = vec![0u64; n_ops];
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
        // transition part: (Σ_t alpha_t · con_t) · invZ
        let mut acc = 0u64;
        for k in 0..n_out {
            acc = addf(acc, mulf(alphas[k], temp[outputs[k] as usize]));
        }
        let mut v = mulf(acc, inv_z[j]);
        // boundary part: Σ_b alpha_{nout+b} · (col_b[j] - val_b) / (xs[j] - g_t^row_b)
        for bi in 0..n_bnd {
            let col = bnd_col[bi] as usize;
            let diff = subf(arena.cols[col][j], bnd_val[bi]);
            let invden = den_vecs[bnd_den_idx[bi]][j];
            v = addf(v, mulf(mulf(alphas[n_out + bi], diff), invden));
        }
        cp[j] = v;
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

/// EXTENSION composition (step 4, GF(p^2)). Same statement as sp_compose, with the alphas — and therefore
/// the composition polynomial — extension-valued.
///
/// The SSA interpretation stays BASE. That is the point of the limb-pair representation: an
/// extension-valued constraint contributes its D COMPONENTS as D consecutive outputs (`ext_pairs` holds
/// each group's first index, mirroring air_ir's), so the constraint program itself needs no extension opcode
/// and only the alpha combination widens. One alpha per LOGICAL constraint — NOT one per output, which is
/// the off-by-one that would silently misalign every constraint past the first extension one. ("pair" is
/// the degree-2 name kept for the wire field; a group is D wide.)
///
/// `alphas` is D*(n_logical + n_bnd) limbs, limb-interleaved per element. `out`, if non-null, receives
/// D*n values LIMB-MAJOR (all of limb 0, then all of limb 1, ...). All D limb columns are retained in the
/// arena and the LIMB-0 id is returned; limb k sits at that id + k, as in sp_fold_ext.
#[no_mangle]
pub unsafe extern "C" fn sp_compose_ext(
    n_ops: usize, ops: *const u32,
    n_consts: usize, consts: *const u64,
    n_out: usize, outputs: *const u32,
    n_pairs: usize, ext_pairs: *const u32,
    w: usize, nper: usize, nchal: usize,
    chals: *const u64,
    alphas: *const u64,          // EXT_DEGREE * (n_logical + n_bnd)
    n_bnd: usize,
    bnd_col: *const u32,
    bnd_val: *const u64,
    bnd_row: *const u64,
    t: usize, blowup: usize, offset: u64,
    degree: usize,               // caller's extf.DEGREE — checked, never assumed
    out: *mut u64,               // EXT_DEGREE * n, limb-major; may be null
) -> i64 {
    if degree != EXT_DEGREE {
        return 7;
    }
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
    let pairs = std::slice::from_raw_parts(ext_pairs, n_pairs.max(1));
    let chals = std::slice::from_raw_parts(chals, nchal.max(1));
    let bnd_col = std::slice::from_raw_parts(bnd_col, n_bnd.max(1));
    let bnd_val = std::slice::from_raw_parts(bnd_val, n_bnd.max(1));
    let bnd_row = std::slice::from_raw_parts(bnd_row, n_bnd.max(1));

    // an extension group consumes D outputs but ONE alpha, so each group adds D-1 EXTRA outputs and the
    // logical count is n_out - n_pairs*(D-1). (n_out - n_pairs was right only at D=2 and would silently
    // over-count alphas at any other degree — the same off-by-one the Python side carried.)
    let n_logical = match n_out.checked_sub(n_pairs * (EXT_DEGREE - 1)) {
        Some(v) => v,
        None => return 5,
    };
    let alphas = std::slice::from_raw_parts(alphas, EXT_DEGREE * (n_logical + n_bnd));

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
    for k in 0..n_pairs {
        // each group must name a real output AND leave room for all D-1 of its partners
        if (pairs[k] as usize) + (EXT_DEGREE - 1) >= n_out {
            return 6;
        }
    }

    let ComposeSetup { inv_z, den_vecs, bnd_den_idx } = compose_setup(n, t, offset, n_bnd, bnd_row);

    // is_pair_start[k] — O(1) lookup instead of scanning ext_pairs per output per point
    let mut is_pair_start = vec![false; n_out];
    for k in 0..n_pairs {
        is_pair_start[pairs[k] as usize] = true;
    }

    let mut cp: Vec<Vec<u64>> = (0..EXT_DEGREE).map(|_| vec![0u64; n]).collect();
    let mut temp = vec![0u64; n_ops];
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
        let mut acc = EXT_ZERO;
        let mut k = 0usize;
        let mut ai = 0usize;
        while k < n_out {
            let mut val = EXT_ZERO;
            if is_pair_start[k] {
                for d in 0..EXT_DEGREE {
                    val[d] = temp[outputs[k + d] as usize];
                }
                k += EXT_DEGREE;
            } else {
                val[0] = temp[outputs[k] as usize];     // base-valued constraint; higher limbs stay zero
                k += 1;
            }
            let mut a = EXT_ZERO;
            for d in 0..EXT_DEGREE {
                a[d] = alphas[EXT_DEGREE * ai + d];
            }
            acc = e_add(acc, e_mul(a, val));
            ai += 1;
        }
        let mut v = e_scalar(acc, inv_z[j]);
        for bi in 0..n_bnd {
            let col = bnd_col[bi] as usize;
            let diff = subf(arena.cols[col][j], bnd_val[bi]);
            let invden = den_vecs[bnd_den_idx[bi]][j];
            let mut a = EXT_ZERO;
            for d in 0..EXT_DEGREE {
                a[d] = alphas[EXT_DEGREE * (n_logical + bi) + d];
            }
            v = e_add(v, e_scalar(a, mulf(diff, invden)));
        }
        for d in 0..EXT_DEGREE {
            cp[d][j] = v[d];
        }
    }
    if !out.is_null() {
        for d in 0..EXT_DEGREE {
            std::ptr::copy_nonoverlapping(cp[d].as_ptr(), out.add(d * n), n);
        }
    }
    let first = arena.cols.len();
    for c in cp {
        arena.cols.push(c);
    }
    first as i64
}

// ── FIAT–SHAMIR TRANSCRIPT, IN RUST ─────────────────────────────────────────────────────────────────
// The FRI prove loop was orchestration in Python calling these kernels one at a time: absorb a root,
// cross the FFI boundary, take a challenge, cross back, fold, cross back. Every layer and every query paid
// that toll, which is why a fold ran for hours. The kernels were never the problem; the glue was.
//
// This is the keystone of moving the loop itself into Rust: challenges must be derived BYTE-IDENTICALLY to
// backend.RecursionBackend, or a Rust-proved proof is simply rejected by every verifier. So it mirrors that
// implementation exactly rather than being written afresh:
//     t_init(label)          = hashn([DOM_ABSORB, sum(label_bytes) % P])
//     t_absorb(state, lanes) = hashn([DOM_ABSORB, *state, *lanes])
//     t_challenge(state)     = s = hashn([DOM_CHAL,  *state]); (s, s[0] % PU64)
//     t_index(state, bound)  = s = hashn([DOM_INDEX, *state]); (s, s[0] % bound)
// Note hashn() here takes els WITHOUT a length prefix (its caller adds one for leaves); the Python
// transcript likewise passes the bare domain-tagged list, so the two agree.
//
// The Python encoder flattens tuples element-wise and reduces strings to sum(bytes) % P. That collapsing of
// a string to one lane is weak hashing, but it is CONSENSUS — the verifier does the same — so it is mirrored
// verbatim. Callers pass pre-encoded lanes; string folding stays on the Python side where the labels live.
const DOM_ABSORB: u64 = 3;
const DOM_CHAL: u64 = 4;
const DOM_INDEX: u64 = 5;

/// Initialise a transcript from a pre-folded label lane. Writes CAP lanes to `out`.
///
/// # Safety
/// `out` must point to CAP writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_tr_init(label_lane: u64, out: *mut u64) {
    let s = hashn(&[2, DOM_ABSORB, label_lane % PU64]);   // 2 = len([DOM, lane])
    core::ptr::copy_nonoverlapping(s.as_ptr(), out, CAP);
}

/// Absorb `n` lanes into the CAP-lane state at `state` (updated in place).
///
/// # Safety
/// `state` must point to CAP writable u64; `lanes` to `n` readable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_tr_absorb(state: *mut u64, lanes: *const u64, n: usize) {
    let mut els = Vec::with_capacity(2 + CAP + n);
    els.push((1 + CAP + n) as u64);              // length prefix, as alghash2.py's hashn prepends
    els.push(DOM_ABSORB);
    for k in 0..CAP {
        els.push(*state.add(k));
    }
    for k in 0..n {
        els.push(*lanes.add(k) % PU64);
    }
    let s = hashn(&els);
    core::ptr::copy_nonoverlapping(s.as_ptr(), state, CAP);
}

/// Squeeze one base-field challenge, advancing the state. Returns the challenge.
///
/// # Safety
/// `state` must point to CAP writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_tr_challenge(state: *mut u64) -> u64 {
    let mut els = Vec::with_capacity(2 + CAP);
    els.push((1 + CAP) as u64);                  // length prefix
    els.push(DOM_CHAL);
    for k in 0..CAP {
        els.push(*state.add(k));
    }
    let s = hashn(&els);
    core::ptr::copy_nonoverlapping(s.as_ptr(), state, CAP);
    s[0] % PU64
}

/// Squeeze a uniform index in [0, bound), advancing the state.
///
/// # Safety
/// `state` must point to CAP writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_tr_index(state: *mut u64, bound: u64) -> u64 {
    let mut els = Vec::with_capacity(2 + CAP);
    els.push((1 + CAP) as u64);                  // length prefix
    els.push(DOM_INDEX);
    for k in 0..CAP {
        els.push(*state.add(k));
    }
    let s = hashn(&els);
    core::ptr::copy_nonoverlapping(s.as_ptr(), state, CAP);
    if bound == 0 { 0 } else { s[0] % bound }
}

/// Squeeze DEGREE independent base draws = one GF(p^D) challenge. Writes `degree` lanes to `out`.
/// Mirrors Transcript.challenge_ext, whose arity comes from extf.DEGREE — passed in rather than hardcoded,
/// because a smaller arity here would still let prover and verifier agree with each other while sampling a
/// weaker space than the soundness analysis claims, and nothing would fail.
///
/// # Safety
/// `state` must point to CAP writable u64; `out` to `degree` writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_tr_challenge_ext(state: *mut u64, degree: usize, out: *mut u64) {
    for i in 0..degree {
        *out.add(i) = sp_tr_challenge(state);
    }
}

// ── RETAINED EXT-LEAF MERKLE COMMIT ─────────────────────────────────────────────────────────────────
// The gap that kept the FRI layer loop in Python. sp_commit_col commits a BASE column, and the extension
// commit lived in the separate alghash2 crate — which returns only a ROOT, with no retained tree, so there
// was nothing to open a query against. Every folded layer above layer 0 is extension-valued, so the loop had
// to come back to Python to commit each one and hold the tree there.
//
// Leaf frames are the SAME as alghash2's, deliberately duplicated rather than shared because the two crates
// are separate .so files: RECURSION uses one permutation over (DOM_LEAF_EXT, limb0..limb_{d-1}, 0.., IV) —
// which is what makes an extension leaf cost the same in-circuit as a base one — and ALGHASH2 uses
// hashn([len, DOM_LEAF_EXT, limb0..]). DOM_LEAF_EXT (7), not DOM_LEAF (1), so a lifted base value and a
// genuine base value can never share a digest; otherwise a prover could present one tree's opening against
// the other's commitment.
const DOM_LEAF_EXT_SP: u64 = 7;

fn rleaf_ext_sp(limbs: &[u64]) -> [u64; CAP] {
    let mut s = [0u64; HW];
    s[0] = DOM_LEAF_EXT_SP;
    for (k, v) in limbs.iter().enumerate() {
        s[1 + k] = *v % PU64;
    }
    unsafe {
        for k in 0..CAP {
            s[RATE + k] = IVH[k];
        }
    }
    permute(&mut s);
    [s[0], s[1], s[2], s[3]]
}

fn a2_leaf_ext_sp(limbs: &[u64]) -> [u64; CAP] {
    let mut els = Vec::with_capacity(2 + limbs.len());
    els.push((1 + limbs.len()) as u64);
    els.push(DOM_LEAF_EXT_SP);
    for v in limbs {
        els.push(*v % PU64);
    }
    hashn(&els)
}

/// Merkle-commit `d` retained columns AS ONE EXTENSION COLUMN (leaf i = the d limbs at row i). Retains the
/// tree so sp_open can serve query paths, writes the CAP-lane root, returns the tree id (or -1).
/// `hash_mode` 0 = RECURSION, 1 = ALGHASH2 — chosen by BACKEND, never guessed: using the wrong one builds a
/// well-formed tree with the wrong root, which fails far from the cause.
///
/// # Safety
/// `col_ids` must point to `d` usize, each indexing a retained column; all must share one length that is a
/// power of two. `root_ptr`, if non-null, must point to CAP writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_commit_col_ext(col_ids: *const usize, d: usize, root_ptr: *mut u64,
                                           hash_mode: u32) -> i64 {
    let mut g = ARENA.lock().unwrap();
    let arena = match g.as_mut() {
        Some(a) => a,
        None => return -1,
    };
    // The RECURSION frame is the four-lane rleaf head, so a degree that no longer fits is REFUSED rather
    // than silently truncated — a truncated limb would commit to a value nobody can reproduce.
    if !HASH_READY || d == 0 || col_ids.is_null() || (hash_mode == 0 && d > RATE - 1) {
        return -1;
    }
    let ids = std::slice::from_raw_parts(col_ids, d);
    for &c in ids {
        if c >= arena.cols.len() {
            return -1;
        }
    }
    let n = arena.cols[ids[0]].len();
    if n < 1 || (n & (n - 1)) != 0 || ids.iter().any(|&c| arena.cols[c].len() != n) {
        return -1;
    }
    let a2 = hash_mode;
    let digs = {
        let cols: Vec<&[u64]> = ids.iter().map(|&c| arena.cols[c].as_slice()).collect();
        build_tree(n, a2, |i| {
            let mut limbs = [0u64; 8];
            for k in 0..d {
                limbs[k] = cols[k][i];
            }
            match a2 {
                1 => a2_leaf_ext_sp(&limbs[..d]),
                2 => b2b_leaf_ext(&limbs[..d]),
                _ => rleaf_ext_sp(&limbs[..d]),
            }
        })
    };
    let root = digs[2 * n - 2];
    if !root_ptr.is_null() {
        for k in 0..CAP {
            *root_ptr.add(k) = root[k];
        }
    }
    arena.trees.push(Tree { n, digs });
    (arena.trees.len() - 1) as i64
}

// ── THE FRI PROVE LOOP, IN RUST ─────────────────────────────────────────────────────────────────────
// This is the function the whole port exists for. fri.prove was ~45 lines of Python orchestration, and every
// one of the primitives it called was already native: commit, absorb, challenge, fold, grind, open. What cost
// hours was the SHAPE — absorb a root, cross the FFI boundary, take a challenge, cross back, fold, cross back
// to open — once per layer and once per query, with 320 queries and the layer count logarithmic in N.
//
// So nothing here is new mathematics. It is the same sequence, run without leaving Rust.
//
// RESULT MARSHALLING. Query paths are variable-length (log2 of each layer), so rather than one FFI call per
// opening — which would reintroduce exactly the per-query round-trip being removed — the whole proof is
// serialised once into a self-describing flat u64 buffer. Caller asks for the size, allocates, asks for the
// bytes. Two calls total for a complete proof.
struct FriResult {
    layer_sizes: Vec<usize>,
    roots: Vec<[u64; CAP]>,
    trees: Vec<usize>,
    limbs_per_layer: Vec<usize>,   // 1 for a base layer, degree for an extension layer
    layer_cols: Vec<Vec<usize>>,   // the arena column ids backing each committed layer
    final_vals: Vec<u64>,          // flattened, limbs_per_value = last limbs_per_layer (or 1)
    final_limbs: usize,
    pow: u64,
    qidx: Vec<u64>,
    ext0: bool,
    degree: usize,
}

static FRI: Mutex<Option<FriResult>> = Mutex::new(None);

// Python absorbs the literal label "final" alongside the last layer, and backend._enc collapses a string to
// sum(bytes) % P. Precomputed here so the transcript sequence matches without carrying string handling into
// Rust: f+i+n+a+l = 102+105+110+97+108.
const LANE_FINAL: u64 = 522;

/// Prove deg(f) < N/blowup entirely in Rust. `col_ids` names the layer-0 column(s) already loaded into the
/// arena — ONE column for a base-valued layer 0, or `degree` columns (limb-major) for an extension-valued one,
/// which is how fri.prove's data-driven `ext0` is expressed here rather than guessed. `tr_state` is the live
/// CAP-lane transcript state and is ADVANCED in place, so the caller's transcript continues correctly
/// afterwards. Returns the layer count, or -1.
///
/// # Safety
/// `col_ids` must point to `n_col_ids` usize naming retained columns of equal power-of-two length;
/// `tr_state` to CAP writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_fri_prove(col_ids: *const usize, n_col_ids: usize, offset: u64,
                                      blowup: usize, num_queries: usize, grind_bits: u32,
                                      tr_state: *mut u64, hash_mode: u32, degree: usize,
                                      use_ext: u32) -> i64 {
    if col_ids.is_null() || tr_state.is_null() || degree == 0 || blowup == 0 || num_queries == 0 {
        return -1;
    }
    let use_ext = use_ext != 0;
    let ext0 = n_col_ids == degree && use_ext;
    if !(n_col_ids == 1 || ext0) {
        return -1;                       // layer 0 is either one base column or exactly `degree` limbs
    }
    let mut cur: Vec<usize> = std::slice::from_raw_parts(col_ids, n_col_ids).to_vec();
    let n0 = {
        let g = ARENA.lock().unwrap();
        match g.as_ref() {
            Some(a) if cur.iter().all(|&c| c < a.cols.len()) => a.cols[cur[0]].len(),
            _ => return -1,
        }
    };
    if n0 < 2 || (n0 & (n0 - 1)) != 0 {
        return -1;
    }

    let mut res = FriResult {
        layer_sizes: Vec::new(), roots: Vec::new(), trees: Vec::new(), limbs_per_layer: Vec::new(),
        layer_cols: Vec::new(),
        final_vals: Vec::new(), final_limbs: 1, pow: 0, qidx: Vec::new(), ext0, degree,
    };
    let mut off = offset % PU64;
    let mut n = n0;
    let mut depth = 0usize;

    // ── layer loop: commit -> absorb root -> challenge -> fold ──────────────────────────────────────
    while n > blowup {
        let is_ext_layer = use_ext && (depth > 0 || ext0);
        let mut root = [0u64; CAP];
        let tree = if is_ext_layer {
            sp_commit_col_ext(cur.as_ptr(), cur.len(), root.as_mut_ptr(), hash_mode)
        } else {
            sp_commit_col(cur[0], root.as_mut_ptr(), hash_mode)
        };
        if tree < 0 {
            return -1;
        }
        res.layer_sizes.push(n);
        res.limbs_per_layer.push(cur.len());
        res.layer_cols.push(cur.clone());
        res.roots.push(root);
        res.trees.push(tree as usize);
        sp_tr_absorb(tr_state, root.as_ptr(), CAP);

        let first = if use_ext {
            let mut alpha = vec![0u64; degree];
            sp_tr_challenge_ext(tr_state, degree, alpha.as_mut_ptr());
            // After the first fold every layer is extension-valued, so a base layer 0 must be LIFTED into
            // `degree` limbs before folding: limb 0 is the value, the rest are zero. Skipping this is how a
            // base layer 0 would fold as if it were already an extension and commit garbage.
            let ids: Vec<usize> = if cur.len() == degree {
                cur.clone()
            } else {
                let mut g = ARENA.lock().unwrap();
                let arena = match g.as_mut() { Some(a) => a, None => return -1 };
                let base = arena.cols[cur[0]].clone();
                let first_id = arena.cols.len();
                arena.cols.push(base);
                for _ in 1..degree {
                    arena.cols.push(vec![0u64; n]);
                }
                (first_id..first_id + degree).collect()
            };
            sp_fold_ext(ids.as_ptr(), ids.len(), off, {
                let p = alpha.as_ptr(); p
            }, degree)
        } else {
            let mut a = [0u64; 1];
            a[0] = sp_tr_challenge(tr_state);
            sp_fold(cur[0], off, a[0])
        };
        if first < 0 {
            return -1;
        }
        let first = first as usize;
        cur = if use_ext { (first..first + degree).collect() } else { vec![first] };
        off = mulf(off, off);
        n /= 2;
        depth += 1;
    }

    // ── final layer in the clear, then the unconditional PoW ────────────────────────────────────────
    {
        let g = ARENA.lock().unwrap();
        let arena = match g.as_ref() { Some(a) => a, None => return -1 };
        res.final_limbs = cur.len();
        for i in 0..n {
            for &c in cur.iter() {
                res.final_vals.push(arena.cols[c][i]);
            }
        }
    }
    // Python: t.absorb("final", *flatten(final)) — the label lane first, then every limb in order.
    {
        let mut lanes = Vec::with_capacity(1 + res.final_vals.len());
        lanes.push(LANE_FINAL);
        lanes.extend_from_slice(&res.final_vals);
        sp_tr_absorb(tr_state, lanes.as_ptr(), lanes.len());
    }
    res.pow = {
        let mut st = [0u64; CAP];
        for k in 0..CAP { st[k] = *tr_state.add(k); }
        let n = sp_grind(st.as_ptr(), 6 /* DOM_GRIND */, grind_bits);
        if n == u64::MAX { return -1; }
        n
    };
    // grind() folds the nonce back in as absorb("grind", nonce); "grind" = 103+114+105+110+100 = 532.
    {
        let lanes = [532u64, res.pow % PU64];
        sp_tr_absorb(tr_state, lanes.as_ptr(), 2);
    }

    // ── queries ─────────────────────────────────────────────────────────────────────────────────────
    for _ in 0..num_queries {
        res.qidx.push(sp_tr_index(tr_state, n0 as u64));
    }

    *FRI.lock().unwrap() = Some(res);
    let g = FRI.lock().unwrap();
    g.as_ref().map(|r| r.layer_sizes.len() as i64).unwrap_or(-1)
}

/// Size in u64 of the serialised proof from the last sp_fri_prove, or -1 if there is none.
#[no_mangle]
pub extern "C" fn sp_fri_size() -> i64 {
    let g = FRI.lock().unwrap();
    let r = match g.as_ref() { Some(r) => r, None => return -1 };
    let nl = r.layer_sizes.len();
    let mut n = 8                                  // header
        + nl * 2                                   // layer_sizes, limbs_per_layer — EXACTLY what serialize
                                                   // writes. This said nl*3 (a "padding slot" the serializer
                                                   // never emitted), so size and written-length disagreed by
                                                   // n_layers and the caller's strict equality check refused
                                                   // every proof. Keep the two in lockstep.
        + nl * CAP                                 // roots
        + r.final_vals.len()
        + r.qidx.len();
    for q in 0..r.qidx.len() {
        let mut a = r.qidx[q] as usize;
        for l in 0..nl {
            let sz = r.layer_sizes[l];
            let half = sz / 2;
            a %= sz;
            let _lo = a % half;
            // trailing_zeros, NOT (sz as f64).log2(): layer sizes are powers of two, and a float log2 is
            // exactly the kind of rounding that produces an off-by-one path length at one size in a
            // thousand and then an unopenable proof far from the cause.
            let path = sz.trailing_zeros() as usize;
            n += 2 * (r.limbs_per_layer[l] + path * CAP);
            a = _lo;
        }
    }
    n as i64
}

/// Serialise the last sp_fri_prove into a self-describing flat u64 buffer of exactly sp_fri_size() lanes.
/// ONE call for the whole proof — a getter per opening would reinstate the per-query FFI round-trip this
/// port removes. Returns lanes written, or -1.
///
/// Layout: [n_layers, n0, blowup_unused, degree, ext0, pow, n_queries, final_limbs]
///         layer_sizes[n_layers], limbs_per_layer[n_layers], roots[n_layers*CAP],
///         final_vals[..], qidx[n_queries],
///         then per query, per layer: lo_limbs[limbs], lo_path[path*CAP], hi_limbs[limbs], hi_path[path*CAP]
///
/// # Safety
/// `out` must point to at least sp_fri_size() writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_fri_serialize(out: *mut u64) -> i64 {
    let fg = FRI.lock().unwrap();
    let r = match fg.as_ref() { Some(r) => r, None => return -1 };
    let g = ARENA.lock().unwrap();
    let arena = match g.as_ref() { Some(a) => a, None => return -1 };
    let nl = r.layer_sizes.len();
    let mut w = 0usize;
    let mut put = |v: u64| { *out.add(w) = v; w += 1; };
    put(nl as u64);
    put(*r.layer_sizes.first().unwrap_or(&0) as u64);
    put(0);
    put(r.degree as u64);
    put(r.ext0 as u64);
    put(r.pow);
    put(r.qidx.len() as u64);
    put(r.final_limbs as u64);
    for l in 0..nl { put(r.layer_sizes[l] as u64); }
    for l in 0..nl { put(r.limbs_per_layer[l] as u64); }
    for l in 0..nl { for k in 0..CAP { put(r.roots[l][k]); } }
    for v in &r.final_vals { put(*v); }
    for q in &r.qidx { put(*q); }
    // Openings, in the SAME (query, layer, lo-then-hi) order fri.prove emits them, because the verifier walks
    // them positionally: a permuted order verifies against nothing and looks like a bad proof.
    for q in 0..r.qidx.len() {
        let mut a = r.qidx[q] as usize;
        for l in 0..nl {
            let sz = r.layer_sizes[l];
            let half = sz / 2;
            a %= sz;
            let lo = a % half;
            let limbs = r.limbs_per_layer[l];
            let tree = r.trees[l];
            let path = sz.trailing_zeros() as usize;
            // The layer's columns are the `limbs` consecutive ids ending at the fold input; recover them from
            // the tree's own leaf count rather than re-deriving, so a mismatch cannot go unnoticed.
            for (pos, _) in [(lo, 0usize), (lo + half, 1usize)] {
                // value limbs
                for k in 0..limbs {
                    put(arena.cols[r.layer_cols[l][k]][pos]);
                }
                // authentication path
                let mut idx = pos;
                let mut start = 0usize;
                let mut len = sz;
                for _ in 0..path {
                    let sib = idx ^ 1;
                    for k in 0..CAP { put(arena.trees[tree].digs[start + sib][k]); }
                    idx /= 2;
                    start += len;
                    len /= 2;
                }
            }
        }
    }
    w as i64
}

// ── PER-ROUND PERMUTATION SNAPSHOTS — the real cost of witness generation ───────────────────────────
// This is the hottest thing in the whole fold, and it was pure Python.
//
// recursion._permute_snapshots returns [state, after_round_0, …, after_round_{R-1}] because the in-circuit
// hash AIR constrains one permutation ROUND per trace row, so the witness needs every intermediate state —
// not just the final digest that permute() returns. Each snapshot set is R=54 rounds of a full 12x12 MDS
// matmul: 7776 field multiplies. comp_verify/_fill_path calls it once per Merkle block, with 2W openings per
// point and path_len+1 blocks each; at W=352 that is on the order of 10^8 Python field multiplications per
// comp proof, and a K->1 fold builds six of them.
//
// The permutation itself has been native for a long time. What was missing was only the ability to SEE
// inside it, so witness generation kept re-deriving in Python what Rust already computes.
/// Write (HR+1)*HW lanes: the input state followed by the state after each of the HR rounds.
/// Byte-identical to recursion._permute_snapshots, which mirrors alghash2.permute round for round.
///
/// # Safety
/// `state` must point to HW readable u64; `out` to (HR+1)*HW writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_permute_snapshots(state: *const u64, out: *mut u64) -> i64 {
    if !HASH_READY || state.is_null() || out.is_null() {
        return -1;
    }
    let mut s = [0u64; HW];
    for i in 0..HW {
        s[i] = *state.add(i) % PU64;
        *out.add(i) = s[i];
    }
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
        for i in 0..HW {
            *out.add((r + 1) * HW + i) = s[i];
        }
    }
    ((HR + 1) * HW) as i64
}

/// Batch form: `n` states in, `n*(HR+1)*HW` lanes out. One FFI crossing for a whole Merkle path's blocks
/// instead of one per block — the same round-trip lesson as the FRI loop.
///
/// # Safety
/// `states` must point to `n*HW` readable u64; `out` to `n*(HR+1)*HW` writable u64.
#[no_mangle]
pub unsafe extern "C" fn sp_permute_snapshots_batch(states: *const u64, n: usize, out: *mut u64) -> i64 {
    if !HASH_READY || states.is_null() || out.is_null() {
        return -1;
    }
    let stride = (HR + 1) * HW;
    for k in 0..n {
        if sp_permute_snapshots(states.add(k * HW), out.add(k * stride)) < 0 {
            return -1;
        }
    }
    (n * stride) as i64
}

// ── WHOLE MERKLE-PATH BLOCK GENERATION ──────────────────────────────────────────────────────────────
// recursion._blocks_for builds the permutation-snapshot blocks for ONE Merkle path: the leaf frame, then one
// node frame per path digest. With snapshots native it already went 146x faster, but it still crossed the FFI
// boundary once PER BLOCK — 2W openings per point, path_len+1 blocks each, so ~12.7k crossings per point at
// W=352. Same round-trip lesson as the FRI loop: do the whole path in one call.
//
// The leaf frame follows the value's own shape, exactly as _blocks_for does: a base leaf is
// (DOM_LEAF, x, 0…, IV); an extension leaf is (DOM_LEAF_EXT, limb0…limb_{d-1}, 0…, IV) in the FOUR-lane
// rleaf head — which is why an ext leaf still costs ONE permutation and the in-circuit membership gadget
// stays affordable. A degree that does not fit the head is REFUSED, never truncated.
/// Emit (path_len+1) snapshot blocks for one Merkle path.
/// `out` receives (path_len+1)*(HR+1)*HW lanes; `dirs_out` receives path_len direction bits;
/// `final_out` receives the CAP-lane root digest. Returns lanes written to `out`, or -1.
///
/// # Safety
/// `leaf` -> `n_limbs` u64 (n_limbs==1 means a base leaf); `path` -> `path_len*CAP` u64;
/// `out` -> (path_len+1)*(HR+1)*HW writable; `dirs_out` -> path_len writable; `final_out` -> CAP writable.
#[no_mangle]
pub unsafe extern "C" fn sp_blocks_for(leaf: *const u64, n_limbs: usize, index: u64,
                                       path: *const u64, path_len: usize,
                                       out: *mut u64, dirs_out: *mut u64, final_out: *mut u64) -> i64 {
    if !HASH_READY || leaf.is_null() || out.is_null() {
        return -1;
    }
    // The head is lanes 0..3: tag + up to 3 limbs. Anything wider cannot be expressed in one permutation.
    if n_limbs == 0 || n_limbs > 3 {
        return -1;
    }
    let stride = (HR + 1) * HW;
    let mut s0 = [0u64; HW];
    if n_limbs == 1 {
        s0[0] = 1;                                   // DOM_LEAF
        s0[1] = *leaf % PU64;
    } else {
        s0[0] = DOM_LEAF_EXT_SP;
        for k in 0..n_limbs {
            s0[1 + k] = *leaf.add(k) % PU64;
        }
    }
    for k in 0..CAP {
        s0[RATE + k] = IVH[k];
    }
    if sp_permute_snapshots(s0.as_ptr(), out) < 0 {
        return -1;
    }
    // cur = the digest lanes of the block's LAST snapshot row (row HR), matching _blocks_for's blocks[0][_R].
    let mut cur = [0u64; CAP];
    for k in 0..CAP {
        cur[k] = *out.add(HR * HW + k);
    }
    let mut idx = index;
    for b in 0..path_len {
        let d = (idx & 1) as u64;
        let mut init = [0u64; HW];
        let sib = std::slice::from_raw_parts(path.add(b * CAP), CAP);
        // direction decides which side the sibling occupies — get this backwards and the digest is wrong at
        // every level above, which surfaces only as a root mismatch far from here.
        let (left, right): (&[u64], &[u64]) = if d == 1 { (sib, &cur[..]) } else { (&cur[..], sib) };
        for k in 0..CAP {
            init[k] = left[k] % PU64;
            init[CAP + k] = right[k] % PU64;
        }
        for k in 0..CAP {
            init[RATE + k] = IVH[k];
        }
        let off = (b + 1) * stride;
        if sp_permute_snapshots(init.as_ptr(), out.add(off)) < 0 {
            return -1;
        }
        for k in 0..CAP {
            cur[k] = *out.add(off + HR * HW + k);
        }
        if !dirs_out.is_null() {
            *dirs_out.add(b) = d;
        }
        idx >>= 1;
    }
    if !final_out.is_null() {
        for k in 0..CAP {
            *final_out.add(k) = cur[k];
        }
    }
    ((path_len + 1) * stride) as i64
}

// ── WITNESS ROW FILL FOR ONE MERKLE PATH ────────────────────────────────────────────────────────────
// The last per-row Python in comp/rowcomp witness generation. fri_verify._fill_path writes, for each of the
// path_len+1 blocks, B rows of: W permutation-snapshot lanes, the witness sibling + direction at the absorb
// row, and the index accumulator. That is (path_len+1) * B * (W+2) Python list writes PER OPENING, with 2W
// openings per point — millions of cells before a single constraint is evaluated.
//
// sp_blocks_for already computes the snapshots natively; this writes them straight into the caller's flat
// row buffer, so the blocks never become Python nested lists at all. That marshalling is what still dominated
// sp_blocks_for's remaining 1.9 ms.
//
// Layout mirrors _fill_block exactly:
//   rows[base+rib][0..W)      = snapshot rib            for rib in 0..=R
//   rows[base+rib][iacc]      = acc_in                  for rib in 0..=R
//   rows[base+R][sibw..+CAP)  = sibling digest
//   rows[base+R][dirw]        = direction bit
//   rows[base+rib][0..W)      = next_state              for rib in R+1..B
//   rows[base+rib][iacc]      = acc_out                 for rib in R+1..B
// and the FINAL block absorbs a zero sibling with direction 0 and holds acc (fri_verify._junk_absorb):
// [digest lanes, zeros, IV].
/// Fill `(path_len+1)*b_rows` rows of a flat `wtot`-wide row buffer for one Merkle path opening.
/// Returns rows written, or -1.
///
/// # Safety
/// `rows` must point to at least (base + (path_len+1)*b_rows) * wtot writable u64; `leaf` to `n_limbs` u64;
/// `path` to `path_len*CAP` u64. Lane indices must satisfy w+CAP <= wtot, dirw < wtot, iacc < wtot.
#[no_mangle]
pub unsafe extern "C" fn sp_fill_path(rows: *mut u64, wtot: usize, base: usize,
                                      leaf: *const u64, n_limbs: usize, index: u64,
                                      path: *const u64, path_len: usize,
                                      b_rows: usize, sibw: usize, dirw: usize, iacc: usize) -> i64 {
    if !HASH_READY || rows.is_null() || b_rows < HR + 2 {
        return -1;
    }
    if HW + CAP > wtot || dirw >= wtot || iacc >= wtot || sibw + CAP > wtot {
        return -1;                                  // refuse a layout that would write out of bounds
    }
    let nblk = path_len + 1;
    let stride = (HR + 1) * HW;
    let mut snaps = vec![0u64; nblk * stride];
    let mut dirs = vec![0u64; if path_len > 0 { path_len } else { 1 }];
    let mut fin = [0u64; CAP];
    if sp_blocks_for(leaf, n_limbs, index, path, path_len,
                     snaps.as_mut_ptr(), dirs.as_mut_ptr(), fin.as_mut_ptr()) < 0 {
        return -1;
    }
    let mut acc = index;
    for b in 0..nblk {
        let blk = &snaps[b * stride..(b + 1) * stride];
        let last = b + 1 == nblk;
        // The next block's INPUT state is what rows R+1..B hold. For the final block that is _junk_absorb of
        // this block's row-R digest: [digest, zeros, IV] — dead lanes whose row-15 link is released there.
        let mut nxt = [0u64; HW];
        if last {
            for k in 0..CAP {
                nxt[k] = blk[HR * HW + k];
            }
            for k in 0..CAP {
                nxt[RATE + k] = IVH[k];
            }
        } else {
            let nb = &snaps[(b + 1) * stride..(b + 2) * stride];
            nxt[..HW].copy_from_slice(&nb[..HW]);
        }
        let d = if last { 0 } else { dirs[b] };
        let acc_out = if last { acc } else { (acc - d) >> 1 };
        for rib in 0..b_rows {
            let row = rows.add((base + b * b_rows + rib) * wtot);
            if rib <= HR {
                for lane in 0..HW {
                    *row.add(lane) = blk[rib * HW + lane] % PU64;
                }
                *row.add(iacc) = acc;
            } else {
                for lane in 0..HW {
                    *row.add(lane) = nxt[lane] % PU64;
                }
                *row.add(iacc) = acc_out;
            }
        }
        let r8 = rows.add((base + b * b_rows + HR) * wtot);
        for lane in 0..CAP {
            *r8.add(sibw + lane) = if last { 0 } else { *path.add(b * CAP + lane) % PU64 };
        }
        *r8.add(dirw) = d;
        acc = acc_out;
    }
    (nblk * b_rows) as i64
}

// ── FLAT-TRACE CARRY FILL AND BULK LDE ──────────────────────────────────────────────────────────────
// The last per-row Python in comp/rowcomp witness generation, and it costs TWICE.
//
// (1) The carry fill: comp_verify/_fill_trace holds each point's 2W opened values constant across its whole
//     span — `for i in span: for k in 2W: rows[i][CARRY+k] = vals[k]`. At T=8192, W=352 that is ~5.8M Python
//     list writes per comp proof.
// (2) The transpose: stark_native.prove then rebuilds each column as
//     `[trace[i][c] for i in range(T)]` — another T*W Python index operations to undo the row-major layout
//     the fill just produced.
//
// Both disappear if the trace is ONE flat row-major buffer that Rust fills and Rust reads. sp_fill_carries
// does the span fill; sp_lde_trace_flat takes the whole buffer and retains all W LDE columns in the arena,
// doing the transpose natively.
/// Hold `n` values constant across rows [r0, r1] at column offset `carry_off` of a flat `wtot`-wide buffer.
///
/// # Safety
/// `rows` must point to at least (r1+1)*wtot writable u64; `vals` to `n` readable u64;
/// carry_off + n <= wtot.
#[no_mangle]
pub unsafe extern "C" fn sp_fill_carries(rows: *mut u64, wtot: usize, r0: usize, r1: usize,
                                         carry_off: usize, vals: *const u64, n: usize) -> i64 {
    if rows.is_null() || vals.is_null() || carry_off + n > wtot || r1 < r0 {
        return -1;
    }
    let src = std::slice::from_raw_parts(vals, n);
    for i in r0..=r1 {
        let dst = rows.add(i * wtot + carry_off);
        for k in 0..n {
            *dst.add(k) = src[k] % PU64;
        }
    }
    (((r1 - r0) + 1) * n) as i64
}

/// LDE and retain ALL `w` columns of a row-major T x w trace buffer, in arena order 0..w.
/// Returns the first column id (0), or -1. Equivalent to calling lde_column once per column with
/// `[trace[i][c] for i in range(T)]`, without ever materialising those lists in Python.
///
/// # Safety
/// `trace` must point to `t_rows * w` readable u64; the arena must already be reset to (T, N, offset).
#[no_mangle]
pub unsafe extern "C" fn sp_lde_trace_flat(trace: *const u64, t_rows: usize, w: usize) -> i64 {
    if trace.is_null() || t_rows == 0 || w == 0 {
        return -1;
    }
    let mut col = vec![0u64; t_rows];
    let mut first: i64 = -1;
    for c in 0..w {
        for i in 0..t_rows {
            col[i] = *trace.add(i * w + c) % PU64;
        }
        let id = sp_lde_column(col.as_ptr(), core::ptr::null_mut());
        if id < 0 {
            return -1;
        }
        if first < 0 {
            first = id;
        }
    }
    first
}

// ---- BLAKE2b-256 -------------------------------------------------------------------------------------
// The shielded pool (joinsplit2) proves under backend.BLAKE2B, which the arena could not commit for -- its
// Merkle spoke only the alghash2 family -- so every shielded proof took the pure-Python prove body (35.1 s
// measured on a real join-split). This is the last Python proving path on a live money path.
//
// Implemented here rather than pulled in as a dependency: the crate has no external deps and this is a
// short, fully specified function (RFC 7693). Bit-identical to hashlib.blake2b(data, digest_size=32),
// asserted by a differential test before anything is wired to it.
const B2B_IV: [u64; 8] = [
    0x6a09e667f3bcc908, 0xbb67ae8584caa73b, 0x3c6ef372fe94f82b, 0xa54ff53a5f1d36f1,
    0x510e527fade682d1, 0x9b05688c2b3e6c1f, 0x1f83d9abfb41bd6b, 0x5be0cd19137e2179,
];
const B2B_SIGMA: [[usize; 16]; 12] = [
    [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15],
    [14,10,4,8,9,15,13,6,1,12,0,2,11,7,5,3],
    [11,8,12,0,5,2,15,13,10,14,3,6,7,1,9,4],
    [7,9,3,1,13,12,11,14,2,6,5,10,4,0,15,8],
    [9,0,5,7,2,4,10,15,14,1,11,12,6,8,3,13],
    [2,12,6,10,0,11,8,3,4,13,7,5,15,14,1,9],
    [12,5,1,15,14,13,4,10,0,7,6,3,9,2,8,11],
    [13,11,7,14,12,1,3,9,5,0,15,4,8,6,2,10],
    [6,15,14,9,11,3,0,8,12,2,13,7,1,4,10,5],
    [10,2,8,4,7,6,1,5,15,11,9,14,3,12,13,0],
    [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15],
    [14,10,4,8,9,15,13,6,1,12,0,2,11,7,5,3],
];

#[inline(always)]
fn b2b_g(v: &mut [u64; 16], a: usize, b: usize, c: usize, d: usize, x: u64, y: u64) {
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(x);
    v[d] = (v[d] ^ v[a]).rotate_right(32);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(24);
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(y);
    v[d] = (v[d] ^ v[a]).rotate_right(16);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(63);
}

fn b2b_compress(h: &mut [u64; 8], block: &[u8; 128], t: u128, last: bool) {
    let mut m = [0u64; 16];
    for i in 0..16 {
        let mut w = [0u8; 8];
        w.copy_from_slice(&block[i * 8..i * 8 + 8]);
        m[i] = u64::from_le_bytes(w);
    }
    let mut v = [0u64; 16];
    v[..8].copy_from_slice(h);
    v[8..].copy_from_slice(&B2B_IV);
    v[12] ^= t as u64;
    v[13] ^= (t >> 64) as u64;
    if last { v[14] = !v[14]; }
    for r in 0..12 {
        let s = &B2B_SIGMA[r];
        b2b_g(&mut v, 0, 4,  8, 12, m[s[0]],  m[s[1]]);
        b2b_g(&mut v, 1, 5,  9, 13, m[s[2]],  m[s[3]]);
        b2b_g(&mut v, 2, 6, 10, 14, m[s[4]],  m[s[5]]);
        b2b_g(&mut v, 3, 7, 11, 15, m[s[6]],  m[s[7]]);
        b2b_g(&mut v, 0, 5, 10, 15, m[s[8]],  m[s[9]]);
        b2b_g(&mut v, 1, 6, 11, 12, m[s[10]], m[s[11]]);
        b2b_g(&mut v, 2, 7,  8, 13, m[s[12]], m[s[13]]);
        b2b_g(&mut v, 3, 4,  9, 14, m[s[14]], m[s[15]]);
    }
    for i in 0..8 { h[i] ^= v[i] ^ v[i + 8]; }
}

/// blake2b with a 32-byte digest, no key. Equivalent to hashlib.blake2b(data, digest_size=32).digest().
fn blake2b32(data: &[u8]) -> [u8; 32] {
    let mut h = B2B_IV;
    h[0] ^= 0x0101_0000 ^ 32u64;             // depth=1, fanout=1, keylen=0, digest_len=32
    let mut t: u128 = 0;
    let full = data.len() / 128;
    let rem = data.len() % 128;
    // all but the final block (a message that is an exact multiple keeps its last block for the final call)
    let last_full = if rem == 0 && full > 0 { full - 1 } else { full };
    for i in 0..last_full {
        let mut blk = [0u8; 128];
        blk.copy_from_slice(&data[i * 128..i * 128 + 128]);
        t += 128;
        b2b_compress(&mut h, &blk, t, false);
    }
    let mut blk = [0u8; 128];
    let tail = &data[last_full * 128..];
    blk[..tail.len()].copy_from_slice(tail);
    t += tail.len() as u128;
    b2b_compress(&mut h, &blk, t, true);
    let mut out = [0u8; 32];
    for i in 0..4 { out[i * 8..i * 8 + 8].copy_from_slice(&h[i].to_le_bytes()); }
    out
}

/// Differential hook: hash `n` bytes and write the 32-byte digest. Exists so the Python test can assert
/// bit-identity against hashlib before this is wired to anything that commits consensus data.
#[no_mangle]
pub unsafe extern "C" fn sp_blake2b32(data: *const u8, n: usize, out: *mut u8) {
    let s = core::slice::from_raw_parts(data, n);
    let d = blake2b32(s);
    for i in 0..32 { *out.add(i) = d[i]; }
}
