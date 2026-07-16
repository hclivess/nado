// Goldilocks field (p = 2^64 - 2^32 + 1) + NTT in WebAssembly for the browser STARK prover. Produces bit-
// identical field values to static/stark/field.js (BigInt) and execnode/stark/field.py, so proofs still verify.
// JS writes u64 field elements into BUF, supplies the root + n_inv (computed in JS), and calls ntt/scale.
#![no_std]
#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { loop {} }

const P: u128 = 0xFFFFFFFF00000001;
const PU64: u64 = 0xFFFFFFFF00000001;
const EPSILON: u64 = 0xFFFFFFFF;      // 2^32 - 1 ( = 2^64 mod p )

// Fast Goldilocks reduction of a 128-bit product to [0, p), NO division — the NTT's field-multiply hot path.
// Bit-identical to (x % p); verified against the pure-Python NTT (execnode.stark.field) over large N.
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
#[inline(always)] fn addf(a: u64, b: u64) -> u64 { (((a as u128) + (b as u128)) % P) as u64 }
#[inline(always)] fn subf(a: u64, b: u64) -> u64 { (((a as u128) + P - (b as u128)) % P) as u64 }

// The browser WASM prover only ever handles small traces (T ~ 1024, N <= 8192), so it keeps the tiny static
// buffer. The NATIVE .so (the Python prover's accelerator) must handle the STARK-RECURSION domains — a fold /
// composition proof's LDE reaches N in the 10^5-10^6 range, which used to fall back to pure-Python big-int NTT
// (the memory/time wall). A larger static buffer lets the native u64 NTT cover them (bit-identical; the NTT
// operates on BUF[0..n] regardless of capacity). 2^22 = 4M elements → BUF 32 MB + TW 16 MB static, fine
// natively; the wasm32 build is unchanged.
#[cfg(target_arch = "wasm32")]
const NMAX: usize = 8192;
#[cfg(not(target_arch = "wasm32"))]
const NMAX: usize = 1 << 22;
static mut BUF: [u64; NMAX] = [0; NMAX];
static mut TW: [u64; NMAX / 2] = [0; NMAX / 2];

#[no_mangle] pub extern "C" fn buf_ptr() -> *mut u64 { unsafe { BUF.as_mut_ptr() } }

fn bitrev(a: &mut [u64], n: usize) {
    let mut j = 0usize;
    let mut i = 1usize;
    while i < n {
        let mut bit = n >> 1;
        while j & bit != 0 { j ^= bit; bit >>= 1; }
        j ^= bit;
        if i < j { a.swap(i, j); }
        i += 1;
    }
}

// In-place NTT on BUF[0..n]. root = primitive n-th root (forward) or its inverse. If inverse!=0, scale by n_inv.
#[no_mangle]
pub extern "C" fn ntt(n: usize, root: u64, inverse: u32, n_inv: u64) {
    let a = unsafe { &mut BUF };
    let tw = unsafe { &mut TW };
    bitrev(a, n);
    let h = n >> 1;
    tw[0] = 1;
    let mut j = 1;
    while j < h { tw[j] = mulf(tw[j - 1], root); j += 1; }
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
    if inverse != 0 {
        let mut k = 0;
        while k < n { a[k] = mulf(a[k], n_inv); k += 1; }
    }
}

// Coset scaling: BUF[j] *= offset^j for j in 0..n.
#[no_mangle]
pub extern "C" fn scale(n: usize, offset: u64) {
    let a = unsafe { &mut BUF };
    let mut s = 1u64;
    let mut j = 0;
    while j < n { a[j] = mulf(a[j], s); s = mulf(s, offset); j += 1; }
}
