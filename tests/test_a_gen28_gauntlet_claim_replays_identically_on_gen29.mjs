/*
 * A Daily Gauntlet claim posted on generation 28 replays to the SAME road and the SAME score on generation 29
 * (static/autogame-daily.js pins its road hash to nadodapp.algHashnV1; doc/stwo/g5-carry.md 2c).
 *
 * The Gauntlet is scored off-chain: the autogame contract stores the claim words and gates the day, and every verifier —
 * the browsers and the faucet's oracle (tests/autogame_daily_verify.mjs) — replays the moves. The road was hashed with the
 * generation's VM hash (algHashn), which becomes BLAKE2s at gen 29, so a claim carried across the reroll would have
 * replayed to a different road: dropped from the board of its day and from the faucet payout. Pins, running the real
 * module as gen 28 and again as gen 29 (NADO_TEST_PROTOCOL_OVERRIDES: BLAKE_EXEC_HEIGHT = 1, as the gen-29 chain runs):
 *   1. the same seed gives the same road words and the same score under both generations;
 *   2. the pinned hash is the gen-28 alghash, while the generation's own algHashn did change (the pin is what holds it);
 *   3. the faucet oracle's replay (verifyClaim) scores a posted claim identically on both.
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
  console.log(JSON.stringify({ v2: N.vmV2(), score: r.score, words, tile: String(w.tileHash),
                               vm: String(N.algHashn([7n, 9n])), packed: packed.map(String), n: ACTS.length + TIERS.length,
                               verdict }));
  process.exit(0);
}

const me = fileURLToPath(import.meta.url);
const run = (over) => JSON.parse(execFileSync(process.execPath, [me], {
  env: { ...process.env, NADO_GAUNTLET_CHILD: "1", NADO_TEST_PROTOCOL_OVERRIDES: JSON.stringify(over) },
  encoding: "utf8" }).trim().split("\n").pop());
let fails = 0;
const check = (name, ok, detail) => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  " + JSON.stringify(detail).slice(0, 400)}`); if (!ok) fails++; };

const g28 = run({});
const g29 = run({ BLAKE_EXEC_HEIGHT: 1 });
check("setup: the two runs are generation 28 and generation 29", g28.v2 === false && g29.v2 === true, [g28.v2, g29.v2]);
check("1. the same seed gives the same road words under both generations",
      JSON.stringify(g28.words) === JSON.stringify(g29.words) && g28.tile === g29.tile, [g28.words[0], g29.words[0]]);
check("1. ...and the same score", g28.score === g29.score && g28.score > 0, [g28.score, g29.score]);
check("2. the generation's own VM hash did change (the pin is what keeps the road)", g28.vm !== g29.vm);
check("3. the oracle's replay (verifyClaim) scores the posted claim identically on gen 29",
      g28.verdict === g29.verdict && g28.verdict > 0, [g28.verdict, g29.verdict]);
console.log(fails ? `${fails} FAILURES` : "ALL PASS — a gen-28 Gauntlet claim replays identically on gen 29");
process.exit(fails ? 1 : 0);
