// BLAKE2b-256 + Merkle tree in WebAssembly for the browser STARK prover. Byte-identical to Python
// hashlib.blake2b(digest_size=32) and execnode/stark/merkle.py. Exports:
//   blake2b256(in,len,out)  — hash arbitrary bytes (transcript/Fiat-Shamir path)
//   merkle_commit(n)        — build a full Merkle tree over n u64 field elements in MIN, layers -> MOUT
#![no_std]
#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { loop {} }

const IV: [u64; 8] = [
    0x6a09e667f3bcc908, 0xbb67ae8584caa73b, 0x3c6ef372fe94f82b, 0xa54ff53a5f1d36f1,
    0x510e527fade682d1, 0x9b05688c2b3e6c1f, 0x1f83d9abfb41bd6b, 0x5be0cd19137e2179,
];
const SIGMA: [[usize; 16]; 12] = [
    [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15],[14,10,4,8,9,15,13,6,1,12,0,2,11,7,5,3],
    [11,8,12,0,5,2,15,13,10,14,3,6,7,1,9,4],[7,9,3,1,13,12,11,14,2,6,5,10,4,0,15,8],
    [9,0,5,7,2,4,10,15,14,1,11,12,6,8,3,13],[2,12,6,10,0,11,8,3,4,13,7,5,15,14,1,9],
    [12,5,1,15,14,13,4,10,0,7,6,3,9,2,8,11],[13,11,7,14,12,1,3,9,5,0,15,4,8,6,2,10],
    [6,15,14,9,11,3,0,8,12,2,13,7,1,4,10,5],[10,2,8,4,7,6,1,5,15,11,9,14,3,12,13,0],
    [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15],[14,10,4,8,9,15,13,6,1,12,0,2,11,7,5,3],
];

#[inline(always)]
fn g(v: &mut [u64; 16], a: usize, b: usize, c: usize, d: usize, x: u64, y: u64) {
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(x); v[d] = (v[d] ^ v[a]).rotate_right(32);
    v[c] = v[c].wrapping_add(v[d]);                 v[b] = (v[b] ^ v[c]).rotate_right(24);
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(y); v[d] = (v[d] ^ v[a]).rotate_right(16);
    v[c] = v[c].wrapping_add(v[d]);                 v[b] = (v[b] ^ v[c]).rotate_right(63);
}
fn compress(h: &mut [u64; 8], m: &[u64; 16], t: u128, last: bool) {
    let mut v = [0u64; 16];
    v[..8].copy_from_slice(h); v[8..].copy_from_slice(&IV);
    v[12] ^= t as u64; v[13] ^= (t >> 64) as u64;
    if last { v[14] ^= 0xFFFFFFFFFFFFFFFF; }
    let mut i = 0;
    while i < 12 {
        let s = &SIGMA[i];
        g(&mut v,0,4,8,12,m[s[0]],m[s[1]]);  g(&mut v,1,5,9,13,m[s[2]],m[s[3]]);
        g(&mut v,2,6,10,14,m[s[4]],m[s[5]]); g(&mut v,3,7,11,15,m[s[6]],m[s[7]]);
        g(&mut v,0,5,10,15,m[s[8]],m[s[9]]); g(&mut v,1,6,11,12,m[s[10]],m[s[11]]);
        g(&mut v,2,7,8,13,m[s[12]],m[s[13]]);g(&mut v,3,4,9,14,m[s[14]],m[s[15]]);
        i += 1;
    }
    let mut k = 0; while k < 8 { h[k] ^= v[k] ^ v[k + 8]; k += 1; }
}
fn read_block(b: &[u8]) -> [u64; 16] {
    let mut m = [0u64; 16]; let mut i = 0;
    while i < 16 {
        let o = i * 8;
        m[i] = (b[o] as u64)|(b[o+1] as u64)<<8|(b[o+2] as u64)<<16|(b[o+3] as u64)<<24
             |(b[o+4] as u64)<<32|(b[o+5] as u64)<<40|(b[o+6] as u64)<<48|(b[o+7] as u64)<<56;
        i += 1;
    }
    m
}
fn hash(input: &[u8], out: &mut [u8; 32]) {
    let mut h = IV; h[0] ^= 0x0101_0020;
    let mut t: u128 = 0; let mut off = 0usize;
    while off + 128 < input.len() {
        t += 128; let m = read_block(&input[off..off + 128]); compress(&mut h, &m, t, false); off += 128;
    }
    let rem = input.len() - off; t += rem as u128;
    let mut block = [0u8; 128]; block[..rem].copy_from_slice(&input[off..off + rem]);
    let m = read_block(&block); compress(&mut h, &m, t, true);
    let mut i = 0; while i < 4 { out[i*8..i*8+8].copy_from_slice(&h[i].to_le_bytes()); i += 1; }
}

