/*
 * A Daily Gauntlet claim the PAGE builds verifies in the FAUCET ORACLE, at the posted score, and the road both of them
 * walk is hashed with the generation's VM hash (nadodapp.algHashn = static/blake2s.js hashWords = zkvm2.hash_words).
 *
 * The Gauntlet is scored off-chain: the autogame contract stores the claim words and gates the day, and the browsers and
 * the faucet distributor's oracle (scripts/operator/_faucet_rewards.py runs `node tests/autogame_daily_verify.mjs <cid>
 * <day>`) each REPLAY the moves. Two road hashes would be a claim the page scores and the oracle refuses — no payout and
 * no error anywhere. Until 2026-10-28 the road was pinned to the gen-28 Goldilocks alghash (static/alghash.js, deleted
 * with G9); this pins the hash it moved to and the whole hop from the page to the oracle:
 *   1. the road is the VM hash: the day's world is hashWords over the seed, equal to Python's zkvm2.hash_words, and a
 *      fixed seed keeps its pinned road and score (a silent change of the road hash re-scores every claim of a live day);
 *   2. the page's flow — read the anchor out of the contract view, seed, walk the road it shows, post packClaim's words
 *      at scoreIfStopped's score — makes a claim the oracle's EXACT command ranks at exactly the posted score;
 *   3. the oracle refuses a forged score and a stolen move list (the seed binds the poster's address), and the page's own
 *      board (verifyEntries over verifyClaim) agrees with the oracle row for row;
 *   4. nothing in static/ imports alghash.js, it is gone, and nadodapp exports no algHashnV1.
 * The exec view is a local stub on an ephemeral port; nothing reaches a node.
 * Run: node tests/test_a_gauntlet_claim_the_page_builds_verifies_in_the_faucet_oracle_on_the_vm_hash.mjs
 */
