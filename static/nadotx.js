// nadotx.js — NADO transaction signing + crypto primitives, shared and HEADLESS-TESTABLE.
// Byte-identical to the node: canonical_bytes (sorted keys, ensure_ascii, no spaces) -> create_txid
// (blake2b over the body minus public_key) -> ML-DSA-44 sign(unhex(txid)). canonicalize handles BigInt so a
// 256-bit contract-call argument (e.g. a commit hash) rides as a bare JSON integer, exactly as the node parses it.
// Usable in the browser (window.crypto) and in Node (globalThis.crypto) so the signing can be unit-tested.

let blake2b, ml_dsa44, bytesToHex, hexToBytes;

export async function loadCrypto(base = ".") {
  if (blake2b && ml_dsa44) return;
  const m = await import(base + "/vendor/nado-crypto.js?v=mlkem");
  blake2b = m.blake2b; ml_dsa44 = m.ml_dsa44; bytesToHex = m.bytesToHex; hexToBytes = m.hexToBytes;
  if (!(blake2b && ml_dsa44)) throw new Error("crypto bundle missing blake2b/ml_dsa44");
}

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
export function makeAddress(pubHex) { const body = "ndo" + pubHex.slice(0, 42); return body + blake2bHash(body, 2); }
export function keyFromSeed(seedHex) {
  const { publicKey } = ml_dsa44.keygen(hexToBytes(seedHex));
  const pubHex = bytesToHex(publicKey);
  return { privateKey: seedHex, publicKey: pubHex, address: makeAddress(pubHex) };
}
export function genKey() { return keyFromSeed(bytesToHex(globalThis.crypto.getRandomValues(new Uint8Array(32)))); }

// ---- transactions --------------------------------------------------------------------------------
function createTxid(body) { const pre = {}; for (const k of Object.keys(body)) if (k !== "public_key") pre[k] = body[k]; return blake2bHash(pre); }

export function finalizeTx(draft, privHex, fee) {
  const body = { ...draft, fee };
  const txid = createTxid(body);
  const { publicKey, secretKey } = ml_dsa44.keygen(hexToBytes(privHex));
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