#[no_mangle]
pub extern "C" fn blake2b256(in_ptr: *const u8, in_len: usize, out_ptr: *mut u8) {
    let input = unsafe { core::slice::from_raw_parts(in_ptr, in_len) };
    let out = unsafe { &mut *(out_ptr as *mut [u8; 32]) };
    hash(input, out);
}

// ---- Merkle over field vectors (matches merkle.py: leaf=H(["stark-leaf","<dec>"]), node=H(["stark-node","<hexA>","<hexB>"])) ----
const NMAX: usize = 8192;
static mut MIN: [u64; NMAX] = [0; NMAX];
static mut MOUT: [u8; 2 * NMAX * 32] = [0; 2 * NMAX * 32];   // all layers concatenated (leaves first)
const HEXD: [u8; 16] = *b"0123456789abcdef";

fn fmt_dec(mut x: u64, out: &mut [u8]) -> usize {
    if x == 0 { out[0] = b'0'; return 1; }
    let mut tmp = [0u8; 20]; let mut i = 0;
    while x > 0 { tmp[i] = b'0' + (x % 10) as u8; x /= 10; i += 1; }
    let mut k = 0; while k < i { out[k] = tmp[i - 1 - k]; k += 1; } i
}
fn fmt_hex(h: &[u8; 32], out: &mut [u8]) {
    let mut k = 0; while k < 32 { out[2*k] = HEXD[(h[k] >> 4) as usize]; out[2*k+1] = HEXD[(h[k] & 15) as usize]; k += 1; }
}
fn leaf_hash(x: u64, out: &mut [u8; 32]) {
    let mut buf = [0u8; 64]; let pre = b"[\"stark-leaf\",\"";
    let pl = pre.len(); buf[..pl].copy_from_slice(pre);
    let dl = fmt_dec(x, &mut buf[pl..]); let mut p = pl + dl;
    buf[p] = b'"'; buf[p+1] = b']'; p += 2; hash(&buf[..p], out);
}
fn node_hash(a: &[u8; 32], b: &[u8; 32], out: &mut [u8; 32]) {
    let mut buf = [0u8; 160]; let mut p = 0;
    let pre = b"[\"stark-node\",\""; buf[..pre.len()].copy_from_slice(pre); p += pre.len();
    fmt_hex(a, &mut buf[p..p+64]); p += 64;
    buf[p..p+3].copy_from_slice(b"\",\""); p += 3;
    fmt_hex(b, &mut buf[p..p+64]); p += 64;
    buf[p..p+2].copy_from_slice(b"\"]"); p += 2; hash(&buf[..p], out);
}

static mut HIN: [u8; 16384] = [0; 16384];
static mut HOUT: [u8; 32] = [0; 32];
#[no_mangle] pub extern "C" fn hin_ptr() -> *mut u8 { unsafe { HIN.as_mut_ptr() } }
#[no_mangle] pub extern "C" fn hout_ptr() -> *mut u8 { unsafe { HOUT.as_mut_ptr() } }
#[no_mangle] pub extern "C" fn min_ptr() -> *mut u64 { unsafe { MIN.as_mut_ptr() } }
#[no_mangle] pub extern "C" fn mout_ptr() -> *mut u8 { unsafe { MOUT.as_mut_ptr() } }

// Build the full tree over MIN[0..n] (n a power of two). Layers written to MOUT: leaves (n*32), then n/2*32, ...
#[no_mangle]
pub extern "C" fn merkle_commit(n: usize) {
    let base = unsafe { MOUT.as_mut_ptr() };
    let min = unsafe { &MIN };
    let mut i = 0;
    while i < n { let mut h = [0u8; 32]; leaf_hash(min[i], &mut h);
        unsafe { core::ptr::copy_nonoverlapping(h.as_ptr(), base.add(i * 32), 32); } i += 1; }
    let mut prev_off = 0usize; let mut cnt = n; let mut off = n * 32;
    while cnt > 1 {
        let half = cnt / 2; let cur_off = off; let mut k = 0;
        while k < half {
            let ao = prev_off + (2*k)*32; let bo = prev_off + (2*k+1)*32;
            let mut a = [0u8; 32]; let mut b = [0u8; 32]; let mut h = [0u8; 32];
            unsafe {
                core::ptr::copy_nonoverlapping(base.add(ao), a.as_mut_ptr(), 32);
                core::ptr::copy_nonoverlapping(base.add(bo), b.as_mut_ptr(), 32);
            }
            node_hash(&a, &b, &mut h);
            unsafe { core::ptr::copy_nonoverlapping(h.as_ptr(), base.add(cur_off + k*32), 32); }
            k += 1;
        }
        prev_off = cur_off; off = cur_off + half * 32; cnt = half;
    }
}
