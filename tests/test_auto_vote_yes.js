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
const m = SRC.match(/function autoVotePicks\(props, canPropose, submitted, allow, mode = "list"\) \{[\s\S]*?\n\}/);
if (!m) { console.error("FAIL  could not find autoVotePicks in static/interface.js"); process.exit(1); }
const autoVotePicks = new Function(m[0] + "; return autoVotePicks;")();

let fails = 0;
function check(name, fn) {
  try { fn(); console.log("PASS  " + name); }
  catch (e) { fails++; console.log("FAIL  " + name + ": " + e.message); }
}
function eq(a, b, m) { if (a !== b) throw new Error((m || "") + " expected " + JSON.stringify(b) + ", got " + JSON.stringify(a)); }

const P = (pid, status, voted, recipient) => ({ pid, status, voted, recipient: recipient || "x",
// (the rules below are the mode-independent ones — already voted, already sent, not open — checked in "all", where no
// recipient list narrows the pick)
                                                amount: 1, memo: "", nonce: 1, expiry: 9 });

check("picks open proposals we have not voted on", () => {
  const r = autoVotePicks([P("a", "open", false), P("b", "open", false)], true, new Set(), [], "all");
  eq(r.reason, "");
  eq(r.pick.length, 2);
});

check("never re-votes something already voted on chain", () => {
  const r = autoVotePicks([P("a", "open", true), P("b", "open", false)], true, new Set(), [], "all");
  eq(r.pick.length, 1);
  eq(r.pick[0].pid, "b");
});

check("never re-votes something submitted this session", () => {
  // A vote takes a few blocks to confirm, so the next refresh still sees voted=false. Without this the
  // wallet pays the fee again on every timer tick until the block lands.
  const r = autoVotePicks([P("a", "open", false)], true, new Set(["a"]), [], "all");
  eq(r.pick.length, 0);
});

check("ignores proposals that are not open", () => {
  const r = autoVotePicks([P("a", "passed", false), P("b", "executed", false)], true, new Set(), [], "all");
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

// THREE MODES (operator 2026-11-21: "people will probably abuse this ... auto vote on whitelisted / auto vote on all / no
// auto vote"): an empty list meant "everyone" until "all" became its own choice — one stray delete away from voting yes
// on every proposal, now once a minute from every tab
check("in the whitelisted mode an EMPTY list approves no one", () => {
  const r = autoVotePicks([P("a", "open", false, "alice"), P("b", "open", false, "bob")], true, new Set(), [], "list");
  eq(r.pick.length, 0);
  eq(autoVotePicks([P("a", "open", false, "alice")], true, new Set(), []).pick.length, 0, "and the whitelisted mode is the default");
});
check("\"every proposal\" approves every open one not yet voted on, whatever the list says", () => {
  const r = autoVotePicks([P("a", "open", false, "alice"), P("b", "open", false, "bob"), P("c", "open", true, "carol")], true, new Set(), ["alice"], "all");
  eq(r.pick.map(p => p.pid).join(","), "a,b");
});
check("\"off\" approves nothing", () => {
  eq(autoVotePicks([P("a", "open", false, "alice")], true, new Set(), ["alice"], "off").pick.length, 0);
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
  const md = SRC.match(/const AUTO_VOTE_MODES = \[[^\]]*\];\nfunction autoVoteMode\(\) \{[\s\S]*?\n\}\nfunction autoVoteEnabled\(\) \{[^\n]*\}/);
  const kl0 = SRC.match(/const AUTO_VOTE_ALLOW_KEY = "[^"]+";/);
  if (!md || !kl0) throw new Error("autoVoteMode / autoVoteEnabled not found");
  const mode = (store) => new Function("localStorage", kl0[0] + "\n" + md[0] + "; return [autoVoteMode(), autoVoteEnabled()];")({ getItem: (k) => (k in store ? store[k] : null) });
  const ALLOW = kl0[0].match(/"([^"]+)"/)[1];
  eq(JSON.stringify(mode({})), JSON.stringify(["list", true]), "an untouched wallet must default to the whitelisted mode, ON");
  eq(mode({ nado_auto_vote_yes: "0" })[0], "off", "an explicit off from the old switch must stick");
  eq(mode({ [ALLOW]: "" })[0], "all", "a deliberately cleared list (which meant everyone) keeps meaning everyone, now as its own mode");
  eq(mode({ [ALLOW]: "abc" })[0], "list", "a wallet with its own list is in the whitelisted mode");
  eq(mode({ nado_auto_vote_mode: "off", [ALLOW]: "" })[0], "off", "a chosen mode wins over everything older");
  eq(mode({ nado_auto_vote_mode: "bogus" })[0], "list", "an unknown stored mode falls back to the default");

  const dl = SRC.match(/const AUTO_VOTE_DEFAULT_ALLOW = \[[^\]]*\];/);
  if (!dl) throw new Error("AUTO_VOTE_DEFAULT_ALLOW not found");
  const def = new Function(dl[0] + "; return AUTO_VOTE_DEFAULT_ALLOW;")();
  if (!def.length) throw new Error("an ON-by-default auto-voter MUST be scoped — an empty default list approves everything");
  // an address, or "faucet" — the one RESERVED recipient a treasury spend may pay (it cannot be claimed or redirected)
  for (const a of def) if (!/^[0-9a-f]{40,64}$/.test(a) && a !== "faucet") throw new Error("default recipient is not an address: " + a);
});

