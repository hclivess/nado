/*
 * test_an_invited_builder_who_taps_before_the_answer_is_told_it_is_checking_not_that_the_plot_is_someone_elses.mjs —
 * playtest 2026-11-15: the agent, invited to build on the operator's plot 0·4999·3438, tapped Place a few seconds after
 * arriving and was told "Plot 0·4999·3438 belongs to someone else" — the server says may_build: true, but the page's
 * builder check had not answered yet. land.js explainNoBuild now says "Checking whether you may build…" and asks at once
 * until that answer is in; once it is in (or the ask failed) the plot's real state is said, never stuck on "checking".
 * The page's own builderCheck and explainNoBuild run here against a stand-in server.
 * Run: node tests/test_an_invited_builder_who_taps_before_the_answer_is_told_it_is_checking_not_that_the_plot_is_someone_elses.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const cut = (a, b) => { const i = page.indexOf(a); return page.slice(i, page.indexOf(b, i)); };
const src = cut("async function builderCheck(plot) {", "\n// ---- THE MAP") + "\n" + cut("function explainNoBuild(plot) {", "\nfunction save()");
ok(/const builderKnown = new Set\(\);/.test(page), "the page keeps which plots' builder answer is in");

function world(answer) {
  const said = [], asked = [];
  const env = {
    net: { me: "3fd1b6", online: true }, mine: new Set(), builds: new Set(), builderKnown: new Set(),
    titles: new Map([[40955246, {}]]), hud() {}, notify: (m) => said.push(m), plotLabel: () => "0·4999·3438", disp: (a) => a,
    rawToNado: (x) => x, T: (k, d, o) => d.replace(/\{(\w+)\}/g, (_, n) => o[n]), signInNotice() {},
    ISSUER: "3cc4c44a94a900f79716dc6d3822a81603b1ce7862ce03572f",   // (the town's own plots are named, not addressed)
    fetch: async (u) => { asked.push(u); if (answer === "fail") throw new Error("offline"); return { json: async () => answer }; },
  };
  const f = new Function(...Object.keys(env), src + "\nreturn { builderCheck, explainNoBuild };")(...Object.values(env));
  return { ...f, env, said, asked };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

{ // invited: tapping before the answer says checking and asks; after it, the plot is theirs to build on
  const w = world({ may_build: true });
  ok(w.explainNoBuild(40955246) === false, "a refusal before the answer still refuses this tap");
  ok(/^Checking whether you may build on plot 0·4999·3438/.test(w.said[0]) && !/someone else/.test(w.said[0]), "…and says it is checking — not that the plot belongs to someone else");
  ok(w.asked.length === 1 && w.asked[0] === "/land/api/plot?plot=40955246", "…and asks the server at once");
  await tick(); await tick();
  ok(w.env.builds.has(40955246) && w.env.builderKnown.has(40955246), "the answer comes in: the invited player may build there");
}
{ // not invited: once the answer is in, the plain refusal comes back
  const w = world({ may_build: false });
  w.explainNoBuild(40955246); await tick(); await tick();
  w.explainNoBuild(40955246);
  ok(/belongs to someone else/.test(w.said[1]) && w.asked.length === 1, "not invited: after the answer the refusal says the plot is someone else's, without asking again");
}
{ // the ask fails: never stuck on "checking"
  const w = world("fail");
  w.explainNoBuild(40955246); await tick(); await tick();
  w.explainNoBuild(40955246);
  ok(/belongs to someone else/.test(w.said[1]), "a failed ask ends the \"checking\" — the next refusal says the plot's state");
}
{ // the aim line: "checking whether you may build here" until the answer is in, and it asks about the plot aimed at
  const ny = cut("const notYours = (what, plot) => {", "\n  if (a.box) {");
  const w = world({ may_build: true }), e = w.env;
  const f = new Function("net", "mine", "titles", "builderKnown", "builderCheck", "T", "rawToNado", "disp", ny + "\nreturn notYours;")(e.net, e.mine, e.titles, e.builderKnown, w.builderCheck, e.T, e.rawToNado, e.disp);
  ok(f("Grass", 40955246) === "Grass · Titled — checking whether you may build here" && w.asked.length === 1, "the aim line says it is checking — not \"not yours to gather here\" — and asks");
  f("Grass", 40955246);
  ok(w.asked.length === 1, "…once a refresh, not every frame");
  await tick(); await tick();
  const n = world({ may_build: false }); n.env.builderKnown.add(40955246);
  const g = new Function("net", "mine", "titles", "builderKnown", "builderCheck", "T", "rawToNado", "disp", ny + "\nreturn notYours;")(n.env.net, n.env.mine, n.env.titles, n.env.builderKnown, n.builderCheck, n.env.T, n.env.rawToNado, n.env.disp);
  ok(g("Grass", 40955246) === "Grass · Titled — not yours to gather here", "once the answer is in and it is no, the line says not yours");
}
ok(Object.keys(I).length === 17 && Object.values(I).every((t) => typeof t["land.checkingBuild"] === "string" && t["land.checkingBuild"].includes("{p}") && typeof t["land.v.checking"] === "string" && t["land.v.checking"].length > 5), "the checking messages are in all 17 languages, the refusal naming the plot");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
