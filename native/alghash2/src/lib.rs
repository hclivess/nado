// alghash2 in native Rust — the wide-sponge algebraic hash on the STARK-recursion hot path
// (doc/zk-recursion.md). Byte-identical to execnode/stark/alghash2.py: the Python side computes the round
// constants / IV / MDS (blake2b nothing-up-my-sleeve) and hands them in via `init`, so Rust just runs the
// field arithmetic FAST. Loaded by ctypes from execnode/stark/alghash2.py when built; otherwise Python falls
// back to itself, bit-for-bit. Width 12, rate 8, capacity 4 (256-bit digest).
#![no_std]

#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { loop {} }

const P: u128 = 0xFFFFFFFF00000001;   // Goldilocks 2^64 - 2^32 + 1
const W: usize = 12;
const R: usize = 8;
const RATE: usize = 8;
const CAP: usize = 4;

static mut RC: [[u64; W]; R] = [[0; W]; R];
static mut IV: [u64; CAP] = [0; CAP];
static mut MDS: [[u64; W]; W] = [[0; W]; W];

#[inline(always)] fn mulf(a: u64, b: u64) -> u64 { (((a as u128) * (b as u128)) % P) as u64 }
#[inline(always)] fn addf(a: u64, b: u64) -> u64 { (((a as u128) + (b as u128)) % P) as u64 }

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
}

#[inline(always)]
unsafe fn permute(s: &mut [u64; W]) {
    for r in 0..R {
        let mut t = [0u64; W];
        for i in 0..W { t[i] = pow7(addf(s[i], RC[r][i])); }
        for i in 0..W {
            let mut acc: u128 = 0;
            for j in 0..W { acc += (mulf(MDS[i][j], t[j])) as u128; }
            s[i] = (acc % P) as u64;
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
