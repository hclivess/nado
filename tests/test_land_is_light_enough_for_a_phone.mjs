/*
 * test_land_is_light_enough_for_a_phone.mjs — "very laggy on a phone" (operator 2026-11-08). Measured as a phone in the
 * town (412 x 915, dpr 3, touch): 1.5 million pixels a frame and, of the world it meshed, ~1.2 million triangles — most
 * of them the meadow's small things: a wild flower was 450-840 triangles (a tube per petal), a flax clump 192, and
 * stones and sticks were drawn in chunks too far to see them. Pinned here:
 *   1. a phone is known before the renderer is made, and gets its own profile: 1.25 pixels per CSS pixel, 4 chunks of
 *      full view, two point lights, no shadows unless asked, full tree models in the nearest ring only;
 *   2. a wild flower is a few dozen triangles; far chunks draw none of the meadow's small things (a planted sapling
 *      still shows);
 *   3. what a phone meshes around the landing stays within a budget (the generator's own world, the page's own lods);
 *   4. a stats readout (/set stats 1, or a tap on the renderer's name) shows frames a second, triangles and draw calls —
 *      so a slow phone can say what is slow.
 *
 * Run: node tests/test_land_is_light_enough_for_a_phone.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(ROOT, "static", "land-world.js")), M = await import(join(ROOT, "static", "land-mesher.js")), T = await import(join(ROOT, "static", "land-trees.js"));
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS  " : "FAIL  ") + m); if (!c) fails++; };

// 1. the phone profile
ok(/^const PHONE = "ontouchstart" in window \|\| navigator\.maxTouchPoints > 0;/m.test(page), "a phone is known from the start (touch), before the renderer is made");
ok(page.includes("const basePR = () => Math.min(PHONE ? 1.25 : 2, devicePixelRatio || 1);") && page.includes("renderer.setPixelRatio(basePR() * SET.res / 100);"),
  "…it renders 1.25 pixels per CSS pixel (not 2), times its render resolution setting (#166)");
ok(page.includes("const SET_PHONE = { shadows: 0, grass: 0, effects: 0, view: 4 };") && page.includes("viewDist = SET.view;"),
  "…sees 4 chunks of full view (the far land still to the horizon) unless the settings say more");
ok(page.includes("const TORCH_LIGHTS = PHONE ? 2 : 8"), "…lights two point lights (eight on a desktop, #181)");
ok(page.includes("const o = { ...SET_DEF, ...(PHONE ? SET_PHONE : {}) };"), "…casts no shadows, and draws no grass or effects, unless asked (the graphics panel)");
ok(page.includes("const chunkLod = (dist) => (PHONE ? (dist <= 1 ? 1 : 2) : SET.view <= 3 ? (dist <= 2 ? 1 : 2) : dist <= 2 ? 0 : dist <= 3 ? 1 : 2);") && page.includes("c.lod = chunkLod(dist);") && page.includes("lodNow = chunkLod(dd);"), "…and (one rule for the request and the re-check; Low takes no level 0 either, #150) draws full tree models in the nearest ring only");

// 2. the meadow's small things
const flower = Math.max(...[0, 1, 2, 3].map((k) => { const m = T.flowerModel(5, k); return (m.bark.idx.length + m.leaves.idx.length) / 3; }));
ok(flower <= 100, `a wild flower is ${flower} triangles at most (it was 450-840)`);
const u = 3435 * 16 + 8, v = 4995 * 16 + 8, top = W.column(0, u, v).top, cell = `0:${u}:${v}:${top + 1}`;
const tri = (r) => (r && !r.empty ? Object.values(r).reduce((n, p) => n + (p && p.idx ? p.idx.length / 3 : 0), 0) : 0);
const at = (ed, lod) => tri(M.meshChunk(0, Math.floor(u / 16), Math.floor(v / 16), Math.floor((top + 1) / 16), ed, null, lod, false));
const none = new Map([[cell, 0]]), fl = new Map([[cell, W.B.poppy]]), sap = new Map([[cell, W.B.sapling]]);
ok(at(fl, 1) > at(none, 1) && at(fl, 2) === at(none, 2), "far chunks draw no wild flowers (near ones do)");
ok(at(sap, 2) > at(none, 2), "…but a sapling someone planted still shows far away");

// 3. a phone's view around the landing, as the page meshes it
const sp = W.plotCoords(W.plotId(0, 5000, 3440)), U = sp.u0 + 8, V = sp.v0 + 8, pcu = Math.floor(U / 16), pcv = Math.floor(V / 16);
let total = 0;
for (let dx = -4; dx <= 4; dx++) for (let dy = -4; dy <= 4; dy++) {
  if (dx * dx + dy * dy > 17) continue;
  const cu = pcu + dx, cv = pcv + dy, t = W.column(0, cu * 16 + 8, cv * 16 + 8).top, dd = Math.max(Math.abs(dx), Math.abs(dy));
  for (let ch = Math.max(0, Math.floor((Math.min(t, W.SEA) - 10) / 16)); ch <= Math.floor((t + 14) / 16); ch++)
    total += tri(M.meshChunk(0, cu, cv, ch, new Map(), null, dd <= 1 ? 1 : 2, false));
}
ok(total <= 160000, `a phone's view around the landing is ${Math.round(total / 1000)}k triangles (budget 160k; it was ~1.2 million in the town)`);

// 4. the stats readout
ok(page.includes("stats: 0, ") && /\$\{fps\} fps · \$\{Math\.round\(r\.triangles \/ 1000\)\}k tris · \$\{r\.drawCalls \?\? r\.calls\} calls/.test(page)
   && page.includes('$("hudGpu").onclick = () => { SET.stats = SET.stats ? 0 : 1;'), "a stats readout shows frames a second, triangles and draw calls (/set stats 1, or a tap)");

// THE LEFT CLUSTER (#139, playtest 2026-11-11: a phone had no chat or console, no run, no piece turn, no fire, no
// wardrobe): five more buttons, each wired, Run honoured by the walk's own speed rule while held
const html = readFileSync(join(ROOT, "static", "land.html"), "utf8");
ok(["tChat", "tRun", "tTurn", "tFire", "tWard"].every((id) => new RegExp(`<button id="${id}" data-i18n="land\\.${id}">`).test(html) && new RegExp(`#${id}\\{left:\\d+px;bottom:\\d+px\\}`).test(html)), "a phone has Chat, Run, Turn, Fire and Wear buttons, placed on the left");
ok(/\$\("tChat"\)\.onclick = \(\) => conShow\(!conOpen\);/.test(page) && /hold\("tRun", "run"\);/.test(page) && /\$\("tTurn"\)\.onclick = \(\) => turnPiece\(\);/.test(page) && /\$\("tFire"\)\.onclick = \(\) => ignite\(\);/.test(page) && /\$\("tWard"\)\.onclick = \(\) => wardrobe\(true\);/.test(page), "…each wired: the console, run while held, the piece turned, fire, the wardrobe");
ok(/const fast = keys\.has\("ShiftLeft"\) \|\| keys\.has\("ShiftRight"\) \|\| !!\(touch && touch\.run\);/.test(page), "…and Run held is the walk's own Shift");
const I2 = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
ok(/body\.touch #hudInfo\{font-size:11px;line-height:1\.3;max-width:min\(380px,calc\(100vw - 130px\)\)\}/.test(html) && /body\.touch #hudPlot \.dim\{display:none\}/.test(html), "on a phone the HUD text is smaller and tighter and the plot card's explanations are folded away (it took the top third of a 480-px screen)");
ok(["land.tChat", "land.tRun", "land.tTurn", "land.tFire", "land.tWard"].every((k) => Object.keys(I2).length === 17 && Object.keys(I2).every((l) => typeof I2[l][k] === "string" && I2[l][k].length > 0)), "the five labels are in all 17 languages");

console.log(fails ? `${fails} FAILED` : "ALL PASS");
process.exit(fails ? 1 : 0);
