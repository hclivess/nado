/* Fiat-Shamir transcript — byte-for-byte port of execnode/stark/transcript.py over the Python default
 * BLAKE2b backend (execnode/stark/backend.py `_Blake2b`). State is a 32-byte hex string. Items are field ints,
 * digest hex strings, or short string labels; each is encoded unambiguously (tag + bytes) so absorb is
 * injective — NO canonical-JSON (that is the scheme the Python side moved off, and staying on it made every
 * browser-generated proof unverifiable). Domain bytes T/A/C/X/G separate init / absorb / challenge / index /
 * grind exactly as the Python backend does. */
import { b2b32, tag, i8le, u16le, hexToBytes } from "./bhash.js";
import { P } from "./field.js";

const _TE = new TextEncoder();

// backend._Blake2b._enc: each item -> ("H" + 32 digest bytes) | ("S" + u16 len + utf8) | ("I" + 8 LE field).
function enc(items) {
  const parts = [];
  for (const x of items) {
    if (typeof x === "string" && x.length === 64 && /^[0-9a-f]{64}$/.test(x)) {
      parts.push(tag("H"), hexToBytes(x));                 // a 256-bit digest (Merkle root / state)
    } else if (typeof x === "string") {
      const bs = _TE.encode(x);
      parts.push(tag("S"), u16le(bs.length), bs);          // a short label
    } else {
      parts.push(tag("I"), i8le(x));                       // a field element
    }
  }
  return parts;
}

// The Fiat-Shamir domain label (mirrors execnode/stark/transcript.py DOMAIN_STARK).
export const DOMAIN_STARK = "stark-v1";

export class Transcript {
  constructor(label = DOMAIN_STARK) { this.state = b2b32(tag("T"), _TE.encode(String(label))); }
  absorb(...items) { this.state = b2b32(tag("A"), hexToBytes(this.state), ...enc(items)); }
  challenge() { this.state = b2b32(tag("C"), hexToBytes(this.state)); return BigInt("0x" + this.state) % P; }
  challengeIndex(bound) { this.state = b2b32(tag("X"), hexToBytes(this.state)); return Number(BigInt("0x" + this.state) % BigInt(bound)); }
  // C-1 proof-of-work — the PoW hash (domain byte "G") must have `bits` leading zero bits; the winning nonce
  // is then absorbed ("grind", nonce) so the queries derive after it. Mirrors Transcript._grind_ok/grind.
  _grindOk(nonce, bits) { const h = BigInt("0x" + b2b32(tag("G"), hexToBytes(this.state), i8le(nonce))); return (h >> BigInt(256 - bits)) === 0n; }
  grind(bits) { let nonce = 0; while (!this._grindOk(nonce, bits)) nonce++; this.absorb("grind", nonce); return nonce; }
}
