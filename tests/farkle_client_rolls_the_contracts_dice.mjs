/*
 * The Farkle page's rollDice must be the contract's dice, die for die. Driven by
 * tests/test_farkle_client_rolls_the_contracts_dice.py, which supplies vectors from execnode.games.farkle.roll_dice
 * and from real contract rolls (the dice the VM wrote into its scratch slots).
 *
 * This evaluates the REAL page code: `function rollDice(...) { ... }` lifted verbatim from static/farkle.js, with
 * the real chainResultAlg from static/nadodapp.js. Negative control: the blake2b derivation the page used before
 * must DISAGREE with the contract, or this test has no teeth.
 */
import { readFileSync } from "node:fs";

const store = new Map();
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
globalThis.location = { search: "", pathname: "/", hash: "", href: "http://x/", origin: "http://x" };
globalThis.history = { replaceState() {} };
globalThis.document = { getElementById: () => null, createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, appendChild() {}, remove() {}, setAttribute() {} }),
  body: { appendChild() {} }, documentElement: { appendChild() {} }, addEventListener() {}, querySelectorAll: () => [] };
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.fetch = async () => ({ ok: false, json: async () => ({}) });

const { chainResultAlg, blake2bHash } = await import(new URL("../static/nadodapp.js", import.meta.url).href);

const src = readFileSync(new URL("../static/farkle.js", import.meta.url), "utf8");
const m = src.match(/^function rollDice\(seatId, grh, grn, diceLeft, aHex, bHex\) \{\n[\s\S]*?\n\}\n/m);
if (!m) { console.log("FAIL  static/farkle.js: no `function rollDice(seatId, grh, grn, diceLeft, aHex, bHex) {…}` to evaluate"); process.exit(1); }
// the derivation farkle.js shipped before 2026-10-10 — kept here ONLY as the negative control
const H = (v) => BigInt("0x" + blake2bHash(v));
// H is in scope too, so a page that regresses to the old blake2b `H` helper fails on the dice, not on a ReferenceError
const rollDice = new Function("chainResultAlg", "H", m[0] + "\nreturn rollDice;")(chainResultAlg, H);
const oldRoll = (seatId, grn, dl, a, b) => {
  const seed = BigInt("0x" + a) + BigInt("0x" + b) + BigInt(seatId) * 1000n + BigInt(grn) * 10n;
  return Array.from({ length: dl }, (_, p) => Number(H(seed + BigInt(p)) % 6n) + 1);
};

let body = "";
for await (const chunk of process.stdin) body += chunk;
const V = JSON.parse(body);

let fails = 0, n = 0;
const eq = (name, good, detail) => { n++; if (!good) fails++; if (!good || n <= 4) console.log(`${good ? "PASS" : "FAIL"}  ${name}${good ? "" : ": " + detail}`); };

for (const kind of ["reference", "contract"]) {
  let ok = 0, oldAgrees = 0;
  for (const v of V[kind]) {
    // the page passes the seat id as a STRING (Object.keys over storage) and the hashes as hex
    const got = rollDice(String(v.seat), 0, v.rolln, v.dl, v.a, v.b);
    const good = JSON.stringify(got) === JSON.stringify(v.dice);
    if (good) ok++;
    eq(`${kind}: seat ${v.seat} roll ${v.rolln} (${v.dl} dice) page == contract`, good, `page ${JSON.stringify(got)} contract ${JSON.stringify(v.dice)}`);
    if (JSON.stringify(oldRoll(v.seat, v.rolln, v.dl, v.a, v.b)) === JSON.stringify(v.dice)) oldAgrees++;
  }
  console.log(`${kind}: ${ok}/${V[kind].length} rolls equal`);
  eq(`${kind}: the old blake2b derivation disagrees with the contract on most rolls (${oldAgrees}/${V[kind].length} agree)`,
     oldAgrees * 4 < V[kind].length, `${oldAgrees} agree`);
}
eq("rollDice returns null until both block hashes exist", rollDice("5", 0, 0, 6, "ab", null) === null && rollDice("5", 0, 0, 6, undefined, "ab") === null, "not null");
console.log(fails ? `${fails}/${n} CHECKS FAILED` : `ALL ${n} FARKLE DICE CHECKS PASS`);
process.exit(fails ? 1 : 0);
