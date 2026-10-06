/* TPM2_MakeCredential for the browser wallet — a byte-for-byte port of ops/tpm_aik.make_credential.
 *
 * WHY THE WALLET NEEDS IT. A bonded wallet can be DRAWN as a challenger for a stranger's TPM enrolment
 * (ops/tpm_enrol, doc/tpm-attestation-without-a-ca.md). Its job is the node's maybe_tpm_challenge: seal a random
 * secret to the enrolling chip's endorsement key, bound to the attestation key's Name, publish the credential
 * (`tpm_challenge`), and once the client's commitment is on chain publish (secret, seed) (`tpm_reveal`).
 *
 * WHAT MUST MATCH THE PYTHON EXACTLY, AND WHAT NEED NOT. On the reveal every node re-derives the credential BLOB
 * from (secret, seed) with the Python make_credential and compares it to the one this wallet published
 * (tpm_enrol.apply_reveal). So credentialBlob() below must agree with Python BYTE FOR BYTE, or the reveal is
 * refused and the enrolment it was drawn for dies at the last step — after the stranger's chip did everything
 * right. The encrypted SEED is RSA-OAEP, randomised, never compared by consensus; it only has to be something a
 * real chip opens (TPM2_ActivateCredential), which tests/test_tpm_cred_js_matches_python.py proves with the
 * Python software chip. INVARIANT: never change a byte of credentialBlob without re-running that test.
 *
 * WHY EVERYTHING IS HAND-WRITTEN AND SYNCHRONOUS. crypto.subtle is a SECURE-CONTEXT-ONLY API — undefined on a
 * wallet served over plain http://<ip>:9173 — and has no AES-CFB at all. The Python side is dependency-free for
 * the same family of reasons. SHA-256, HMAC, AES-128 (encrypt direction only: CFB never needs the inverse cipher)
 * and RSA over BigInt are small and fully specified, so they live here; only randomness comes from the platform
 * (crypto.getRandomValues, which IS available over http).
 *
 * No imports, no DOM: interface.js imports it, and node tests import it directly.
 */

// ---- bytes ------------------------------------------------------------------------------------------------
export function hexToBytes(h) {
  const s = String(h || "");
  if (s.length % 2 || /[^0-9a-fA-F]/.test(s)) throw new Error("not hex");
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(s.substr(i * 2, 2), 16);
  return out;
}
export function bytesToHex(b) {
  let s = "";
  for (const x of b) s += (x < 16 ? "0" : "") + x.toString(16);
  return s;                                          // lowercase, like Python's bytes.hex()
}
function concat(...parts) {
  let n = 0;
  for (const p of parts) n += p.length;
  const out = new Uint8Array(n);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}
const ascii = (s) => Uint8Array.from(s, (c) => c.charCodeAt(0));
function u32be(v) { return Uint8Array.of((v >>> 24) & 255, (v >>> 16) & 255, (v >>> 8) & 255, v & 255); }

// Labels are NUL-terminated in the TPM's KDF and OAEP usage (part 1 §24.4, §B.10.3) — exactly tpm_aik._LABEL_*.
export const LABEL_IDENTITY = ascii("IDENTITY\0");
export const LABEL_STORAGE = ascii("STORAGE\0");
export const LABEL_INTEGRITY = ascii("INTEGRITY\0");

/** A TPM2B_* — a 16-bit big-endian size followed by that many bytes (tpm_aik.tpm2b). */
export function tpm2b(data) {
  if (data.length > 0xffff) throw new Error("TPM2B overflow");
  return concat(Uint8Array.of((data.length >> 8) & 255, data.length & 255), data);
}

// ---- SHA-256 / HMAC-SHA256 (FIPS 180-4, RFC 2104) -----------------------------------------------------------
const K256 = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2]);

