/* Spending an amount that no single shielded banknote covers.
 *
 * WHY IT EXISTS. The wallet used to refuse with "No single banknote covers that amount yet (splitting
 * across banknotes isn't supported here)", and that described a real structural limit rather than a missing
 * convenience: joinsplit2.prove_transfer takes ONE input note (one value_in/rho_in, one nullifier) and emits
 * TWO outputs. The circuit can SPLIT a note and can never MERGE two, so there is no "consolidate first" move
 * to offer — a wallet that has accumulated change notes is simply stuck below its own balance. Three
 * receipts of 4 leave you unable to spend 5 while holding 12.
 *
 * With a 1-in circuit the only way out is several transfers, one proof per note. What matters then is
 * choosing the fewest notes (each proof is ~15s of on-device work) and being honest when a later proof
 * fails, because the earlier ones are already applied and irreversible.
 *
 * selectNotesFor is pure, so this runs with no DOM, no wallet and no chain.
 *
 * Run: node tests/test_shielded_note_selection.js
 */
"use strict";
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "static", "interface.js"), "utf8");

// Lift the pure helpers out of the wallet bundle rather than re-typing them — a copy in the test would
// happily keep passing after the real one changed, which is the failure mode this repo keeps hitting.
function lift(name) {
  const m = SRC.match(new RegExp("function " + name + "\\([\\s\\S]*?\\n\\}"));
  if (!m) throw new Error("could not find " + name + " in static/interface.js");
  return m[0];
}
const NOTES = [];
const ctx = {
  loadNotes: () => NOTES,
  BigInt,
};
const factory = new Function("loadNotes",
  lift("spendableNotes") + "\n" + lift("totalSpendable") + "\n" + lift("selectNotesFor") +
  "\nreturn { spendableNotes, totalSpendable, selectNotesFor };");
const A = factory(ctx.loadNotes);

let fails = 0;
function check(name, fn) {
  try { fn(); console.log("PASS  " + name); }
  catch (e) { fails++; console.log("FAIL  " + name + ": " + e.message); }
}
function eq(a, b, m) { if (a !== b) throw new Error((m || "") + " expected " + b + ", got " + a); }
function setNotes(vals) { NOTES.length = 0; vals.forEach((v, i) => NOTES.push({ value: String(v), cm: "cm" + i, spent: false })); }

check("a single covering note is chosen alone", () => {
  setNotes([10, 3, 2]);
  const p = A.selectNotesFor(7n);
  eq(p.length, 1, "one note suffices;");
  eq(p[0].value, "10");
});

check("THE BUG: an amount no single note covers is now spendable", () => {
  setNotes([4, 4, 4]);                       // holds 12, largest is 4
  const p = A.selectNotesFor(5n);
  if (!p) throw new Error("5 must be spendable from 4+4+4 — this is the whole point");
  eq(p.length, 2, "two notes cover 5;");
});

check("largest first, so the fewest proofs are run", () => {
  setNotes([1, 1, 9, 1, 5]);
  const p = A.selectNotesFor(13n);
  eq(p.length, 2, "9+5 covers 13, so two proofs — not five;");
  eq(p[0].value, "9");
  eq(p[1].value, "5");
});

check("it stops as soon as the amount is covered", () => {
  setNotes([8, 8, 8, 8]);
  eq(A.selectNotesFor(9n).length, 2, "9 needs two of the four;");
});

check("an exact total is spendable", () => {
  setNotes([3, 4]);
  eq(A.selectNotesFor(7n).length, 2);
});

check("one unit over the total is refused", () => {
  setNotes([3, 4]);
  eq(A.selectNotesFor(8n), null, "refuse rather than half-spend;");
});

check("spent notes are never selected", () => {
  setNotes([10, 10]);
  NOTES[0].spent = true;
  eq(A.selectNotesFor(15n), null, "only 10 is really available;");
  eq(A.selectNotesFor(9n).length, 1);
});

check("zero-value notes are ignored", () => {
  setNotes([0, 0, 5]);
  eq(A.spendableNotes().length, 1, "a 0-value note is not spendable;");
  eq(A.selectNotesFor(5n).length, 1);
});

check("an empty wallet refuses", () => {
  setNotes([]);
  eq(A.selectNotesFor(1n), null);
  eq(A.totalSpendable(), 0n);
});

check("totalSpendable is what the refusal message quotes", () => {
  setNotes([2, 3, 4]);
  eq(A.totalSpendable(), 9n);
});

// ---- the callers' failure semantics -------------------------------------------------------------------

check("a partial spend is reported, never claimed as success", () => {
  // Everything proved before a failure is already applied and irreversible. Reporting success would be a
  // lie, and dropping the earned claim codes would destroy value.
  for (const key of ["shield.partial", "shield.partialSend"]) {
    if (SRC.indexOf(key) === -1) throw new Error("missing partial-failure message " + key);
  }
  const send = SRC.slice(SRC.indexOf("async function doSendShielded"), SRC.indexOf("async function doReceiveShielded"));
  if (send.indexOf("if (codes.length)") === -1) throw new Error("codes earned before a failure must still be shown");
});

check("notes are re-read on every pass, not held stale", () => {
  // Each proof mutates stored notes (spent flag + change note); holding one array across a multi-minute
  // loop is how a change note gets dropped.
  const send = SRC.slice(SRC.indexOf("async function doSendShielded"), SRC.indexOf("async function doReceiveShielded"));
  const uns = SRC.slice(SRC.indexOf("async function doUnshield"), SRC.indexOf("async function doSendShielded"));
  for (const [nm, body] of [["send", send], ["unshield", uns]]) {
    if (body.indexOf("const notes = loadNotes();") === -1) throw new Error(nm + " must re-read notes inside the loop");
  }
});

check("every spent note yields its own claim code", () => {
  const send = SRC.slice(SRC.indexOf("async function doSendShielded"), SRC.indexOf("async function doReceiveShielded"));
  if (send.indexOf("codes.push(") === -1) throw new Error("one code per note spent");
  if (send.indexOf("codes.join(" ) === -1) throw new Error("all codes must be shown, not just the first");
});

check("delivery sends every code, not just the first", () => {
  const d = SRC.slice(SRC.indexOf("async function doDeliverZbill"), SRC.indexOf("async function doReceiveShielded"));
  if (d.indexOf("for (const c of codes)") === -1) throw new Error("delivery must loop over all codes");
});

check("the QR is dropped when one code cannot represent the payment", () => {
  const send = SRC.slice(SRC.indexOf("async function doSendShielded"), SRC.indexOf("async function doReceiveShielded"));
  if (send.indexOf("if (codes.length === 1) _drawQR") === -1)
    throw new Error("a single QR must not stand in for a multi-banknote payment");
});

console.log();
if (fails) { console.log(fails + " FAILURES"); process.exit(1); }
console.log("ALL PASS");
