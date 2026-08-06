/* Auto-vote-yes: the fee-safety rules.
 *
 * The feature votes yes on open treasury proposals unattended. Every vote costs a fee and approves real
 * treasury money, and renderQuorum re-runs on several timers — so the ONLY way this quietly hurts someone
 * is by submitting the same vote over and over. These checks pin the rules that stop that.
 *
 * autoVotePicks is pure precisely so this can run with no DOM, no wallet and no chain.
 *
 * Run: node tests/test_auto_vote_yes.js
 */
"use strict";
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "static", "interface.js"), "utf8");

// Lift the pure function out of the wallet bundle rather than re-typing it — a copy in the test would
// happily keep passing after the real one changed, which is the failure mode this repo keeps hitting.
const m = SRC.match(/function autoVotePicks\(props, canPropose, submitted\) \{[\s\S]*?\n\}/);
if (!m) { console.error("FAIL  could not find autoVotePicks in static/interface.js"); process.exit(1); }
const autoVotePicks = new Function(m[0] + "; return autoVotePicks;")();

let fails = 0;
function check(name, fn) {
  try { fn(); console.log("PASS  " + name); }
  catch (e) { fails++; console.log("FAIL  " + name + ": " + e.message); }
}
function eq(a, b, m) { if (a !== b) throw new Error((m || "") + " expected " + JSON.stringify(b) + ", got " + JSON.stringify(a)); }

const P = (pid, status, voted) => ({ pid, status, voted, recipient: "x", amount: 1, memo: "", nonce: 1, expiry: 9 });

check("picks open proposals we have not voted on", () => {
  const r = autoVotePicks([P("a", "open", false), P("b", "open", false)], true, new Set());
  eq(r.reason, "");
  eq(r.pick.length, 2);
});

check("never re-votes something already voted on chain", () => {
  const r = autoVotePicks([P("a", "open", true), P("b", "open", false)], true, new Set());
  eq(r.pick.length, 1);
  eq(r.pick[0].pid, "b");
});

check("never re-votes something submitted this session", () => {
  // A vote takes a few blocks to confirm, so the next refresh still sees voted=false. Without this the
  // wallet pays the fee again on every timer tick until the block lands.
  const r = autoVotePicks([P("a", "open", false)], true, new Set(["a"]));
  eq(r.pick.length, 0);
});

check("ignores proposals that are not open", () => {
  const r = autoVotePicks([P("a", "passed", false), P("b", "executed", false)], true, new Set());
  eq(r.pick.length, 0, "passed/executed proposals must never be voted on");
});

check("refuses entirely when the node omits the voted flag", () => {
  // The dangerous case: without ground truth, voting is a silent fee loop (a re-vote overwrites, so
  // nothing visibly breaks). Refusing is the only safe answer.
  const r = autoVotePicks([P("a", "open", undefined)], true, new Set());
  eq(r.reason, "no_voted_flag");
  eq(r.pick.length, 0);
});

check("one stale proposal disables the whole batch, not just itself", () => {
  const r = autoVotePicks([P("a", "open", false), P("b", "open", undefined)], true, new Set());
  eq(r.reason, "no_voted_flag");
  eq(r.pick.length, 0);
});

check("does nothing when the wallet cannot vote", () => {
  const r = autoVotePicks([P("a", "open", false)], false, new Set());
  eq(r.reason, "ineligible");
  eq(r.pick.length, 0);
});

check("handles an empty or missing proposal list", () => {
  eq(autoVotePicks([], true, new Set()).pick.length, 0);
  eq(autoVotePicks(null, true, new Set()).pick.length, 0);
  eq(autoVotePicks(undefined, true, new Set()).pick.length, 0);
});

check("it is OFF by default in the markup", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "static", "interface.html"), "utf8");
  const i = html.indexOf('id="qAutoYes"');
  if (i < 0) throw new Error("the qAutoYes toggle is missing from interface.html");
  const tag = html.slice(html.lastIndexOf("<", i), html.indexOf(">", i));
  if (/checked/.test(tag)) throw new Error("auto-vote must not be checked in the markup — it approves treasury spends unattended");
});

check("it never executes a payout", () => {
  // Voting is reversible-ish (a re-vote overwrites); EXECUTING moves the money and is not. The auto path
  // must only ever construct treasury_vote.
  const body = SRC.slice(SRC.indexOf("async function autoVoteYes"), SRC.indexOf("function wireAutoVoteToggle"));
  if (body.indexOf("treasury_execute") !== -1) throw new Error("the auto-voter must never execute a payout");
  if (body.indexOf('"yes"') === -1) throw new Error("the auto-voter should be voting yes");
});

console.log();
if (fails) { console.log(fails + " FAILURES"); process.exit(1); }
console.log("ALL PASS");
