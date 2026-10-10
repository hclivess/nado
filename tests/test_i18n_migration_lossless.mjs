// THE I18N MIGRATION LOST NOTHING: the generated static/i18n.js of the migration commit (the commit that added
// tools/build_i18n.py) yields, for every language, a table byte-identical to the hand-layered i18n.js of its parent —
// same languages in the same order, same keys, same strings.
//
// The old file was a base table plus 110 Object.assign patch tables, a generated games block and a hand-written site
// block, with 129 keys defined more than once (the last definition won). The migration dumped the MERGED per-language
// tables by evaluating that file and split them into static/i18n/*.json; this test evaluates both files the same way
// and compares the final tables, so a key lost or a string changed by the split cannot hide behind "the build passed".
// Key ORDER inside a language is not compared (t() looks keys up; the generator emits them grouped by source file), so
// each table is serialised with sorted keys before the byte comparison.
//
// Before the migration is committed it compares HEAD's i18n.js with the working tree's. Needs git history; a shallow
// checkout without the parent commit prints SKIP rather than passing vacuously.
// Run: node tests/test_i18n_migration_lossless.mjs
import { execFileSync } from "child_process";
import fs from "fs";
import vm from "vm";

let fails = 0;
const check = (name, ok, detail = "") => { console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  " + detail)); if (!ok) fails++; };
const git = (...a) => execFileSync("git", ["-c", "safe.directory=*", ...a], { encoding: "utf8", maxBuffer: 64 << 20 });

function tables(src) {
  const anchor = "  const NAMES = {";
  if (src.split(anchor).length !== 2) throw new Error("NAMES anchor not unique — the runtime changed shape");
  src = src.replace(anchor, "  window.__T = T;\n" + anchor);
  const win = {};
  const ctx = { window: win, localStorage: { getItem() { return null; }, setItem() {} }, navigator: { languages: ["en"] },
    document: { readyState: "loading", addEventListener() {}, documentElement: { setAttribute() {} } } };
  vm.createContext(ctx);
  vm.runInContext(src, ctx);
  return win.__T;
}
const canon = (o) => JSON.stringify(Object.keys(o).sort().map((k) => [k, o[k]]));

let oldSrc, newSrc, what;
try {
  const added = git("log", "--diff-filter=A", "--format=%H", "--", "tools/build_i18n.py").trim().split("\n").filter(Boolean);
  if (added.length) {
    const rev = added[added.length - 1];
    oldSrc = git("show", `${rev}^:static/i18n.js`);
    newSrc = git("show", `${rev}:static/i18n.js`);
    what = `migration commit ${rev.slice(0, 10)} vs its parent`;
  } else {
    oldSrc = git("show", "HEAD:static/i18n.js");
    newSrc = fs.readFileSync("static/i18n.js", "utf8");
    what = "working tree vs HEAD (migration not committed yet)";
  }
} catch (e) {
  console.log("SKIP  git history unavailable (" + String(e.message).split("\n")[0] + ")");
  process.exit(0);
}
console.log("comparing " + what);
const A = tables(oldSrc), B = tables(newSrc);
check("same languages in the same order (the picker lists Object.keys(T))", JSON.stringify(Object.keys(A)) === JSON.stringify(Object.keys(B)),
  Object.keys(A) + " vs " + Object.keys(B));
for (const l of Object.keys(A)) {
  const a = canon(A[l]), b = B[l] ? canon(B[l]) : "";
  let detail = "";
  if (a !== b) {
    const ka = Object.keys(A[l]), kb = Object.keys(B[l] || {});
    const lost = ka.filter((k) => !(k in (B[l] || {}))), added = kb.filter((k) => !(k in A[l]));
    const changed = ka.filter((k) => B[l] && k in B[l] && A[l][k] !== B[l][k]);
    detail = `lost ${lost.slice(0, 5)} added ${added.slice(0, 5)} changed ${changed.slice(0, 5)}`;
  }
  check(`${l}: ${Object.keys(A[l]).length} keys, byte-identical table (${a.length} bytes)`, a === b, detail);
}
console.log(fails ? `${fails} FAILURES` : "ALL PASS");
process.exit(fails ? 1 : 0);
