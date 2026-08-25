// alghash2 in native Rust — the wide-sponge algebraic hash on the STARK-recursion hot path
// (doc/zk-recursion.md). Byte-identical to execnode/stark/alghash2.py: the Python side computes the round
// constants / IV / MDS (blake2b nothing-up-my-sleeve) and hands them in via `init`, so Rust just runs the
// field arithmetic FAST. Loaded by ctypes from execnode/stark/alghash2.py when built; otherwise Python falls
// back to itself, bit-for-bit. Width 12, rate 8, capacity 4 (256-bit digest).
#![no_std]

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { loop {} }

const P: u128 = 0xFFFFFFFF00000001;   // Goldilocks 2^64 - 2^32 + 1
const PU64: u64 = 0xFFFFFFFF00000001;
const EPSILON: u64 = 0xFFFFFFFF;      // 2^32 - 1  ( = 2^64 mod p )
const W: usize = 12;
const R: usize = 54;   // alghash2 full rounds — MUST match execnode/stark/alghash2.py ROUNDS (7^54 ≥ 2^128)
const RATE: usize = 8;
const CAP: usize = 4;

static mut RC: [[u64; W]; R] = [[0; W]; R];
static mut IV: [u64; CAP] = [0; CAP];
static mut MDS: [[u64; W]; W] = [[0; W]; W];
// INIT CHECK. RC/IV/MDS arrive from Python via `init`; before that they are all zero and every entry point
// would still run, producing well-formed but WRONG digests — the same silent-desync class as the 8→54 round
// change. `ready` lets the loader verify init happened before it trusts this library (and starkprove's
// HASH_READY does the same for its copy of the constants).
static mut READY: u64 = 0;

#[no_mangle]
pub unsafe extern "C" fn ready() -> u64 { READY }

// Fast Goldilocks reduction of a 128-bit product to [0, p), NO division (p = 2^64 - 2^32 + 1, so
// 2^64 ≡ 2^32-1 and 2^96 ≡ -1 mod p). Bit-identical to (x % p) — verified exhaustively against the Python
// `% P` via the native==Python hash/NTT/Merkle/composition tests. This is the field-multiply hot path of the
// whole prover (permute/NTT/composition), and the generic u128 `%` (a division) was the dominant cost.
#[inline(always)]
fn reduce128(x: u128) -> u64 {
    let x_lo = x as u64;
    let x_hi = (x >> 64) as u64;
    let x_hi_hi = x_hi >> 32;
    let x_hi_lo = x_hi & 0xFFFFFFFF;
    let (mut t0, borrow) = x_lo.overflowing_sub(x_hi_hi);
    if borrow { t0 = t0.wrapping_sub(EPSILON); }
    let t1 = x_hi_lo.wrapping_mul(EPSILON);
    let (res, carry) = t0.overflowing_add(t1);
    let mut r = res.wrapping_add(EPSILON * (carry as u64));
    if r >= PU64 { r -= PU64; }
    r
}

#[inline(always)] fn mulf(a: u64, b: u64) -> u64 { reduce128((a as u128) * (b as u128)) }
// NO DIVISION. This was `((a as u128) + (b as u128)) % P` -- a 128-bit modulo, i.e. a hardware division --
// sitting directly under a comment observing that "the generic u128 % (a division) was the dominant cost".
// It runs W*R = 648 times per permutation (round-constant add) plus once per MDS accumulation. Inputs are
// already reduced (< p), so a + b < 2^65: fold the carry with 2^64 = EPSILON (mod p), then one conditional
// subtract.
#[inline(always)] fn addf(a: u64, b: u64) -> u64 {
    let (r, carry) = a.overflowing_add(b);
    let mut r = if carry { r.wrapping_add(EPSILON) } else { r };
    if r >= PU64 { r -= PU64; }
    r
}

