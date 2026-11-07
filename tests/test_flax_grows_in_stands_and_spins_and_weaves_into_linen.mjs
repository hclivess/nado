/*
 * test_flax_grows_in_stands_and_spins_and_weaves_into_linen.mjs — textiles in Land ("start creating various structures
 * and adding additional recipes and materials to the game in a sensible, realistic yet engaging manner", operator
 * 2026-11-07):
 *   1. flax grows on the meadows in STANDS — a patch thick with it, then none for a while — never in a forest, on rock
 *      or under the sea, and it lies where litter lies (the air cell just above the ground);
 *   2. it is pulled up by hand (no tool) for its fibre, and it is drawn as itself: a clump of thin stems, each with its
 *      flower, inside its cell;
 *   3. from bare hands a player can make a drop spindle (a stick and a stone whorl), spin flax into linen thread (and
 *      better cordage), build a loom and weave linen cloth — and a bed's tick is linen stuffed with fibre;
 *   4. the world server knows every block and every new item, tool and station is named in 17 languages.
 *
 * Run: node tests/test_flax_grows_in_stands_and_spins_and_weaves_into_linen.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const Tr = await import(join(ROOT, "static", "land-trees.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const B = Wd.B;

// 1. stands
const sp = Wd.plotCoords(Wd.plotId(0, Wd.SPAWN_PLOT_ROW, Wd.SPAWN_PLOT_COL));
let meadow = 0, flax = 0, wrongBiome = 0, wrongCell = 0;
const regions = new Map();
for (let u = sp.u0 - 300; u < sp.u0 + 300; u++) for (let v = sp.v0 - 300; v < sp.v0 + 300; v += 2) {
  const col = Wd.column(0, u, v);
  const f = Wd.terrainBlock(0, u, v, col.top + 1) === B.flax;
  if (col.biome === "grass") {
    meadow++;
    const k = (u >> 3) + ":" + (v >> 3), r = regions.get(k) || [0, 0];
    r[0]++; if (f) { r[1]++; flax++; }
    regions.set(k, r);
  } else if (f) wrongBiome++;
  if (f && Wd.terrainBlock(0, u, v, col.top + 2) === B.flax) wrongCell++;
}
const stands = [...regions.values()].filter((r) => r[1] > 0), dense = stands.filter((r) => r[1] / r[0] > 0.3);
ok(flax > 50 && flax / meadow > 0.02 && flax / meadow < 0.15, `flax grows on ${(100 * flax / meadow).toFixed(1)}% of the meadow`);
ok(stands.length > 3 && dense.length / stands.length > 0.8 && stands.length / regions.size < 0.2,
   `…in stands: ${stands.length} of ${regions.size} 8 m patches hold it, ${dense.length} of those thick with it`);
ok(!wrongBiome && !wrongCell, "never off the meadow, and only in the cell just above the ground");

// 2.
const rule = R.breaking[String(B.flax)];
ok(rule && !rule.needs && rule.yields[0][0] === "flax" && Wd.LITTER.has(B.flax) && !Wd.BLOCKS[B.flax].solid, "flax is pulled up by hand, and a player walks through it");
for (const seed of [1, 77, 500]) {
  const m = Tr.flaxModel(seed), P = m.bark.pos;
  let rMax = 0, hMax = 0;
  for (let i = 0; i < P.length; i += 3) { rMax = Math.max(rMax, Math.hypot(P[i], P[i + 1])); hMax = Math.max(hMax, P[i + 2]); }
  ok(m.bark.n > 40 && rMax < 0.45 && hMax > 0.5 && hMax < 1, `a clump of flax (seed ${seed}) is stems and flowers inside its cell: ${m.bark.n} vertices, ${rMax.toFixed(2)} m wide, ${hMax.toFixed(2)} m tall`);
}
{
  // a stand drawn: the chunk holding one draws more bark (stems) than the same chunk with its flax pulled
  let at = null;
  for (let u = sp.u0 - 300; u < sp.u0 + 300 && !at; u++) for (let v = sp.v0 - 300; v < sp.v0 + 300 && !at; v++) {
    const col = Wd.column(0, u, v);
    if (Wd.terrainBlock(0, u, v, col.top + 1) === B.flax) at = { u, v, h: col.top + 1 };
  }
  const draw = (edits) => { const r = M.meshChunk(0, Math.floor(at.u / 16), Math.floor(at.v / 16), Math.floor(at.h / 16), edits, null, 0); return r.bark ? r.bark.pos.length : 0; };
  const pulled = new Map([[`0:${at.u}:${at.v}:${at.h}`, B.air]]);
  ok(at && draw(null) > draw(pulled), "a flax plant in the world is drawn as its model, and gone once pulled");
}

// 3. reach
const have = new Set(), tools = new Set(), stations = new Set();
const hasClass = (c) => [...tools].some((t) => t === c || R.tools[t].class === c);
for (let grew = true, n = 0; grew && n < 60; n++) {
  grew = false;
  for (const rr of Object.values(R.breaking)) {
    if (typeof rr !== "object" || !rr.yields || (rr.needs && !hasClass(rr.needs))) continue;
    for (const [id] of rr.yields) if (!have.has(id)) { have.add(id); grew = true; }
  }
  for (const r of R.recipes) {
    if (!r.uses.every(([id]) => have.has(id)) || !(r.with || []).every((w) => stations.has(w) || hasClass(w))) continue;
    for (const [id] of r.makes) { const s = id in R.tools ? tools : id in R.stations ? stations : have; if (!s.has(id)) { s.add(id); grew = true; } }
  }
}
ok(tools.has("spindle") && stations.has("loom") && ["flax", "thread", "linen"].every((i) => have.has(i)), "spindle, thread, loom and linen are all reachable from bare hands");
const rec = (id) => R.recipes.find((r) => r.id === id);
ok(rec("spindle").uses.some(([i]) => i === "stone") && !(rec("spindle").with || []).length, "a drop spindle is a stick and a stone whorl, made in the hand");
ok(rec("thread").with.includes("spindle") && rec("linen").with.includes("loom") && rec("cordage_flax").makes[0][0] === "cordage",
   "flax is spun into thread (and better cordage) on the spindle and woven into linen on the loom");
ok(rec("bed").uses.some(([i]) => i === "linen"), "a bed's tick is linen");

// 4.
const srv = Number((readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8").match(/^N_BLOCKS = (\d+)/m) || [])[1]);
ok(srv === Wd.BLOCKS.length, `the world server knows every block (${srv})`);
const tr = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
const names = ["land.i.flax", "land.i.thread", "land.i.linen", "land.t.spindle", "land.s.loom"];
ok(Object.keys(tr).length === 17 && Object.values(tr).every((l) => names.every((k) => l[k])), "every new item, tool and station is named in 17 languages");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