export function sha256(msg) {
  const len = msg.length;
  const padded = new Uint8Array(((len + 9 + 63) >> 6) << 6);
  padded.set(msg);
  padded[len] = 0x80;
  const bits = len * 8;                              // < 2^53: fine for every input this module ever hashes
  const dv = new DataView(padded.buffer);
  dv.setUint32(padded.length - 8, Math.floor(bits / 0x100000000));
  dv.setUint32(padded.length - 4, bits >>> 0);
  const H = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                             0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
  const W = new Uint32Array(64);
  const rotr = (x, n) => (x >>> n) | (x << (32 - n));
  for (let off = 0; off < padded.length; off += 64) {
    for (let t = 0; t < 16; t++) W[t] = dv.getUint32(off + t * 4);
    for (let t = 16; t < 64; t++) {
      const s0 = rotr(W[t - 15], 7) ^ rotr(W[t - 15], 18) ^ (W[t - 15] >>> 3);
      const s1 = rotr(W[t - 2], 17) ^ rotr(W[t - 2], 19) ^ (W[t - 2] >>> 10);
      W[t] = (W[t - 16] + s0 + W[t - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = H;
    for (let t = 0; t < 64; t++) {
      const S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const ch = (e & f) ^ (~e & g);
      const t1 = (h + S1 + ch + K256[t] + W[t]) >>> 0;
      const S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) >>> 0;
      h = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    H[0] += a; H[1] += b; H[2] += c; H[3] += d; H[4] += e; H[5] += f; H[6] += g; H[7] += h;
  }
  const out = new Uint8Array(32);
  const ov = new DataView(out.buffer);
  for (let i = 0; i < 8; i++) ov.setUint32(i * 4, H[i]);
  return out;
}

export function hmacSha256(key, msg) {
  let k = key.length > 64 ? sha256(key) : key;
  const k0 = new Uint8Array(64);
  k0.set(k);
  const ipad = k0.map((x) => x ^ 0x36), opad = k0.map((x) => x ^ 0x5c);
  return sha256(concat(opad, sha256(concat(ipad, msg))));
}

/** TPM 2.0 KDFa (part 1 §11.4.10.2), SHA-256: HMAC(key, UINT32(i) || label || u || v || UINT32(bits)) for
 *  i = 1, 2, … truncated to `bits`. `label` arrives already NUL-terminated (tpm_aik.kdfa). UINT32(bits) is in
 *  EVERY block, so a different width is a different key, not a prefix of it. */
export function kdfa(key, label, contextU, contextV, bits) {
  const n = (bits + 7) >> 3;
  const blocks = [];
  let have = 0;
  for (let i = 1; have < n; i++) {
    const d = hmacSha256(key, concat(u32be(i), label, contextU, contextV, u32be(bits)));
    blocks.push(d);
    have += d.length;
  }
  return concat(...blocks).slice(0, n);
}

// ---- AES-128, encrypt direction only (FIPS 197) --------------------------------------------------------------
// The S-box is GENERATED by the same integer walk as tpm_aik._aes_tables rather than pasted: a mistyped byte in a
// 256-entry table is invisible to review and wrong only for some inputs.
let _SBOX = null;
function sbox() {
  if (_SBOX) return _SBOX;
  const s = new Uint8Array(256);
  let p = 1, q = 1;
  do {
    p = p ^ ((p << 1) & 0xff) ^ (p & 0x80 ? 0x1b : 0);
    q ^= q << 1; q ^= q << 2; q ^= q << 4; q &= 0xff;
    if (q & 0x80) q ^= 0x09;
    const x = q ^ ((q << 1) | (q >> 7)) ^ ((q << 2) | (q >> 6)) ^ ((q << 3) | (q >> 5)) ^ ((q << 4) | (q >> 4));
    s[p] = (x ^ 0x63) & 0xff;
  } while (p !== 1);
  s[0] = 0x63;
  return (_SBOX = s);
}
const xtime = (a) => ((a << 1) ^ (a & 0x80 ? 0x1b : 0)) & 0xff;

function aes128Expand(key) {
  if (key.length !== 16) throw new Error("AES-128 key must be 16 bytes");
  const s = sbox();
  const w = [];
  for (let i = 0; i < 4; i++) w.push([key[4 * i], key[4 * i + 1], key[4 * i + 2], key[4 * i + 3]]);
  let rcon = 1;
  for (let i = 4; i < 44; i++) {
    let t = w[i - 1].slice();
    if (i % 4 === 0) {
      t = [t[1], t[2], t[3], t[0]].map((b) => s[b]);
      t[0] ^= rcon;
      rcon = xtime(rcon);
    }
    w.push(w[i - 4].map((b, j) => b ^ t[j]));
  }
  return w;
}

function aes128EncryptBlock(w, block) {
  const s = sbox();
  const st = [0, 1, 2, 3].map((r) => [0, 1, 2, 3].map((c) => block[r + 4 * c]));   // column-major state
  const addRoundKey = (rnd) => {
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) st[r][c] ^= w[rnd * 4 + c][r];
  };
  addRoundKey(0);
  for (let rnd = 1; rnd <= 10; rnd++) {
    for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) st[r][c] = s[st[r][c]];
    for (let r = 1; r < 4; r++) st[r] = st[r].slice(r).concat(st[r].slice(0, r));
    if (rnd !== 10) {
      for (let c = 0; c < 4; c++) {
        const a = [st[0][c], st[1][c], st[2][c], st[3][c]];
        st[0][c] = xtime(a[0]) ^ (xtime(a[1]) ^ a[1]) ^ a[2] ^ a[3];
        st[1][c] = a[0] ^ xtime(a[1]) ^ (xtime(a[2]) ^ a[2]) ^ a[3];
        st[2][c] = a[0] ^ a[1] ^ xtime(a[2]) ^ (xtime(a[3]) ^ a[3]);
        st[3][c] = (xtime(a[0]) ^ a[0]) ^ a[1] ^ a[2] ^ xtime(a[3]);
      }
    }
    addRoundKey(rnd);
  }
  const out = new Uint8Array(16);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) out[4 * c + r] = st[r][c];
  return out;
}

