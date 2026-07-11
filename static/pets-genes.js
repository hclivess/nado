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
export const START_BELLY = 432000;            // fresh egg/pet is fed for 30 days (6s blocks)
export const BELLY_CAP   = 432000;            // belly can never exceed 30 days ahead
export const FEED_DIV    = 1400n;             // raw per block of life per appetite point
export const STALE       = 18000;             // pending hash-bindings older than this are prunable
export const DIE_PCT     = 10;                // battle loser's death chance, % (small — most losers are claimed)
export const EXHAUST     = 3600;              // post-battle rest: both fighters sleep it off for 6h

// rarity TIER (contract map `sp`, 1..3) — decides stats/training; r = gene%100: <70 common, <95 rare
export const TIERS = {
  1: { rarity: "Common",    pct: 70, color: "#e3b341" },
  2: { rarity: "Rare",      pct: 25, color: "#c86bfa" },
  3: { rarity: "Legendary", pct: 5,  color: "#00c9a7" },
};
export const STAT_NAMES = ["Strength", "Agility", "Vitality", "Intelligence", "Wisdom",
                           "Charisma", "Loyalty", "Luck", "Speed", "Appetite"];
export const STAT_ICONS = ["💪", "🤸", "❤️", "🧠", "🦉", "✨", "🤝", "🍀", "⚡", "🍖"];
// what each stat DOES in a battle (the v2 combat roles — see battleOf below; shown as UI tooltips)
export const STAT_ROLES = [
  "attack damage", "dodge (harder to hit)", "hit points (×3)", "accuracy (beats dodge)",
  "mitigation (shrinks damage taken)", "intimidation (flat damage reduction)",
  "regeneration (heals every turn)", "critical hits (double damage)",
  "turn share (attacks more often)", "bulk & bite (+HP, +damage). Food cost is fixed by the HATCHED appetite — training this is free muscle, it never raises your food bill"];

// ---- the VM's HASH over a BigInt (canonicalize emits bare digits, exactly json.dumps(int)) ---------
export const vmHash = (v) => BigInt("0x" + blake2bHash(v));
const hexInt = (h) => BigInt("0x" + h);

// gene = HASH( BLOCKHASH(b) + BLOCKHASH(b+1) + petId ) — needs both hashes (hex) from /exec/blockhash
export function geneOf(bh0Hex, bh1Hex, pid) {
  if (!bh0Hex || !bh1Hex) return null;
  return vmHash(hexInt(bh0Hex) + hexInt(bh1Hex) + BigInt(pid));
}
export function speciesOf(gene) { const r = gene % 100n; return 1 + (r >= 70n ? 1 : 0) + (r >= 95n ? 1 : 0); }

