/* A game record carried across the reroll is shown as the contract paid it, never redrawn as another result (G6;
 * doc/stwo/g5-carry.md 2c "History displays recompute from stored seeds").
 *
 * Several pages RECOMPUTE a finished game's face, race, board or fight from stored seeds or block heights through the
 * VM hash. A record carried to gen 29 was played under gen 28's hash on the OLD chain's blocks: its heights name other
 * blocks here (or none yet), so a recompute draws something else — a coin face beside the other slot's payout, a race
 * whose leader is not the hamster paid, a poker board that does not make the hands scored, a fight the loser wins.
 * No record says which generation made it, so every page follows ONE rule: a recompute is shown only when it reaches
 * the stored result exactly; otherwise the stored result stands alone. A record made on THIS chain always recomputes
 * to its own result, so nothing changes for it.
 *
 * The pages' own code is RUN (extracted from static/*.js) with the chain stubbed; no key is involved.
 *
 * Run: node tests/test_a_pre_reroll_game_record_is_shown_as_paid_never_redrawn.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const read = (f) => fs.readFileSync(path.join(HERE, "..", "static", f), "utf8");
function fnSrc(src, name) {
  const i = src.indexOf("function " + name + "(");
  if (i === -1) throw new Error(name + " not found");
  let depth = 0, j = src.indexOf("{", src.indexOf(")", i));
  for (; j < src.length; j++) { if (src[j] === "{") depth++; else if (src[j] === "}" && --depth === 0) break; }
  return src.slice(i, j + 1);
}
const between = (src, a, b) => { const i = src.indexOf(a), j = src.indexOf(b, i); if (i < 0 || j < 0) throw new Error("not found: " + a); return src.slice(i, j + b.length); };
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + JSON.stringify(detail))); if (!ok) fails++; };
const _m = (sto, name) => (sto && sto[name]) || {};

// ---- coinflip: a settled face is read from the stored winner -------------------------------------------------------
{
  const gameFrom = new Function("_m", "dapp", "chainResultAlg", "hex", fnSrc(read("coinflip.js"), "gameFrom") + "return gameFrom;");
  const sto = { nn: { 5: 2 }, p1: { 5: "a" }, p2: { 5: "b" }, sd: { 5: 1 }, ws: { 5: 2 }, md: { 5: 1 }, dl: { 5: 9 },
                c1: { 5: 1 }, c2: { 5: 1 }, v1: { 5: 1 }, v2: { 5: 1 }, s1: { 5: 11 }, s2: { 5: 22 } };
  // a re-flip under another hash says heads (slot 1) for a game whose tails player (slot 2) was paid
  const g = gameFrom(_m, { cursor: 100 }, () => 0, (v) => BigInt(v).toString(16))(sto, 5);
  check("coinflip: a settled game shows the face of the slot that was paid", g.winner_slot === 2 && g.result === 1, g);
  const live = { ...sto, sd: {}, ws: {} };
  const g2 = gameFrom(_m, { cursor: 100 }, () => 0, (v) => BigInt(v).toString(16))(live, 5);
  check("coinflip: an unsettled revealed game still flips from its secrets", g2.result === 0 && g2.winner_slot === 1 && g2.ready, g2);
}

// ---- hamster: a settled race is redrawn only when the redraw reaches its stored distances ---------------------------
{
  const RACE_LEN = 3, COATS = [["#a", "#b"]];
  const settledRows = new Function("window", "COATS", "RACE_LEN", fnSrc(read("hamster.js"), "settledRows") + "return settledRows;")(
    { t: (k, d, v) => d.replace("{n}", v.n) }, COATS, RACE_LEN);
  const race = { sd: true, di: [9, 4, 7], fh: 500, cur: 900 };
  const rows = (d) => d.map((x, l) => ({ lane: l, speed: 3, name: "Hammy" + l, coat: ["#c", "#d"], dist: x, blocks: RACE_LEN }));
  check("hamster: a redraw that reaches the stored distances is kept", settledRows(race, rows([9, 4, 7]))[0].name === "Hammy0");
  const off = settledRows(race, rows([3, 12, 7]));
  check("hamster: a redraw that does not is replaced by plain lanes at the stored distances",
    off.map((r) => r.dist).join() === "9,4,7" && off.every((r) => r.speed === null && /^lane \d$/.test(r.name)), off);
  const carried = settledRows({ ...race, cur: 100 }, null);
  check("hamster: a race settled before this chain reached its finish (carried) shows plain lanes",
    carried && carried.map((r) => r.dist).join() === "9,4,7", carried);
  check("hamster: a redraw still loading waits (null), an unsettled race is untouched",
    settledRows(race, null) === null && settledRows({ ...race, sd: false }, rows([1, 2, 3]))[2].dist === 3);
}

// ---- holdem: a closed hand's board is shown only when it scores the stored hands -----------------------------------
{
  const block = between(read("poker.js"), "  const drawn = tb.exists", "  const board = preReroll ? [] : drawn;");
  const run = ({ closed, drawn, seats, score, td = 1 }) => new Function("tb", "dapp", "boardCards", "activeTable", "lastSeats", "holeCards", "holeBase", "eval7",
    block + "\nreturn { board, preReroll };")(
    { exists: true, td, closed }, { cursor: 10 }, () => drawn, 1, seats,
    (a, b, s) => [Number(s), Number(s) + 1], () => [null, null], (cards) => ({ v: score(cards) }));
  const sum = (cards) => cards.reduce((a, c) => a + c, 0);
  const seats = [{ revealed: true, secret: "1", value: sum([1, 2, 10, 11, 12, 13, 14]) }, { revealed: false }];
  let r = run({ closed: true, drawn: [10, 11, 12, 13, 14], seats, score: sum });
  check("holdem: a closed hand whose board scores every shown hand is redrawn", !r.preReroll && r.board.length === 5, r);
  r = run({ closed: true, drawn: [20, 11, 12, 13, 14], seats, score: sum });
  check("holdem: a closed hand whose board does not score them shows no board", r.preReroll && r.board.length === 0, r);
  r = run({ closed: true, drawn: [], seats, score: sum });
  check("holdem: a closed hand with no board here (carried above this chain's cursor) shows none", r.preReroll && r.board.length === 0, r);
  r = run({ closed: true, drawn: [], seats: [], score: sum, td: 0 });
  check("holdem: a table cancelled before the deal is not called a pre-reroll hand", !r.preReroll, r);
  r = run({ closed: false, drawn: [20, 11, 12], seats, score: sum });
  check("holdem: a live hand deals as before", !r.preReroll && r.board.length === 3, r);
}

// ---- pets: a settled battle is replayed only when the replay's winner is the stored one ----------------------------
{
  const line = between(read("pets.js"), "  const res = b.wn === 3 && res0", ": res0;");
  const pick = (b, res0) => new Function("b", "res0", line + "\nreturn res;")(b, res0);
  const b = { wn: 3, a: 7, b: 8, ww: 8 };
  check("pets: a replay whose winner is not the paid one is dropped", pick(b, { aWins: true, log: [1] }) === null);
  check("pets: a replay whose winner is the paid one is kept", pick(b, { aWins: false, log: [1] }).log.length === 1);
  check("pets: an unsettled battle's replay is untouched", pick({ ...b, wn: 2 }, { aWins: true }).aWins === true);
}

console.log(fails ? `\nFAILED: ${fails}` : "\nALL PASS — a pre-reroll game record is shown as paid, never redrawn");
process.exit(fails ? 1 : 0);
