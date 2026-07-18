// nadotx.js — NADO transaction signing + crypto primitives, shared and HEADLESS-TESTABLE.
// Byte-identical to the node: canonical_bytes (sorted keys, ensure_ascii, no spaces) -> create_txid
// (blake2b over the body minus public_key) -> ML-DSA-44 sign(unhex(txid)). canonicalize handles BigInt so a
// 256-bit contract-call argument (e.g. a commit hash) rides as a bare JSON integer, exactly as the node parses it.
// Usable in the browser (window.crypto) and in Node (globalThis.crypto) so the signing can be unit-tested.

// Crypto primitives are STATICALLY imported. The vendor bundle is ~50KB of PURE JS (no wasm), so there is no
// reason to defer it — and deferring it was an active bug: blake2b is a pure, SYNCHRONOUS hash that
// deterministic game logic calls at MODULE-LOAD time (e.g. Scrapline's solo-offer render paints before init()
// runs). Gating it behind the async loadCrypto() made that logic throw "blake2b is not a function" before the
// bundle finished loading, which aborted the whole module (so sign-in return handling never ran). Binding it
// eagerly removes that entire class of races. (Node's ESM loader rejects the ?v= cache-bust query, and
// merkle.js / messaging.js / the crosscheck tests already import this bundle by its bare path — so we match.)
import { blake2b, ml_dsa44, bytesToHex, hexToBytes } from "./vendor/nado-crypto.js";

// Kept as an awaited no-op so every existing call site (nadodapp.init, the .mjs tests, interface.js) is
// unchanged — the primitives are already bound by the static import above.
export async function loadCrypto() { return; }

// ---- canonical encoding (matches the node's canonical_bytes) --------------------------------------
function jsonEscapeAscii(s) {
  let out = '"';
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    switch (c) {
      case 0x22: out += '\\"'; continue;
      case 0x5c: out += "\\\\"; continue;
      case 0x08: out += "\\b"; continue;
      case 0x09: out += "\\t"; continue;
      case 0x0a: out += "\\n"; continue;
      case 0x0c: out += "\\f"; continue;
      case 0x0d: out += "\\r"; continue;
    }
    out += (c < 0x20 || c > 0x7e) ? "\\u" + c.toString(16).padStart(4, "0") : s[i];
  }
  return out + '"';
}

export function canonicalize(data) {
  if (data === null || data === undefined) return "null";
  const t = typeof data;
  if (t === "boolean") return data ? "true" : "false";
  if (t === "bigint") return data.toString();
  if (t === "number") {
    if (!Number.isFinite(data) || !Number.isInteger(data)) throw new Error("canonical: floats forbidden: " + data);
    if (!Number.isSafeInteger(data)) throw new Error("integer > 2^53; pass a BigInt");
    return String(data);
  }
  if (t === "string") return jsonEscapeAscii(data);
  if (Array.isArray(data)) {
    let out = "[";
    for (let i = 0; i < data.length; i++) { if (i) out += ","; out += canonicalize(data[i]); }
    return out + "]";
  }
  if (t === "object") {
    const keys = Object.keys(data).sort();
    let out = "{";
    for (let i = 0; i < keys.length; i++) { if (i) out += ","; out += jsonEscapeAscii(keys[i]) + ":" + canonicalize(data[keys[i]]); }
    return out + "}";
  }
  throw new Error("canonical: unsupported type " + t);
}

const _enc = new TextEncoder();
export function canonicalBytes(data) { return _enc.encode(canonicalize(data)); }
export function blake2bHash(data, size = 32) { return bytesToHex(blake2b(canonicalBytes(data), { dkLen: size })); }

