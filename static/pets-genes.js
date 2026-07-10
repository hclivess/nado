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
export const DIE_PCT     = 10;                // battle loser's death chance, % (small — most losers are claimed)

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

// ---- cosmetic COAT variant (derived from the gene, no contract state) ------------------------------
// Each species has a palette of coat colors; the gene picks one deterministically (so it's fixed at hatch
// and identical on every client). Plus a rare "shiny" roll (~1/16) that applies an extra shimmer — a pet's
// desirability signal independent of its stats. All cosmetic; never touches money or the contract.
export const COATS = {
  1: [ // Poodle
    { name: "Cream",    body: "#f7f2e9", shade: "#d9c49a", line: "#bfae8e" },
    { name: "Apricot",  body: "#f2d9b8", shade: "#e0b483", line: "#b98a4e" },
    { name: "Silver",   body: "#dfe4ea", shade: "#b9c2cd", line: "#8a95a3" },
    { name: "Chocolate",body: "#8a5a3c", shade: "#6d4326", line: "#4a2c17" },
    { name: "Jet",      body: "#3a3f45", shade: "#25292e", line: "#14171a" },
  ],
  2: [ // African Grey Parrot
    { name: "Ash Grey", body: "#b9c0c9", shade: "#9aa2ad", line: "#5d6570" },
    { name: "Slate",    body: "#8b95a1", shade: "#69727d", line: "#454d56" },
    { name: "Dove",     body: "#d5dae0", shade: "#b2bac3", line: "#7f8892" },
    { name: "Timneh",   body: "#6d6f74", shade: "#4f5155", line: "#333333" },
  ],
  3: [ // Dragon
    { name: "Emerald",  body: "#17b795", shade: "#0d7a66", line: "#075a4c" },
    { name: "Sapphire", body: "#2f7bd6", shade: "#1c4f97", line: "#123566" },
    { name: "Crimson",  body: "#d0362b", shade: "#9a2018", line: "#6a1109" },
    { name: "Amethyst", body: "#a15cf0", shade: "#7137c0", line: "#4c2185" },
    { name: "Onyx",     body: "#2b3038", shade: "#1a1e24", line: "#0c0e12" },
    { name: "Gold",     body: "#e3b341", shade: "#b5810f", line: "#7a5606" },
  ],
};
export function coatOf(gene, sp) {
  const palette = COATS[sp] || COATS[1];
  const idx = Number(vmHash(gene + 7000n) % BigInt(palette.length));
  const shiny = vmHash(gene + 9000n) % 16n === 0n;   // ~6.25% shiny (extra shimmer, cosmetic)
  return { ...palette[idx], idx, shiny };
}
// rarity visual tier: 1 subtle, 2 purple glow, 3 legendary aura (+shiny stacks on top)
export const auraOf = (sp, shiny) => ({ 1: shiny ? "shiny" : "", 2: shiny ? "rare shiny" : "rare", 3: shiny ? "legend shiny" : "legend" }[sp] || "");
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

// ---- turn-based battle (mirrors tests/pets_ref.ref_battle_turns + the contract bytecode EXACTLY) -----
// Combat stats from the 10 effective stats: HP=vit*3+20, ATK=str, DODGE=min(agi,60), SPD=speed. The faster
// pet swings on even turns; a hit lands iff hitRoll>=defender DODGE; damage = ATK*(60+dmgRoll%61)/100 + 1.
// After CAP_BATTLE turns the higher remaining HP wins (tie -> defender). Then the loser's small death roll.
export const CAP_BATTLE = 20;   // MUST equal CAP_BATTLE in the contract + pets_ref.py
const combat = (eff) => ({ hp: eff[2] * 3 + 20, atk: eff[0], dodge: Math.min(eff[1], 60), spd: eff[8] });
export function battleOf(bh0Hex, bh1Hex, bid, effA, effB) {
  if (!bh0Hex || !bh1Hex) return null;
  const q = hexInt(bh0Hex) + hexInt(bh1Hex) + BigInt(bid) * 8n;
  const A = combat(effA), B = combat(effB);
  let h0 = A.hp, h1 = B.hp;
  const sf = A.spd >= B.spd ? 0 : 1;              // initiative: 0 => A swings on even turns
  const log = [];
  for (let t = 0; t < CAP_BATTLE; t++) {
    const cur = t % 2 === 0 ? sf : 1 - sf;        // attacker (0=A, 1=B)
    const atk = cur === 0 ? A.atk : B.atk;
    const dodge = cur === 0 ? B.dodge : A.dodge;  // the defender's dodge
    const hitRoll = Number(vmHash(q + BigInt(t)) % 100n);
    const dmgRoll = Number(vmHash(q + BigInt(t + 4096)) % 61n);
    const alive = h0 > 0 && h1 > 0 ? 1 : 0;
    const hit = hitRoll >= dodge ? 1 : 0;
    const dmg = hit * alive * (Math.floor(atk * (60 + dmgRoll) / 100) + 1);
    if (cur === 0) h1 -= dmg; else h0 -= dmg;
    log.push({ t, atk: cur, hit: hit && alive, dmg, h0, h1 });
  }
  const aWins = h0 > h1;
  return { aWins, dies: Number(vmHash(q + 999999n) % 100n) < DIE_PCT, h0, h1, log, hpA: A.hp, hpB: B.hp };
}

// ---- husbandry math (ints, exactly the contract's) -------------------------------------------------
export const feedBlocks = (valueRaw, appetite) => Number(BigInt(valueRaw) / (BigInt(appetite) * FEED_DIV));
export const feedCost = (blocks, appetite) => BigInt(blocks) * BigInt(appetite) * FEED_DIV;   // raw for N blocks
export const levelOf = (tfRaw) => Math.max(1, Math.floor(Math.sqrt(Number(BigInt(tfRaw) / 10n ** 10n))));
