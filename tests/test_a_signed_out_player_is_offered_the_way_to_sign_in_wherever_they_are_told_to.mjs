/*
 * test_a_signed_out_player_is_offered_the_way_to_sign_in_wherever_they_are_told_to.mjs — playtest 2026-11-15, a
 * signed-out visitor on the phone layout: the Bag said "Sign in to gather, make things and trade." with nothing to tap,
 * and Use on Maren said "Sign in first." and nothing more — the only sign-in link was the HUD's, behind the panel. The
 * signed-out Bag carries the HUD's link (/land/api/login, "Sign in to build", already in all 17 languages), and every
 * "sign in" notice is a bar with that button (signInNotice); offline, the words alone. The page's own code runs here.
 * Run: node tests/test_a_signed_out_player_is_offered_the_way_to_sign_in_wherever_they_are_told_to.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const I = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const a = page.indexOf("  if (!net.me) { $(\"palGrid\").innerHTML = "), b = page.indexOf("return; }", a) + "return; }".length;
const run = (online) => { const el = { innerHTML: "" }; new Function("net", "$", "esc", "T", page.slice(a, b))({ me: null, online }, () => el, (x) => x, (k, d) => d); return el.innerHTML; };
ok(a > 0 && /Sign in to gather, make things and trade\./.test(run(true)) && /<a class="btn" href="\/land\/api\/login">Sign in to build<\/a>/.test(run(true)), "signed out, the Bag says to sign in and has the link to do it");
ok(!/api\/login/.test(run(false)), "…not while the world server cannot be reached");
ok(/const signIn = net\.online && !net\.me \? ` <a class="btn" href="\/land\/api\/login">\$\{esc\(T\("signInBuild", "Sign in to build"\)\)\}<\/a>` : "";/.test(page), "…the same link and words as the HUD's");
{ // the notice: a bar with the sign-in button, online; the words alone offline
  const i0 = page.indexOf("function signInNotice(msg) {"), src = page.slice(i0, page.indexOf("\n}\n", i0) + 2);
  const said = [], go = [];
  const sn = (online) => new Function("net", "notify", "alertBar", "T", "location", src + "\nreturn signInNotice;")(
    { online }, (m) => said.push(["notify", m]), (m, label, fn, o) => said.push(["bar", m, label, fn, o]), (k, d) => d, { assign: (u) => go.push(u) });
  sn(true)("Sign in first.");
  ok(said[0][0] === "bar" && said[0][1] === "Sign in first." && said[0][2] === "Sign in to build" && said[0][4].tone === "info", "online, \"Sign in first.\" comes with a Sign in to build button");
  said[0][3]();
  ok(go[0] === "/land/api/login", "…which goes where the HUD's link goes");
  sn(false)("Sign in first.");
  ok(said[1][0] === "notify" && said[1][1] === "Sign in first.", "offline, the words alone");
  const left = (page.match(/notify\(T\("signIn(First|Build2)", /g) || []).length, through = (page.match(/signInNotice\(T\("signIn(First|Build2)", /g) || []).length;
  ok(left === 0 && through >= 14, `every "sign in" notice goes through it (${through}; none left plain)`);
}
ok(Object.values(I).length === 17 && Object.values(I).every((t) => typeof t["land.signInBuild"] === "string" && typeof t["land.bagSignIn"] === "string"), "both strings are in all 17 languages");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