check("an untouched wallet only approves the default recipients", () => {
  const al = SRC.match(/function autoVoteAllow\(\)[\s\S]*?\n\}/);
  const dl = SRC.match(/const AUTO_VOTE_DEFAULT_ALLOW = \[[^\]]*\];/);
  const kl = SRC.match(/const AUTO_VOTE_ALLOW_KEY = "[^"]+";/);
  if (!kl) throw new Error("AUTO_VOTE_ALLOW_KEY not found");
  // Lift the KEY too. Without it the snippet throws ReferenceError, autoVoteAllow's catch returns the
  // default, and the "cleared" case appears to pass for entirely the wrong reason.
  // ...and the earlier shipped defaults: without them the upgrade check throws, the catch returns the default, and a
  // CLEARED list reads as the default (this test failed that way from the day "faucet" joined the default until 2026-09-28)
  const pl = SRC.match(/const AUTO_VOTE_PREV_DEFAULTS = \[[\s\S]*?\]\];/);
  if (!pl) throw new Error("AUTO_VOTE_PREV_DEFAULTS not found");
  const mk = (raw) => new Function("localStorage",
    dl[0] + "\n" + kl[0] + "\n" + pl[0] + "\n" + al[0] + "; return autoVoteAllow();")({ getItem: () => raw });
  const def = mk(null);
  if (!def.length) throw new Error("an untouched wallet must get the shipped list");
  // and that list must actually restrict: a proposal to someone else is not auto-approved
  const r = autoVotePicks([P("a", "open", false, "deadbeef" + "0".repeat(38))], true, new Set(), def);
  eq(r.pick.length, 0, "the default list must not approve an unrelated recipient");
  const r2 = autoVotePicks([P("b", "open", false, def[0])], true, new Set(), def);
  eq(r2.pick.length, 1, "the default list must approve its own recipient");
  eq(mk("").length, 0, "a CLEARED box is no recipients (autoVoteMode reads a wallet's old cleared box as \"all\")");
  // every earlier shipped default follows forward — the gen-27 one named the operator's OLD address, which matches no
  // proposal on a format-2 chain — while a list the user edited stays exactly as stored
  const prevs = new Function(pl[0] + "; return AUTO_VOTE_PREV_DEFAULTS;")();
  for (const prev of prevs) eq(JSON.stringify(mk(prev.join(","))), JSON.stringify(def), "a never-customised earlier default follows forward");
  eq(JSON.stringify(mk("deadbeef" + "0".repeat(38))), JSON.stringify(["deadbeef" + "0".repeat(38)]), "a customised list is kept");
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
  const i = html.indexOf("quorum.autoModeSub");
  if (i < 0) throw new Error("the auto-vote description is missing from interface.html");
  const txt = html.slice(i, html.indexOf("</span>", i)).toLowerCase();
  for (const phrase of ["on by default", "fee", "switch this off", "once a minute"]) {
    if (txt.indexOf(phrase) === -1) throw new Error('the description must say "' + phrase + '"');
  }
  // the three modes, as one choice, the whitelisted one first (and the default the code reads)
  const sel = html.slice(html.indexOf('<select id="qAutoMode"'), html.indexOf("</select>", html.indexOf('<select id="qAutoMode"')));
  const vals = [...sel.matchAll(/<option value="([a-z]+)"/g)].map((m) => m[1]).join(",");
  eq(vals, "list,all,off", "the mode choice offers whitelisted, every proposal and off, in that order");
  const ls = html.slice(html.indexOf("quorum.autoModeListSub"), html.indexOf("</span>", html.indexOf("quorum.autoModeListSub"))).toLowerCase();
  if (ls.indexOf("empty list approves no one") === -1) throw new Error("the recipient box must say an empty list approves no one");
});

