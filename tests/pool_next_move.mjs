/*
 * pool_next_move.mjs — LIVE-chain shot oracle for the Pool E2E: reads the on-chain shot log, replays it
 * through the REAL browser engine with the REAL rack seed (the pinned join block's hashes), and prints
 * ONE JSON line — the next legal shot for whoever is at the table, or the terminal/blocked status.
 * Usage: node tests/pool_next_move.mjs <gameId> <cid> [seed] [execUrl]
 */
import { loadCrypto } from "../static/nadotx.js";
await loadCrypto(".");
const E = await import("../static/pool-engine.js");

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
  recs.push({ enc, side: rec % 4 });
}
const bh = (await J(`${exec}/exec/blockhash?ns=default&provisional=1&heights=${kh},${kh + 1}`)).hashes || {};
const q = (bh[String(kh)] && bh[String(kh + 1)]) ? BigInt("0x" + bh[String(kh)]) + BigInt("0x" + bh[String(kh + 1)]) : null;
if (q == null) out({ blocked: true, why: "rack seed block not mined yet" });

const st = E.replay(Number(g), q, recs);
if (st.setup || st.blocked) out({ blocked: true, at: st.blockedAt });
if (st.corrupt) out({ corrupt: true, why: st.corruptWhy });
if (st.over) out({ over: true, result: st.result, mc });

const side = st.turn;
const enc = E.botEnc(st, side, prng((Number(seedArg) * 7919 + mc) >>> 0));
const shot = E.decShot(enc);
out({ actor: side, enc, ply: mc, angle: shot.angle, power: shot.power,
      group: st.open ? "open" : (st.grp[side] === 0 ? "solids" : "stripes"),
      onEight: E.targetGroup(st, side) === 2, inHand: st.inHand,
      left: [E.remaining(st, 0), E.remaining(st, 1)] });
