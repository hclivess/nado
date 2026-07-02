/*
 * BIP39 recovery phrase for NADO wallets. A NADO wallet is fully defined by its 32-byte ML-DSA-44 seed (the
 * "private key"), so a phrase just needs to encode ↔ that seed. This is standard BIP39: 256 bits of entropy
 * (the seed) + an 8-bit SHA-256 checksum → 24 words. Restoring a phrase yields the exact same keypair (keygen
 * is deterministic from the seed). Interoperable with any BIP39 tool at the entropy level; the ML-DSA
 * derivation on top is NADO's.
 */
import { BIP39_WORDS } from "./vendor/bip39_wordlist.js";

async function _sha256(bytes) { return new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)); }
function _bits(bytes) { let s = ""; for (const b of bytes) s += b.toString(2).padStart(8, "0"); return s; }

// 32-byte seed → 24-word phrase
export async function seedToMnemonic(seed) {
  if (!(seed instanceof Uint8Array) || seed.length !== 32) throw new Error("seed must be 32 bytes");
  const h = await _sha256(seed);
  const bits = _bits(seed) + h[0].toString(2).padStart(8, "0");   // 256 entropy + 8 checksum = 264 bits
  const words = [];
  for (let i = 0; i < 264; i += 11) words.push(BIP39_WORDS[parseInt(bits.slice(i, i + 11), 2)]);
  return words.join(" ");
}

// 24-word phrase → 32-byte seed (validates the checksum)
export async function mnemonicToSeed(phrase) {
  const words = String(phrase || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length !== 24) throw new Error("recovery phrase must be exactly 24 words");
  let bits = "";
  for (const w of words) {
    const idx = BIP39_WORDS.indexOf(w);
    if (idx < 0) throw new Error("not a valid recovery word: " + w);
    bits += idx.toString(2).padStart(11, "0");
  }
  const seed = new Uint8Array(32);
  for (let i = 0; i < 32; i++) seed[i] = parseInt(bits.slice(i * 8, i * 8 + 8), 2);
  const h = await _sha256(seed);
  if (bits.slice(256) !== h[0].toString(2).padStart(8, "0"))
    throw new Error("recovery phrase checksum failed — check the words and their order");
  return seed;
}

export function looksLikeMnemonic(s) {
  return String(s || "").trim().split(/\s+/).filter(Boolean).length >= 12;
}
