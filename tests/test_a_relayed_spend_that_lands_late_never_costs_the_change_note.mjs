/* A relayed Stwo spend that lands late never costs the wallet its change note, and never leaves a spent note counted.
 *
 * Pre-push review 2026-10-12 (stwo-on). REPRODUCES (FAILS on 941a93f7):
 * a private Stwo payment is published by a RELAY node (_onDeviceProveStwo -> /stwo/relay). The wallet marks the input
 * spent, banks the change note (rho r2 is random and lives ONLY in this note) and waits for an output commitment to
 * appear. reconcileSpentNotes restores the input and DELETES the change once SPEND_LAND_GRACE_MS (20 min) passes with no
 * output in the tree — by the clock alone, never asking whether the input's nullifier is spent
 * (/exec/stwo_nullifiers, which the restore path already reads). But the relay holds a valid bundle for far longer than
 * 20 min: a Stwo spend may anchor to any block-closing root of the last ANCHOR_BLOCKS = 1024 blocks (~1.9 h at 6.8 s;
 * execnode/shielded_stwo.py knows_root). So a relay that answers ok and publishes at minute 21 (malicious, or simply an
 * exec tail stalled for 20 min) lands the payment AFTER the wallet has:
 *   - thrown the change note away — its value is now unrecoverable (change "cannot be found from the chain"), and
 *   - put the spent input back in the balance — every later spend of it is refused as a double spend.
 * Before the relay, the account published its own spend, so no third party chose when it landed.
 *
 * reconcileSpentNotes is RUN from static/interface.js with the exec node stubbed; no key is involved.
 *
 * Run: node tests/test_a_relayed_spend_that_lands_late_never_costs_the_change_note.mjs
 */
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(HERE, "..", "static", "interface.js"), "utf8");
function fnSrc(name, isAsync = false) {
  const i = SRC.indexOf((isAsync ? "async function " : "function ") + name + "(");
  if (i === -1) throw new Error(name + " not found in interface.js");
  let depth = 0, j = SRC.indexOf("{", SRC.indexOf(")", i));
  for (; j < SRC.length; j++) { if (SRC[j] === "{") depth++; else if (SRC[j] === "}" && --depth === 0) break; }
  return SRC.slice(i, j + 1);
}
const constSrc = (name) => { const m = SRC.match(new RegExp("const " + name + " = [^;]+;")); if (!m) throw new Error(name); return m[0]; };
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

const h = (c) => c.repeat(64);
const IN = h("a"), OUT1 = h("b"), CHANGE = h("c");
let stored = [
  // the input: spent through a relay at t0, waiting for OUT1 / CHANGE to land
  { value: "1000", rho: "7", cm: IN, spent: true, spentAt: 0, spentOuts: [OUT1, CHANGE], ts: 0 },
  // the change note the spend made (value 990 - the relay fee already out); its rho exists nowhere else
  { value: "600", rho: "99", cm: CHANGE, spent: false, ts: 0 },
];
const tree = { leaves: [IN] };
let now = 0;
const env = {
  loadNotes: () => stored.map((n) => ({ ...n, spentOuts: n.spentOuts && [...n.spentOuts] })),
  saveNotes: (ns) => { stored = ns.map((n) => ({ ...n })); },
  execJSON: async (p) => (p === "/exec/field_leaves" ? { leaves: [...tree.leaves] } : {}),
  log: () => {}, i18: (k, fb) => fb,
  Date: { now: () => now },
};
const reconcile = new Function(...Object.keys(env),
  constSrc("SPEND_LAND_GRACE_MS") + "\n" + fnSrc("reconcileSpentNotes", true) + "\nreturn reconcileSpentNotes;")(...Object.values(env));

now = 21 * 60 * 1000;                 // the relay has said ok, and holds the bundle past the grace window
await reconcile();
tree.leaves.push(OUT1, CHANGE);        // ...then publishes it (its anchor is still within ANCHOR_BLOCKS): the spend lands
now += 60 * 1000;
await reconcile();

const change = stored.find((n) => n.cm === CHANGE);
const input = stored.find((n) => n.cm === IN);
check("the change note of a spend that landed is still in the wallet", !!change && !change.spent,
      "the change note (600 raw) was deleted at the 20-minute mark; the spend then landed and its value is unrecoverable");
check("an input whose spend landed is not counted as spendable", !!input && input.spent,
      "the spent input (1000 raw) is back in the balance; every spend of it is refused as a double spend");
console.log(fails ? `${fails} FAILURES` : "ALL PASS — a relayed spend that lands late never costs the change note");
process.exit(fails ? 1 : 0);
