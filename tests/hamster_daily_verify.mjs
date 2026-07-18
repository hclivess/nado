/*
 * hamster_daily_verify.mjs — the faucet distributor's replay oracle for the Hamster Daily Derby: reads the
 * day's posted claims AND the day's anchor (av[day], stored on-chain by _lib.daily_anchor — no L1 history
 * needed) from the contract view, REPLAYS every claim through the shared derby engine, and prints ONE JSON
 * line: the verified best-per-address rows, ranked by points. A forged or copied claim never ranks (each
 * claim's seed binds the poster's address, and the replayed score must match the posted score).
 * Usage: node tests/hamster_daily_verify.mjs <cid> <utcDay> [execUrl]
 */
import { entriesFrom, verifyEntries } from "../static/provable.js";
import { verifyClaim } from "../static/hamster-daily.js";

const [cid, dayArg, execArg] = process.argv.slice(2);
const exec = execArg || "http://127.0.0.1:9273";
const day = Number(dayArg);
const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };

const sto = (await (await fetch(`${exec}/exec/contract?ns=default&cid=${cid}&provisional=1`)).json()).storage || {};
const m = (s, n) => s[n] || {};
const anchor = m(sto, "av")[day] ? String(m(sto, "av")[day]) : null;
if (!anchor) out([]);
const entries = entriesFrom(sto, m, day, ["ew0"]);
const rows = await verifyEntries(entries, (en) => verifyClaim(day, en.n, en.words, anchor, en.addr));
out(rows.map((r) => [r.addr, r.score]));
