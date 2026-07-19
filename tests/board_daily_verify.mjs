/*
 * board_daily_verify.mjs — the faucet distributor's replay oracle for the BOARD-GAME Daily Challenge
 * (tic-tac-toe / connect four / reversi). One oracle for all three: they share the harness in
 * static/board-daily.js and differ only by their pure rules module, so the game is selected by argument.
 *
 * Reads the day's posted claims AND the day's anchor (av[day], stored on-chain by _lib.daily_anchor — no
 * L1 history needed) from the contract view, REPLAYS every claim against the deterministic bot that the
 * day's seed defines, and prints ONE JSON line: verified best-per-address rows, ranked by score.
 *
 * A forged or copied claim never ranks: the seed binds the POSTER'S OWN address, so a claim lifted from
 * someone else replays against a different bot, and the replayed score must equal the posted one.
 * Usage: node tests/board_daily_verify.mjs <game> <cid> <utcDay> [execUrl]
 */
import { entriesFrom, verifyEntries } from "../static/provable.js";
import { verifyClaim } from "../static/board-daily.js";

const RULES = { tictactoe: "../static/tictactoe-rules.js",
                connect4:  "../static/connect4-rules.js",
                reversi:   "../static/reversi-rules.js" };

const [game, cid, dayArg, execArg] = process.argv.slice(2);
const out = (o) => { console.log(JSON.stringify(o)); process.exit(0); };
if (!RULES[game]) { console.error("unknown game: " + game); out([]); }

const rules = await import(RULES[game]);
const exec = execArg || "http://127.0.0.1:9273";
const day = Number(dayArg);

const sto = (await (await fetch(`${exec}/exec/contract?ns=default&cid=${cid}&provisional=1`)).json()).storage || {};
const m = (s, n) => s[n] || {};
const anchor = m(sto, "av")[day] ? String(m(sto, "av")[day]) : null;
if (!anchor) out([]);

// how many packed move words this game's board carries — must match the contract's DAILY_WORDS
const words = Math.ceil(rules.MAX_MOVES / Math.floor(50 / rules.MOVE_BITS));
const entries = entriesFrom(sto, m, day, [...Array(words)].map((_x, k) => "ew" + k));
const rows = await verifyEntries(entries, (en) => verifyClaim(rules, day, en.n, en.words, anchor, en.addr));
out(rows.map((r) => [r.addr, r.score]));