// ---- keys / address ------------------------------------------------------------------------------
// ADDRESS FORMAT — mirrors protocol.py ADDRESS_PREFIX/BODY/CHECKSUM (the one-constant rebrand point).
export const ADDR_PREFIX = "mldsa44";
export const ADDR_BODY = 42;                                   // hex chars of pubkey in the address
export const ADDR_LEN = ADDR_PREFIX.length + ADDR_BODY + 4;    // + 4-hex blake2b checksum (49 today)
export const ADDR_RE = new RegExp("^" + ADDR_PREFIX + "[0-9a-f]{" + (ADDR_BODY + 4) + "}$");
export const isAddress = (a) => typeof a === "string" && ADDR_RE.test(a);
export function makeAddress(pubHex) { const body = ADDR_PREFIX + pubHex.slice(0, ADDR_BODY); return body + blake2bHash(body, 2); }
// The seed MUST be exactly 32 bytes (64 hex). noble zero-PADS a short seed into the SHAKE preimage while the
// node's dilithium builds a different-length preimage, so a 63-hex seed (e.g. a dropped leading-zero byte)
// derives a DIFFERENT address in the browser than on the node -> the node rejects the tx as pubkey!=sender.
function reqSeed(seedHex) {
  if (typeof seedHex !== "string" || !/^[0-9a-fA-F]{64}$/.test(seedHex))
    throw new Error("seed must be exactly 32 bytes (64 hex chars)");
  return seedHex.toLowerCase();
}
export function keyFromSeed(seedHex) {
  const { publicKey } = ml_dsa44.keygen(hexToBytes(reqSeed(seedHex)));
  const pubHex = bytesToHex(publicKey);
  return { privateKey: seedHex, publicKey: pubHex, address: makeAddress(pubHex) };
}
export function genKey() { return keyFromSeed(bytesToHex(globalThis.crypto.getRandomValues(new Uint8Array(32)))); }

// ---- transactions --------------------------------------------------------------------------------
function createTxid(body) { const pre = {}; for (const k of Object.keys(body)) if (k !== "public_key") pre[k] = body[k]; return blake2bHash(pre); }

export function finalizeTx(draft, privHex, fee) {
  const body = { ...draft, fee };
  const txid = createTxid(body);
  const { publicKey, secretKey } = ml_dsa44.keygen(hexToBytes(reqSeed(privHex)));
  const m = hexToBytes(txid);
  // ML-DSA-44 signing is hedged (randomized) — a rare bad hedge yields a non-verifying sig; re-sign until ours verifies.
  let signature = null;
  for (let i = 0; i < 8; i++) { const sig = ml_dsa44.sign(secretKey, m); if (ml_dsa44.verify(publicKey, m, sig)) { signature = bytesToHex(sig); break; } }
  if (!signature) throw new Error("could not produce a verifying signature — retry");
  return { ...body, txid, signature };
}

export function randNonce(len = 8) {
  const a = "abcdefghijklmnopqrstuvwxyz"; let s = "";
  const r = globalThis.crypto.getRandomValues(new Uint8Array(len));
  for (let i = 0; i < len; i++) s += a[r[i] % 26];
  return s;
}
export function nowSeconds() { return Math.floor(Date.now() / 1000); }

// build+sign a `blob` tx carrying an opaque exec-layer payload (deploy/call/…)
export function buildBlobTx(wallet, payload, targetBlock, fee, chainId) {
  const draft = { sender: wallet.address, recipient: "blob", amount: 0, timestamp: nowSeconds(), data: payload,
    nonce: randNonce(), public_key: wallet.publicKey, max_block: targetBlock, chain_id: chainId };
  return finalizeTx(draft, wallet.privateKey, fee);
}

export async function submitTx(relayBase, tx) {
  const res = await fetch(relayBase + "/submit_transaction", {
    method: "POST", headers: { "Content-Type": "application/json" }, cache: "no-store", body: canonicalize(tx) });
  const text = await res.text();
  let data; try { data = JSON.parse(text); } catch { data = { result: false, message: (text || "").slice(0, 200) }; }
  return { ok: res.ok, status: res.status, data };
}
