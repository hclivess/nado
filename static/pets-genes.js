// pets-genes.js — the PURE derivation core of NADO Pets, shared by the dapp (pets.js) and the Node
// crosscheck (tests/pets_js_crosscheck.mjs). Every formula here MUST stay byte-identical to the contract
// bytecode and the Python reference in tests/test_pets_contract.py — this module decides what animal a
// player sees, its stats, training odds and battle outcomes, so it is differentially verified against the
// reference. No DOM, no fetch: pass in hex block hashes + storage ints, get facts out.
import { blake2bHash } from "./nadotx.js";

// ---- constants (mirror tests/test_pets_contract.py) ------------------------------------------------
export const MINT_FEE    = 10n ** 10n;        // 1 NADO adopts an egg
export const TRAIN_FEE   = 5n * 10n ** 9n;    // 0.5 NADO per training attempt
export const HATCH_DELAY = 2;                 // gene block = mint cursor + 2
export const START_BELLY = 43200;             // fresh egg/pet is fed for 3 days (6s blocks)
export const BELLY_CAP   = 100800;            // belly can never exceed 7 days ahead
export const FEED_DIV    = 14000n;            // raw per block of life per appetite point
export const STALE       = 18000;             // pending hash-bindings older than this are prunable
export const DIE_PCT     = 20;                // battle loser's death chance, %

export const SPECIES = {
  1: { name: "Poodle",             rarity: "Common",    pct: 70, color: "#e3b341", emoji: "🐩" },
  2: { name: "African Grey Parrot", rarity: "Rare",      pct: 25, color: "#c86bfa", emoji: "🦜" },
  3: { name: "Dragon",             rarity: "Legendary", pct: 5,  color: "#00c9a7", emoji: "🐉" },
};
export const STAT_NAMES = ["Strength", "Agility", "Vitality", "Intelligence", "Wisdom",
                           "Charisma", "Loyalty", "Luck", "Speed", "Appetite"];
export const STAT_ICONS = ["💪", "🤸", "❤️", "🧠", "🦉", "✨", "🤝", "🍀", "⚡", "🍖"];

// ---- the VM's HASH over a BigInt (canonicalize emits bare digits, exactly json.dumps(int)) ---------
export const vmHash = (v) => BigInt("0x" + blake2bHash(v));
const hexInt = (h) => BigInt("0x" + h);

// gene = HASH( BLOCKHASH(b) + BLOCKHASH(b+1) + petId ) — needs both hashes (hex) from /exec/blockhash
export function geneOf(bh0Hex, bh1Hex, pid) {
  if (!bh0Hex || !bh1Hex) return null;
  return vmHash(hexInt(bh0Hex) + hexInt(bh1Hex) + BigInt(pid));
}
export function speciesOf(gene) { const r = gene % 100n; return 1 + (r >= 70n ? 1 : 0) + (r >= 95n ? 1 : 0); }
export function statOf(gene, sp, i) { return Number(vmHash(gene + 1000n + BigInt(i)) % 60n) + 1 + (sp - 1) * 15; }
export function baseStats(gene, sp) { return STAT_NAMES.map((_n, i) => statOf(gene, sp, i)); }
export function powerOf(gene, sp) { return baseStats(gene, sp).reduce((a, b) => a + b, 0); }

// ---- training: the rarity-scaled limit function ----------------------------------------------------
export const trainK = (sp) => 10 + 30 * sp;                        // Poodle 40, Parrot 70, Dragon 100
export const trainChance = (sp, cur) => 100 * trainK(sp) / (trainK(sp) + cur);   // % (display; contract uses ints)
export function trainRollOf(bh0Hex, bh1Hex, pid, i) {
  if (!bh0Hex || !bh1Hex) return null;
  return Number(vmHash(hexInt(bh0Hex) + hexInt(bh1Hex) + BigInt(pid) * 16n + BigInt(i)) % 100n);
}
export const trainOk = (roll, cur, sp) => roll * (trainK(sp) + cur) < 100 * trainK(sp);

// ---- battles: q = bh0+bh1+bid*8; score = power * (75 + HASH(q+k)%100); loser dies at HASH(q+3)%100<20
export function battleOf(bh0Hex, bh1Hex, bid, pwA, pwB) {
  if (!bh0Hex || !bh1Hex) return null;
  const q = hexInt(bh0Hex) + hexInt(bh1Hex) + BigInt(bid) * 8n;
  const rollA = Number(vmHash(q + 1n) % 100n), rollB = Number(vmHash(q + 2n) % 100n);
  const scoreA = pwA * (75 + rollA), scoreB = pwB * (75 + rollB);
  const aWins = scoreA > scoreB;                                   // tie -> the defender
  return { rollA, rollB, scoreA, scoreB, aWins, dies: Number(vmHash(q + 3n) % 100n) < DIE_PCT };
}

// ---- husbandry math (ints, exactly the contract's) -------------------------------------------------
export const feedBlocks = (valueRaw, appetite) => Number(BigInt(valueRaw) / (BigInt(appetite) * FEED_DIV));
export const feedCost = (blocks, appetite) => BigInt(blocks) * BigInt(appetite) * FEED_DIV;   // raw for N blocks
export const levelOf = (tfRaw) => Math.max(1, Math.floor(Math.sqrt(Number(BigInt(tfRaw) / 10n ** 10n))));
