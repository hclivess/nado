/*
 * test_a_scanned_piece_is_never_black_while_its_scan_loads_and_does_not_repeat_every_metre.mjs — playtest 2026-11-15,
 * the agent's page at the town square: the two stone-brick paths drew pure black for the first ~half minute after a
 * load and then their bricks (photographed: black at 30 s, bricks at 70 s, with the sun's shadows on and off alike);
 * and the operator, the same hour: "can you fix the repetitive tiles" — a path or a wall is one 1 m scan stamped edge to
 * edge. Pinned on the page's code:
 *   1. loadTex gives every texture a `ready` promise that settles when its image arrives, or fails;
 *   2. a scanned piece material starts as its block's own flat colour (PAINT, via the block's side tile) and takes its
 *      scan and normal map only when both are ready (an empty normal map lights nothing: the black), keeping the flat
 *      colour if the scan never comes;
 *   3. the scan is multiplied by pieceVariation: smooth noise at 0.37 and 0.11 per metre (periods ~2.7 m and ~9.1 m)
 *      and a hue drift at 0.23 — none a whole number of the scans' 1 m repeat — brightness within ±15 %, never a
 *      per-tile (floor of uv) term, which would draw the 1 m grid;
 *   4. the painted, thatch and steel surfaces (canvas textures, ready at once) are drawn as before.
 * Run: node tests/test_a_scanned_piece_is_never_black_while_its_scan_loads_and_does_not_repeat_every_metre.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const fn = (name) => { const a = page.indexOf("function " + name + "("); return page.slice(a, page.indexOf("\n}\n", a)); };

const lt = fn("loadTex");   // (it loads `file`: the ground at 512 px on a phone, every other texture by its own name)
ok(/let done; const ready = new Promise\(\(r\) => \{ done = r; \}\);/.test(lt) && /\.load\(`\/static\/vendor\/textures\/\$\{file\}\.jpg`, \(\) => done\(true\), undefined, \(\) => done\(false\)\);/.test(lt) && /t\.userData\.ready = ready;/.test(lt),
  "1. every loaded texture carries a ready promise, settled on load (true) or on failure (false)");
const pm = fn("pieceMaterial");
ok(/const flat = new THREE\.Color\(\(PAINT\[Wd\.BLOCKS\[blk\]\.tex\[1\]\] \|\| \["#8a8478"\]\)\[0\]\);/.test(pm) && /m\.colorNode = shadeByClouds\(TSL\.vec3\(flat\.r, flat\.g, flat\.b\)/.test(pm),
  "2. a scanned piece starts as its block's own flat colour");
ok(/Promise\.all\(\[col\.userData\.ready, nor\.userData\.ready\]\)\.then\(\(\[a, b\]\) => \{\n\s+if \(!a\) return;/.test(pm) && /m\.colorNode = textured\(\);\n\s+if \(b\) m\.normalNode = TSL\.normalMap\(TSL\.texture\(nor, uv\)\);\n\s+m\.needsUpdate = true;/.test(pm),
  "…and takes its scan and normal map only once both are in (the flat colour stays if the scan fails)");
ok(!/m\.normalNode = TSL\.normalMap/.test(pm.slice(0, pm.indexOf("Promise.all"))), "…no normal map is sampled before it is ready");
const pv = fn("pieceVariation");
const freqs = [...pv.matchAll(/uv\.mul\(([0-9.]+)\)/g)].map((m) => Number(m[1]));
ok(freqs.length === 3 && freqs.every((f) => f > 0 && f < 1 && Math.abs(1 / f - Math.round(1 / f)) > 0.05), `3. the drift's noise runs at ${freqs.join(", ")} per metre — periods ${freqs.map((f) => (1 / f).toFixed(2)).join(", ")} m, none a whole number of the 1 m repeat`);
ok(/TSL\.float\(1\)\.add\(n\.mul\(0\.15\)\)/.test(pv) && !/floor/.test(pv), "…brightness within ±15 %, and nothing per tile (no floor of uv: that would draw the grid)");
ok(/TSL\.texture\(col, uv\)\.rgb\.mul\(scanned \? pieceVariation\(uv\) : TSL\.float\(1\)\)/.test(pm), "…and every scanned piece's colour is multiplied by it");
ok(/const scanned = name !== "thatch" && name !== "steel" && name !== "paint";/.test(pm) && /\} else m\.colorNode = textured\(\);/.test(pm), "4. paint, thatch and steel (canvas textures) are drawn at once, as before");
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
