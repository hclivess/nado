/* ----------------------------------------------------------------------------------------------
 * NADO messaging (doc/messaging.md) — client crypto + transport for the off-chain, E2E-encrypted,
 * post-quantum message pool. Self-contained + framework-free so it runs BOTH in the browser wallet
 * and under Node (for the protocol test). No DOM, no wallet state — pure functions over a seed.
 *
 * v1 crypto: per-message ML-KEM-768 encapsulation to the recipient's identity key + a blake2b-CTR
 * AEAD (encrypt-then-MAC, the same construction the wallet uses at rest), signed with ML-DSA-44.
 * Recipient is HIDDEN: no cleartext `to` — a detection tag (recomputable only after decapsulation)
 * plus trial-decapsulation on fetch. The KEM Double Ratchet (forward secrecy + PCS) layers on top
 * of this transport later without changing the envelope shape or the node.
 * -------------------------------------------------------------------------------------------- */
// Messaging hashcash domain (mirrors ops/message_pool.py DOMAIN_MSG_POW).
const DOMAIN_MSG_POW = "msg-pow-v1";

import { blake2b, bytesToHex, hexToBytes, ml_dsa44, ml_kem768 } from './vendor/nado-crypto.js?v=mlkem';

const _enc = new TextEncoder();

// ---- canonical hashing: byte-identical to the node's hashing.blake2b_hash(list) --------------------------
function jsonEscape(s) {
  let out = '"';
  for (const ch of s) {
    const c = ch.codePointAt(0);
    if (ch === '"') out += '\\"';
    else if (ch === '\\') out += '\\\\';
    else if (c === 8) out += '\\b';
    else if (c === 9) out += '\\t';
    else if (c === 10) out += '\\n';
    else if (c === 12) out += '\\f';
    else if (c === 13) out += '\\r';
    else if (c < 0x20) out += '\\u' + c.toString(16).padStart(4, '0');
    else if (c < 0x7f) out += ch;
    else if (c <= 0xffff) out += '\\u' + c.toString(16).padStart(4, '0');
    else { const v = c - 0x10000; out += '\\u' + (0xd800 + (v >> 10)).toString(16).padStart(4, '0')
                                       + '\\u' + (0xdc00 + (v & 0x3ff)).toString(16).padStart(4, '0'); }
  }
  return out + '"';
}
function canonicalize(d) {
  const t = typeof d;
  if (d === null) return 'null';
  if (t === 'boolean') return d ? 'true' : 'false';
  if (t === 'number') { if (!Number.isFinite(d) || !Number.isInteger(d)) throw new Error('non-integer in canonical'); return String(d); }
  if (t === 'string') return jsonEscape(d);
  if (Array.isArray(d)) return '[' + d.map(canonicalize).join(',') + ']';
  if (t === 'object') { const k = Object.keys(d).sort(); return '{' + k.map(x => jsonEscape(x) + ':' + canonicalize(d[x])).join(',') + '}'; }
  throw new Error('unsupported type in canonical encoding');
}
export function b2hash(list, size = 32) { return bytesToHex(blake2b(_enc.encode(canonicalize(list)), { dkLen: size })); }

// ---- blake2b-CTR AEAD (encrypt-then-MAC), keyed by the KEM shared secret ----------------------------------
function keyed(data, key, len) { return blake2b(data, { key, dkLen: len }); }
function u8cat(...a) { const n = a.reduce((s, x) => s + x.length, 0), o = new Uint8Array(n); let p = 0; for (const x of a) { o.set(x, p); p += x.length; } return o; }
function ctrXor(data, keyEnc, nonce) {
  const out = new Uint8Array(data.length);
  for (let off = 0; off < data.length; off += 64) {
    const blk = off >>> 6, ctr = new Uint8Array([(blk >>> 24) & 255, (blk >>> 16) & 255, (blk >>> 8) & 255, blk & 255]);
    const ks = keyed(u8cat(nonce, ctr), keyEnc, 64);
    for (let i = 0; i < 64 && off + i < data.length; i++) out[off + i] = data[off + i] ^ ks[i];
  }
  return out;
}
function ctEq(a, b) { if (a.length !== b.length) return false; let d = 0; for (let i = 0; i < a.length; i++) d |= a[i] ^ b[i]; return d === 0; }
function aeadKeys(ss) {  // derive independent enc + mac keys from the KEM shared secret (domain-separated)
  return { enc: keyed(ss, _enc.encode('nado-msg-enc'), 32), mac: keyed(ss, _enc.encode('nado-msg-mac'), 32) };
}
function seal(ss, ptBytes) {          // -> { nonce, ct }  where ct = mac(64hex) || cipher(hex)
  const { enc, mac } = aeadKeys(ss);
  const nonce = globalThis.crypto.getRandomValues(new Uint8Array(16));
  const cipher = ctrXor(ptBytes, enc, nonce);
  const tag = keyed(u8cat(nonce, cipher), mac, 32);
  return { nonce: bytesToHex(nonce), ct: bytesToHex(tag) + bytesToHex(cipher) };
}
function open(ss, nonceHex, ctHex) {  // -> plaintext bytes | null (null on MAC failure => not ours / tampered)
  try {
    const { enc, mac } = aeadKeys(ss);
    const nonce = hexToBytes(nonceHex), tag = hexToBytes(ctHex.slice(0, 64)), cipher = hexToBytes(ctHex.slice(64));
    if (!ctEq(keyed(u8cat(nonce, cipher), mac, 32), tag)) return null;
    return ctrXor(cipher, enc, nonce);
  } catch { return null; }
}