// ---- the 100-animal roster ---------------------------------------------------------------------------
// Species id si = gene%100 + 1 (stored on-chain at hatch; 0 = a legacy pet hatched before the roster).
// The FIRST 70 ids are common tier, the next 25 rare, the last 5 legendary — exactly the r-thresholds the
// contract uses for `sp`, so tier(si) always equals the stored sp. Each entry: name, emoji, archetype `a`
// (which body the SVG art system draws), palette `pal`, and variant params `v` the archetype interprets.
// ALL COSMETIC — stats, training and battles key off the tier only; the roster never touches money.
const A = (n, e, a, pal, v) => ({ n, e, a, pal, v: v || {} });
export const ANIMALS = [
  // ---- commons (si 1..70, 1% each) ----
  A("Poodle", "🐩", "poodle", "poodle"),
  A("Beagle", "🐶", "quad", "dog", { ears: "floppy", patch: 1 }),
  A("Corgi", "🐶", "quad", "gold", { ears: "point", chest: 1 }),
  A("Dalmatian", "🐶", "quad", "white", { ears: "floppy", spots: 1 }),
  A("Pug", "🐶", "quad", "sand", { ears: "floppy", chubby: 1 }),
  A("Tabby Cat", "🐱", "quad", "cat", { ears: "point", whiskers: 1, stripes: 1, tail: "curl" }),
  A("Black Cat", "🐈‍⬛", "quad", "night", { ears: "point", whiskers: 1, tail: "curl" }),
  A("Calico Cat", "🐱", "quad", "white", { ears: "point", whiskers: 1, patch: 1, tail: "curl" }),
  A("Rabbit", "🐰", "quad", "bunny", { ears: "tall", tail: "pom" }),
  A("Hamster", "🐹", "quad", "gold", { ears: "round", chubby: 1 }),
  A("Mouse", "🐭", "quad", "slate", { ears: "round", tail: "thin" }),
  A("Hedgehog", "🦔", "quad", "brown", { ears: "round", spikes: 1 }),
  A("Squirrel", "🐿️", "quad", "orange", { ears: "point", tail: "fluff" }),
  A("Chipmunk", "🐿️", "quad", "brown", { ears: "round", stripes: 1, tail: "fluff" }),
  A("Raccoon", "🦝", "quad", "slate", { ears: "point", mask: 1, tail: "rings" }),
  A("Otter", "🦦", "quad", "brown", { ears: "round", whiskers: 1 }),
  A("Beaver", "🦫", "quad", "brown", { ears: "round", teeth: 1, tail: "paddle" }),
  A("Skunk", "🦨", "quad", "night", { ears: "round", stripeback: 1, tail: "fluff" }),
  A("Pig", "🐷", "quad", "pink", { ears: "floppy", snout: 1, tail: "thin" }),
  A("Goat", "🐐", "quad", "white", { ears: "floppy", horns: 1, beard: 1 }),
  A("Sheep", "🐑", "quad", "white", { ears: "floppy", wool: 1 }),
  A("Cow", "🐮", "quad", "white", { ears: "floppy", patch: 1, horns: 1, snout: 1 }),
  A("Pony", "🐴", "quad", "dog", { ears: "point", mane: 1, tail: "hair" }),
  A("Donkey", "🫏", "quad", "slate", { ears: "tall", mane: 1, tail: "hair" }),
  A("Chick", "🐤", "bird", "gold", { tiny: 1 }),
  A("Hen", "🐔", "bird", "white", { comb: 1 }),
  A("Turkey", "🦃", "bird", "brown", { fan: 1, wattle: 1 }),
  A("Duck", "🦆", "bird", "gold", { beak: "flat" }),
  A("Goose", "🪿", "bird", "white", { beak: "flat" }),
  A("Sparrow", "🐦", "bird", "brown", {}),
  A("Robin", "🐦", "bird", "brown", { chest: "#e06a3a" }),
  A("Canary", "🐤", "bird", "gold", {}),
  A("Bluebird", "🐦", "bird", "blue", { chest: "#f2c078" }),
  A("Cardinal", "🐦", "bird", "red", { crest: 1 }),
  A("Pigeon", "🕊️", "bird", "slate", {}),
  A("Crow", "🐦‍⬛", "bird", "night", {}),
  A("Seagull", "🐦", "bird", "white", {}),
  A("Gecko", "🦎", "lizard", "green", {}),
  A("Goldfish", "🐠", "fishy", "orange", {}),
  A("Guppy", "🐟", "fishy", "teal", { fan: 1 }),
  A("Koi", "🎏", "fishy", "white", { patch: 1 }),
  A("Clownfish", "🐠", "fishy", "orange", { stripes: 1 }),
  A("Chameleon", "🦎", "lizard", "green", { curl: 1, crest: 1 }),
  A("Spider", "🕷️", "bug", "night", { legs8: 1 }),
  A("Garden Snake", "🐍", "snake", "green", {}),
  A("Angelfish", "🐠", "fishy", "gold", { tall: 1, stripes: 1 }),
  A("Crab", "🦀", "crab", "red", {}),
  A("Shrimp", "🦐", "crab", "pink", { slim: 1 }),
  A("Hermit Crab", "🐚", "crab", "orange", { shell: 1 }),
  A("Snail", "🐌", "snail", "sand", {}),
  A("Earthworm", "🪱", "wiggler", "pink", {}),
  A("Caterpillar", "🐛", "wiggler", "green", { fuzz: 1 }),
  A("Ant", "🐜", "bug", "brown", { slim: 1 }),
  A("Ladybug", "🐞", "bug", "red", { spots: 1 }),
  A("Beetle", "🪲", "bug", "teal", { sheen: 1 }),
  A("Stag Beetle", "🪲", "bug", "night", { pincers: 1 }),
  A("Bee", "🐝", "bug", "gold", { stripes: 1, wings: 1 }),
  A("Bumblebee", "🐝", "bug", "gold", { stripes: 1, wings: 1, chubby: 1 }),
  A("Wasp", "🐝", "bug", "gold", { stripes: 1, wings: 1, slim: 1 }),
  A("Grasshopper", "🦗", "bug", "green", { jumper: 1 }),
  A("Cricket", "🦗", "bug", "night", { jumper: 1 }),
  A("Firefly", "✨", "bug", "night", { wings: 1, glow: 1 }),
  A("Dragonfly", "🐝", "butterfly", "teal", { slim: 1 }),
  A("Butterfly", "🦋", "butterfly", "blue", {}),
  A("Monarch Butterfly", "🦋", "butterfly", "orange", { veins: 1 }),
  A("Moth", "🦋", "butterfly", "sand", { fuzz: 1 }),
  A("Frog", "🐸", "frog", "green", {}),
  A("Toad", "🐸", "frog", "brown", { warts: 1 }),
  A("Pond Turtle", "🐢", "turtle", "green", {}),
  A("Box Turtle", "🐢", "turtle", "brown", {}),
  // ---- rares (si 71..95) ----
  A("African Grey Parrot", "🦜", "parrot", "grey", { tail: "#d0362b" }),
  A("Scarlet Macaw", "🦜", "parrot", "red", { tail: "#2f7bd6" }),
  A("Blue Macaw", "🦜", "parrot", "blue", { tail: "#f2c040" }),
  A("Cockatoo", "🦜", "parrot", "white", { tail: "#f2c040", bigcrest: 1 }),
  A("Owl", "🦉", "bird", "brown", { owl: 1, tufts: 1 }),
  A("Penguin", "🐧", "penguin", "night", {}),
  A("Peacock", "🦚", "bird", "teal", { peafan: 1, crest: 1 }),
  A("Toucan", "🦜", "parrot", "night", { bigbeak: "#f2a03b", tail: "#f2c040" }),
  A("Flamingo", "🦩", "bird", "pink", { longlegs: 1 }),
  A("Fox", "🦊", "quad", "orange", { ears: "point", tail: "fluff", chest: 1 }),
  A("Wolf", "🐺", "quad", "slate", { ears: "point", tail: "fluff", chest: 1 }),
  A("Panda", "🐼", "quad", "white", { ears: "round", panda: 1, chubby: 1 }),
  A("Koala", "🐨", "quad", "slate", { ears: "round", bignose: 1, chubby: 1 }),
  A("Red Panda", "🦝", "quad", "red", { ears: "round", mask: 1, tail: "rings" }),
  A("Capuchin Monkey", "🐵", "monkey", "brown", {}),
  A("Gorilla", "🦍", "monkey", "night", { big: 1 }),
  A("Ring-tailed Lemur", "🐒", "monkey", "slate", { tail: "rings" }),
  A("Octopus", "🐙", "octo", "purple", {}),
  A("Squid", "🦑", "octo", "pink", { cone: 1 }),
  A("Jellyfish", "🪼", "jelly", "pink", {}),
  A("Pufferfish", "🐡", "fishy", "gold", { puffer: 1 }),
  A("Shark", "🦈", "fishy", "slate", { dorsal: 1, big: 1 }),
  A("Dolphin", "🐬", "whale", "blue", { snout: 1 }),
  A("Sea Turtle", "🐢", "turtle", "teal", { flippers: 1 }),
  A("Axolotl", "🦎", "frog", "pink", { gills: 1, fintail: 1 }),
  // ---- legendaries (si 96..100) ----
  A("Dragon", "🐉", "dragon", "dragon"),
  A("Phoenix", "🐦‍🔥", "bird", "red", { crest: 1, flame: 1 }),
  A("Kraken", "🐙", "octo", "teal", { big: 1, glow: 1 }),
  A("Unicorn", "🦄", "quad", "white", { ears: "point", horn: 1, mane: 1, tail: "hair" }),
  A("Star Whale", "🐋", "whale", "purple", { stars: 1 }),
];
// tier of a species id (1-based si): matches the contract's r-thresholds exactly
export const tierOfSi = (si) => si <= 70 ? 1 : si <= 95 ? 2 : 3;
// the animal an on-chain pet renders as: si>0 -> roster entry; si==0 (legacy, pre-roster) -> the OG three
const LEGACY = { 1: 0, 2: 70, 3: 95 };   // sp tier -> roster index of Poodle / African Grey / Dragon
export const animalOf = (si, sp) => ANIMALS[si > 0 ? si - 1 : (LEGACY[sp] ?? 0)];

