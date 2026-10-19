//! Scalar reference of execnode/csmt.py — the compressed sparse tree's hashes, word for word as the circuit sees them.
//!
//! BLAKE2s-256 of one 64-byte block with an 8-byte personalization is ONE compression: h0 = IV ^ param block (digest
//! length 32, fanout 1, depth 1, personalization in words 6-7), the block's 16 little-endian words as the message, the
//! byte counter 64 and the last-block flag. A leaf is BLAKE2s(key || H(value)) under "NADOcsL1", an internal node
//! BLAKE2s(left || right) under "NADOcsN1"; digests and keys travel as 8 little-endian words, so a child's digest is
//! literally half of its parent's message. tests/test_the_stwo_tree_reference_equals_csmt_py.py checks every function
//! here against the Python tree.

pub const IV: [u32; 8] =
    [0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19];
const SIGMA: [[usize; 16]; 10] = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
    [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
    [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
    [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
    [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
    [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
    [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
    [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
    [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
    [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
];

pub const PERSON_LEAF: &[u8; 8] = b"NADOcsL1";
pub const PERSON_NODE: &[u8; 8] = b"NADOcsN1";
pub const PERSON_VALUE: &[u8; 8] = b"NADOcsV1";

/// The chaining value a one-block BLAKE2s-256 starts from under `person`.
pub fn h0(person: &[u8; 8]) -> [u32; 8] {
    let mut h = IV;
    h[0] ^= 0x0101_0020;
    h[6] ^= u32::from_le_bytes(person[0..4].try_into().unwrap());
    h[7] ^= u32::from_le_bytes(person[4..8].try_into().unwrap());
    h
}

/// The 16-word state the compression's rounds start from: h0, then IV with the 64-byte counter and last-block flag.
pub fn v_init(person: &[u8; 8]) -> [u32; 16] {
    let h = h0(person);
    [h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7], IV[0], IV[1], IV[2], IV[3], IV[4] ^ 64, IV[5], !IV[6], IV[7]]
}

fn g(v: &mut [u32; 16], a: usize, b: usize, c: usize, d: usize, x: u32, y: u32) {
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(x);
    v[d] = (v[d] ^ v[a]).rotate_right(16);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(12);
    v[a] = v[a].wrapping_add(v[b]).wrapping_add(y);
    v[d] = (v[d] ^ v[a]).rotate_right(8);
    v[c] = v[c].wrapping_add(v[d]);
    v[b] = (v[b] ^ v[c]).rotate_right(7);
}

/// The 16-word state after the ten rounds (what upstream's scheduler publishes as its output state).
pub fn rounds(v0: [u32; 16], m: &[u32; 16]) -> [u32; 16] {
    let mut v = v0;
    for s in SIGMA.iter() {
        g(&mut v, 0, 4, 8, 12, m[s[0]], m[s[1]]);
        g(&mut v, 1, 5, 9, 13, m[s[2]], m[s[3]]);
        g(&mut v, 2, 6, 10, 14, m[s[4]], m[s[5]]);
        g(&mut v, 3, 7, 11, 15, m[s[6]], m[s[7]]);
        g(&mut v, 0, 5, 10, 15, m[s[8]], m[s[9]]);
        g(&mut v, 1, 6, 11, 12, m[s[10]], m[s[11]]);
        g(&mut v, 2, 7, 8, 13, m[s[12]], m[s[13]]);
        g(&mut v, 3, 4, 9, 14, m[s[14]], m[s[15]]);
    }
    v
}

/// One-block BLAKE2s-256 under `person`: the digest words h0 ^ v[0..8] ^ v[8..16].
pub fn compress(person: &[u8; 8], m: &[u32; 16]) -> [u32; 8] {
    let v = rounds(v_init(person), m);
    let h = h0(person);
    std::array::from_fn(|i| h[i] ^ v[i] ^ v[i + 8])
}

pub fn words(b: &[u8; 32]) -> [u32; 8] {
    std::array::from_fn(|i| u32::from_le_bytes(b[4 * i..4 * i + 4].try_into().unwrap()))
}

pub fn bytes(w: &[u32; 8]) -> [u8; 32] {
    let mut out = [0u8; 32];
    for i in 0..8 {
        out[4 * i..4 * i + 4].copy_from_slice(&w[i].to_le_bytes());
    }
    out
}

fn cat(a: &[u32; 8], b: &[u32; 8]) -> [u32; 16] {
    std::array::from_fn(|i| if i < 8 { a[i] } else { b[i - 8] })
}

pub fn leaf(key: &[u32; 8], vh: &[u32; 8]) -> [u32; 8] {
    compress(PERSON_LEAF, &cat(key, vh))
}

pub fn node(l: &[u32; 8], r: &[u32; 8]) -> [u32; 8] {
    compress(PERSON_NODE, &cat(l, r))
}

/// bit `depth` of the key, most significant first — csmt.py `bit`: byte depth/8 of the 32-byte key, bit 7 - depth%8
pub fn bit(key: &[u32; 8], depth: usize) -> u32 {
    let b = bytes(key);
    ((b[depth >> 3] >> (7 - (depth & 7))) & 1) as u32
}

/// The root a leaf at depth `sibs.len()` implies: fold up through the siblings (root first, as csmt.prove lists them).
pub fn root_from_path(key: &[u32; 8], vh: &[u32; 8], sibs: &[[u32; 8]]) -> [u32; 8] {
    let mut h = leaf(key, vh);
    for i in (0..sibs.len()).rev() {
        h = if bit(key, i) == 1 { node(&sibs[i], &h) } else { node(&h, &sibs[i]) };
    }
    h
}
