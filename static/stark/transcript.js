/* Fiat-Shamir transcript — exact port of execnode/stark/transcript.py. */
import { H } from "./hashing.js";
import { P } from "./field.js";
export class Transcript {
  constructor(label = "nado-stark") { this.state = H(["transcript", label]); }
  absorb(...items) { this.state = H(["absorb", this.state, ...items.map(String)]); }
  challenge() { this.state = H(["challenge", this.state]); return BigInt("0x" + this.state) % P; }
  challengeIndex(bound) { this.state = H(["index", this.state]); return Number(BigInt("0x" + this.state) % BigInt(bound)); }
  // C-1 proof-of-work — exact port of Transcript.grind/check_grind. The PoW hash must have `bits` leading
  // zero bits; the winning nonce is folded into the transcript (absorb) so the queries derive after it.
  _grindOk(nonce, bits) { const h = BigInt("0x" + H(["grind", this.state, String(nonce)])); return (h >> BigInt(256 - bits)) === 0n; }
  grind(bits) { let nonce = 0; while (!this._grindOk(nonce, bits)) nonce++; this.absorb("grind", nonce); return nonce; }
}