// ---- cosmetic COAT variant (derived from the gene, no contract state) ------------------------------
// Each animal names a palette; the gene picks a coat deterministically (fixed at hatch, identical on
// every client). Plus a rare "shiny" roll (~1/16) that applies an extra shimmer. The poodle / grey /
// dragon palettes are the ORIGINAL three, byte-identical, so legacy pets keep the exact coat they had.
export const PALS = {
  poodle: [
    { name: "Cream",    body: "#f7f2e9", shade: "#d9c49a", line: "#bfae8e" },
    { name: "Apricot",  body: "#f2d9b8", shade: "#e0b483", line: "#b98a4e" },
    { name: "Silver",   body: "#dfe4ea", shade: "#b9c2cd", line: "#8a95a3" },
    { name: "Chocolate",body: "#8a5a3c", shade: "#6d4326", line: "#4a2c17" },
    { name: "Jet",      body: "#3a3f45", shade: "#25292e", line: "#14171a" },
  ],
  grey: [
    { name: "Ash Grey", body: "#b9c0c9", shade: "#9aa2ad", line: "#5d6570" },
    { name: "Slate",    body: "#8b95a1", shade: "#69727d", line: "#454d56" },
    { name: "Dove",     body: "#d5dae0", shade: "#b2bac3", line: "#7f8892" },
    { name: "Timneh",   body: "#6d6f74", shade: "#4f5155", line: "#333333" },
  ],
  dragon: [
    { name: "Emerald",  body: "#17b795", shade: "#0d7a66", line: "#075a4c" },
    { name: "Sapphire", body: "#2f7bd6", shade: "#1c4f97", line: "#123566" },
    { name: "Crimson",  body: "#d0362b", shade: "#9a2018", line: "#6a1109" },
    { name: "Amethyst", body: "#a15cf0", shade: "#7137c0", line: "#4c2185" },
    { name: "Onyx",     body: "#2b3038", shade: "#1a1e24", line: "#0c0e12" },
    { name: "Gold",     body: "#e3b341", shade: "#b5810f", line: "#7a5606" },
  ],
  dog: [
    { name: "Golden",   body: "#e2b378", shade: "#c08a45", line: "#8a5c26" },
    { name: "Chestnut", body: "#a06a40", shade: "#7d4e28", line: "#54321a" },
    { name: "Chocolate",body: "#8a5a3c", shade: "#6d4326", line: "#4a2c17" },
    { name: "Tricolor", body: "#c9976a", shade: "#5c4230", line: "#3a281c" },
    { name: "Cream",    body: "#f2e9d8", shade: "#d9c49a", line: "#a8946c" },
  ],
  cat: [
    { name: "Ginger",   body: "#e89a52", shade: "#c9762e", line: "#8f5220" },
    { name: "Smoke",    body: "#a7aeb8", shade: "#848c98", line: "#5a616c" },
    { name: "Sand",     body: "#e8d2ae", shade: "#ccae7e", line: "#97794e" },
    { name: "Cocoa",    body: "#7a5844", shade: "#5c3f2e", line: "#3d281c" },
  ],
  night: [
    { name: "Jet",      body: "#3a3f45", shade: "#25292e", line: "#14171a" },
    { name: "Ink",      body: "#2c3140", shade: "#1d2130", line: "#10131e" },
    { name: "Ash",      body: "#565d66", shade: "#3d434b", line: "#26292e" },
  ],
  white: [
    { name: "Snow",     body: "#f5f3ee", shade: "#d8d3c8", line: "#a09a8c" },
    { name: "Ivory",    body: "#efe8d8", shade: "#d6c9ac", line: "#a4937a" },
    { name: "Pearl",    body: "#e9ecf2", shade: "#c6ccd8", line: "#9299a8" },
  ],
  bunny: [
    { name: "Snow",     body: "#f5f3ee", shade: "#d8d3c8", line: "#a09a8c" },
    { name: "Dust",     body: "#d8cfc2", shade: "#b5a893", line: "#83786a" },
    { name: "Fawn",     body: "#d9b48a", shade: "#bb9161", line: "#8a6640" },
    { name: "Smoke",    body: "#a7aeb8", shade: "#848c98", line: "#5a616c" },
  ],
  brown: [
    { name: "Hazel",    body: "#b3805a", shade: "#8f6140", line: "#61402a" },
    { name: "Chestnut", body: "#96603a", shade: "#744826", line: "#4d2f18" },
    { name: "Umber",    body: "#6e4a32", shade: "#523522", line: "#352215" },
  ],
  gold: [
    { name: "Sunny",    body: "#f2c94c", shade: "#d1a022", line: "#96700f" },
    { name: "Amber",    body: "#e8a83b", shade: "#c48318", line: "#8a5b0c" },
    { name: "Honey",    body: "#e6b877", shade: "#c4924a", line: "#8c6428" },
  ],
  red: [
    { name: "Scarlet",  body: "#d0362b", shade: "#9a2018", line: "#6a1109" },
    { name: "Ruby",     body: "#b8283f", shade: "#8c1a2e", line: "#5e0f1e" },
    { name: "Brick",    body: "#b04a32", shade: "#873321", line: "#5c2013" },
  ],
  orange: [
    { name: "Tangerine",body: "#ef8b3a", shade: "#cc6a1a", line: "#8f480f" },
    { name: "Rust",     body: "#c96a3a", shade: "#a04d22", line: "#6e3314" },
    { name: "Coral",    body: "#ef7a5a", shade: "#c8563a", line: "#8c3722" },
  ],
  green: [
    { name: "Leaf",     body: "#6fbf4a", shade: "#4c9430", line: "#31651e" },
    { name: "Emerald",  body: "#2fae7a", shade: "#1c8258", line: "#0f5a3b" },
    { name: "Moss",     body: "#8aa53e", shade: "#677f26", line: "#455618" },
    { name: "Jade",     body: "#57c4a2", shade: "#379a7b", line: "#206a54" },
  ],
  blue: [
    { name: "Sky",      body: "#5aa8e8", shade: "#3580c4", line: "#1f568a" },
    { name: "Azure",    body: "#3b7fd6", shade: "#265d9f", line: "#173e6c" },
    { name: "Navy",     body: "#3d5a94", shade: "#2a406e", line: "#1a2a4a" },
  ],
  pink: [
    { name: "Rose",     body: "#f2a0b8", shade: "#d4718f", line: "#a04a66" },
    { name: "Blossom",  body: "#f6bcd0", shade: "#df8fae", line: "#ab5f7e" },
    { name: "Salmon",   body: "#f2917a", shade: "#d16650", line: "#984434" },
  ],
  purple: [
    { name: "Lilac",    body: "#b28ae0", shade: "#8c60c0", line: "#5f3d8a" },
    { name: "Violet",   body: "#8a5fd0", shade: "#6740a4", line: "#452a72" },
    { name: "Plum",     body: "#7a4a78", shade: "#5b345a", line: "#3c1f3b" },
  ],
  teal: [
    { name: "Lagoon",   body: "#3fbfb0", shade: "#26948a", line: "#15645d" },
    { name: "Seafoam",  body: "#7ad4c0", shade: "#4daa96", line: "#2c7a6a" },
    { name: "Deep Teal",body: "#1f8a8a", shade: "#136464", line: "#0a4242" },
  ],
  sand: [
    { name: "Sand",     body: "#dbc292", shade: "#bb9c64", line: "#876c3e" },
    { name: "Dune",     body: "#cbb083", shade: "#a88a56", line: "#755e34" },
    { name: "Buff",     body: "#e6d2a8", shade: "#c4a874", line: "#8c7448" },
  ],
  slate: [
    { name: "Slate",    body: "#8b95a1", shade: "#69727d", line: "#454d56" },
    { name: "Pebble",   body: "#a8adb4", shade: "#83888f", line: "#575b61" },
    { name: "Storm",    body: "#6c7684", shade: "#4f5762", line: "#333941" },
  ],
};
export function coatOf(gene, animal) {
  const palette = PALS[animal && animal.pal] || PALS.poodle;
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

// ---- turn-based battle v2 (mirrors tests/pets_ref.ref_battle_turns + the contract bytecode EXACTLY) --
// EVERY stat fights, Monte-Carlo balanced so power = Σstats is a true score (see pets_ref.py):
// str damage, agi dodge, vit HP(x3), int accuracy, wis mitigation, cha intimidation, loy regen,
// luck crit(x2), spd turn-share, app bulk+bite. Winner = higher remaining FRACTION of HP (tie -> defender).
export const CAP_BATTLE = 12;   // MUST equal CAP_BATTLE in the contract + pets_ref.py
export function battleOf(bh0Hex, bh1Hex, bid, effA, effB) {
  if (!bh0Hex || !bh1Hex) return null;
  const q = hexInt(bh0Hex) + hexInt(bh1Hex) + BigInt(bid) * 8n;
  const hA = 20 + effA[2] * 3 + effA[9], hB = 20 + effB[2] * 3 + effB[9];
  let h0 = hA, h1 = hB;
  const span = BigInt(effA[8] + effB[8] + 120), thrA = BigInt(effA[8] + 60);
  const log = [];
  for (let t = 0; t < CAP_BATTLE; t++) {
    const alive = h0 > 0 && h1 > 0 ? 1 : 0;
    const cur = vmHash(q + BigInt(t + 8192)) % span < thrA ? 0 : 1;   // speed: who owns this turn
    const A = cur === 0 ? effA : effB, B = cur === 0 ? effB : effA;
    const acc = 15 + 2 * A[3];
    const hit = Number(vmHash(q + BigInt(t)) % 100n) * (acc + B[1]) < 100 * acc ? 1 : 0;
    let dmg = Math.floor((50 + A[0] + Math.floor(A[9] / 4)) * (60 + Number(vmHash(q + BigInt(t + 4096)) % 61n)) / 100) + 1;
    const crit = Number(vmHash(q + BigInt(t + 12288)) % 100n) < A[7] ? 1 : 0;
    dmg += crit * dmg;
    dmg = Math.floor(dmg * 90 / (90 + B[4]));
    dmg = Math.max(1, dmg - Math.floor(B[5] / 2));
    dmg = dmg * hit * alive;
    if (cur === 0) h1 -= dmg; else h0 -= dmg;
    h0 = Math.min(hA, h0 + alive * Math.floor(effA[6] / 4));
    h1 = Math.min(hB, h1 + alive * Math.floor(effB[6] / 4));
    log.push({ t, atk: cur, hit: hit && alive, crit: crit && hit && alive, dmg, h0, h1 });
  }
  const aWins = h0 * hB > h1 * hA;                 // remaining FRACTION decides (tie -> defender)
  return { aWins, dies: Number(vmHash(q + 999999n) % 100n) < DIE_PCT, h0, h1, log, hpA: hA, hpB: hB };
}

// ---- husbandry math (ints, exactly the contract's) -------------------------------------------------
export const feedBlocks = (valueRaw, appetite) => Number(BigInt(valueRaw) / (BigInt(appetite) * FEED_DIV));
export const feedCost = (blocks, appetite) => BigInt(blocks) * BigInt(appetite) * FEED_DIV;   // raw for N blocks
export const levelOf = (tfRaw) => Math.max(1, Math.floor(Math.sqrt(Number(BigInt(tfRaw) / 10n ** 10n))));
