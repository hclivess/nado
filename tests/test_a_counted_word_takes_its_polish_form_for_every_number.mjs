// A counted word takes its Polish form for every number (static/i18n/runtime.js.tmpl t(), 2026-11-04).
//
// English has two forms and the code picks one (n === 1 ? "tile" : "tiles"); Polish has four — 1 pole, 2-4 pola,
// 5+ pól, 1,5 pola — so "Odkryj 5 pola" was wrong for every count of five or more. A table may write
// {n|one:..|few:..|many:..|other:..} or {word@n|...}, and t() picks the form with Intl.PluralRules. This runs the
// GENERATED static/i18n.js (the file every page loads) in a sandbox with a Polish browser and pins:
//   - the plural token picks one / few / many / other by the number, including 12-14 (many) and 22-24 (few);
//   - {word@n|...} declines the code-passed English word away, and {n} still renders;
//   - the same keys in English are unchanged (the token exists only in the Polish table);
//   - a token whose count is missing from the call is left as written (never a crash, never a wrong form).
// Run: node tests/test_a_counted_word_takes_its_polish_form_for_every_number.mjs
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const src = fs.readFileSync(path.join(ROOT, "static", "i18n.js"), "utf8");
let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };

function load(langs) {
  const el = () => ({ setAttribute() {}, getAttribute() { return null; }, appendChild() {}, insertBefore() {}, style: {},
    classList: { add() {}, remove() {}, toggle() {} }, addEventListener() {}, querySelectorAll: () => [], firstChild: null });
  const document = { documentElement: el(), readyState: "complete", head: el(), body: el(),
    querySelectorAll: () => [], querySelector: () => null, getElementById: () => null, createElement: el,
    createTextNode: () => ({}), addEventListener() {} };
  const store = {};
  const window = { localStorage: { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } },
    navigator: { languages: langs, language: langs[0] }, document, addEventListener() {}, matchMedia: () => ({ matches: false, addEventListener() {} }) };
  window.window = window;
  const ctx = vm.createContext({ window, document, navigator: window.navigator, localStorage: window.localStorage,
    Intl, console, setTimeout, MutationObserver: class { observe() {} }, CustomEvent: class {}, location: { search: "" } });
  vm.runInContext(src, ctx);
  return window.t;
}

const pl = load(["pl-PL", "pl"]);
const en = load(["en-US", "en"]);
check("a Polish browser gets the Polish table", pl("tab.wallet", "Wallet") !== "Wallet", pl("tab.wallet", "Wallet"));

const reveal = (t, n) => t("mines.revealN", "Reveal {n} {tiles}", { n, tiles: n === 1 ? "tile" : "tiles" });
const want = { 1: "1 pole", 2: "2 pola", 4: "4 pola", 5: "5 pól", 12: "12 pól", 14: "14 pól", 21: "21 pól", 22: "22 pola", 25: "25 pól", 1.5: "1.5 pola" };
for (const [n, w] of Object.entries(want)) {
  const got = reveal(pl, Number(n));
  check(`mines: ${n} → "${w}"`, got.endsWith(w), got);
}
check("the code-passed English word never reaches the Polish string", !/tiles?\b/.test(reveal(pl, 5)), reveal(pl, 5));
check("English is unchanged: Reveal 5 tiles / Reveal 1 tile", reveal(en, 5) === "Reveal 5 tiles" && reveal(en, 1) === "Reveal 1 tile",
      reveal(en, 5) + " | " + reveal(en, 1));

const players = (t, n) => t("poker.playersN", "{n} players", { n });
check("players: 2 gracze, 5 graczy, 22 gracze, 0 graczy",
      players(pl, 2) === "2 gracze" && players(pl, 5) === "5 graczy" && players(pl, 22) === "22 gracze" && players(pl, 0) === "0 graczy",
      [2, 5, 22, 0].map((n) => players(pl, n)).join(" | "));
check("a token whose count the call does not pass is left as written", pl("poker.playersN", "{n} players", {}).includes("{n|"),
      pl("poker.playersN", "{n} players", {}));

if (fails) { console.log(`${fails} FAILED`); process.exit(1); }
console.log("ALL PASS — a counted word takes its Polish form for every number");
