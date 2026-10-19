// BLAKE2s-256 (RFC 7693) with an 8-byte personalization, in plain JS — the browser half of the gen-29 hashes
// (Goldilocks retirement G3/G6): the contract VM's hash accumulator (execnode/zkvm2.hash_words, person "NADOvmH1") and
// whatever else the client must recompute exactly. No key, no salt, digest 32 bytes, fanout/depth 1 — the parameters
// Python's hashlib.blake2s(data, digest_size=32, person=...) uses. tests/test_the_browser_blake2s_equals_hashlib.mjs
// checks it against hashlib over many lengths and personalizations; never edit it without that test.
const IV = new Uint32Array([0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19]);
const SIGMA = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
  [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4], [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
  [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13], [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
  [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11], [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
  [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5], [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0]];
const rotr = (x, n) => (x >>> n) | (x << (32 - n));

function compress(h, block, t, last) {
  const v = new Uint32Array(16), m = new Uint32Array(16);
  for (let i = 0; i < 16; i++) m[i] = block[4 * i] | (block[4 * i + 1] << 8) | (block[4 * i + 2] << 16) | (block[4 * i + 3] << 24);
  for (let i = 0; i < 8; i++) { v[i] = h[i]; v[i + 8] = IV[i]; }
  v[12] ^= t >>> 0;
  v[13] ^= Math.floor(t / 0x100000000) >>> 0;
  if (last) v[14] = ~v[14];
  const G = (a, b, c, d, x, y) => {
    v[a] = (v[a] + v[b] + x) >>> 0; v[d] = rotr(v[d] ^ v[a], 16);
    v[c] = (v[c] + v[d]) >>> 0;     v[b] = rotr(v[b] ^ v[c], 12);
    v[a] = (v[a] + v[b] + y) >>> 0; v[d] = rotr(v[d] ^ v[a], 8);
    v[c] = (v[c] + v[d]) >>> 0;     v[b] = rotr(v[b] ^ v[c], 7);
  };
  for (let r = 0; r < 10; r++) {
    const s = SIGMA[r];
    G(0, 4, 8, 12, m[s[0]], m[s[1]]); G(1, 5, 9, 13, m[s[2]], m[s[3]]);
    G(2, 6, 10, 14, m[s[4]], m[s[5]]); G(3, 7, 11, 15, m[s[6]], m[s[7]]);
    G(0, 5, 10, 15, m[s[8]], m[s[9]]); G(1, 6, 11, 12, m[s[10]], m[s[11]]);
    G(2, 7, 8, 13, m[s[12]], m[s[13]]); G(3, 4, 9, 14, m[s[14]], m[s[15]]);
  }
  for (let i = 0; i < 8; i++) h[i] = (h[i] ^ v[i] ^ v[i + 8]) >>> 0;
}

// blake2s(data: Uint8Array, person: Uint8Array of length 0 or 8) -> Uint8Array(32)
export function blake2s(data, person = new Uint8Array(0)) {
  if (person.length !== 0 && person.length !== 8) throw new Error("blake2s personalization is 8 bytes");
  const h = new Uint32Array(IV);
  h[0] ^= 0x01010020;                                   // digest 32, key 0, fanout 1, depth 1
  if (person.length === 8) {
    h[6] ^= person[0] | (person[1] << 8) | (person[2] << 16) | (person[3] << 24);
    h[7] ^= person[4] | (person[5] << 8) | (person[6] << 16) | (person[7] << 24);
  }
  let t = 0, off = 0;
  while (data.length - off > 64) { t += 64; compress(h, data.subarray(off, off + 64), t, false); off += 64; }
  const last = new Uint8Array(64);
  last.set(data.subarray(off));
  t += data.length - off;
  compress(h, last, t, true);
  const out = new Uint8Array(32);
  for (let i = 0; i < 8; i++) { out[4 * i] = h[i] & 255; out[4 * i + 1] = (h[i] >>> 8) & 255; out[4 * i + 2] = (h[i] >>> 16) & 255; out[4 * i + 3] = h[i] >>> 24; }
  return out;
}

const ENC = new TextEncoder();
export const personOf = (s) => ENC.encode(s);

// a 256-bit word as 32 bytes big-endian, and back — the encoding zkvm2 hashes (int.to_bytes(32, "big"))
export function wordBytes(x) {
  let v = BigInt(x) & ((1n << 256n) - 1n);
  const b = new Uint8Array(32);
  for (let i = 31; i >= 0; i--) { b[i] = Number(v & 255n); v >>= 8n; }
  return b;
}
export function bytesWord(b) {
  let v = 0n;
  for (const x of b) v = (v << 8n) | BigInt(x);
  return v;
}

// hashWords(words): execnode/zkvm2.hash_words — h = 0; for each word: h = BLAKE2s(h || word, person "NADOvmH1")
const VM_PERSON = personOf("NADOvmH1");
export function hashWords(words) {
  let h = new Uint8Array(32);
  for (const w of words) {
    const buf = new Uint8Array(64);
    buf.set(h, 0); buf.set(wordBytes(w), 32);
    h = blake2s(buf, VM_PERSON);
  }
  return bytesWord(h);
}