#[inline(always)] fn pow7(x: u64) -> u64 {         // x^7 = x·(x^2)·(x^4)
    let x2 = mulf(x, x);
    let x3 = mulf(x2, x);
    let x6 = mulf(x3, x3);
    mulf(x6, x)
}

#[no_mangle]
pub unsafe extern "C" fn init(rc: *const u64, iv: *const u64, mds: *const u64) {
    for r in 0..R { for i in 0..W { RC[r][i] = *rc.add(r * W + i); } }
    for i in 0..CAP { IV[i] = *iv.add(i); }
    for i in 0..W { for j in 0..W { MDS[i][j] = *mds.add(i * W + j); } }
    READY = 1;
}

#[inline(always)]
unsafe fn permute(s: &mut [u64; W]) {
    for r in 0..R {
        let mut t = [0u64; W];
        for i in 0..W { t[i] = pow7(addf(s[i], RC[r][i])); }
        for i in 0..W {
            // ACCUMULATE THE RAW 128-BIT PRODUCTS, REDUCE ONCE PER ROW. This used to call mulf per term,
            // i.e. reduce128 on EVERY product — 144 reductions per round plus 12 more for the rows, where
            // 12 suffice. Measured baseline: 28.07 us per permutation (CPU time, so load-robust), and the
            // MDS is 144 of the 192 multiplies per round.
            //
            // The wider accumulator is exact, not approximate. Each product is < p^2 < 2^128 and W = 12, so
            // the true sum needs 132 bits: keep the low 128 in `lo` and COUNT the overflows in `hi`
            // (hi <= 11). Reducing that is one identity — since 2^64 = 2^32 - 1 (mod p),
            //     2^128 = (2^64)^2 = (2^32 - 1)^2 = 2^64 - 2^33 + 1 = -2^32   (mod p)
            // so the carried part contributes exactly -(hi * 2^32). With hi <= 11 that correction is
            // < 2^36 < p, so it needs no division and no second reduction — just one conditional add.
            let mut lo: u128 = 0;
            let mut hi: u64 = 0;
            for j in 0..W {
                let prod = (MDS[i][j] as u128) * (t[j] as u128);
                let (sum, carry) = lo.overflowing_add(prod);
                lo = sum;
                if carry { hi += 1; }
            }
            let a = reduce128(lo);
            let corr = hi << 32;                       // hi <= 11 => corr < 2^36 < p
            s[i] = if a >= corr { a - corr } else { a + PU64 - corr };
        }
    }
}

#[no_mangle]
pub unsafe extern "C" fn permute12(state: *mut u64) {
    let mut s = [0u64; W];
    for i in 0..W { s[i] = *state.add(i); }
    permute(&mut s);
    for i in 0..W { *state.add(i) = s[i]; }
}

// hashn(elements) with the length prefix (matches Python: els = [len] + elements). `els` already includes the
// length prefix as els[0]; `n` is the total length. Writes the CAP-lane digest to `out`.
#[no_mangle]
pub unsafe extern "C" fn hashn(els: *const u64, n: usize, out: *mut u64) {
    let mut state = [0u64; W];
    for i in 0..CAP { state[RATE + i] = IV[i]; }
    let mut off = 0usize;
    while off < n {
        let end = core::cmp::min(off + RATE, n);
        for i in 0..(end - off) { state[i] = addf(state[i], *els.add(off + i)); }
        permute(&mut state);
        off += RATE;
    }
    for i in 0..CAP { *out.add(i) = state[i]; }
}

