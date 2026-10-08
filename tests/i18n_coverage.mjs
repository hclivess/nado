// i18n coverage guard — refuses the two ways the wallet has actually shipped untranslated text:
//   1. a language table missing keys that `en` has (partial translation);
//   2. a key referenced by interface.js / any HTML / any game JS that exists in NO table at all,
//      so every language silently renders the hardcoded English fallback (the 2026-07-21 audit found
//      129 of these: whole vault/allow/mine panels, the nodes table, history-log types, coat names).
// Dynamic-prefix call sites (t("hist.cp." + r)) surface as keys ending in "." or "_" — those are
// concatenation stubs, not keys, and each FAMILY MEMBER is guarded by being referenced elsewhere or
// covered here once someone references it literally.
// Run: node tests/i18n_coverage.mjs   (exits non-zero on any gap)
import fs from "fs";

let src = fs.readFileSync("static/i18n.js", "utf8")
  .replace("window.NADO_i18n = {", "window.NADO_i18n = { T: T, ");
global.window = {};
global.document = { readyState: "loading", addEventListener() {}, getElementById() { return null; },
  querySelector() { return null; },
  createElement() { return { style: {}, setAttribute() {}, addEventListener() {}, appendChild() {} }; } };
// node >= 21 exposes getter-only global `navigator`/`localStorage` in ESM — plain assignment throws
Object.defineProperty(global, "navigator", { value: { languages: ["en"] }, configurable: true });
Object.defineProperty(global, "localStorage", { value: { getItem() { return null; }, setItem() {} }, configurable: true });
eval(src);
const T = window.NADO_i18n.T;
const en = new Set(Object.keys(T.en));

let fails = 0;
for (const l of Object.keys(T)) {
  if (l === "en") continue;
  const missing = [...en].filter((k) => !(k in T[l]));
  if (missing.length) { fails++; console.error(`FAIL ${l}: ${missing.length} keys missing vs en, e.g. ${missing.slice(0, 5).join(", ")}`); }
}

const refs = new Set();
const collect = (txt, prefix) => {
  // window.t(…) is how every game client calls it: the lookbehind alone refused "window.t(", so no game JS key was ever
  // checked until the ternary case below exposed it
  // a literal followed by + is a key PREFIX ("poker.rank" + cat + "name"), not a key: (?!\s*\+) leaves it out
  for (const m of txt.matchAll(/(?<![\w.])(?:window\.)?(?:t|i18)\(\s*["']([a-zA-Z0-9_.\-]+)["'](?!\s*\+)/g)) {
    const k = m[1];
    refs.add(prefix && !k.includes(".") ? prefix + k : k);
  }
  // a key chosen by a ternary, t(cond ? "a.x" : "a.y", …): both branches are referenced (pets.critsFor / hitsFor
  // shipped untranslated in every language because only a literal first argument was read)
  for (const m of txt.matchAll(/(?<![\w.])(?:window\.)?(?:t|i18)\(\s*[^,()"']*\?\s*["']([a-zA-Z0-9_.\-]+)["']\s*:\s*["']([a-zA-Z0-9_.\-]+)["']/g)) {
    for (const k of [m[1], m[2]]) refs.add(prefix && !k.includes(".") ? prefix + k : k);
  }
  for (const m of txt.matchAll(/data-i18n(?:-ph|-title)?="([^"]+)"/g)) refs.add(m[1]);
};
for (const f of fs.readdirSync("static")) {
  if (f.endsWith(".html")) collect(fs.readFileSync("static/" + f, "utf8"), "");
  else if (f.endsWith(".js") && f !== "i18n.js") {
    const txt = fs.readFileSync("static/" + f, "utf8");
    if (!txt.includes("window.t")) continue;
    const pm = txt.match(/window\.t\(\s*"([a-z0-9]+)\." \+ /);   // per-file prefix wrapper (autogame., sdk., …)
    collect(txt, pm ? pm[1] + "." : "");
  }
}
// THE LOBBY TOO (website/apps.html, served at nadochain.com/apps with THIS i18n.js). It lives outside static/, so
// this guard never read it, and 61 of its keys — nav, hero, footer, the DEX/Lend/Pool/Sovereign/Scrapline/Hexholm/
// Stormhold entries — rendered English in every language until 2026-09-29. Its game keys are built at runtime
// ("games." + slug + ".name"), so they are derived here from the GAMES table itself: a new entry without its
// translations fails this test instead of shipping English to fifteen locales.
{
  const a = fs.readFileSync("website/apps.html", "utf8");
  collect(a, "");
  for (const m of a.matchAll(/(?<![\w.])T\(\s*"([a-zA-Z0-9_.\-]+)"/g)) refs.add(m[1]);
  let n = 0;
  for (const m of a.matchAll(/\{ svg:SVG\.\w+,([\s\S]*?)\] \},?\n/g)) {
    const b = m[1], slug = (b.match(/slug:"([^"]+)"/) || [])[1];
    if (!slug) continue;
    n++;
    refs.add(`games.${slug}.name`); refs.add(`games.${slug}.blurb`);
    const meta = b.match(/meta:\[([^\]]*)/);
    if (meta) JSON.parse("[" + meta[1] + "]").forEach((_, i) => refs.add(`games.${slug}.m${i}`));
    if (/kind:"(?!game")/.test(b)) refs.add(`apps.kind.${slug}`);
  }
  if (!n) { fails++; console.error("FAIL: parsed no entries out of website/apps.html GAMES — this guard's parser is stale"); }
}
const undef_ =[...refs].filter((k) => !en.has(k) && !k.endsWith(".") && !k.endsWith("_") && !k.includes("${"));
if (undef_.length) { fails++; console.error(`FAIL: ${undef_.length} referenced key(s) in NO table (English-only fallbacks): ${undef_.slice(0, process.env.ALL ? 999 : 10).join(", ")}`); }

if (fails) process.exit(1);
console.log(`OK: ${Object.keys(T).length} languages x ${en.size} keys, every referenced key defined`);