/** AES-128-CFB128 (tpm_aik.aes_cfb_encrypt): full-block feedback; a short final block still feeds a full one. */
export function aesCfbEncrypt(key, iv, data) {
  const w = aes128Expand(key);
  const out = new Uint8Array(data.length);
  let prev = Uint8Array.from(iv);
  for (let i = 0; i < data.length; i += 16) {
    const ks = aes128EncryptBlock(w, prev);
    const chunk = data.subarray(i, i + 16);
    const c = chunk.map((x, j) => x ^ ks[j]);
    out.set(c, i);
    prev = concat(c, ks.subarray(c.length));
  }
  return out;
}

// ---- RSA-OAEP (RFC 8017 §7.1.1, SHA-256 + MGF1-SHA-256) over BigInt -------------------------------------------
const toBig = (b) => (b.length ? BigInt("0x" + bytesToHex(b)) : 0n);
function fromBig(x, k) {
  let h = x.toString(16);
  if (h.length > 2 * k) throw new Error("integer too large");
  return hexToBytes(h.padStart(2 * k, "0"));
}
function modPow(b, e, m) {
  let r = 1n;
  b %= m;
  while (e > 0n) {
    if (e & 1n) r = (r * b) % m;
    b = (b * b) % m;
    e >>= 1n;
  }
  return r;
}

/** (n, e) out of a SubjectPublicKeyInfo by the SAME minimal DER walk as tpm_aik.rsa_public_numbers_from_spki —
 *  deliberately not a strict parser: real vendor endorsement certificates are not strictly DER. */
export function rsaPublicFromSpki(spki) {
  const tlv = (b, i) => {
    const ln = b[i + 1];
    if (ln < 0x80) return [b[i], i + 2, ln];
    const k = ln & 0x7f;
    return [b[i], i + 2 + k, Number(toBig(b.subarray(i + 2, i + 2 + k)))];
  };
  const [, h] = tlv(spki, 0);                        // SEQUENCE
  const [, h2, n2] = tlv(spki, h);                   // AlgorithmIdentifier
  const i = h + n2 + (h2 - h);
  const [, h3, n3] = tlv(spki, i);                   // BIT STRING
  const inner = spki.subarray(h3 + 1, h3 + n3);      // skip the unused-bits byte
  const [, ih] = tlv(inner, 0);
  const [, nh, nn] = tlv(inner, ih);
  const n = toBig(inner.subarray(nh, nh + nn));
  const [, eh, en] = tlv(inner, nh + nn);
  const e = toBig(inner.subarray(eh, eh + en));
  if (n < 2n || e < 1n) throw new Error("endorsement key is not an RSA key");
  return { n, e };
}

