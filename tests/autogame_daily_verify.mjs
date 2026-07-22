/*
 * autogame_daily_verify.mjs — the faucet distributor's replay oracle for the Autogame Daily Gauntlet.
 * Reads the day's posted claims AND the day's anchor (av[day], written on-chain by _lib.daily_anchor, so no
 * L1 history is ever needed) out of the contract view, REPLAYS every claim through the SAME engine the game
 * and the contract agree on, and prints ONE JSON line: the verified best-per-address rows, ranked by renown.
 *
 * A forged score never ranks (the replay must reproduce it) and a copied move list never ranks either (the
 * seed binds the poster's own address, so the same moves score differently for a thief).
 *
 * Usage: node tests/autogame_daily_verify.mjs <cid> <utcDay> [execUrl]
 */
import { entriesFrom, verifyEntries } from "../static/provable.js";
import { verifyClaim, WORDS } from "../static/autogame-daily.js";

const [cid, dayArg, execArg] = process.argv.slice(2);
const exec = execArg || "http://127.0.0.1:9273";
const day = Number(dayArg);
const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };

const sto = (await (await fetch(`${exec}/exec/contract?ns=default&cid=${cid}&provisional=1`)).json()).storage || {};
const m = (s, n) => s[n] || {};
const anchor = m(sto, "av")[day] ? String(m(sto, "av")[day]) : null;
if (!anchor) out([]);
const wordMaps = Array.from({ length: WORDS }, (_, k) => "ew" + k);
const entries = entriesFrom(sto, m, day, wordMaps);
const rows = await verifyEntries(entries, (en) => verifyClaim(day, en.n, en.words, anchor, en.addr));
out(rows.map((r) => [r.addr, r.score]));
