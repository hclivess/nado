// hamster-daily.js — the FREE Daily Derby: a deterministic solo handicapping challenge whose score is
// provable (doc/provable-practice.md + static/provable.js). Each player gets their OWN slate of races for the
// UTC day, seeded by the on-chain day anchor + their address (so a claim is non-transferable and a forged
// score never verifies). You read each race's form (the six speed genes) and PICK one hamster; a correct pick
// scores its ODDS in points, so backing a winning longshot pays off. The whole slate is a pure function of the
// seed, so every browser AND the faucet oracle replay a posted claim identically. Shared by hamster.js (play +
// board) and tests/hamster_daily_verify.mjs (the faucet distributor's replay oracle).
import { H, provableSeed, unpackMoves } from "./provable.js";

export const SLUG = "hamster";
export const RACES = 8;         // races in a day's slate
export const NH = 6;            // hamsters per race
export const RACE_LEN = 6;      // race blocks
export const GENE_SPREAD = 8;   // speed = 1 + rng % 8   (1..8), mirrors the on-chain feel
export const STEP_BASE = 6;     // per-block step = rng % (speed + 6)
export const PICK_BITS = 3;     // a pick is a lane 0..5 -> 3 bits; RACES picks pack into ONE word (<2^50)
export const WORDS = 1;

// deterministic unsigned int from the seed + a tag (blake2b stream — the same H the provable SDK uses).
function rint(seed, tag) { return parseInt(String(H(seed + ":" + tag)).slice(0, 12), 16); }

// flavour names — deterministic per (seed, race, lane). Cosmetic only (never consensus).
const NAMES = ["Nibbles", "Peanut", "Biscuit", "Waffles", "Pebble", "Cheeko", "Tumble", "Marbles", "Sprocket",
  "Pippin", "Gizmo", "Noodle", "Bandit", "Truffle", "Bram", "Cinnamon", "Widget", "Momo", "Dashi", "Clover"];
export function dailyName(seed, race, lane) { return NAMES[rint(seed, "n" + race + "-" + lane) % NAMES.length]; }

// odds points for a lane given the race's speeds: model win-prob ∝ speed, points = 100 · Σspeed ÷ speed
// (a slow hamster that wins is worth far more than the favourite). Integer, so client & oracle agree exactly.
function oddsPts(speeds, lane) {
  const tot = speeds.reduce((a, b) => a + b, 0);
  return Math.max(100, Math.round(100 * tot / speeds[lane]));
}

// dailyRaces(seed): the day's fixed slate — [{speeds[6], dist[6], winner, odds[6]}], a pure function of seed.
export function dailyRaces(seed) {
  const races = [];
  for (let r = 0; r < RACES; r++) {
    const speeds = [];
    for (let l = 0; l < NH; l++) speeds.push(1 + (rint(seed, "g" + r + "-" + l) % GENE_SPREAD));
    const dist = new Array(NH).fill(0);
    for (let bi = 1; bi <= RACE_LEN; bi++)
      for (let l = 0; l < NH; l++) dist[l] += rint(seed, "s" + r + "-" + bi + "-" + l) % (speeds[l] + STEP_BASE);
    let winner = 0; for (let l = 1; l < NH; l++) if (dist[l] > dist[winner]) winner = l;   // ties -> lowest lane
    const odds = speeds.map((_s, l) => oddsPts(speeds, l));
    races.push({ speeds, dist, winner, odds });
  }
  return races;
}

// score a full slate of picks (one lane per race). A correct pick scores that lane's odds points.
export function scorePicks(races, picks) {
  let s = 0;
  for (let r = 0; r < RACES && r < picks.length; r++) if (picks[r] === races[r].winner) s += races[r].odds[picks[r]];
  return s;
}

// verifyClaim(day, n, words, anchorHash, addr) -> the TRUE score (or -1 if malformed). The faucet oracle
// (verifyEntries) keeps a claim only when this equals the posted score, so a fake score never ranks.
export function verifyClaim(day, n, words, anchorHash, addr) {
  if (Number(n) !== RACES) return -1;
  const picks = unpackMoves(words, PICK_BITS, RACES);
  if (picks.some((p) => p < 0 || p >= NH)) return -1;
  const seed = provableSeed(SLUG, day, anchorHash, addr);
  return scorePicks(dailyRaces(seed), picks);
}

// the max points a perfect day could score — for the UI's progress headline (not consensus).
export function maxScore(seed) { return dailyRaces(seed).reduce((a, r) => a + r.odds[r.winner], 0); }
