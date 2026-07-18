/*
 * hexholm_daily_verify.mjs — the faucet distributor's replay oracle for the Hexholm daily island:
 * reads the day's posted claims from the contract view, derives the day anchor from L1 (the same
 * provable.js bisection every browser runs), REPLAYS every claim through the real engine + bot, and
 * prints ONE JSON line: the verified best-per-address rows, ranked. A forged claim never ranks.
 * Usage: node tests/hexholm_daily_verify.mjs <cid> <utcDay> [execUrl] [l1Url]
 */
import { verifyClaim } from "../static/hexholm-bot.js";
import { dayAnchor, verifyEntries } from "../static/provable.js";

const [cid, dayArg, execArg, l1Arg] = process.argv.slice(2);
const exec = execArg || "http://127.0.0.1:9273";
const L1 = l1Arg || "http://127.0.0.1:9173";
const day = Number(dayArg);
const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };

const sto = (await (await fetch(`${exec}/exec/contract?ns=default&cid=${cid}&provisional=1`)).json()).storage || {};
const m = (n) => sto[n] || {};
const anch = await dayAnchor(L1, day);
if (!anch) out([]);
const entries = [];
for (const e of Object.keys(m("eday"))) {
  if (m("eday")[e] !== day) continue;
  const words = [];
  for (let i = 0; i < 150; i++) words.push(m("ew")[String(Number(e) * 10000 + i)] || 0);
  entries.push({ e, day, addr: m("eaddr")[e], score: m("escore")[e] || 0, n: m("en")[e] || 0, words });
}
const rows = await verifyEntries(entries, (en) => verifyClaim(day, en.n, en.words, anch, en.addr));
out(rows.map((r) => [r.addr, r.score]));
