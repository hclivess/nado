/*
 * hexholm_next_move.mjs — LIVE-chain move oracle for the Hexholm E2E: reads the table's on-chain move
 * log + the L1 block hashes it pins, replays it through the REAL engine (exactly what the browser does),
 * and prints ONE line of JSON: the next legal move for the current actor (from the shared bot), or the
 * table's terminal/blocked status. The python driver submits the move with the right key.
 * Usage: node tests/hexholm_next_move.mjs <gameId> <cid> <botSeed> [execUrl] [x1 x2 x3 x4]
 * The driver plays EVERY seat, so it legitimately passes every secret — the oracle replays in full
 * knowledge and can buy/play scrolls legally.
 */
import * as E from "../static/hexholm-engine.js";
import { prng, pickMove } from "../static/hexholm-bot.js";

const [g, cid, seedArg, execArg, ...xs] = process.argv.slice(2);
const exec = execArg || "http://127.0.0.1:9273";
const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };
const J = async (u) => (await fetch(u)).json();

const sto = (await J(`${exec}/exec/contract?ns=default&cid=${cid}&provisional=1`)).storage || {};
const m = (n) => sto[n] || {};
const nn = m("nn")[g] || 0, cap = m("cap")[g] || 0, mc = m("mc")[g] || 0, kh = m("kh")[g] || 0;
if (!nn || nn < cap || !kh) out({ waiting: "join", nn, cap });
if (m("sd")[g]) out({ settled: true, wr: m("wr")[g] || 0 });

const recs = [];
for (let i = 0; i < mc; i++) {
  const enc = m("mv")[String(g * 10000 + i)], rec = m("mh")[String(g * 10000 + i)];
  if (!enc || !rec) out({ waiting: "log" });
  recs.push({ enc, side: rec % 8, rh: Math.floor(rec / 8) });
}
const heights = [kh, kh + 1, ...recs.flatMap((r) => [r.rh, r.rh + 1])];
const bh = (await J(`${exec}/exec/blockhash?ns=default&provisional=1&heights=${[...new Set(heights)].join(",")}`)).hashes || {};
const qOf = (h) => (bh[h] && bh[h + 1]) ? BigInt("0x" + bh[h]) + BigInt("0x" + bh[h + 1]) : null;

const secrets = {}, commits = [];
for (let s = 1; s <= 4; s++) {
  secrets[s] = xs[s - 1] ? BigInt(xs[s - 1]) : null;
  commits.push(m("c" + s)[g] || 0);
}
const st = E.replay(qOf(kh), recs.map((r) => ({ enc: r.enc, side: r.side, q: qOf(r.rh) })),
                    { cap, secrets, commits });
if (st.corrupt) out({ corrupt: st.corrupt, why: st.why });
if (st.over) out({ over: true, winner: st.winner, vp: E.totalVp(st, st.winner) });
if (st.blocked || st.mi < recs.length) out({ blocked: true, mi: st.mi, mc });

for (const seat of E.actorsNow(st)) {
  const mv = pickMove(st, seat, prng(seedArg + ":" + mc + ":" + seat));
  if (mv != null) out({ actor: seat - 1, enc: mv, ply: mc, phase: st.phase, turn: st.turnSeat });
}
out({ waiting: "no actor has a legal move", phase: st.phase });
