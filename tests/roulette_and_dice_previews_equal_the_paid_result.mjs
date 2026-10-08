/*
 * The roulette and dice pages PREVIEW a seat's result before anyone settles it (the wheel, "won — collect", the
 * auto-collect that fires on a previewed win). That preview must be the number the contract will PAY on, for a
 * beacon seat (gb != 0: HASH(BEACON(gb) + seat id)) and for a legacy seat (gb == 0: HASH(BHASH(gh) + BHASH(gh+1) +
 * seat id)). roulette.js once salted its preview with the TABLE id while the contract salts with the SEAT id, so
 * the page showed one number and the chain paid another.
 *
 * This drives the REAL code: it evaluates the `spinOf` / `rollOf` definitions taken verbatim from
 * static/roulette.js and static/dice.js, with the real chainResultAlg from static/nadodapp.js, against results the
 * Python driver read back out of the contract after settle ran on an ExecState.
 *
 * Run (via the driver):  python3 tests/test_roulette_and_dice_previews_equal_the_paid_result.py
 */
import { readFileSync } from "node:fs";

// nadodapp.js touches a few browser globals at import time
const store = new Map();
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
globalThis.location = { search: "", pathname: "/", hash: "", href: "http://x/", origin: "http://x" };
globalThis.history = { replaceState() {} };
globalThis.document = { getElementById: () => null, createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, appendChild() {}, remove() {}, setAttribute() {} }),
  body: { appendChild() {} }, documentElement: { appendChild() {} }, addEventListener() {}, querySelectorAll: () => [] };
globalThis.window = globalThis;
globalThis.addEventListener = () => {};
globalThis.fetch = async () => ({ ok: false, json: async () => ({}) });

const { chainResultAlg } = await import(new URL("../static/nadodapp.js", import.meta.url).href);

/** the page's own preview function, lifted verbatim from its source (one `const name = (s, g) => …;` line) */
function pageFn(file, name) {
  const src = readFileSync(new URL("../static/" + file, import.meta.url), "utf8");
  const m = src.match(new RegExp("^const " + name + " = (\\(s, g\\) => .*);$", "m"));
  if (!m) throw new Error(`${file}: no one-line \`const ${name} = (s, g) => …;\` to evaluate`);
  return (dapp, PN) => new Function("chainResultAlg", "dapp", "PN", "return " + m[1])(chainResultAlg, dapp, PN);
}

let body = "";
for await (const chunk of process.stdin) body += chunk;
const V = JSON.parse(body);

let fails = 0, n = 0;
const eq = (name, got, want) => { n++; const good = String(got) === String(want); if (!good) fails++; console.log(`${good ? "PASS" : "FAIL"}  ${name}${good ? "" : `: got ${got} want ${want}`}`); };

for (const [game, file, name, PN] of [["roulette", "roulette.js", "spinOf", 37], ["dice", "dice.js", "rollOf", 100]]) {
  const vs = V[game];
  const dapp = { bc: (e) => vs.beacons[String(e)], bh: (h) => vs.hashes[String(h)] };
  const preview = pageFn(file, name)(dapp, PN);
  let tableSaltAgrees = 0;
  for (const s of vs.seats) {
    const kind = s.gb ? `beacon seat (gb ${s.gb})` : `legacy seat (gh ${s.gh})`;
    // the seat key arrives as a STRING (Object.keys over the storage map), exactly as on the page
    eq(`${game}: ${kind} #${s.g} preview == the result settle paid`, preview({ gb: s.gb, gh: s.gh }, String(s.g)), s.paid);
    const bySalt = s.gb ? chainResultAlg(vs.beacons[String(s.gb)], "0", s.table, PN)
                        : chainResultAlg(vs.hashes[String(s.gh)], vs.hashes[String(s.gh + 1)], s.table, PN);
    if (bySalt === s.paid) tableSaltAgrees++;
  }
  // teeth: the old table-id salt would have previewed the wrong number on most of these seats
  eq(`${game}: a table-id salt disagrees with the paid result on most seats (${tableSaltAgrees}/${vs.seats.length} agree)`,
     tableSaltAgrees * 2 < vs.seats.length, true);
}
console.log(fails ? `${fails}/${n} CHECKS FAILED` : `ALL ${n} PREVIEW == PAID CHECKS PASS`);
process.exit(fails ? 1 : 0);
