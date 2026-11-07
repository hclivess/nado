/*
 * test_the_dex_page_speaks_every_language.mjs — the DEX page (static/dex.html + static/dex.js) says everything it shows
 * in all 17 languages (CLAUDE.md rule 7, GitHub issue #103):
 *   a. every LT("key", "English") in dex.js and every data-i18n / data-i18n-html / data-i18n-ph / data-i18n-title key in
 *      dex.html exists in every language of static/i18n_games/dex.json, non-empty, with the SAME {placeholders} as the
 *      English (a dropped {n} renders a literal "{n}"), and the code's English default IS the table's English (the
 *      fallback a missing table shows must not drift from what translators translated); every LT( takes a literal key;
 *   b. no text in dex.html's body (outside <script>/<style>) sits outside an element that carries a data-i18n* attribute,
 *      except brand and ticker words — so the next English-only label added to the page fails here, not in fifteen
 *      locales;
 *   c. dex.js hands no literal English to alertBar(…) or to a uiConfirm / uiPrompt title, body, row label, confirm or
 *      cancel button, and the dapp.onReturn status map is all LT(…) — the places the page's English-only strings lived.
 *
 * Run: node tests/test_the_dex_page_speaks_every_language.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const js = readFileSync(join(ROOT, "static", "dex.js"), "utf8"), html = readFileSync(join(ROOT, "static", "dex.html"), "utf8");
const T = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "dex.json"), "utf8"));
const LANGS = ["en", "cs", "es", "pt", "fr", "de", "it", "ru", "zh", "ja", "ko", "ar", "hi", "tr", "id", "vi", "pl"];

// a. ---------------------------------------------------------------------------------------------------------------
ok(LANGS.every((l) => T[l]) && Object.keys(T).length === LANGS.length, `dex.json carries exactly the ${LANGS.length} languages`);
// placeholders as tools/build_i18n.py counts them: plain {name} plus the names a plural token {n|one:…} / {w@n|…} reads
const ph = (s) => [...new Set([...[...String(s).matchAll(/\{([A-Za-z_]\w*)\}/g)].map((m) => m[1]),
  ...[...String(s).matchAll(/\{([A-Za-z_]\w*)(?:@([A-Za-z_]\w*))?\|[^{}]*\}/g)].flatMap((m) => (m[2] ? [m[1], m[2]] : [m[1]]))])].sort().join(",");
const used = new Map();                                   // key -> the English the code / markup carries
const calls = [...js.matchAll(/(?<![\w.$])LT\(/g)].length;
const lits = [...js.matchAll(/(?<![\w.$])LT\(\s*"([\w.\-]+)"\s*,\s*"((?:[^"\\]|\\.)*)"/g)];
for (const m of lits) used.set("dex." + m[1], JSON.parse(`"${m[2]}"`));
ok(calls > 400 && calls === lits.length, `every LT( in dex.js takes a literal key and a literal English default (${lits.length} of ${calls})`);
const htmlKeys = [...html.matchAll(/data-i18n(?:-html|-ph|-title)?="([^"]+)"/g)].map((m) => m[1]);
ok(htmlKeys.length > 60 && htmlKeys.every((k) => k.startsWith("dex.")), `dex.html tags ${htmlKeys.length} strings, all under dex.`);
for (const k of htmlKeys) if (!used.has(k)) used.set(k, null);
const missing = [], badPh = [], drift = [];
for (const [k, en] of used) {
  if (en != null && T.en[k] != null && T.en[k] !== en) drift.push(k);
  const want = ph(en != null ? en : T.en[k]);
  for (const l of LANGS) {
    const v = T[l] && T[l][k];
    if (typeof v !== "string" || !v.trim()) { missing.push(`${l}:${k}`); continue; }
    if (ph(v) !== want) badPh.push(`${l}:${k} {${ph(v)}} != {${want}}`);
  }
}
ok(!missing.length, `all ${used.size} keys the page uses exist in all 17 languages` + (missing.length ? ` — missing ${missing.length}: ${missing.slice(0, 12).join(", ")}` : ""));
ok(!badPh.length, "every language keeps the English placeholders" + (badPh.length ? ` — ${badPh.slice(0, 8).join("; ")}` : ""));
ok(!drift.length, "the code's English defaults are the table's English" + (drift.length ? ` — ${drift.slice(0, 8).join(", ")}` : ""));

// b. ---------------------------------------------------------------------------------------------------------------
// The words a translator keeps as they are: the brand, the coin tickers, the chart range buttons.
const KEEP = new Set(["NADO", "DEX", "BTC", "ETH", "SOL", "ALL", "1H", "1D", "1W", "24h"]);
const body = html.slice(html.indexOf("<body"), html.lastIndexOf("</body>"));
const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"]);
const stack = [];                                        // [{tag, tagged}] — tagged = it or an ancestor carries data-i18n*
const english = [];
let skip = null;                                          // inside <script> / <style>
for (const m of body.matchAll(/<!--[\s\S]*?-->|<(\/?)([a-zA-Z][\w-]*)([^>]*?)(\/?)>|([^<]+)/g)) {
  if (m[0].startsWith("<!--")) continue;
  if (m[5] != null) {                                     // a text node
    if (skip) continue;
    const words = (m[5].match(/[A-Za-z0-9][A-Za-z0-9'’]*/g) || []).filter((w) => /[A-Za-z]{3,}/.test(w) && !KEEP.has(w));
    if (words.length && !(stack.length && stack[stack.length - 1].tagged)) english.push(m[5].trim().slice(0, 70));
    continue;
  }
  const close = m[1] === "/", tag = m[2].toLowerCase(), attrs = m[3] || "", selfClose = m[4] === "/" || VOID.has(tag);
  if (skip) { if (close && tag === skip) skip = null; continue; }
  if (!close && (tag === "script" || tag === "style")) { if (!selfClose) skip = tag; continue; }
  if (close) { while (stack.length && stack.pop().tag !== tag); continue; }
  if (selfClose) continue;
  const parentTagged = stack.length ? stack[stack.length - 1].tagged : false;
  stack.push({ tag, tagged: parentTagged || /\sdata-i18n(?:-html|-ph|-title)?="/.test(attrs) });
}
ok(!english.length, "every word in dex.html's body is under a data-i18n* element (brand and tickers aside)"
  + (english.length ? ` — untagged: ${english.slice(0, 8).map((x) => JSON.stringify(x)).join(", ")}` : ""));
// every visible placeholder is translated too (a placeholder that is only a number or "0.0" needs nothing)
const phs = [...body.matchAll(/<input\b[^>]*>/g)].map((m) => m[0]).filter((t) => /placeholder="[^"]*[A-Za-z]{3,}/.test(t) && !/data-i18n-ph="/.test(t));
ok(!phs.length, "every worded placeholder in dex.html carries data-i18n-ph" + (phs.length ? ` — ${phs.slice(0, 4).join(" ")}` : ""));

// c. ---------------------------------------------------------------------------------------------------------------
const code = js.replace(/^\s*\/\/.*$/gm, "");                                       // comment lines say what they like
const lit = String.raw`(["'\`])(?:(?!\1)[^\\]|\\.)*?[A-Za-z]{3,}`;               // a string literal holding a word
const alerts = [...code.matchAll(new RegExp(String.raw`alertBar\(\s*` + lit, "g"))].map((m) => m[0].slice(0, 80));
ok(!alerts.length, "no alertBar( takes a literal English string" + (alerts.length ? ` — ${alerts.slice(0, 6).join(" | ")}` : ""));
const dialogs = [...code.matchAll(new RegExp(String.raw`\b(?:title|body|confirmText|cancelText|placeholder|searchPlaceholder):\s*` + lit, "g")),
                 ...code.matchAll(new RegExp(String.raw`\{\s*k:\s*` + lit + String.raw`[^\n]*?,\s*v:`, "g"))]     // a confirm row {k, v}
  .map((m) => m[0].slice(0, 80));
ok(!dialogs.length, "no uiConfirm / uiPrompt title, body, row label or button — and no picker placeholder — is a literal English string"
  + (dialogs.length ? ` — ${dialogs.slice(0, 6).join(" | ")}` : ""));
const ret = (code.match(/dapp\.showReturn\(pend, ok, err, \{([\s\S]*?)\}\);/) || [])[1] || "";
const retRows = ret.split("\n").map((s) => s.trim()).filter(Boolean);
ok(retRows.length >= 15 && retRows.every((r) => /^\w+: LT\("/.test(r)), `every dapp.onReturn status (${retRows.length}) is an LT(…)`);
const plain = [...code.matchAll(/new Error\(\s*(["'`])[^"'`]*[A-Za-z]{3,}/g)].map((m) => m[0]);
ok(!plain.length, "no thrown error the page shows is literal English" + (plain.length ? ` — ${plain.slice(0, 4).join(" | ")}` : ""));

if (fails) { console.log(`\n${fails} check(s) failed`); process.exit(1); }
console.log("\nall checks passed");
