/* Fiat-Shamir transcript — exact port of execnode/stark/transcript.py. */
import { H } from "./hashing.js";
import { P } from "./field.js";
export class Transcript {
  constructor(label = "nado-stark") { this.state = H(["transcript", label]); }
  absorb(...items) { this.state = H(["absorb", this.state, ...items.map(String)]); }
  challenge() { this.state = H(["challenge", this.state]); return BigInt("0x" + this.state) % P; }
  challengeIndex(bound) { this.state = H(["index", this.state]); return Number(BigInt("0x" + this.state) % BigInt(bound)); }
}
