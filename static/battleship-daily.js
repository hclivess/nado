// battleship-daily.js — the FREE "Daily Salvo": a deterministic solo Battleship you play against a hidden
// fleet decided by the day's on-chain anchor + your address (per-player, non-transferable — a forged or
// copied score never verifies). Hunt & sink all five ships in as few shots as you can; your shot sequence is
// posted and every browser + the faucet oracle REPLAYS it against the same fleet to confirm the score. Shared
// by battleship.js (play + board) and tests/battleship_daily_verify.mjs (the faucet replay oracle).
// Provable-practice model: doc/provable-practice.md + static/provable.js.
import { H, provableSeed, unpackMoves } from "./provable.js";

export const SLUG = "battleship";
export const N = 10, CELLS = 100;
export const FLEET = [5, 4, 3, 3, 2];      // classic fleet, 17 cells
export const SHIPS = 17;
export const BUDGET = 40;                  // max shots a daily run may post
export const SHOT_BITS = 7;                // a cell 0..99 fits in 7 bits
export const WORDS = 6;                    // ceil(BUDGET / floor(50/7)=7) = 6 packed words
// scoring: reward hits, sinking ships, and finishing in few shots.
const HIT_PTS = 10, SINK_PTS = 30, EFF_PTS = 5;

// deterministic unsigned int from the seed + tag (the same blake2b stream the provable SDK uses).
function rint(seed, tag) { return parseInt(String(H(seed + ":" + tag)).slice(0, 12), 16); }

// dailyFleet(seed): place FLEET on the 10x10 grid deterministically, non-overlapping (ships may touch — a
// solo puzzle, not the strict PvP rule). Returns { occ:Set(cells), ships:[[cells...]] }, a pure fn of seed.
export function dailyFleet(seed) {
  const occ = new Set(), ships = [];
  FLEET.forEach((len, si) => {
    for (let attempt = 0; attempt < 200; attempt++) {
      const horiz = rint(seed, "o" + si + "-" + attempt) % 2 === 0;
      const maxR = horiz ? N : N - len + 1, maxC = horiz ? N - len + 1 : N;
      const r = rint(seed, "r" + si + "-" + attempt) % maxR;
      const c = rint(seed, "c" + si + "-" + attempt) % maxC;
      const cells = [];
      for (let k = 0; k < len; k++) cells.push((r + (horiz ? 0 : k)) * N + (c + (horiz ? k : 0)));
      if (cells.some((x) => occ.has(x))) continue;   // overlap -> try the next deterministic spot
      cells.forEach((x) => occ.add(x)); ships.push(cells); return;
    }
    ships.push([]);   // pathologically unplaceable (never happens on 10x10) -> empty ship
  });
  return { occ, ships };
}

// scoreShots(fleet, shots): replay the shot sequence (deduped, in order) and score it. Pure fn.
export function scoreShots(fleet, shots) {
  const hitSet = new Set();
  let shotCount = 0;
  const seen = new Set();
  for (const cell of shots) {
    if (cell < 0 || cell >= CELLS || seen.has(cell)) continue;   // ignore repeats/out-of-range
    seen.add(cell); shotCount++;
    if (fleet.occ.has(cell)) hitSet.add(cell);
    if (shotCount >= BUDGET) break;
  }
  const hits = hitSet.size;
  const sunk = fleet.ships.filter((s) => s.length && s.every((x) => hitSet.has(x))).length;
  const allSunk = hits === SHIPS;
  return hits * HIT_PTS + sunk * SINK_PTS + (allSunk ? Math.max(0, BUDGET - shotCount) * EFF_PTS : 0);
}

// verifyClaim(day, n, words, anchorHash, addr) -> the TRUE score (or -1 if malformed). verifyEntries keeps a
// claim only when this equals the posted score, so a fake score never ranks.
export function verifyClaim(day, n, words, anchorHash, addr) {
  n = Number(n);
  if (!(n > 0 && n <= BUDGET)) return -1;
  const shots = unpackMoves(words, SHOT_BITS, n);
  if (shots.some((s) => s < 0 || s >= CELLS)) return -1;
  const seed = provableSeed(SLUG, day, anchorHash, addr);
  return scoreShots(dailyFleet(seed), shots);
}

export const coord = (cell) => "ABCDEFGHIJ"[Math.floor(cell / N)] + (cell % N + 1);
