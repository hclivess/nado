/*
 * test_a_house_can_be_furnished_with_real_models_reached_from_bare_hands.mjs — furniture and fittings in Land ("start
 * creating various structures and adding additional recipes and materials to the game in a sensible, realistic yet
 * engaging manner", operator 2026-11-07):
 *   1. a table, chair, bench, rope bed, fence and torch are each reachable from bare hands by the rules a player follows,
 *      and each is a unit item (made whole, placed whole at a realistic size: a table top at 76 cm, a seat at 42-46 cm);
 *   2. each is DRAWN as its model — every part inside its unit box, both ways round (T turns it), and more than the box's
 *      six faces (legs, rails, a back) — and a part of another material (the bed's straw tick and blanket, the torch's
 *      flame) is its own draw group, the groups covering every index exactly once;
 *   3. a model's box hides no neighbour's face (a wall beside a table still shows), a glowing part is emissive, and the
 *      torchlight is a FIXED pool of lights (a changing light count recompiles every material);
 *   4. the world server knows every block, and each new item is named in all 17 languages.
 *
 * Run: node tests/test_a_house_can_be_furnished_with_real_models_reached_from_bare_hands.mjs
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
const B = Wd.B, FURN = ["table", "chair", "bench", "bed", "fence", "torch"];

// 1. reach, the way a player would (as in the house test)
const have = new Set(), tools = new Set(), stations = new Set();
const hasClass = (c) => [...tools].some((t) => t === c || R.tools[t].class === c);
for (let grew = true, n = 0; grew && n < 60; n++) {
  grew = false;
  for (const rule of Object.values(R.breaking)) {
    if (typeof rule !== "object" || !rule.yields || (rule.needs && !hasClass(rule.needs))) continue;
    for (const [id] of rule.yields) if (!have.has(id)) { have.add(id); grew = true; }
  }
  for (const r of R.recipes) {
    if (!r.uses.every(([id]) => have.has(id)) || !(r.with || []).every((w) => stations.has(w) || hasClass(w))) continue;
    for (const [id] of r.makes) { const s = id in R.tools ? tools : id in R.stations ? stations : have; if (!s.has(id)) { s.add(id); grew = true; } }
  }
}
ok(FURN.every((i) => have.has(i)), `every piece of furniture is reachable from bare hands (${FURN.filter((i) => !have.has(i)).join(", ") || "all"})`);
ok(FURN.every((i) => R.items[i].places === B[i] && R.items[i].unit && R.breaking[String(B[i])].yields[0][0] === i), "each is a unit item that places its block and gives itself back when taken down");
ok(R.items.table.unit[2] === 76 && R.items.chair.unit[2] === 95 && R.items.bed.unit[0] === 200, "real sizes: a 76 cm table, a 95 cm chair, a 2 m bed");

// 2. drawn as models
const sp = Wd.plotCoords(Wd.plotId(0, Wd.SPAWN_PLOT_ROW, Wd.SPAWN_PLOT_COL));
// a piece's height is absolute (cm); hang it in the air above the ground, wholly inside one chunk
const CH = Math.floor((Wd.column(0, sp.u0 + 8, sp.v0 + 8).top + 40) / 16), Y0 = CH * 1600 + 100;
const mesh = (bx) => M.meshChunk(0, sp.u0 / 16, sp.v0 / 16, CH, null, bx, 0).pieces || { idx: [], groups: [] };
for (const k of FURN) {
  const u = R.items[k].unit;
  for (const turned of [false, true]) {
    const [w, d] = turned ? [u[1], u[0]] : [u[0], u[1]], L = Math.max(w, d), S = Math.min(w, d);
    const parts = M.MODELS[B[k]](L, S);
    const inside = parts.every(([l0, l1, s0, s1, y0, y1]) => l0 >= 0 && l1 <= L && s0 >= 0 && s1 <= S && y0 >= 0 && y1 <= u[2] && l0 < l1 && s0 < s1 && y0 < y1);
    const pc = mesh([[300, 300, Y0, w, d, u[2], B[k]]]), tris = pc.idx.length / 3;
    const covered = pc.groups.reduce((a, g) => a + g[1], 0), mats = new Set(pc.groups.map((g) => g[2]));
    const want = new Set(parts.map((p) => p[6] ?? B[k]));
    ok(inside && tris === parts.length * 12 && tris > 12 && covered === pc.idx.length && [...want].every((m) => mats.has(m)),
       `a ${k}${turned ? " (turned)" : ""} is drawn as ${parts.length} parts inside its box, ${want.size} material(s), groups covering ${covered}/${pc.idx.length}`);
  }
}

// 3.
const mesher = readFileSync(join(ROOT, "static", "land-mesher.js"), "utf8"), land = readFileSync(join(ROOT, "static", "land.js"), "utf8");
ok(/shapeOf\(n\) \|\| MODELS\[n\[6\]\] \|\| n\[6\] === B\.window\) continue;/.test(mesher), "a model's box hides no neighbour's face");
{
  // a wall beside a table: its face toward the table is still drawn
  const wall = [100, 300, Y0, 100, 20, 100, B.planks], table = [100, 320, Y0, 120, 80, 76, B.table];
  const n = (bx) => mesh(bx).idx.length;
  ok(n([wall, table]) === n([wall]) + n([table]), "a wall beside a table keeps every face");
}
{
  // a chair pulled up to a table faces it, from either side: its back is on the side away from the table
  const chair = [300, 300, Y0, 50, 45, 95, B.chair];
  const back = M.MODELS[B.chair](50, 45).filter((p) => p[5] > 60);
  ok(back.every((p) => p[2] >= 45 - 6), "drawn as it stands, a chair's back is at its far side");
  ok(M.facesAway(chair, [[265, 360, Y0, 120, 80, 76, B.table]]) === true && M.facesAway(chair, [[265, 210, Y0, 120, 80, 76, B.table]]) === false
     && M.facesAway(chair, []) === false && M.facesAway(chair, [[265, 900, Y0, 120, 80, 76, B.table]]) === false,
     "a table beyond the back flips it to face the table; a table in front, none, or one out of reach leaves it");
  ok(/const flip = b\[6\] === B\.chair && facesAway\(b, boxes\)/.test(mesher), "the mesher draws a chair by that rule");
}
ok(Wd.BLOCKS[B.lamp].glow && /BLOCKS\[blk\]\.glow\)[\s\S]{0,300}emissiveNode/.test(land), "a glowing part (a lamp, a torch's flame) is emissive");
ok(/const TORCH_LIGHTS = 4/.test(land) && /for \(let i = 0; i < TORCH_LIGHTS; i\+\+\) \{ const l = new THREE\.PointLight/.test(land) && /l\.intensity = w \?/.test(land),
   "torchlight is a fixed pool of point lights, unused ones dark");

// 3b. grass never grows up through a piece lying on the ground (a plank floor in the meadow, the furniture render)
{
  // a meadow spot: grass on top, gentle
  let at = null;
  for (let i = 2; i < 14 && !at; i++) for (let j = 2; j < 14 && !at; j++) {
    const c = Wd.column(0, sp.u0 + i, sp.v0 + j);
    if (c.biome === "grass" && Wd.terrainBlock(0, sp.u0 + i, sp.v0 + j, c.top) === B.grass) at = { i, j, top: c.top };
  }
  const blades = (bx) => {
    let inF = 0, outF = 0;
    for (const ch of [Math.floor(at.top / 16) - 1, Math.floor(at.top / 16), Math.floor(at.top / 16) + 1]) {
      const r = M.meshChunk(0, sp.u0 / 16, sp.v0 / 16, ch, null, bx, 0);
      if (!r.grass) continue;
      for (let k = 0; k < r.grass.inst.length; k += 7) {
        const x = r.anchor[0] + r.grass.inst[k], y = r.anchor[1] + r.grass.inst[k + 1], z = r.anchor[2] + r.grass.inst[k + 2], rr = Math.hypot(x, y, z), g = Wd.gridOf([x / rr, y / rr, z / rr]);
        const lu = g.u - sp.u0, lv = g.v - sp.v0;
        if (lu > at.i - 1 + 0.05 && lu < at.i + 2 - 0.05 && lv > at.j - 1 + 0.05 && lv < at.j + 2 - 0.05) inF++; else outF++;
      }
    }
    return [inF, outF];
  };
  const floor = [(at.i - 1) * 100, (at.j - 1) * 100, (at.top + 1) * 100 - 2, 300, 300, 4, B.planks];
  const [bare] = blades([]), [onF, beside] = blades([floor]);
  ok(at && bare > 10 && onF === 0 && beside > 0, `no blade grows through a floor laid on the meadow (${bare} blades there bare, ${onF} with the floor, ${beside} beside it)`);
}

// 4.
const srv = Number((readFileSync(join(ROOT, "scripts", "land_server.py"), "utf8").match(/^N_BLOCKS = (\d+)/m) || [])[1]);
ok(srv === Wd.BLOCKS.length, `the world server knows every block (${srv})`);
const tr = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
ok(Object.keys(tr).length === 17 && Object.values(tr).every((l) => FURN.every((k) => l["land.i." + k])), "every new item is named in 17 languages");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
