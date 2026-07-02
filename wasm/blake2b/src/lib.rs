// BLAKE2b-256 (no key, no salt/person) for the browser STARK prover — matches Python hashlib.blake2b(digest_size=32)
// and the noble JS impl exactly. Exports blake2b256(in_ptr, in_len, out_ptr) over wasm linear memory.
#![no_std]
#[panic_handler]
fn panic(_: &core::panic::PanicInfo) -> ! { loop {} }

const IV: [u64; 8] = [
    0x6a09e667f3bcc908, 0xbb67ae8584caa73b, 0x3c6ef372fe94f82b, 0xa54ff53a5f1d36f1,
    0x510e527fade682d1, 0x9b05688c2b3e6c1f, 0x1f83d9abfb41bd6b, 0x5be0cd19137e2179,
];
const SIGMA: [[usize; 16]; 12] = [
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
fn g(v: &mut [u64; 16], a: usize, b: usize, c: usize, d: usize, x: u64, y: u64) {
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(x);
    v[d] = (v[d] ^ v[a]).rotate_right(32);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(24);
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(y);
    v[d] = (v[d] ^ v[a]).rotate_right(16);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(63);
}

fn compress(h: &mut [u64; 8], m: &[u64; 16], t: u128, last: bool) {
    let mut v = [0u64; 16];
    v[..8].copy_from_slice(h);
    v[8..].copy_from_slice(&IV);
    v[12] ^= t as u64;
    v[13] ^= (t >> 64) as u64;
    if last { v[14] ^= 0xFFFFFFFFFFFFFFFF; }
    let mut i = 0;
    while i < 12 {
        let s = &SIGMA[i];
        g(&mut v, 0, 4, 8, 12, m[s[0]], m[s[1]]);
        g(&mut v, 1, 5, 9, 13, m[s[2]], m[s[3]]);
        g(&mut v, 2, 6, 10, 14, m[s[4]], m[s[5]]);
        g(&mut v, 3, 7, 11, 15, m[s[6]], m[s[7]]);
        g(&mut v, 0, 5, 10, 15, m[s[8]], m[s[9]]);
        g(&mut v, 1, 6, 11, 12, m[s[10]], m[s[11]]);
        g(&mut v, 2, 7, 8, 13, m[s[12]], m[s[13]]);
        g(&mut v, 3, 4, 9, 14, m[s[14]], m[s[15]]);
        i += 1;
    }
    let mut k = 0;
    while k < 8 { h[k] ^= v[k] ^ v[k + 8]; k += 1; }
}

fn read_block(b: &[u8]) -> [u64; 16] {
    let mut m = [0u64; 16];
    let mut i = 0;
    while i < 16 {
        let o = i * 8;
        m[i] = (b[o] as u64) | (b[o+1] as u64) << 8 | (b[o+2] as u64) << 16 | (b[o+3] as u64) << 24
             | (b[o+4] as u64) << 32 | (b[o+5] as u64) << 40 | (b[o+6] as u64) << 48 | (b[o+7] as u64) << 56;
        i += 1;
    }
    m
}

#[no_mangle]
pub extern "C" fn blake2b256(in_ptr: *const u8, in_len: usize, out_ptr: *mut u8) {
    let mut h = IV;
    h[0] ^= 0x0101_0020; // 0x01010000 ^ (kk<<8=0) ^ outlen(32)
    let input = unsafe { core::slice::from_raw_parts(in_ptr, in_len) };
    let mut t: u128 = 0;
    let mut off = 0usize;
    while off + 128 < in_len {
        t += 128;
        let m = read_block(&input[off..off + 128]);
        compress(&mut h, &m, t, false);
        off += 128;
    }
    let rem = in_len - off; // 0..=128
    t += rem as u128;
    let mut block = [0u8; 128];
    block[..rem].copy_from_slice(&input[off..off + rem]);
    let m = read_block(&block);
    compress(&mut h, &m, t, true);
    let out = unsafe { core::slice::from_raw_parts_mut(out_ptr, 32) };
    let mut i = 0;
    while i < 4 {
        let b = h[i].to_le_bytes();
        out[i*8..i*8+8].copy_from_slice(&b);
        i += 1;
    }
}
