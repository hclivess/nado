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
const m = SRC.match(/function autoVotePicks\(props, canPropose, submitted, allow\) \{[\s\S]*?\n\}/);
if (!m) { console.error("FAIL  could not find autoVotePicks in static/interface.js"); process.exit(1); }
const autoVotePicks = new Function(m[0] + "; return autoVotePicks;")();

let fails = 0;
function check(name, fn) {
  try { fn(); console.log("PASS  " + name); }
  catch (e) { fails++; console.log("FAIL  " + name + ": " + e.message); }
}
function eq(a, b, m) { if (a !== b) throw new Error((m || "") + " expected " + JSON.stringify(b) + ", got " + JSON.stringify(a)); }

const P = (pid, status, voted, recipient) => ({ pid, status, voted, recipient: recipient || "x",
                                                amount: 1, memo: "", nonce: 1, expiry: 9 });

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

check("an empty whitelist means any recipient", () => {
  const r = autoVotePicks([P("a", "open", false, "alice"), P("b", "open", false, "bob")], true, new Set(), []);
  eq(r.pick.length, 2);
});

check("a whitelist restricts to its recipients", () => {
  const props = [P("a", "open", false, "alice"), P("b", "open", false, "bob"), P("c", "open", false, "faucet")];
  const r = autoVotePicks(props, true, new Set(), ["alice", "faucet"]);
  eq(r.pick.length, 2);
  eq(r.pick.map(p => p.pid).join(","), "a,c");
});

check("whitelist matching is case-insensitive and trims", () => {
  const r = autoVotePicks([P("a", "open", false, "ABCdef")], true, new Set(), ["  abcDEF  "]);
  eq(r.pick.length, 1, "addresses differ only in case/whitespace; a mismatch here silently votes on nothing");
});

check("a whitelist that matches nothing votes on nothing", () => {
  const r = autoVotePicks([P("a", "open", false, "alice")], true, new Set(), ["mallory"]);
  eq(r.pick.length, 0);
  eq(r.reason, "");
});

check("the whitelist never overrides the voted flag", () => {
  // A deliberate NO stays in the voter set (weight 0), so `voted` is true — whitelisting the recipient
  // must not flip that vote back to yes.
  const r = autoVotePicks([P("a", "open", true, "alice")], true, new Set(), ["alice"]);
  eq(r.pick.length, 0);
});

check("the shipped default is ON but SCOPED to a recipient list", () => {
  // Shipping this ON means a wallet casts fee-bearing governance votes unattended. That is only defensible
  // while it is NARROW: a default of "approve every proposal" would hand a yes vote to whoever proposed
  // first. Pin both halves — enabled by default, AND a non-empty default recipient list.
  const en = SRC.match(/function autoVoteEnabled\(\)[\s\S]*?\n\}/);
  if (!en) throw new Error("autoVoteEnabled not found");
  const enabled = new Function("localStorage", en[0] + "; return autoVoteEnabled();");
  eq(enabled({ getItem: () => null }), true, "untouched wallet must default ON");
  eq(enabled({ getItem: () => "0" }), false, "an explicit off must stick");

  const dl = SRC.match(/const AUTO_VOTE_DEFAULT_ALLOW = \[[^\]]*\];/);
  if (!dl) throw new Error("AUTO_VOTE_DEFAULT_ALLOW not found");
  const def = new Function(dl[0] + "; return AUTO_VOTE_DEFAULT_ALLOW;")();
  if (!def.length) throw new Error("an ON-by-default auto-voter MUST be scoped — an empty default list approves everything");
  for (const a of def) if (!/^[0-9a-f]{40,64}$/.test(a)) throw new Error("default recipient is not an address: " + a);
});

check("an untouched wallet only approves the default recipients", () => {
  const al = SRC.match(/function autoVoteAllow\(\)[\s\S]*?\n\}/);
  const dl = SRC.match(/const AUTO_VOTE_DEFAULT_ALLOW = \[[^\]]*\];/);
  const kl = SRC.match(/const AUTO_VOTE_ALLOW_KEY = "[^"]+";/);
  if (!kl) throw new Error("AUTO_VOTE_ALLOW_KEY not found");
  // Lift the KEY too. Without it the snippet throws ReferenceError, autoVoteAllow's catch returns the
  // default, and the "cleared" case appears to pass for entirely the wrong reason.
  const mk = (raw) => new Function("localStorage",
    dl[0] + "\n" + kl[0] + "\n" + al[0] + "; return autoVoteAllow();")({ getItem: () => raw });
  const def = mk(null);
  if (!def.length) throw new Error("an untouched wallet must get the shipped list");
  // and that list must actually restrict: a proposal to someone else is not auto-approved
  const r = autoVotePicks([P("a", "open", false, "deadbeef" + "0".repeat(38))], true, new Set(), def);
  eq(r.pick.length, 0, "the default list must not approve an unrelated recipient");
  const r2 = autoVotePicks([P("b", "open", false, def[0])], true, new Set(), def);
  eq(r2.pick.length, 1, "the default list must approve its own recipient");
  eq(mk("").length, 0, "CLEARING the box means any recipient — an explicit user choice, not the default");
});

check("the recipient box is never persisted on blur alone", () => {
  // THE BUG THIS CAUGHT: `ta.onchange = ta.onblur = save` wrote "" the moment someone opened the tab and
  // clicked away, without editing anything. Since "" means "cleared -> approve any recipient", every wallet
  // that saw that build looked like a deliberate clear and could never receive the shipped default.
  // A textarea's `change` fires on blur only IF the value was edited; `blur` fires regardless.
  const body = SRC.slice(SRC.indexOf("function wireAutoVoteToggle"));
  const end = body.indexOf("\n}");
  const fn = body.slice(0, end);
  if (/\bta\.onblur\b/.test(fn)) throw new Error("must not persist the recipient list on blur — use change only");
  if (!/\bta\.onchange\b/.test(fn)) throw new Error("the recipient list must persist on change");
});

check("the allow-list key is versioned so accidental writes retire", () => {
  const k = SRC.match(/const AUTO_VOTE_ALLOW_KEY = "([^"]+)"/);
  if (!k) throw new Error("AUTO_VOTE_ALLOW_KEY not found");
  if (!/_v\d+$/.test(k[1])) throw new Error("the key must carry a version suffix: " + k[1]);
  // and nothing may still read the unversioned key, or the old poisoned value comes straight back
  if (SRC.indexOf('"nado_auto_vote_allow"') !== -1) throw new Error("the unversioned key is still read somewhere");
});

check("the UI discloses that it is on and what it votes for", () => {
  // A default that spends someone's fees and casts their governance vote must be visible in the UI, not
  // only in the code. This is the check that stops it from quietly becoming silent.
  const html = fs.readFileSync(path.join(__dirname, "..", "static", "interface.html"), "utf8");
  const i = html.indexOf("quorum.autoYesSub");
  if (i < 0) throw new Error("the auto-vote description is missing from interface.html");
  const txt = html.slice(i, html.indexOf("</span>", i)).toLowerCase();
  for (const phrase of ["on by default", "fee", "switch this off"]) {
    if (txt.indexOf(phrase) === -1) throw new Error('the description must say "' + phrase + '"');
  }
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