// merkle_commit(leaves[n], n, out): build a whole alghash2 Merkle tree in native code (the STARK's Merkle
// commit is O(N) hashes and was a Python loop calling native permute per node). Bit-identical to
// merkle.commit over backend.ALGHASH2: leaf digest = hashn([DOM_LEAF, x]); inner = hashn([DOM_NODE, a.., b..]).
// `n` MUST be a power of two. `out` receives ALL layer digests bottom-up concatenated (n + n/2 + … + 1 =
// 2n-1 digests, each CAP lanes): layer 0 (n leaf digests), then n/2, …, then the single root. Python slices
// it back into the nested `layers` list merkle.open_at expects. DOM_LEAF=1, DOM_NODE=2 (match alghash2.py).
#[no_mangle]
pub unsafe extern "C" fn merkle_commit(leaves: *const u64, n: usize, out: *mut u64) {
    // leaf layer
    for i in 0..n {
        let els = [2u64, 1u64, *leaves.add(i)]; // [len=2, DOM_LEAF, x]
        let mut d = [0u64; CAP];
        hashn(els.as_ptr(), 3, d.as_mut_ptr());
        for k in 0..CAP { *out.add(i * CAP + k) = d[k]; }
    }
    let mut layer_start = 0usize; // digest index of current layer's first node
    let mut layer_len = n;
    let mut off = n;              // next free digest slot
    while layer_len > 1 {
        let half = layer_len / 2;
        for i in 0..half {
            let a = layer_start + 2 * i;
            let b = a + 1;
            let mut els = [9u64, 2u64, 0, 0, 0, 0, 0, 0, 0, 0]; // [len=9, DOM_NODE, a0..3, b0..3]
            for k in 0..CAP {
                els[2 + k] = *out.add(a * CAP + k);
                els[6 + k] = *out.add(b * CAP + k);
            }
            let mut d = [0u64; CAP];
            hashn(els.as_ptr(), 10, d.as_mut_ptr());
            for k in 0..CAP { *out.add((off + i) * CAP + k) = d[k]; }
        }
        layer_start = off;
        off += half;
        layer_len = half;
    }
}

// merkle_commit_ext / rmerkle_commit_ext: the same two whole-tree builds, over EXTENSION leaves.
//
// WHY THESE EXIST. FRI's per-layer commitments hash extension leaves once folding starts, and only the
// BASE-field builds above were native — so every extension FRI layer did n leaf permutations plus n-1 node
// permutations in a Python loop. That is the dominant cost of an extension proof and it lands squarely on
// the settlement fold, which is the thing the extension migration exists to make sound. Measured on a
// loaded box, one in-circuit fold test sat 45 minutes inside alghash2.permute via _commit_ext.
//
// The leaf frame is (DOM_LEAF_EXT, limb0 … limb_{D-1}) — DOM_LEAF_EXT, not DOM_LEAF, so a lifted base value
// and a genuine base value never share a digest; a prover could otherwise present one tree's opening against
// the other's commitment. `d` is the extension degree and `leaves` holds n*d limbs, leaf-major.
const DOM_LEAF_EXT: u64 = 7;

// Shared inner-layer build: both variants differ ONLY in how a leaf is hashed, so the tree half is written
// once. Writing it twice is how the base pair above drifts.
unsafe fn build_inner(n: usize, out: *mut u64, recursion: bool) {
    let mut layer_start = 0usize;
    let mut layer_len = n;
    let mut off = n;
    while layer_len > 1 {
        let half = layer_len / 2;
        for i in 0..half {
            let a = layer_start + 2 * i;
            let b = a + 1;
            let mut d = [0u64; CAP];
            if recursion {
                let mut s = [0u64; W];
                for k in 0..CAP {
                    s[k] = *out.add(a * CAP + k);
                    s[CAP + k] = *out.add(b * CAP + k);
                    s[RATE + k] = IV[k];
                }
                permute(&mut s);
                for k in 0..CAP { d[k] = s[k]; }
            } else {
                let mut els = [9u64, 2u64, 0, 0, 0, 0, 0, 0, 0, 0]; // [len=9, DOM_NODE, a0..3, b0..3]
                for k in 0..CAP {
                    els[2 + k] = *out.add(a * CAP + k);
                    els[6 + k] = *out.add(b * CAP + k);
                }
                hashn(els.as_ptr(), 10, d.as_mut_ptr());
            }
            for k in 0..CAP { *out.add((off + i) * CAP + k) = d[k]; }
        }
        layer_start = off;
        off += half;
        layer_len = half;
    }
}

