/*
 * test_the_ground_holds_veins_of_coal_and_metal_and_beds_of_clay.mjs — below ground, realistic and worth digging for
 * ("start creating various structures and adding additional recipes and materials to the game in a sensible,
 * realistic yet engaging manner", operator 2026-11-07):
 *   1. the rock holds veins of coal, iron, copper and tin — coal commonest, tin rarest — about a tenth of the rock all
 *      told; a vein is ONE ore along its stretch (the type is the region's, so following it keeps the ore);
 *   2. clay lies in beds in the subsoil (two to four layers down) under a good share of the meadows and forests, and is
 *      dug by hand (no tool needed), quicker with a shovel; clay is no longer conjured from earth and sand;
 *   3. coal, copper and tin need a pickaxe; exposed ore and clay are TINTED in the drawn ground (a vein must be seen to
 *      be followed);
 *   4. bronze — three copper ore and a tin ore with fuel at the bloomery — makes tools between stone and iron
 *      (speeds 3 < 4.5 < 6), and coal is the better fuel (one coal does what two charcoal do);
 *   5. the world server knows every block (N_BLOCKS) and every new item and tool has its name in 17 languages.
 *
 * Run: node tests/test_the_ground_holds_veins_of_coal_and_metal_and_beds_of_clay.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Wd = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const B = Wd.B, ORES = [B.coal, B.ironore, B.copperore, B.tinore];

// 1
const sp = Wd.plotCoords(Wd.plotId(0, Wd.SPAWN_PLOT_ROW, Wd.SPAWN_PLOT_COL));
const n = {}; let rock = 0, mixed = 0, veinPairs = 0;
for (let u = sp.u0 - 160; u < sp.u0 + 160; u += 3) for (let v = sp.v0 - 160; v < sp.v0 + 160; v += 3) {
  const col = Wd.column(0, u, v);
  for (let h = 10; h < col.top - col.soil; h += 4) {
    const b = Wd.terrainBlock(0, u, v, h);
    rock++;
    if (ORES.includes(b)) {
      n[b] = (n[b] || 0) + 1;
      // a neighbour in the same 8 m region that is also ore must be the SAME ore
      const b2 = Wd.terrainBlock(0, u ^ 1, v, h);
      if (ORES.includes(b2) && (u >> 3) === ((u ^ 1) >> 3)) { veinPairs++; if (b2 !== b) mixed++; }
    }
  }
}
const pct = (b) => (100 * (n[b] || 0)) / rock, total = ORES.reduce((a, b) => a + pct(b), 0);
ok(ORES.every((b) => pct(b) > 0.3), `every ore is in the rock (${ORES.map((b) => Wd.BLOCKS[b].key + " " + pct(b).toFixed(1) + "%").join(", ")})`);
ok(pct(B.coal) > pct(B.copperore) && pct(B.copperore) > pct(B.tinore) && pct(B.ironore) > pct(B.tinore), "coal and iron commonest, tin rarest");
ok(total > 6 && total < 18, `ore is about a tenth of the rock (${total.toFixed(1)}%)`);
ok(veinPairs > 20 && mixed === 0, `a vein is one ore along its stretch (${veinPairs} neighbouring ore pairs in one region, ${mixed} mixed)`);

// 2
let cols = 0, clayCols = 0, wrongDepth = 0;
for (let u = sp.u0 - 200; u < sp.u0 + 200; u += 4) for (let v = sp.v0 - 200; v < sp.v0 + 200; v += 4) {
  const col = Wd.column(0, u, v);
  if (col.biome !== "grass" && col.biome !== "forest") continue;
  cols++;
  let has = false;
  for (let h = col.top - 6; h <= col.top; h++) if (Wd.terrainBlock(0, u, v, h) === B.clay) { has = true; if (h > col.top - 2 || h < col.top - 4) wrongDepth++; }
  if (has) clayCols++;
}
ok(clayCols / cols > 0.1 && clayCols / cols < 0.6 && !wrongDepth, `clay beds lie two to four layers down under ${(100 * clayCols / cols).toFixed(0)}% of meadow and forest`);
const clay = R.breaking[String(B.clay)];
ok(clay && !clay.needs && clay.class === "shovel" && clay.yields[0][0] === "clay", "clay is dug by hand, quicker with a shovel");
ok(!R.recipes.some((r) => r.makes.some(([i]) => i === "clay")), "clay is no longer made from earth and sand");

// 3
ok([B.coal, B.copperore, B.tinore].every((b) => R.breaking[String(b)].needs === "pick"), "coal, copper and tin need a pickaxe");
ok([B.coal, B.copperore, B.tinore, B.clay].every((b) => Wd.NATURAL.has(b)), "they are natural ground (the smooth surface draws them)");
const mesher = readFileSync(join(ROOT, "static", "land-mesher.js"), "utf8");
ok(/ORE_TINT = \{[^}]*B\.coal[^}]*B\.ironore[^}]*B\.copperore[^}]*B\.tinore[^}]*B\.clay/.test(mesher), "exposed ore and clay are tinted in the drawn ground");
{
  // dig into rock until ore shows, mesh it, and find its tint on the surface
  let found = null;
  for (let u = sp.u0 + 4; u < sp.u0 + 400 && !found; u++) {
    if (u % 16 < 3 || u % 16 > 12) continue;                          // the pit stays inside one chunk column
    const col = Wd.column(0, u, sp.v0 + 6);
    for (let h = col.top - col.soil - 1; h > col.top - col.soil - 8 && !found; h--) if (Wd.terrainBlock(0, u, sp.v0 + 6, h) === B.coal) found = { u, h, col };
  }
  if (found) {
    const edits = new Map();
    // a 5 x 5 pit down to the vein (a one-column trench's floor shares its surface points with the rock walls beside it)
    for (let du = -2; du <= 2; du++) for (let dv = -2; dv <= 2; dv++) {
      const top = Wd.column(0, found.u + du, sp.v0 + 6 + dv).top;
      for (let h = found.h + 1; h <= top + 2; h++) edits.set(0 + ":" + (found.u + du) + ":" + (sp.v0 + 6 + dv) + ":" + h, B.air);
    }
    let dark = 0;
    for (const ch of new Set([Math.floor(found.h / 16), Math.floor((found.h + 1) / 16)])) {
      const r = M.meshChunk(0, Math.floor(found.u / 16), Math.floor((sp.v0 + 6) / 16), ch, edits, null, 0);
      const C = r.smooth ? r.smooth.col : [];
      for (let i = 0; i < C.length; i += 3) if (C[i] < 0.5 && C[i + 2] < 0.5) dark++;
    }
    ok(dark > 0, `a coal vein dug into shows dark on the ground's surface (${dark} vertices)`);
  } else ok(false, "found a coal vein to dig into");
}

// 4
const T = R.tools;
ok(T.axe.speed < T.bronze_axe.speed && T.bronze_axe.speed < T.iron_axe.speed && T.bronze_pick.class === "pick", "tools: stone 3 < bronze 4.5 < iron 6");
const bz = R.recipes.find((r) => r.id === "bronze");
ok(bz && bz.with.includes("bloomery") && bz.uses.some(([i, k]) => i === "copperore" && k === 3) && bz.uses.some(([i, k]) => i === "tinore" && k === 1), "bronze is three copper ore and a tin ore at the bloomery");
const ic = R.recipes.find((r) => r.id === "iron_coal"), ich = R.recipes.find((r) => r.id === "iron");
ok(ic && ic.uses.find(([i]) => i === "coal")[1] * 2 === ich.uses.find(([i]) => i === "charcoal")[1], "coal is the better fuel: one coal does what two charcoal do");

// 5
const srv = Number((readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8").match(/^N_BLOCKS = (\d+)/m) || [])[1]);
ok(srv === Wd.BLOCKS.length, `the world server knows every block (${srv})`);
const tr = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
const names = ["land.i.coal", "land.i.copperore", "land.i.tinore", "land.i.bronze", "land.t.bronze_axe", "land.t.bronze_pick", "land.t.bronze_shovel"];
ok(Object.keys(tr).length === 17 && Object.values(tr).every((l) => names.every((k) => l[k])), "every new item and tool is named in 17 languages");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
