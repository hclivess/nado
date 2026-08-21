/* ----------------------------------------------------------------------------------------------
 * NADO messaging (doc/messaging.md) — client crypto + transport for the off-chain, E2E-encrypted,
 * post-quantum message pool. Self-contained + framework-free so it runs BOTH in the browser wallet
 * and under Node (for the protocol test). No DOM, no wallet state — pure functions over a seed.
 *
 * v1 crypto (legacy, receive-only now): per-message ML-KEM-768 encapsulation to the recipient's
 * identity key + a blake2b-CTR AEAD (encrypt-then-MAC), signed with ML-DSA-44.
 *
 * v2 crypto (doc/messaging.md §3): a KEM DOUBLE RATCHET — Signal's state machine with every DH
 * replaced by an ML-KEM-768 encapsulation. Per-message keys are derived from a one-way symmetric
 * chain and deleted after use (FORWARD SECRECY: a stolen session cannot read earlier messages); a
 * fresh ratchet keypair is generated on every new sending chain and the peer encapsulates to it
 * (POST-COMPROMISE SECURITY: after one round-trip a past leak stops decrypting). Sessions live in
 * a caller-owned, JSON-serialisable store (`sessionsNew()`); the envelope shape + node are unchanged.
 *
 * Recipient is HIDDEN either way: no cleartext `to` — a detection tag, recomputable only with the
 * session's detection key (v2) or after decapsulation (v1 / a v2 session-init), plus trial decryption
 * on fetch. Nodes never learn who a message is for.
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
function seal(ss, ptBytes, ad = new Uint8Array(0)) {   // -> { nonce, ct }  where ct = mac(64hex) || cipher(hex)
  const { enc, mac } = aeadKeys(ss);
  const nonce = globalThis.crypto.getRandomValues(new Uint8Array(16));
  const cipher = ctrXor(ptBytes, enc, nonce);
  const tag = keyed(u8cat(ad, nonce, cipher), mac, 32);
  return { nonce: bytesToHex(nonce), ct: bytesToHex(tag) + bytesToHex(cipher) };
}
function open(ss, nonceHex, ctHex, ad = new Uint8Array(0)) {  // -> plaintext bytes | null (MAC failure => not ours / tampered)
  try {
    const { enc, mac } = aeadKeys(ss);
    const nonce = hexToBytes(nonceHex), tag = hexToBytes(ctHex.slice(0, 64)), cipher = hexToBytes(ctHex.slice(64));
    if (!ctEq(keyed(u8cat(ad, nonce, cipher), mac, 32), tag)) return null;
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
  return finishEnvelope(id, env);
}

// v1 (legacy): try to decrypt a fetched envelope as ours. Returns the plaintext object or null.
export function tryOpen(id, env) {
  if (env.v !== 1) return null;
  let ss;
  try { ss = ml_kem768.decapsulate(hexToBytes(env.hdr), id.kemSecret); } catch { return null; }
  if (detectionTag(ss) !== env.tag) return null;              // cheap reject before the AEAD
  const pt = open(ss, env.nonce, env.ct);
  if (!pt) return null;
  try { return JSON.parse(new TextDecoder().decode(pt)); } catch { return null; }
}

// Sign + PoW a filled envelope (shared by v1 makeEnvelope and the v2 ratchet)
function finishEnvelope(id, env) {
  env.pow = minePow(env.sender, env.tag, env.ct, env.ts);
  env.sig = signBytes(id, hexToBytes(b2hash([env.v, env.sender, env.public_key, env.tag, env.hdr, env.nonce, env.ct, env.ts, env.pow])));
  return env;
}

/* ==========================================================================================================
 * v2 — KEM Double Ratchet (doc/messaging.md §3.2)
 *
 * Signal's Double Ratchet with the DH swapped for ML-KEM-768. Because a KEM is one-sided, the party that
 * STARTS a new sending chain encapsulates to the peer's latest ratchet public key and ships the ciphertext
 * `c` in every header of that chain (the way Signal ships its DH pub), together with its own freshly
 * generated ratchet public key `k` for the peer to encapsulate to in turn. Receiving a header whose `k` is
 * new = a ratchet step: decapsulate `c` with our current ratchet secret, mix into the root key, start a
 * new receiving chain, and force our next send to start a new sending chain (fresh keypair → healing).
 *
 *   kdfRk(rk, ss)  -> [rk', ck]        root-key step (keyed blake2b, 64 B out)
 *   kdfCk(ck)      -> [ck', mk]        symmetric chain step; mk is used once and deleted
 *
 * Session setup ("KEM-X3DH" with the on-chain identity KEM key as the peer's initial ratchet key): the
 * initiator encapsulates `i` to the peer's identity key → ss0 → rk0; the FIRST chain then encapsulates to
 * the identity key again, so the session is normal-ratchet from message #1. `i` rides along on every
 * message until the peer has replied (a lost first message must not strand the session).
 *
 * Recipient hiding: tag = H_dk(nonce) with dk = KDF(rk0, 'detect'), a session-constant detection key.
 * The receiver hashes each fetched nonce under every session's dk (cheap, no KEM) and only decapsulates
 * `i` for envelopes no session claims. dk never leaves the two parties, so the node still can't route.
 *
 * Header bytes (base64 in `hdr` — a third smaller than hex; the node treats `hdr` as an opaque string):
 *   flags(1) ‖ pn(4) ‖ n(4) ‖ k(1184) ‖ c(1088) ‖ [i(1088) if flags&1]
 * Envelope overhead is ~10.8 KB (chain message) / ~12.3 KB (session-init) against the node's 16 KiB cap,
 * leaving ~2.5 KB / ~1.9 KB of body — MSG_BODY_MAX below keeps the wallet inside that.
 *
 * Session state is a plain JSON-able object (secrets hex) so the wallet can persist it as-is. Every
 * receive works on a COPY and commits only on a successful AEAD open — a bogus envelope never corrupts
 * state. `kem.sec === null` means "the identity KEM key" (never duplicated into the store).
 * ======================================================================================================= */
