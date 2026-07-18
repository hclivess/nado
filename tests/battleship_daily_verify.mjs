/*
 * battleship_daily_verify.mjs — the faucet distributor's replay oracle for the Battleship Daily Salvo: reads
 * the day's posted claims + the on-chain day anchor (av[day]) from the contract view, REPLAYS every claim's
 * shot sequence against the same per-address fleet, and prints ONE JSON line of verified best-per-address
 * rows, ranked by score. A forged/copied claim never ranks (per-address seed + score must reproduce).
 * Usage: node tests/battleship_daily_verify.mjs <cid> <utcDay> [execUrl]
 */
import { entriesFrom, verifyEntries } from "../static/provable.js";
import { verifyClaim, WORDS } from "../static/battleship-daily.js";

const [cid, dayArg, execArg] = process.argv.slice(2);
const exec = execArg || "http://127.0.0.1:9273";
const day = Number(dayArg);
const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };

const sto = (await (await fetch(`${exec}/exec/contract?ns=default&cid=${cid}&provisional=1`)).json()).storage || {};
const m = (s, n) => s[n] || {};
const anchor = m(sto, "av")[day] ? String(m(sto, "av")[day]) : null;
if (!anchor) out([]);
const wordMaps = Array.from({ length: WORDS }, (_x, k) => "ew" + k);
const entries = entriesFrom(sto, m, day, wordMaps);
const rows = await verifyEntries(entries, (en) => verifyClaim(day, en.n, en.words, anchor, en.addr));
out(rows.map((r) => [r.addr, r.score]));