// Sponge (ALGHASH2) backend: leaf = hashn([DOM_LEAF_EXT, limb0 … ]), inner = hashn([DOM_NODE, a.., b..]).
#[no_mangle]
pub unsafe extern "C" fn merkle_commit_ext(leaves: *const u64, n: usize, d: usize, out: *mut u64) -> i64 {
    if d < 1 || d > 8 { return -1; }
    for i in 0..n {
        // hashn takes [len, elements…]; len counts the DOM tag plus the limbs.
        let mut els = [0u64; 10];
        els[0] = (1 + d) as u64;
        els[1] = DOM_LEAF_EXT;
        for k in 0..d { els[2 + k] = *leaves.add(i * d + k); }
        let mut dg = [0u64; CAP];
        hashn(els.as_ptr(), 2 + d, dg.as_mut_ptr());
        for k in 0..CAP { *out.add(i * CAP + k) = dg[k]; }
    }
    build_inner(n, out, false);
    0
}

// RECURSION backend: leaf = permute([DOM_LEAF_EXT, limb0 … , 0…, IV])[:CAP] — ONE permutation, the property
// that makes the in-circuit extension leaf cost the same as a base one. The frame occupies the four-lane
// rleaf head, so a degree that no longer fits must be REFUSED rather than silently truncated.
#[no_mangle]
pub unsafe extern "C" fn rmerkle_commit_ext(leaves: *const u64, n: usize, d: usize, out: *mut u64) -> i64 {
    if d < 1 || d > (RATE / 2 - 1) { return -1; }
    for i in 0..n {
        let mut s = [0u64; W];
        s[0] = DOM_LEAF_EXT;
        for k in 0..d { s[1 + k] = *leaves.add(i * d + k); }
        for k in 0..CAP { s[RATE + k] = IV[k]; }
        permute(&mut s);
        for k in 0..CAP { *out.add(i * CAP + k) = s[k]; }
    }
    build_inner(n, out, true);
    0
}

// rmerkle_commit(leaves[n], n, out): the RECURSION-backend (rleaf/rnode) whole tree in native code. The
// recursion backend commits with ONE permutation per node (no hashn length prefix), and building it was a
// Python loop calling native permute per node — ~2N FFI crossings, the dominant cost of recursion-backend
// proving (fold/comp/segment proofs, which MUST use this backend to be foldable). Bit-identical to
// merkle.commit over backend.RECURSION: leaf = rleaf(x) = permute([DOM_LEAF, x, 0,0,0,0,0,0, IV])[:CAP];
// inner = rnode(a,b) = permute([a0..3, b0..3, IV])[:CAP]. `n` MUST be a power of two; `out` receives all
// 2n-1 layer digests bottom-up concatenated (CAP lanes each), same layout as merkle_commit. DOM_LEAF = 1.
#[no_mangle]
pub unsafe extern "C" fn rmerkle_commit(leaves: *const u64, n: usize, out: *mut u64) {
    // leaf layer: rleaf(x)
    for i in 0..n {
        let mut s = [0u64; W];
        s[0] = 1;                 // DOM_LEAF
        s[1] = *leaves.add(i);
        for k in 0..CAP { s[RATE + k] = IV[k]; }   // lanes 2..7 stay 0
        permute(&mut s);
        for k in 0..CAP { *out.add(i * CAP + k) = s[k]; }
    }
    // inner layers: rnode(a,b)
    let mut layer_start = 0usize;
    let mut layer_len = n;
    let mut off = n;
    while layer_len > 1 {
        let half = layer_len / 2;
        for i in 0..half {
            let a = layer_start + 2 * i;
            let b = a + 1;
            let mut s = [0u64; W];
            for k in 0..CAP {
                s[k] = *out.add(a * CAP + k);          // a in lanes 0..3
                s[CAP + k] = *out.add(b * CAP + k);    // b in lanes 4..7
                s[RATE + k] = IV[k];                   // IV in lanes 8..11
            }
            permute(&mut s);
            for k in 0..CAP { *out.add((off + i) * CAP + k) = s[k]; }
        }
        layer_start = off;
        off += half;
        layer_len = half;
    }
}