const KEM_PUB_LEN = 1184, KEM_CT_LEN = 1088, HDR_FIXED = 1 + 4 + 4 + KEM_PUB_LEN + KEM_CT_LEN;
export const MAX_SKIP = 200;          // most message keys we will derive-and-cache for one out-of-order gap
const MAX_SKIPPED_STORE = 600;        // cap on cached skipped keys per session (FIFO)
const MAX_SESSIONS_PER_PEER = 3;      // concurrent-initiation leaves two live sessions; keep a few, evict the stalest
const L = (s) => _enc.encode(s);
export const MSG_BODY_MAX = 1800;    // ASCII chars of body text that fit a session-init envelope under the 16 KiB cap
const ENVELOPE_CAP = 16 * 1024;      // ops/message_pool.MSG_MAX_BYTES — the node drops anything larger
const ENVELOPE_FIXED = 4840 + 2624 + 64 + 32 + 32 + 46 + 120;   // sig + public_key + mac + tag + nonce + sender + json/pow/ts slack
export function bodyBudgetBytes(sessionInit) {   // plaintext bytes that still fit, given the header size
  return Math.floor((ENVELOPE_CAP - ENVELOPE_FIXED - (sessionInit ? 4492 : 3042)) / 2);   // ct is hex: 2 chars/byte
}
function b64enc(b) { let s = ''; for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode.apply(null, b.subarray(i, i + 0x8000)); return btoa(s); }
function b64dec(s) { const t = atob(s), o = new Uint8Array(t.length); for (let i = 0; i < t.length; i++) o[i] = t.charCodeAt(i); return o; }

