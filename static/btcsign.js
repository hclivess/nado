// btcsign.js — in-browser Bitcoin HTLC spending for the OTC cross-chain swap (doc/dex-bridge.md §6.5).
// Signs the CLAIM (reveals the secret) and REFUND (after the timelock) spends of the P2WSH HTLC that
// btcleg.js builds — BIP143 sighash, RFC-6979 ECDSA via the vendored @noble/secp256k1. Byte-identical to
// scripts/otc_btc_leg.py (deterministic nonces → the same tx hex), so what the browser broadcasts is what
// the Python leg and the test suite already verify. No key ever leaves the page.
import * as secp from "./vendor/noble-secp256k1.js?v=1";
import { htlcScript } from "./btcleg.js?v=3854b338";

// noble 2.x needs an async HMAC-SHA256 wired for RFC-6979 signing; WebCrypto provides it.
secp.etc.hmacSha256Async = async (key, ...msgs) => {
  const k = await crypto.subtle.importKey("raw", key, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", k, secp.etc.concatBytes(...msgs)));
};

const hexToBytes = (h) => new Uint8Array((h.match(/../g) || []).map((x) => parseInt(x, 16)));
const bytesToHex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
const cat = (...a) => secp.etc.concatBytes(...a.map((x) => (x instanceof Uint8Array ? x : new Uint8Array(x))));
const u32 = (n) => new Uint8Array([n & 0xff, (n >>> 8) & 0xff, (n >>> 16) & 0xff, (n >>> 24) & 0xff]);
const u64 = (n) => { const b = new Uint8Array(8); let v = BigInt(n); for (let i = 0; i < 8; i++) { b[i] = Number(v & 0xffn); v >>= 8n; } return b; };
const sha256 = async (b) => new Uint8Array(await crypto.subtle.digest("SHA-256", b));
const sha256d = async (b) => sha256(await sha256(b));

function compact(n) {
  n = Number(n);
  if (n < 0xfd) return new Uint8Array([n]);
  if (n <= 0xffff) return cat([0xfd], new Uint8Array([n & 0xff, n >>> 8]));
  return cat([0xfe], u32(n));
}
const pushd = (b) => { if (b.length > 75) throw new Error("push too big"); return cat([b.length], b); };

// (r,s) -> DER, low-S enforced (BIP62). noble's Signature carries normalizeS/hasHighS.
function derFromSig(sig) {
  const s2 = sig.hasHighS() ? sig.normalizeS() : sig;
  const enc = (x) => { let b = Array.from(secp.etc.numberToBytesBE(x, 32)); while (b.length > 1 && b[0] === 0 && !(b[1] & 0x80)) b.shift(); if (b[0] & 0x80) b.unshift(0); return new Uint8Array(b); };
  const r = enc(s2.r), s = enc(s2.s);
  const body = cat([0x02, r.length], r, [0x02, s.length], s);
  return cat([0x30, body.length], body);
}

async function bip143Sighash(txidLE, vout, scriptCode, amtSat, outScript, outSat, locktime, sequence) {
  const prevout = cat(txidLE, u32(vout));
  const outputs = cat(u64(outSat), compact(outScript.length), outScript);
  const pre = cat(u32(2), await sha256d(prevout), await sha256d(u32(sequence)), prevout,
                  compact(scriptCode.length), scriptCode, u64(amtSat), u32(sequence),
                  await sha256d(outputs), u32(locktime), u32(1)); // SIGHASH_ALL
  return sha256d(pre);
}

function serialize(txidLE, vout, sequence, outScript, outSat, witness, locktime) {
  const wit = cat(compact(witness.length), ...witness.map((w) => cat(compact(w.length), w)));
  return cat(u32(2), [0x00, 0x01], [0x01], txidLE, u32(vout), [0x00], u32(sequence),
             [0x01], u64(outSat), compact(outScript.length), outScript, wit, u32(locktime));
}

async function spend({ scriptHex, branchWitness, privHex, fundTxid, vout, amountSat, outScriptHex, feeSat, locktime, sequence }) {
  const script = hexToBytes(scriptHex);
  const txidLE = hexToBytes(fundTxid).reverse();
  const outScript = hexToBytes(outScriptHex);
  const outSat = amountSat - feeSat;
  if (outSat <= 0) throw new Error("fee exceeds the output");
  const digest = await bip143Sighash(txidLE, vout, script, amountSat, outScript, outSat, locktime, sequence);
  const sig = await secp.signAsync(digest, hexToBytes(privHex));
  const sigDer = cat(derFromSig(sig), [0x01]); // + SIGHASH_ALL
  const witness = [sigDer, ...branchWitness, script];
  return bytesToHex(serialize(txidLE, vout, sequence, outScript, outSat, witness, locktime));
}

// PUBLIC: build a signed claim tx (reveals the 32-byte secret). outScriptHex is where the BTC goes.
export function claimTx({ scriptHex, secretHex, privHex, fundTxid, vout, amountSat, outScriptHex, feeSat = 500 }) {
  return spend({ scriptHex, branchWitness: [hexToBytes(secretHex), new Uint8Array([1])], privHex,
                 fundTxid, vout, amountSat, outScriptHex, feeSat, locktime: 0, sequence: 0xffffffff });
}
// PUBLIC: build a signed refund tx (valid only at/after locktime).
export function refundTx({ scriptHex, locktime, privHex, fundTxid, vout, amountSat, outScriptHex, feeSat = 500 }) {
  // nLockTime is 32 bits. A script demanding more can never be satisfied, so building this spend would
  // hand the user a transaction that is rejected forever rather than one that waits.
  if (!(Number.isInteger(locktime) && locktime > 0 && locktime < 2 ** 32))
    throw new Error("this swap's deadline is out of range — its refund branch cannot be spent");
  return spend({ scriptHex, branchWitness: [new Uint8Array(0)], privHex,
                 fundTxid, vout, amountSat, outScriptHex, feeSat, locktime, sequence: 0xfffffffe });
}
export { hexToBytes, bytesToHex };

// ---- address -> scriptPubKey (where a claim/refund pays) ----------------------------------------------
// Supports the formats a normal user pastes: bech32/bech32m segwit (P2WPKH/P2WSH/P2TR) and base58check
// legacy (P2PKH/P2SH). Returns the output script hex, or throws with a plain message.
const B32C = "qpzry9x8gf2tvdw0s3jn54khce6mua7l";
function bech32Decode(addr) {
  // Case must not be mixed (BIP-173) — check BEFORE lowercasing.
  if (/[a-z]/.test(addr) && /[A-Z]/.test(addr)) throw new Error("mixed-case address");
  addr = addr.toLowerCase();
  const pos = addr.lastIndexOf("1");
  if (pos < 1) throw new Error("not a bech32 address");
  const hrp = addr.slice(0, pos);
  const data = [];
  for (const c of addr.slice(pos + 1)) { const v = B32C.indexOf(c); if (v < 0) throw new Error("bad bech32 char"); data.push(v); }
  const exp = [...hrp].map((c) => c.charCodeAt(0) >>> 5).concat([0], [...hrp].map((c) => c.charCodeAt(0) & 31));
  const poly = (() => { const G = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]; let chk = 1;
    for (const x of exp.concat(data)) { const b = chk >>> 25; chk = ((chk & 0x1ffffff) << 5) ^ x; for (let i = 0; i < 5; i++) if ((b >>> i) & 1) chk ^= G[i]; } return chk >>> 0; })();
  const ver = data[0];
  if (ver > 16) throw new Error("bad witness version");
  // BIP-350: v0 uses the bech32 constant, v1+ uses bech32m. Accepting EITHER for any version (which this
  // did) lets a mistyped/foreign address through and can produce an anyone-can-spend output.
  const want = ver === 0 ? 1 : 0x2bc830a3;
  if (poly !== want) throw new Error("bad checksum for that address type");
  let acc = 0, bits = 0; const prog = [];
  for (const d of data.slice(1, -6)) { acc = (acc << 5) | d; bits += 5; if (bits >= 8) { bits -= 8; prog.push((acc >>> bits) & 0xff); } }
  if (bits >= 5 || ((acc << (8 - bits)) & 0xff) !== 0) throw new Error("bad padding in the address");
  if (prog.length < 2 || prog.length > 40) throw new Error("bad witness program");
  if (ver === 0 && prog.length !== 20 && prog.length !== 32) throw new Error("bad v0 program length");
  if (ver === 1 && prog.length !== 32) throw new Error("bad taproot program length");
  // A version this build does not know is refused rather than encoded blindly: an unrecognised witness
  // program of the wrong length is spendable by ANYONE under current relay rules.
  if (ver >= 2) throw new Error("unsupported address type (witness v" + ver + ")");
  return { hrp, ver, prog: new Uint8Array(prog) };
}
async function base58checkDecode(addr) {
  const A = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz";
  let num = 0n; for (const c of addr) { const v = A.indexOf(c); if (v < 0) throw new Error("bad base58 char"); num = num * 58n + BigInt(v); }
  let bytes = []; while (num > 0n) { bytes.unshift(Number(num & 0xffn)); num >>= 8n; }
  for (const c of addr) { if (c === "1") bytes.unshift(0); else break; }
  const full = new Uint8Array(bytes);
  const payload = full.slice(0, -4), chk = full.slice(-4);
  const h = await sha256d(payload);
  for (let i = 0; i < 4; i++) if (h[i] !== chk[i]) throw new Error("bad base58 checksum");
  return { version: payload[0], hash: payload.slice(1) };
}
export async function addressToScript(addr, hrpExpected) {
  addr = (addr || "").trim();
  if (/^(bc|tb|bcrt)1/i.test(addr)) {
    const d = bech32Decode(addr);
    if (hrpExpected && d.hrp !== hrpExpected) throw new Error(`that is a ${d.hrp} address, but this swap is on ${hrpExpected}`);
    const op = d.ver === 0 ? 0x00 : 0x50 + d.ver;         // OP_0 / OP_1.. witness version
    return bytesToHex(cat([op, d.prog.length], d.prog));
  }
  const { version, hash } = await base58checkDecode(addr);
  if (hash.length !== 20) throw new Error("bad legacy address");
  const main = version === 0x00 || version === 0x05;                    // vs testnet/regtest 0x6f / 0xc4
  if (hrpExpected && (hrpExpected === "bc") !== main)
    throw new Error(`that is a ${main ? "mainnet" : "testnet"} address, but this swap is on ${hrpExpected === "bc" ? "mainnet" : "testnet"}`);
  if (version === 0x00 || version === 0x6f) return bytesToHex(cat([0x76, 0xa9, 0x14], hash, [0x88, 0xac])); // P2PKH
  if (version === 0x05 || version === 0xc4) return bytesToHex(cat([0xa9, 0x14], hash, [0x87]));             // P2SH
  throw new Error("unsupported address type — paste a bech32 (bc1…) or legacy address");
}

// PUBLIC: a fresh Bitcoin keypair for one swap — generated per order, stored only in the browser.
export function genKeypair() {
  const k = secp.utils.randomPrivateKey();
  return { k: bytesToHex(k), pub: bytesToHex(secp.getPublicKey(k, true)) };
}