// grind(state[CAP], dom, bits): the STARK-transcript proof-of-work, run ENTIRELY in native code (the fold's
// dominant cost — GRIND_BITS≈18 ⇒ ~2^18 hashes per proof, and doing them one-at-a-time over ctypes from
// Python was the recursion bottleneck). Byte-identical to transcript.grind over the alghash2 backend: the PoW
// hash is hashn([DOM_GRIND, *state, nonce]) and the target is `bits` leading zero bits of the 256-bit digest
// to_int = (lane0<<192)|(lane1<<128)|(lane2<<64)|lane3. For bits<=64 that is exactly lane0 >> (64-bits) == 0.
// Scans nonce = 0,1,2,… and returns the FIRST hit — the same nonce the Python loop would find. bits is capped
// at 64 (every real GRIND_BITS is far below that); returns u64::MAX if somehow unsatisfiable in range.
#[no_mangle]
pub unsafe extern "C" fn grind(state: *const u64, dom: u64, bits: u32) -> u64 {
    let mut els = [CAP as u64 + 2, dom, *state, *state.add(1), *state.add(2), *state.add(3), 0u64];
    let n = 7usize;                       // [len=6, dom, s0,s1,s2,s3, nonce]
    let mut out = [0u64; CAP];
    let shift = if bits >= 64 { 0u32 } else { 64 - bits };
    let mut nonce: u64 = 0;
    loop {
        els[6] = nonce;
        hashn(els.as_ptr(), n, out.as_mut_ptr());
        let hit = if bits >= 64 { out[0] == 0 } else { (out[0] >> shift) == 0 };
        if hit { return nonce; }
        if nonce == u64::MAX { return u64::MAX; }
        nonce += 1;
    }
}

