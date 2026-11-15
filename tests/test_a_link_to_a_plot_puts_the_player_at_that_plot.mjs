/*
 * test_a_link_to_a_plot_puts_the_player_at_that_plot.mjs — playtest 2026-11-16: every plot's title carries its place in
 * the game (https://land.nadochain.com/?plot=N — the market's "Walk it in Land", nft.js), but the page read no ?plot= at
 * all: a fresh browser asked for 0·4999·3438 stood at the landing, 0·5000·3440. land.js linkPlace reads it — half a
 * metre inside the plot's south edge, looking north across it, so the HUD names the plot asked for (1.5 m off the edge
 * it named the neighbour, 0·4998·3438) — and load() puts the player there over a saved place and over the server's kept
 * one, then drops ?plot= from the address. When the plot's pieces arrive and stand there, the player steps out over the
 * edge (setPlotBoxes). The page's linkPlace and that step run here.
 * Run: node tests/test_a_link_to_a_plot_puts_the_player_at_that_plot.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const nft = readFileSync(join(ROOT, "static", "nft.js"), "utf8");
const Wd = await import(join(ROOT, "static", "land-world.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const i0 = page.indexOf("function linkPlace(search) {"), src = page.slice(i0, page.indexOf("\n}\n", i0) + 2);
const linkPlace = new Function("Wd", src + "\nreturn linkPlace;")(Wd);
const X = 4999 * Wd.FACE_N + 3438;                                  // the X fighter's plot, 0·4999·3438
const at = linkPlace("?plot=" + X), q = Wd.plotCoords(X);
ok(at && at[0] === q.face && at[1] === q.u0 + Wd.PLOT / 2 && at[2] === q.v0 + 0.5 && at[3] === 0 && at[4] === X, `?plot=${X} stands mid-way along the plot's south edge, half a metre in, looking north: ${JSON.stringify(at)}`);
ok(Wd.plotOf(at[0], at[1], at[2]) === X, "…ON the plot asked for, so the HUD names it (not the neighbour south)");
ok([q.u0, q.v0].every(Number.isInteger) && Wd.plotOf(q.face, q.u0 + 8, q.v0 + 8) === X, "(plotCoords and plotOf agree on the plot)");
ok(["", "?plot=", "?plot=abc", "?plot=-3", "?plot=" + Wd.PLOT_MAX, "?plot=99999999999", "?x=1"].every((s) => linkPlace(s) === null), "no place for a missing, malformed or out-of-planet plot");
const ld = page.slice(page.indexOf("function load() {"), page.indexOf("\n}\n", page.indexOf("function load() {")));
ok(ld.indexOf("const link = linkPlace(location.search);") >= 0 && ld.indexOf("const link = linkPlace(location.search);") < ld.indexOf("restorePlace(d.p"), "load takes the link before a saved place");
ok(/localPlace = Infinity;/.test(ld) && /if \(m\.pos && \(m\.pos_at \|\| 0\) > localPlace\) takePlace\(m\.pos\);/.test(page), "…and over the server's kept place (taken only when newer than the page's)");
ok(/history\.replaceState\(null, "", location\.pathname \+ location\.hash\)/.test(ld), "…then drops ?plot= so a reload stays where they walked");
ok(/href="\$\{esc\(LAND\)\}\/\?plot=\$\{p\}"/.test(nft), "the market's \"Walk it in Land\" is such a link");
{ // the plot's pieces arrive: standing in one, the player steps out over the south edge; standing clear, they stay
  const sp = page.slice(page.indexOf("function setPlotBoxes(plot, list) {"), page.indexOf("\n}\n", page.indexOf("function setPlotBoxes(plot, list) {")) + 2);
  const run = (blocked) => {
    const P = { face: q.face, u: at[1], v: at[2], h: 40 }; let saved = 0;
    const f = new Function("plotBoxes", "indexBoxes", "topSeq", "Wd", "remeshPlotRange", "collides", "groundAt", "save", "P", "linkArrive",
      "let topSeqV = 0;\n" + sp.replace("topSeq++", "topSeqV++") + "\nsetPlotBoxes(" + X + ", []);\nreturn linkArrive;");
    const left = f(new Map(), () => new Map(), 0, Wd, () => {}, () => blocked, () => 39, () => saved++, P, X);
    return { P, saved, left };
  };
  const inPiece = run(true), clear = run(false);
  ok(inPiece.P.v === q.v0 - 1.5 && inPiece.P.h === 39 && inPiece.saved === 1 && Wd.plotOf(q.face, inPiece.P.u, inPiece.P.v) !== X, "standing in one of its pieces when they arrive, the player steps out over the south edge onto the ground");
  ok(clear.P.v === at[2] && clear.saved === 0, "…standing clear, they stay where the link put them");
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