function kdfRk(rkHex, ss) {  // -> [rk', ck] hex
  const out = keyed(u8cat(L('nado-msg-rk'), ss), hexToBytes(rkHex), 64);
  return [bytesToHex(out.subarray(0, 32)), bytesToHex(out.subarray(32))];
}
function kdfCk(ckHex) {      // -> [ck', mk]  (mk as bytes — it is consumed immediately)
  const ck = hexToBytes(ckHex);
  return [bytesToHex(keyed(L('nado-msg-ck'), ck, 32)), keyed(L('nado-msg-mk'), ck, 32)];
}
function tagFor(dkHex, nonceBytes) { return bytesToHex(keyed(u8cat(L('nado-msg-detect-v2'), nonceBytes), hexToBytes(dkHex), 16)); }
function rootFromInit(ss0) {
  const rk0 = bytesToHex(keyed(L('nado-msg-init'), ss0, 32));
  return { rk0, dk: bytesToHex(keyed(L('nado-msg-dk'), hexToBytes(rk0), 32)) };
}
function u32(n) { return new Uint8Array([(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255]); }
function rdU32(b, o) { return ((b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]) >>> 0; }
function packHdr(h) {
  return b64enc(u8cat(new Uint8Array([h.i ? 1 : 0]), u32(h.pn), u32(h.n), hexToBytes(h.k), hexToBytes(h.c), h.i ? hexToBytes(h.i) : new Uint8Array(0)));
}
export function parseHdr(hdrB64) {
  let b; try { b = b64dec(hdrB64); } catch { return null; }
  const hasInit = (b[0] & 1) === 1;
  if (b.length !== HDR_FIXED + (hasInit ? KEM_CT_LEN : 0)) return null;
  let o = 1; const pn = rdU32(b, o); o += 4; const n = rdU32(b, o); o += 4;
  const k = bytesToHex(b.subarray(o, o + KEM_PUB_LEN)); o += KEM_PUB_LEN;
  const c = bytesToHex(b.subarray(o, o + KEM_CT_LEN)); o += KEM_CT_LEN;
  const i = hasInit ? bytesToHex(b.subarray(o, o + KEM_CT_LEN)) : null;
  return { pn, n, k, c, i };
}
function kemSec(id, kem) { return kem.sec === null ? id.kemSecret : hexToBytes(kem.sec); }
function skipKey(pubHex, n) { return pubHex.slice(0, 32) + ':' + n; }

export function sessionsNew() { return { v: 2, peers: {} }; }
function peerSessions(store, peer) { return (store.peers[peer] = store.peers[peer] || []); }
function pickSession(list) {   // the session the peer most recently spoke on, else the newest we created
  if (!list.length) return null;
  return list.slice().sort((a, b) => (b.lastRecv - a.lastRecv) || (b.created - a.created))[0];
}
function newSession(peer, rk0, dk, ts, theirPub, ownKem) {
  return { peer, rk: rk0, dk, kem: ownKem, kemPrev: null, theirPub, cks: null, ckr: null, ns: 0, nr: 0, pn: 0,
           c: null, init: null, skipped: [], created: ts, lastRecv: 0 };
}
function addSession(store, s) {
  const list = peerSessions(store, s.peer);
  list.push(s);
  while (list.length > MAX_SESSIONS_PER_PEER) {
    list.sort((a, b) => (a.lastRecv - b.lastRecv) || (a.created - b.created)); list.shift();
  }
  return s;
}

// Encrypt `plaintextObj` to `peerAddr` through the ratchet (creating the session from the peer's on-chain
// identity KEM key `peerKemPubHex` if none exists). Mutates `store`; returns the signed envelope.
export function ratchetSeal(id, senderAddr, store, peerAddr, peerKemPubHex, plaintextObj, ts) {
  let s = pickSession(peerSessions(store, peerAddr));
  if (!s) {
    const { cipherText, sharedSecret } = ml_kem768.encapsulate(hexToBytes(peerKemPubHex));
    const { rk0, dk } = rootFromInit(sharedSecret);
    s = addSession(store, newSession(peerAddr, rk0, dk, ts, peerKemPubHex, null));
    s.init = bytesToHex(cipherText);
  }
  const ptBytes = _enc.encode(JSON.stringify(plaintextObj));
  if (ptBytes.length > bodyBudgetBytes(s.init !== null))   // refuse BEFORE touching chain state: no burned keys on a reject
    throw new Error('message too long (' + ptBytes.length + ' > ' + bodyBudgetBytes(s.init !== null) + ' bytes)');
  if (s.cks === null) {                                   // start a new sending chain (= our half of a ratchet step)
    const { cipherText, sharedSecret } = ml_kem768.encapsulate(hexToBytes(s.theirPub));
    [s.rk, s.cks] = kdfRk(s.rk, sharedSecret);
    s.pn = s.ns; s.ns = 0; s.c = bytesToHex(cipherText);
    const kp = ml_kem768.keygen();                        // fresh ratchet keypair: the peer encapsulates to THIS next
    s.kemPrev = s.kem; s.kem = { pub: bytesToHex(kp.publicKey), sec: bytesToHex(kp.secretKey) };
  }
  let mk; [s.cks, mk] = kdfCk(s.cks);
  const hdr = packHdr({ pn: s.pn, n: s.ns, k: s.kem.pub, c: s.c, i: s.init });
  s.ns += 1;
  const sealed = seal(mk, ptBytes, b64dec(hdr));
  const env = { v: 2, sender: senderAddr, public_key: id.dsaPub, tag: tagFor(s.dk, hexToBytes(sealed.nonce)),
                hdr, nonce: sealed.nonce, ct: sealed.ct, ts, pow: '', sig: '' };
  return finishEnvelope(id, env);
}

// Try to open `env` against every session in `store` (then as a session-init to us). On success the session
// state is committed and { pt, peer, session } returned; otherwise null and `store` is untouched.
export function ratchetOpen(id, store, env, ts) {
  if (env.v !== 2) return null;
  const h = parseHdr(env.hdr); if (!h) return null;
  let nonce; try { nonce = hexToBytes(env.nonce); } catch { return null; }
  for (const peer of Object.keys(store.peers)) for (const s of store.peers[peer]) {
    if (tagFor(s.dk, nonce) !== env.tag) continue;
    const r = _recv(id, s, h, env, ts);
    if (!r) return null;                                  // it claimed our session but did not decrypt: drop
    Object.assign(s, r.s);
    return { pt: r.pt, peer, session: s };
  }
  if (!h.i) return null;
  let ss0; try { ss0 = ml_kem768.decapsulate(hexToBytes(h.i), id.kemSecret); } catch { return null; }
  const { rk0, dk } = rootFromInit(ss0);
  if (tagFor(dk, nonce) !== env.tag) return null;        // not for us
  const fresh = newSession(env.sender, rk0, dk, ts, null, { pub: id.kemPub, sec: null });
  const r = _recv(id, fresh, h, env, ts);
  if (!r) return null;
  addSession(store, r.s);
  return { pt: r.pt, peer: env.sender, session: r.s };
}

function _recv(id, s0, h, env, ts) {
  const s = JSON.parse(JSON.stringify(s0));              // work on a copy; commit only on success
  const ad = b64dec(env.hdr);
  const finish = (mk) => {
    const pt = open(mk, env.nonce, env.ct, ad); if (!pt) return null;
    let obj; try { obj = JSON.parse(new TextDecoder().decode(pt)); } catch { return null; }
    s.lastRecv = ts; return { pt: obj, s };
  };
  const stash = (pub, n, mk) => { s.skipped.push([skipKey(pub, n), bytesToHex(mk)]); if (s.skipped.length > MAX_SKIPPED_STORE) s.skipped.shift(); };
  const advanceTo = (pub, n) => {                         // derive keys nr..n on the receiving chain, caching the skipped ones
    if (n - s.nr > MAX_SKIP) return null;
    let mk;
    while (s.nr < n) { [s.ckr, mk] = kdfCk(s.ckr); stash(pub, s.nr, mk); s.nr++; }
    [s.ckr, mk] = kdfCk(s.ckr); s.nr++;
    return mk;
  };
  if (h.k === s.theirPub) {                               // same receiving chain
    if (h.n < s.nr) {                                     // a late message: use (and burn) its cached key
      const key = skipKey(h.k, h.n), idx = s.skipped.findIndex(e => e[0] === key);
      if (idx < 0) return null;
      const mk = hexToBytes(s.skipped[idx][1]); s.skipped.splice(idx, 1);
      return finish(mk);
    }
    if (s.ckr === null) return null;
    const mk = advanceTo(h.k, h.n); return mk ? finish(mk) : null;
  }
  // A new remote ratchet key: finish the old chain's skipped keys, then step the root key with decap(c).
  if (s.ckr !== null && s.theirPub !== null) {
    if (h.pn - s.nr > MAX_SKIP) return null;
    let mk; while (s.nr < h.pn) { [s.ckr, mk] = kdfCk(s.ckr); stash(s.theirPub, s.nr, mk); s.nr++; }
  }
  const before = JSON.stringify(s);
  for (const kem of [s.kem, s.kemPrev]) {                 // kemPrev = one-step grace for crossed messages
    if (!kem) continue;
    const t = JSON.parse(before); Object.assign(s, t);    // rewind for the retry
    let ss; try { ss = ml_kem768.decapsulate(hexToBytes(h.c), kemSec(id, kem)); } catch { continue; }
    [s.rk, s.ckr] = kdfRk(s.rk, ss);
    s.theirPub = h.k; s.nr = 0;
    s.cks = null; s.c = null; s.init = null;              // our next send starts a fresh chain (+ fresh keypair)
    const mk = advanceTo(h.k, h.n); if (!mk) continue;
    const r = finish(mk); if (r) return r;
  }
  return null;
}

// Drop the state of every session with `peer` (e.g. "reset secure session"). The next send re-initialises.
export function sessionsForget(store, peer) { delete store.peers[peer]; }

export function makePrekeyBundle(id, addr, ts) {
  const b = { address: addr, public_key: id.dsaPub, ik_pub: id.kemPub, spk_pub: id.kemPub, spk_ts: ts, ts, sig: '' };
  b.sig = signBytes(id, hexToBytes(b2hash([b.address, b.public_key, b.ik_pub, b.spk_pub, b.spk_ts, b.ts])));
  return b;
}

export function messageId(env) {
  return b2hash([env.v, env.sender, env.public_key, env.tag, env.hdr, env.nonce, env.ct, env.ts, env.pow, env.sig]);
}