function mgf1(seed, length) {
  const parts = [];
  let have = 0;
  for (let i = 0; have < length; i++) { const d = sha256(concat(seed, u32be(i))); parts.push(d); have += d.length; }
  return concat(...parts).slice(0, length);
}

/** tpm_aik.rsa_oaep_encrypt. `rand` (32 bytes) is the OAEP seed — injectable so tests can pin the output against
 *  the Python byte for byte; production passes nothing and gets crypto.getRandomValues. */
export function rsaOaepEncrypt(n, e, message, label, rand) {
  const k = (n.toString(16).length + 1) >> 1;
  const hLen = 32;
  const ps = k - message.length - 2 * hLen - 2;
  if (ps < 0) throw new Error("message too long for this RSA key");
  const db = concat(sha256(label), new Uint8Array(ps), Uint8Array.of(1), message);
  const seed = rand || globalThis.crypto.getRandomValues(new Uint8Array(hLen));
  if (seed.length !== hLen) throw new Error("OAEP seed must be 32 bytes");
  const dbMask = mgf1(seed, k - hLen - 1);
  const maskedDb = db.map((x, i) => x ^ dbMask[i]);
  const seedMask = mgf1(maskedDb, hLen);
  const maskedSeed = seed.map((x, i) => x ^ seedMask[i]);
  const em = concat(Uint8Array.of(0), maskedSeed, maskedDb);
  return fromBig(modPow(toBig(em), e, n), k);
}

// ---- MakeCredential -------------------------------------------------------------------------------------------
/** The DETERMINISTIC half — the one consensus replays on the reveal: tpm2b(tpm2b(outerHmac) || encIdentity) with
 *    symKey      = KDFa(SHA-256, seed, "STORAGE\0",   name, "", 128)
 *    encIdentity = AES-128-CFB(symKey, IV = 0, tpm2b(secret))
 *    hmacKey     = KDFa(SHA-256, seed, "INTEGRITY\0", "",   "", 256)
 *    outerHmac   = HMAC-SHA256(hmacKey, encIdentity || name)
 *  INVARIANT: byte-identical to tpm_aik.make_credential(...)[0] (tests/test_tpm_cred_js_matches_python.py). */
export function credentialBlob(name, secret, seed) {
  const symKey = kdfa(seed, LABEL_STORAGE, name, new Uint8Array(0), 128);
  const encIdentity = aesCfbEncrypt(symKey, new Uint8Array(16), tpm2b(secret));
  const hmacKey = kdfa(seed, LABEL_INTEGRITY, new Uint8Array(0), new Uint8Array(0), 256);
  const outerHmac = hmacSha256(hmacKey, concat(encIdentity, name));
  return tpm2b(concat(tpm2b(outerHmac), encIdentity));
}

/** TPM2_MakeCredential (tpm_aik.make_credential): seal `secret` so that only a TPM holding BOTH the endorsement key
 *  (`ekSpki`, its SubjectPublicKeyInfo) and the object named `name` can recover it. All arguments are bytes;
 *  returns { blob, enc }, each already TPM2B-wrapped — the form TPM2_ActivateCredential expects and the form
 *  the `tpm_challenge` message carries (as hex). `oaepRand` is for tests only. */
export function makeCredential(ekSpki, name, secret, seed, oaepRand) {
  if (!(seed instanceof Uint8Array) || seed.length !== 32) throw new Error("seed must be 32 bytes");
  const { n, e } = rsaPublicFromSpki(ekSpki);
  const enc = tpm2b(rsaOaepEncrypt(n, e, seed, LABEL_IDENTITY, oaepRand));
  return { blob: credentialBlob(name, secret, seed), enc };
}