// ---- identity: ML-DSA (sign/address) + ML-KEM (encrypt), both derived from the account seed ---------------
export function identity(accountSeedHex) {
  const dsa = ml_dsa44.keygen(hexToBytes(accountSeedHex));        // 32-byte seed
  const kemSeed = hexToBytes(b2hash(['nado-msg-kem', accountSeedHex], 64));  // ML-KEM wants 64 bytes
  const kem = ml_kem768.keygen(kemSeed);
  return {
    dsaPub: bytesToHex(dsa.publicKey), dsaSecret: dsa.secretKey, dsaPubBytes: dsa.publicKey,
    kemPub: bytesToHex(kem.publicKey), kemSecret: kem.secretKey,
  };
}
export function signBytes(id, msgBytes) {   // verify-before-return, re-sign a rare non-verifying hedge
  for (let i = 0; i < 8; i++) {
    const sig = ml_dsa44.sign(id.dsaSecret, msgBytes);
    if (ml_dsa44.verify(id.dsaPubBytes, msgBytes, sig)) return bytesToHex(sig);
  }
  throw new Error('could not produce a verifying signature — retry');
}

// ---- proof-of-work (hashcash) — matches ops/message_pool.pow_ok --------------------------------------------
export const POW_BITS = 12;
function leadingZeroBits(hex) {
  let n = 0;
  for (const ch of hex) { const v = parseInt(ch, 16); if (v === 0) { n += 4; continue; } n += 3 - (31 - Math.clz32(v)); break; }
  return n;
}
function minePow(sender, tag, ct, ts, bits = POW_BITS) {
  for (let i = 0; ; i++) { const p = i.toString(16); if (leadingZeroBits(b2hash([DOMAIN_MSG_POW, sender, tag, ct, ts, p])) >= bits) return p; }
}

// ---- envelope + prekey bundle ------------------------------------------------------------------------------
export function detectionTag(ssBytes) { return b2hash(['nado-msg-detect', bytesToHex(ssBytes)], 16); }

// Encrypt `plaintextObj` to `recipientKemPubHex` and produce a signed, PoW'd envelope from `id`.
export function makeEnvelope(id, senderAddr, recipientKemPubHex, plaintextObj, ts) {
  const { cipherText, sharedSecret } = ml_kem768.encapsulate(hexToBytes(recipientKemPubHex));
  const sealed = seal(sharedSecret, _enc.encode(JSON.stringify(plaintextObj)));
  const env = {
    v: 1, sender: senderAddr, public_key: id.dsaPub,
    tag: detectionTag(sharedSecret), hdr: bytesToHex(cipherText),
    nonce: sealed.nonce, ct: sealed.ct, ts, pow: '', sig: '',
  };
  env.pow = minePow(env.sender, env.tag, env.ct, env.ts);
  env.sig = signBytes(id, hexToBytes(b2hash([env.v, env.sender, env.public_key, env.tag, env.hdr, env.nonce, env.ct, env.ts, env.pow])));
  return env;
}

// Try to decrypt a fetched envelope as ours. Returns the plaintext object or null.
export function tryOpen(id, env) {
  let ss;
  try { ss = ml_kem768.decapsulate(hexToBytes(env.hdr), id.kemSecret); } catch { return null; }
  if (detectionTag(ss) !== env.tag) return null;              // cheap reject before the AEAD
  const pt = open(ss, env.nonce, env.ct);
  if (!pt) return null;
  try { return JSON.parse(new TextDecoder().decode(pt)); } catch { return null; }
}

export function makePrekeyBundle(id, addr, ts) {
  const b = { address: addr, public_key: id.dsaPub, ik_pub: id.kemPub, spk_pub: id.kemPub, spk_ts: ts, ts, sig: '' };
  b.sig = signBytes(id, hexToBytes(b2hash([b.address, b.public_key, b.ik_pub, b.spk_pub, b.spk_ts, b.ts])));
  return b;
}

export function messageId(env) {
  return b2hash([env.v, env.sender, env.public_key, env.tag, env.hdr, env.nonce, env.ct, env.ts, env.pow, env.sig]);
}
