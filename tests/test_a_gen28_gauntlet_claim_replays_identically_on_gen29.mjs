/*
 * A Daily Gauntlet claim posted on generation 28 replays to the SAME road and the SAME score on generation 29
 * (static/autogame-daily.js pins its road hash to nadodapp.algHashnV1; doc/stwo/g5-carry.md 2c).
 *
 * The Gauntlet is scored off-chain: the autogame contract stores the claim words and gates the day, and every verifier —
 * the browsers and the faucet's oracle (tests/autogame_daily_verify.mjs) — replays the moves. The road was hashed with the
 * generation's VM hash (algHashn), which becomes BLAKE2s at gen 29, so a claim carried across the reroll would have
 * replayed to a different road: dropped from the board of its day and from the faucet payout. Pins, running the real
 * module as the gen-29 chain runs it, against the values the same module computed AS GENERATION 28 (recorded from main
 * under BLAKE_EXEC_HEIGHT = 2^62 when G9 inlined that gate — the gen-28 run itself retired with it):
 *   1. the same seed gives the same road words and the same score as on generation 28;
 *   2. the pinned hash is the gen-28 alghash, while the generation's own algHashn is not (the pin is what holds it);
 *   3. the faucet oracle's replay (verifyClaim) scores a posted claim as generation 28 scored it.
 * Run: node tests/test_a_gen28_gauntlet_claim_replays_identically_on_gen29.mjs
 */
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const SEED = "nado-gauntlet-carry-test-seed";
const TIERS = [1, 3, 2, 4];
const ACTS = Array.from({ length: 60 }, (_, i) => (i * 5 + 3) % 8);

if (process.env.NADO_GAUNTLET_CHILD) {
  const _el = new Proxy(function () {}, { get: (t, k) => k === Symbol.toPrimitive ? () => "" : _el, apply: () => _el });
  for (const k of ["document", "window", "localStorage", "sessionStorage", "location", "history"]) if (!(k in globalThis)) globalThis[k] = _el;
  await import("./protocol_hook.mjs");
  const { loadCrypto } = await import("../static/nadotx.js");
  await loadCrypto(".");
  const D = await import("../static/autogame-daily.js");
  const N = await import("../static/nadodapp.js");
  const w = D.dailyWorld(SEED);
  const r = D.play(SEED, TIERS, ACTS);
  const words = Array.from({ length: 8 }, (_, i) => D.wordsAt(w, i));
  const packed = D.packClaim(TIERS, ACTS);
  // the faucet oracle's path: replay a posted claim (day, move count, packed words, the day's anchor, the poster)
  const verdict = D.verifyClaim(20750, ACTS.length + TIERS.length, packed, "ab".repeat(32), "ndoGAUNTLETPLAYER");
  console.log(JSON.stringify({ score: r.score, words, tile: String(w.tileHash), vm: String(N.algHashn([7n, 9n])),
                               v1: String(N.algHashnV1([7n, 9n])), packed: packed.map(String), n: ACTS.length + TIERS.length,
                               verdict }));
  process.exit(0);
}

const me = fileURLToPath(import.meta.url);
const run = (over) => JSON.parse(execFileSync(process.execPath, [me], {
  env: { ...process.env, NADO_GAUNTLET_CHILD: "1", NADO_TEST_PROTOCOL_OVERRIDES: JSON.stringify(over) },
  encoding: "utf8" }).trim().split("\n").pop());
let fails = 0;
const check = (name, ok, detail) => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  " + JSON.stringify(detail).slice(0, 400)}`); if (!ok) fails++; };

// GENERATION 28's OUTPUT for this seed, recorded from main (the module run with BLAKE_EXEC_HEIGHT = 2^62) when G9 inlined
// the gate. The gen-28 run cannot be repeated on a tree without the gate, so its result is the fixture.
const G28 = {
  score: 32131, tile: "7390402136126404711", vm: "13249511955133414348", verdict: 196,
  words: [{ tw: 2160337101, rw: 2747328613 }, { tw: 3294666403, rw: 4130716123 }, { tw: 339805848, rw: 2634703715 },
          { tw: 840108888, rw: 4045292860 }, { tw: 2806726917, rw: 246821969 }, { tw: 3231900657, rw: 219868566 },
          { tw: 1459047549, rw: 4226330365 }, { tw: 4045365297, rw: 1543393099 }],
};
const g29 = run({});
check("1. the same seed gives the same road words as on generation 28",
      JSON.stringify(G28.words) === JSON.stringify(g29.words) && G28.tile === g29.tile, [G28.words[0], g29.words[0]]);
check("1. ...and the same score", G28.score === g29.score && g29.score > 0, [G28.score, g29.score]);
check("2. the road's pinned hash is the gen-28 alghash, and the generation's own VM hash is not",
      g29.v1 === G28.vm && g29.vm !== G28.vm, [g29.v1, g29.vm]);
check("3. the oracle's replay (verifyClaim) scores the posted claim as generation 28 did",
      g29.verdict === G28.verdict && g29.verdict > 0, [G28.verdict, g29.verdict]);
console.log(fails ? `${fails} FAILURES` : "ALL PASS — a gen-28 Gauntlet claim replays identically on gen 29");
process.exit(fails ? 1 : 0);