check("it never executes a payout", () => {
  // Voting is reversible-ish (a re-vote overwrites); EXECUTING moves the money and is not. The auto path
  // must only ever construct treasury_vote.
  const body = SRC.slice(SRC.indexOf("async function autoVoteYes"), SRC.indexOf("function wireAutoVoteToggle"));
  if (body.indexOf("treasury_execute") !== -1) throw new Error("the auto-voter must never execute a payout");
  if (body.indexOf('"yes"') === -1) throw new Error("the auto-voter should be voting yes");
});

console.log();
// ---- FROM EVERY TAB, ON A TIMER (operator 2026-11-21: "default tab and all other tabs should also check periodically and
// vote ... unless of course an address was removed from the whitelist"). The real autoVoteTick, lifted, against stubs.
const tm = SRC.match(/const AUTO_VOTE_EVERY_MS = (\d+);\nlet _autoVoteAt = 0;\nasync function autoVoteTick\(now = Date\.now\(\)\) \{[\s\S]*?\n\}/);
check("the wallet's poll asks for auto-votes on every pass, whatever tab is open", () => {
  const poll = SRC.slice(SRC.indexOf("async function pollOnce() {"), SRC.indexOf("async function pollOnce() {") + 1200);
  if (!poll.includes("autoVoteTick().catch(() => {});")) throw new Error("pollOnce does not call autoVoteTick");
  if (!tm) throw new Error("autoVoteTick not found");
});
function tickWorld({ bonded, enabled = true, allow = ["me", "faucet"] }) {
  const w = { asked: [], voted: [], fetched: 0 };
  const env = {
    state: { wallet: { address: "W" } }, _autoVoting: false, B_MIN_RAW: 10n,
    autoVoteEnabled: () => enabled, relayBase: () => "",
    getAccount: async () => ({ bonded: String(bonded) }),
    fetch: async (u) => { w.fetched++; w.asked.push(u); return { json: async () => ({ proposals: [P("p1", "open", false, "me"), P("p2", "open", false, "stranger")] }) }; },
    autoVoteYes: async (props, can) => { w.voted.push(autoVotePicks(props, can, new Set(), allow).pick.map((x) => x.pid)); },
  };
  const f = new Function(...Object.keys(env), tm[0] + "; return autoVoteTick;")(...Object.values(env));
  return { w, f };
}
(async () => {
  const a = tickWorld({ bonded: 50 });
  await a.f(1_000_000); await a.f(1_030_000); await a.f(1_061_000);
  check("…once a minute: three polls in 61 s ask twice", () => eq(a.w.fetched, 2));
  check("…with this wallet's own vote state (the node's `voted` flag)", () => eq(a.w.asked[0], "/treasury_status?address=W"));
  check("…and votes only the allow-listed recipient", () => eq(JSON.stringify(a.w.voted[0]), JSON.stringify(["p1"])));
  const r = tickWorld({ bonded: 50, allow: ["faucet"] });
  await r.f(2_000_000);
  check("an address taken off the allow-list gets no vote on the next pass", () => eq(JSON.stringify(r.w.voted[0]), "[]"));
  const u = tickWorld({ bonded: 5 });
  await u.f(3_000_000);
  check("an unbonded wallet (no vote would count) asks nothing further", () => eq(u.w.fetched, 0));
  const off = tickWorld({ bonded: 50, enabled: false });
  await off.f(4_000_000);
  check("switched off, it does nothing", () => eq(off.w.fetched + off.w.voted.length, 0));
  console.log(fails ? fails + " FAILED" : "ALL PASS");
  process.exit(fails ? 1 : 0);
})();
