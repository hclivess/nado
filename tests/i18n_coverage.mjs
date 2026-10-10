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
  // WRAPPER HELPERS, found by SHAPE rather than by name: a function whose body forwards its first parameter to
  // window.t, optionally behind a literal prefix — `const T = (k, d, v) => … window.t("sov." + k, d, v)`. The code
  // calls them as T( / _t( / TS( …, and this guard used to read only t( / i18( / window.t(, so seven keys
  // (sdk.connectWallet, sdk.hdrWalletIn/Out, sdk.howThisWorks, sdk.postedAlready, sov.allyActive/allySolo) — and
  // every other key behind such a wrapper — shipped English-only without a failure (found 2026-10-10). t / i18 keep
  // the per-file-prefix rule above.
  for (const w of wrappersIn(txt)) collectWrapped(txt, w.name, w.prefix);
};
const wrappersIn = (txt) => {
  const out = [];
  const shapes = [
    /(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\(\s*([A-Za-z_$][\w$]*)\s*(?:,[^)]*)?\)\s*=>[^\n]*?window\.t\(\s*(?:"([\w.\-]*)"\s*\+\s*)?\2\b(?!\s*\+)/g,
    /function\s+([A-Za-z_$][\w$]*)\s*\(\s*([A-Za-z_$][\w$]*)[^)]*\)\s*\{[^\n]*?window\.t\(\s*(?:"([\w.\-]*)"\s*\+\s*)?\2\b(?!\s*\+)/g,
  ];
  for (const re of shapes) for (const m of txt.matchAll(re)) if (m[1] !== "t" && m[1] !== "i18") out.push({ name: m[1], prefix: m[3] || "" });
  return out;
};
const collectWrapped = (txt, name, prefix) => {
  const n = name.replace(/[.$]/g, "\\$&");                        // "this.T" / "$t": literal, not regex
  for (const m of txt.matchAll(new RegExp(`(?<![\\w.$])${n}\\(\\s*["']([a-zA-Z0-9_.\\-]+)["'](?!\\s*\\+)`, "g"))) refs.add(prefix + m[1]);
  for (const m of txt.matchAll(new RegExp(`(?<![\\w.$])${n}\\(\\s*[^,()"']*\\?\\s*["']([a-zA-Z0-9_.\\-]+)["']\\s*:\\s*["']([a-zA-Z0-9_.\\-]+)["']`, "g")))
    for (const k of [m[1], m[2]]) refs.add(prefix + k);
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
// duelgame.js: `this.T = (k, …) => T0(cfg.prefix, k, …)` resolves a key under the prefix of the GAME built on it,
// so a literal this.T("x") must exist as <prefix>.x for every such game (pool, scrap, hex, storm, …).
{
  const dg = fs.readFileSync("static/duelgame.js", "utf8");
  const prefixes = new Set();
  for (const f of fs.readdirSync("static")) {
    if (!f.endsWith(".js") || f === "duelgame.js") continue;
    const txt = fs.readFileSync("static/" + f, "utf8");
    if (!txt.includes("duelgame.js")) continue;
    for (const m of txt.matchAll(/^\s*prefix:\s*"([a-z0-9]+)"/gm)) prefixes.add(m[1]);
  }
  if (!prefixes.size) { fails++; console.error("FAIL: found no DuelGame prefix — this guard's parser is stale"); }
  for (const p of prefixes) collectWrapped(dg, "this.T", p + ".");
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

// PLACEHOLDERS: the code's English default and every table must name the SAME {placeholders}, because the code
// only supplies the ones its default uses. farkle.callReclaim passed {g} to a table reading "#{t}", hamster.stRun
// passed {k,n,t} to "{b}", and shield.badCode was one key for two messages, one with {m} and one without — each
// rendered a literal "{t}" / "{b}" / "{m}" to the user in every language (fixed 2026-10-10).
{
  const ph = (x) => [...new Set([...String(x).matchAll(/\{([A-Za-z_]\w*)\}/g)].map((m) => m[1]))].sort().join(",");
  const files = fs.readdirSync("static").filter((f) => /\.(js|html)$/.test(f) && f !== "i18n.js").map((f) => "static/" + f);
  const bad = [];
  for (const f of files) {
    const txt = fs.readFileSync(f, "utf8");
    const pm = txt.match(/window\.t\(\s*"([a-z0-9]+)\." \+ /);
    const forms = [["window.t", ""], ["i18", ""], ["t", pm ? pm[1] + "." : ""], ...wrappersIn(txt).map((w) => [w.name, w.prefix])];
    for (const [name, prefix] of forms) {
      const re = new RegExp(`(?<![\\w.$])${name.replace(/[.$]/g, "\\$&")}\\(\\s*"([a-zA-Z0-9_.\\-]+)"\\s*,\\s*"((?:[^"\\\\]|\\\\.)*)"`, "g");
      for (const m of txt.matchAll(re)) {
        const k = name === "t" && m[1].includes(".") ? m[1] : prefix + m[1];
        if (!(k in T.en)) continue;
        for (const l of Object.keys(T)) {
          if (T[l][k] != null && ph(T[l][k]) !== ph(m[2])) { bad.push(`${f}: ${k} [${l}] code passes {${ph(m[2])}}, table has {${ph(T[l][k])}}`); break; }
        }
      }
    }
  }
  if (bad.length) { fails++; console.error(`FAIL: ${bad.length} key(s) whose table placeholders differ from the code's:\n  ` + bad.slice(0, process.env.ALL ? 999 : 10).join("\n  ")); }
}

if (fails) process.exit(1);
console.log(`OK: ${Object.keys(T).length} languages x ${en.size} keys, every referenced key defined`);
