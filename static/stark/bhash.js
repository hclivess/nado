/* Binary BLAKE2b transcript/Merkle byte-packing — a byte-for-byte port of the Python prover's default
 * backend (execnode/stark/backend.py `_Blake2b`). The Python STARK backend was moved OFF canonical-JSON
 * hashing onto raw domain-tagged byte packing (it removed ~18s of json.dumps overhead per execution-AIR
 * proof and the 2^GRIND_BITS grind hashes). merkle.js + transcript.js must pack IDENTICALLY or a browser-
 * generated proof's Merkle roots / Fiat-Shamir challenges won't match what Python recomputes, and the
 * verifier rejects it (that drift is exactly what made the browser prover unverifiable). The wasm Merkle
 * (vendor/blake2b-wasm.js, Rust wasm/blake2b/) already uses this packing; this module makes the pure-JS
 * fallback + the transcript agree with it and with Python. */
import { blake2b, bytesToHex, hexToBytes } from "../vendor/nado-crypto.js";
import { P } from "./field.js";

// blake2b-256 over concatenated byte parts -> 32-byte hex digest. Mirrors backend._b2b32(*parts).
export function b2b32(...parts) {
  let len = 0;
  for (const p of parts) len += p.length;
  const buf = new Uint8Array(len);
  let o = 0;
  for (const p of parts) { buf.set(p, o); o += p.length; }
  return bytesToHex(blake2b(buf, { dkLen: 32 }));
}

// a single domain-tag byte, e.g. tag("A"); tag("\x00") for the Merkle leaf tag.
export const tag = (c) => Uint8Array.of(c.charCodeAt(0) & 0xff);

// (v mod P) as 8 little-endian bytes. Mirrors (int(x) % F.P).to_bytes(8, "little").
export function i8le(v) {
  let x = ((BigInt(v) % P) + P) % P;
  const b = new Uint8Array(8);
  for (let i = 0; i < 8; i++) { b[i] = Number(x & 0xffn); x >>= 8n; }
  return b;
}

// a 16-bit little-endian length prefix (for the "S" string encoding).
export const u16le = (n) => Uint8Array.of(n & 0xff, (n >> 8) & 0xff);

export { hexToBytes };