import "./protocol_hook.mjs";
import { execFile, execFileSync } from "node:child_process";
import { createServer } from "node:http";
import { existsSync, readFileSync, readdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const D = await import("../static/autogame-daily.js");
const E = await import("../static/autogame-engine.js");
const R = await import("../static/autogame-rules.js");
const N = await import("../static/nadodapp.js");
const { hashWords } = await import("../static/blake2s.js");
const { H, provableSeed, anchorOf, entriesFrom, verifyEntries } = await import("../static/provable.js");

let fails = 0;
const check = (name, ok, detail) => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}${ok ? "" : "  " + JSON.stringify(detail).slice(0, 400)}`); if (!ok) fails++; };

// ---- 1. the road is the VM hash -----------------------------------------------------------------------------------
const SEED = "nado-gauntlet-vm-hash-test-seed";
const TIERS = [1, 3, 2, 4];
const ACTS = Array.from({ length: 60 }, (_, i) => (i * 5 + 3) % 8);
const s = BigInt("0x" + String(H(SEED)).slice(0, 32));
const w = D.dailyWorld(SEED);
check("1. the day's world is the VM hash (hashWords) of the seed",
      w.tileHash === hashWords([s, 1n]) && w.rollHash === hashWords([s, 2n]) && w.tileHash === N.algHashn([s, 1n]),
      [String(w.tileHash), String(hashWords([s, 1n]))]);
const lo32 = (x) => Number(x & 0xFFFFFFFFn);
const step3 = D.wordsAt(w, 3);
check("1. ...and every step's words are lo32(hashWords(world, runId, i))",
      step3.tw === lo32(hashWords([w.tileHash, 0n, 3n])) && step3.rw === lo32(hashWords([w.rollHash, 0n, 3n])), step3);
const home = mkdtempSync(join(tmpdir(), "nado-gauntlet-"));
let py;
try {
  // zkvm2 is hashlib-only; HOME and the exec paths still point at a throwaway dir (CLAUDE.md rule 4)
  py = execFileSync("python3", ["-c",
    "import sys; sys.path.insert(0, sys.argv[1]); from execnode import zkvm2; " +
    "print(zkvm2.hash_words([int(sys.argv[2]), 1]), zkvm2.hash_words([int(sys.argv[2]), 2]))", ROOT, String(s)],
    { cwd: home, encoding: "utf8",
      env: { ...process.env, HOME: home, NADO_EXEC_STATE: join(home, "st"), NADO_EXEC_DA: join(home, "da") } }).trim().split(" ");
} finally { rmSync(home, { recursive: true, force: true }); }
check("1. ...which is the contract VM's own hash (zkvm2.hash_words)",
      py[0] === String(w.tileHash) && py[1] === String(w.rollHash), [py, String(w.tileHash)]);
// Recorded 2026-10-28 when the road moved to the VM hash. A change here re-scores every claim of an in-flight day.
const PIN = { tile: "64891803208571573833272737274915865485664889936714162570004406089999318777508", score: 959 };
const r = D.play(SEED, TIERS, ACTS);
check("1. a fixed seed keeps its pinned road and score", String(w.tileHash) === PIN.tile && r.score === PIN.score,
      { tile: String(w.tileHash), score: r.score });

// ---- 2. the page's claim, through the oracle's exact command --------------------------------------------------------
const CID = "f6ccb08e979e1989516f35c4bfb7dea1", DAY = 20755;
const ME = "ndoGAUNTLETPAGEPLAYER0000000000000000000000000001", THIEF = "ndoGAUNTLETTHIEF00000000000000000000000000000002";
// the view serves a resolved anchor as a JSON INTEGER (a block-hash value), exactly as the exec node does — every
// JavaScript reader rounds it identically, so the page and the oracle must both read it out of the view, never be handed it
let entriesJson = "";
const view = () => `{"storage":{"av":{"${DAY}":4823474900883014428123456789012345678901234567890123456789012345678}` +
                   entriesJson + "}}";
const srv = createServer((req, res) => {
  const u = new URL(req.url, "http://x");
  if (u.pathname === "/exec/contract" && u.searchParams.get("cid") === CID) {
    res.writeHead(200, { "content-type": "application/json" }); res.end(view());
  } else { res.writeHead(404); res.end("{}"); }
});
await new Promise((ok) => srv.listen(0, "127.0.0.1", ok));
const EXEC = `http://127.0.0.1:${srv.address().port}`;
try {
  // the page (autogame-dailyui.js): getStorage -> anchorOf -> provableSeed(SLUG, day, anchor, me) -> dailyWorld, then a
  // walk over the tile it shows (roadAhead), the score it offers to post (scoreIfStopped of the OPEN replay) and the
  // words post() sends (packClaim, n = HEAD + actions)
  const sto = (await (await fetch(`${EXEC}/exec/contract?ns=default&cid=${CID}&provisional=1`)).json()).storage;
  const anchor = anchorOf(sto, (x, n) => x[n] || {}, DAY);
  const seed = provableSeed(D.SLUG, DAY, anchor, ME);
  const world = D.dailyWorld(seed);
  const tiers = [0, 2, 4, 3];
  const actions = [];
  for (let i = 0; i < D.STEPS; i++) {
    const open = D.play(seed, tiers, actions, true).run;
    if (!open.alive || open.done) break;
    const tile = D.roadAhead(world, open, i, 1)[0];
    const opts = R.ACTS_FOR[tile.tile] || [0];
    actions.push(opts[i % opts.length]);
  }
  const score = D.scoreIfStopped(D.play(seed, tiers, actions, true).run);
  const words = D.packClaim(tiers, actions);
  const n = D.HEAD + actions.length;
  check("2. the page's walk scores a real run", score > 0 && actions.length > 0, { score, steps: actions.length });

  const rows = [[ME, score, words], [ME, score + 1, words], [THIEF, score, words]];   // honest, forged, stolen
  // a word the run never reached is zero, and the view omits a zero slot (packClaim emits only the words it filled)
  const m = (k, f) => `"${k}":{` + rows.map((x, e) => [e + 1, f(x)]).filter(([, v]) => v !== undefined && v !== "undefined")
    .map(([e, v]) => `"${e}":${v}`).join(",") + "}";
  entriesJson = "," + [m("eday", () => DAY), m("eaddr", (x) => `"${x[0]}"`), m("escore", (x) => x[1]), m("en", () => n),
                       m("ets", () => 1793145600),
                       ...Array.from({ length: D.WORDS }, (_, k) => m("ew" + k, (x) => (x[2][k] ? String(x[2][k]) : undefined)))].join(",");
  // THE ORACLE'S EXACT COMMAND (scripts/operator/_faucet_rewards.py DAILY_VERIFY["autogame-daily"], cwd = the repo)
  const out = await new Promise((ok, no) => execFile("node", ["tests/autogame_daily_verify.mjs", CID, String(DAY), EXEC],
    { cwd: ROOT, encoding: "utf8" }, (err, so, se) => (err ? no(new Error(se || String(err))) : ok(so))));
  const ranked = JSON.parse(out.trim().split("\n").pop());
  check("2. the faucet oracle ranks the page's claim at exactly the posted score",
        ranked.some(([a, sc]) => a === ME && sc === score), ranked);
  // ---- 3. refusals, and the page's board agrees -----------------------------------------------------------------
  check("3. ...and refuses the forged score and the stolen move list", ranked.length === 1, ranked);
  const sto2 = (await (await fetch(`${EXEC}/exec/contract?ns=default&cid=${CID}&provisional=1`)).json()).storage;
  const mm = (x, k) => x[k] || {};
  const anchor2 = anchorOf(sto2, mm, DAY);
  const board = await verifyEntries(entriesFrom(sto2, mm, DAY, Array.from({ length: D.WORDS }, (_, k) => "ew" + k)),
    (en) => D.verifyClaim(DAY, en.n, en.words, anchor2, en.addr));
  check("3. the page's own board shows exactly the oracle's rows",
        JSON.stringify(board.map((b) => [b.addr, b.score])) === JSON.stringify(ranked), [board, ranked]);
} finally { srv.close(); }

// ---- 4. Goldilocks is gone from the browser -----------------------------------------------------------------------
const STATIC = join(ROOT, "static");
const importers = readdirSync(STATIC).filter((f) => /\.(m?js|html)$/.test(f))
  .filter((f) => /["'/]alghash\.js["']/.test(readFileSync(join(STATIC, f), "utf8")));
check("4. no static file imports alghash.js, and it is gone", importers.length === 0 && !existsSync(join(STATIC, "alghash.js")),
      importers);
check("4. ...and nadodapp exports no gen-28 algHashnV1", !("algHashnV1" in N), Object.keys(N).filter((k) => /alg/i.test(k)));

console.log(fails ? `${fails} FAILURES` : "ALL PASS — a Gauntlet claim the page builds verifies in the faucet oracle on the VM hash");
process.exit(fails ? 1 : 0);
