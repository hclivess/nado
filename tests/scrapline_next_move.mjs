/*
 * scrapline_next_move.mjs — LIVE-chain move oracle for the Scrapline E2E: replays the on-chain draft
 * through the REAL engine with the REAL pinned block hashes and prints ONE JSON line — the next legal
 * draft move for whichever player can act (drafting is concurrent), or the terminal/blocked status.
 * Usage: node tests/scrapline_next_move.mjs <gameId> <cid> [seed] [execUrl]
 */
import { loadCrypto } from "../static/nadotx.js";
await loadCrypto(".");
const E = await import("../static/scrapline-engine.js");

const [g, cid, seedArg, exec] = [process.argv[2], process.argv[3], process.argv[4] || "1", process.argv[5] || "http://127.0.0.1:9273"];
const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };
const J = async (u) => (await fetch(u)).json();
function prng(seed) { let s = seed >>> 0; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32); }

const sto = (await J(`${exec}/exec/contract?ns=default&cid=${cid}&provisional=1`)).storage || {};
const m = (n) => sto[n] || {};
const nn = m("nn")[g] || 0, mc = m("mc")[g] || 0, kh = m("kh")[g] || 0;
if (nn < 2 || !kh) out({ waiting: "join" });
const recs = [];
for (let i = 0; i < mc; i++) {
  const enc = m("mv")[String(g * 10000 + i)], rec = m("mh")[String(g * 10000 + i)];
  if (!enc || !rec) out({ waiting: "log" });
  recs.push({ enc, side: rec % 4, rh: Math.floor(rec / 4) });
}
const heights = [kh, kh + 1, ...recs.flatMap((r) => [r.rh, r.rh + 1])];
const bh = (await J(`${exec}/exec/blockhash?ns=default&provisional=1&heights=${[...new Set(heights)].join(",")}`)).hashes || {};
const qOf = (h) => (bh[String(h)] && bh[String(h + 1)]) ? BigInt("0x" + bh[String(h)]) + BigInt("0x" + bh[String(h + 1)]) : null;

const st = E.replay(Number(g), qOf(kh), recs.map((r) => ({ enc: r.enc, side: r.side, q: qOf(r.rh) })));
if (st.setup || st.blocked) out({ blocked: true, at: st.blockedAt });
if (st.corrupt) out({ corrupt: true, why: st.corruptWhy });
if (st.over) out({ over: true, result: st.result, hp: st.combat && st.combat.hp, mc });
const rnd = prng((Number(seedArg) * 7919 + mc) >>> 0);
const cand = [0, 1].filter((p) => st.ps[p].round < E.ROUNDS && E.offerFor(st, p) != null);
if (!cand.length) out({ blocked: true, at: mc });     // both waiting on their next offer's seed block
const p = cand[Math.floor(rnd() * cand.length)];
const offer = E.offerFor(st, p);
let enc;
if (rnd() < 0.1) enc = E.encMove(2, 0);
else {
  const choice = Math.floor(rnd() * 3);
  // prefer a merge slot when one exists, else a random slot
  const z = st.ps[p];
  let slot = z.gear.findIndex((gi) => gi && gi.id === offer[choice] && gi.rank < E.MAXRANK);
  if (slot < 0) slot = z.gear.findIndex((gi) => !gi);
  if (slot < 0) slot = Math.floor(rnd() * E.SLOTS);
  enc = E.encMove(1, choice + 4 * slot);
}
out({ actor: p, enc, ply: mc, rounds: [st.ps[0].round, st.ps[1].round] });
