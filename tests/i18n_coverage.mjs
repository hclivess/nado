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
  for (const m of txt.matchAll(/(?<![\w.])(?:t|i18)\(\s*["']([a-zA-Z0-9_.\-]+)["']/g)) {
    const k = m[1];
    refs.add(prefix && !k.includes(".") ? prefix + k : k);
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
const undef_ = [...refs].filter((k) => !en.has(k) && !k.endsWith(".") && !k.endsWith("_") && !k.includes("${"));
if (undef_.length) { fails++; console.error(`FAIL: ${undef_.length} referenced key(s) in NO table (English-only fallbacks): ${undef_.slice(0, 10).join(", ")}`); }

if (fails) process.exit(1);
console.log(`OK: ${Object.keys(T).length} languages x ${en.size} keys, every referenced key defined`);
