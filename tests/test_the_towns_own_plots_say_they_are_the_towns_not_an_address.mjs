/*
 * test_the_towns_own_plots_say_they_are_the_towns_not_an_address.mjs — playtest 2026-11-16, a new visitor's first
 * screen on a phone: over the town square the HUD said "Owned by 3cc4c4…3572f". The four town plots are held by the land
 * issuer itself (measured: /exec/assets?issuer=…&holder=… lists exactly 0·4999·3439, 0·4999·3440, 0·5000·3439,
 * 0·5000·3440), whose address means nothing to a player. land.js ownedBy says "Owned by the town" for the issuer
 * (land.ownedTown, 17 languages) and "Owned by …" with the holder for anyone else; every place that names an owner — the
 * HUD's two pills and the aim line — goes through it. The page's ownedBy runs here.
 * Run: node tests/test_the_towns_own_plots_say_they_are_the_towns_not_an_address.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const lang = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const issuerLine = page.split("\n").find((l) => l.startsWith("const ISSUER = ")), ownedLine = page.split("\n").find((l) => l.startsWith("const ownedBy = "));
ok(!!issuerLine && !!ownedLine, "(the page's issuer and ownedBy)");
const T = (k, d, a = {}) => d.replace(/\{(\w+)\}/g, (_, n) => a[n]);
const disp = (a) => a.slice(0, 6) + "…" + a.slice(-5);
const { ISSUER, ownedBy } = new Function("T", "disp", issuerLine + "\n" + ownedLine + "\nreturn { ISSUER, ownedBy };")(T, disp);
ok(ownedBy(ISSUER) === "Owned by the town", `the town's own plots: "${ownedBy(ISSUER)}"`);
const someone = "b7a08de8351e3af97f6f2bbcb19f2a8c722abad81c3460caf9";
ok(ownedBy(someone) === "Owned by " + disp(someone), `anyone else's: "${ownedBy(someone)}"`);
ok(!/T\("owned", "Owned by \{o\}"/.test(page.replace(ownedLine, "")), "every place that names an owner goes through ownedBy (the HUD's pills and the aim line)");
ok((page.match(/ownedBy\(t\.holder\)/g) || []).length === 3, "…all three of them");
ok(Object.values(lang).every((t) => typeof t["land.ownedTown"] === "string" && t["land.ownedTown"].length > 2 && !/\{/.test(t["land.ownedTown"])), "the phrase is in all 17 languages");
{ // tapping to build there says the same: the town's, by name — not "is owned by 3cc4c4…, ask them to invite you"
  const e0 = page.indexOf("function explainNoBuild(plot) {"), src = page.slice(e0, page.indexOf("\n}\n", e0) + 2);
  const said = [];
  const run = (holder) => { said.length = 0; new Function("titles", "net", "mine", "builderKnown", "builderCheck", "notify", "signInNotice", "T", "plotLabel", "disp", "rawToNado", "ISSUER", src + "\nexplainNoBuild(7);")(
    new Map([[7, { holder }]]), { me: "x", online: true }, new Set(), new Set([7]), () => {}, (x) => said.push(x), () => {}, T, () => "0·1·2", disp, String, ISSUER); return said[0]; };
  ok(run(ISSUER) === "Plot 0·1·2 belongs to the town — gather and build on open land, or on a plot of your own.", `tapping to build on the town's plot: "${run(ISSUER)}"`);
  ok(run(someone) === "Plot 0·1·2 is owned by " + disp(someone) + " — ask them to invite you to build here.", "…on anyone else's: whose it is, and to ask them");
  ok(Object.values(lang).every((t) => typeof t["land.notYoursTown"] === "string" && t["land.notYoursTown"].includes("{p}")), "…in all 17 languages, the plot kept");
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