// merkle_verify_paths: verify M authentication paths in ONE crossing.
//
// WHY. The prover was ported to Rust; the VERIFIER never was, and nobody profiled it. Measured on a single
// usehint sub-proof: stark.verify spent 82% of its 145.7 ms inside alghash2.permute/hashn — 16240 permute
// calls for 5 verifies, i.e. ~3248 per proof, each one its own ctypes crossing. The kernel was already
// native (pure-Python permute 3167 us vs 54 us through ctypes, 58x), so this was never an arithmetic
// problem: it is the same Python-loop-around-a-native-kernel shape that made _permute_snapshots 146x and
// fri.prove the fold's bottleneck. Batching the permute alone only reaches ~23 us/call, so the fix is to
// move the LOOP, exactly as doc/rust-only-proving.md says.
//
// Bit-identical to execnode/stark/merkle.verify:
//     h = leaf(value); for sib in path: h = node(h, sib) if idx%2==0 else node(sib, h); idx //= 2
//     ok = (h == root)
// `mode`: 0 = RECURSION backend (rleaf/rnode, one permutation per node, no length prefix)
//         1 = ALGHASH2 backend (hashn with the length prefix)
// `ext` : 0 = base leaf (one field element), 1 = extension leaf (d limbs, DOM_LEAF_EXT frame),
//         2 = the leaf DIGEST is supplied directly (d == CAP lanes), for row-commitment openings where the
//             caller already hashed a whole trace row (rrow) — this is merkle.verify_digest's entry point.
//             Without it those openings had to climb in PYTHON, one ctypes crossing per level: measured on
//             the live 118.57 MiB settle proof, 57,600 alghash2.node calls / 4.35 s came back through
//             merkle.verify_digest while the batched path next door did the rest natively.
// `d`   : limbs per leaf (1 when ext == 0, CAP when ext == 2)
// Layout: roots[m*CAP], indices[m], leaves[m*d], paths[m*plen*CAP]. Writes out[m] as 1/0.
// Returns 0, or -1 on a rejected shape — a bad degree is REFUSED rather than silently truncated, because a
// truncated ext frame would alias a base leaf and let one tree's opening verify against the other's root.
#[no_mangle]
pub unsafe extern "C" fn merkle_verify_paths(roots: *const u64, indices: *const u64, leaves: *const u64,
                                             paths: *const u64, m: usize, plen: usize, d: usize,
                                             mode: u32, ext: u32, out: *mut u8) -> i64 {
    if d < 1 || d > 8 { return -1; }
    if ext == 1 && mode == 0 && d > (RATE / 2 - 1) { return -1; }   // must fit the 4-lane rleaf head
    if mode > 1 || ext > 2 { return -1; }
    // A supplied digest must be exactly CAP lanes. Refuse anything else rather than pad or truncate: a
    // short frame would alias a DIFFERENT leaf and let one tree's opening verify against another's root.
    if ext == 2 && d != CAP { return -1; }

    for i in 0..m {
        // ---- leaf digest -------------------------------------------------------------------------
        let mut h = [0u64; CAP];
        if ext == 2 {
            // Already a digest (the caller hashed the row): no leaf framing, climb straight from it.
            for k in 0..CAP { h[k] = *leaves.add(i * d + k); }
        } else if mode == 0 {
            let mut s = [0u64; W];
            if ext == 1 {
                s[0] = DOM_LEAF_EXT;
                for k in 0..d { s[1 + k] = *leaves.add(i * d + k); }
            } else {
                s[0] = 1;                                  // DOM_LEAF
                s[1] = *leaves.add(i * d);
            }
            for k in 0..CAP { s[RATE + k] = IV[k]; }
            permute(&mut s);
            for k in 0..CAP { h[k] = s[k]; }
        } else {
            let mut els = [0u64; 10];
            let n = if ext == 1 {
                els[0] = (1 + d) as u64; els[1] = DOM_LEAF_EXT;
                for k in 0..d { els[2 + k] = *leaves.add(i * d + k); }
                2 + d
            } else {
                els[0] = 2; els[1] = 1;                    // [len=2, DOM_LEAF, x]
                els[2] = *leaves.add(i * d);
                3
            };
            hashn(els.as_ptr(), n, h.as_mut_ptr());
        }

        // ---- climb ------------------------------------------------------------------------------
        let mut idx = *indices.add(i);
        for lvl in 0..plen {
            let sib = paths.add((i * plen + lvl) * CAP);
            // left child is `h` when idx is even, else the sibling is the left child
            let (lo, hi): ([u64; CAP], [u64; CAP]) = if idx % 2 == 0 {
                let mut b = [0u64; CAP];
                for k in 0..CAP { b[k] = *sib.add(k); }
                (h, b)
            } else {
                let mut a = [0u64; CAP];
                for k in 0..CAP { a[k] = *sib.add(k); }
                (a, h)
            };
            if mode == 0 {
                let mut s = [0u64; W];
                for k in 0..CAP { s[k] = lo[k]; s[CAP + k] = hi[k]; s[RATE + k] = IV[k]; }
                permute(&mut s);
                for k in 0..CAP { h[k] = s[k]; }
            } else {
                let mut els = [9u64, 2u64, 0, 0, 0, 0, 0, 0, 0, 0];   // [len=9, DOM_NODE, a0..3, b0..3]
                for k in 0..CAP { els[2 + k] = lo[k]; els[6 + k] = hi[k]; }
                hashn(els.as_ptr(), 10, h.as_mut_ptr());
            }
            idx /= 2;
        }

        let mut ok = 1u8;
        for k in 0..CAP { if h[k] != *roots.add(i * CAP + k) { ok = 0; } }
        *out.add(i) = ok;
    }
    0
}
