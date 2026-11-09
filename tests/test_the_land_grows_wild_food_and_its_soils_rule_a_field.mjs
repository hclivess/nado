/*
 * test_the_land_grows_wild_food_and_its_soils_rule_a_field.mjs — "we will need all the civilisation essentials like
 * berries, hunting, crops, water, wells…", "farmland, farming, soil types, etc" (operator 2026-11-09; #153, #154,
 * doc/land-civilisation.md). Through static/land-world.js, land-mesher.js and land-recipes.json:
 *   1. the planet grows wild food: berry bushes and stands of wild grain, on the meadows and in the woods — and only where
 *      no older litter stood (a pebble, sticks, flax, a flower are where they were);
 *   2. the ground has soils: all five kinds occur, sand by the sea, stone on the heights, and each has a farming rule —
 *      stony ground cannot be tilled, the rest ripen in their own time and yield their own harvest;
 *   3. drawn: a berry bush, wild grain and a sown field are models (no cube), farmland is smooth ground (no crisp cube),
 *      its earth tinted by its soil;
 *   4. nothing from nothing: berries, grain and seed come from the planet's breaking table, the hoe from a recipe of what
 *      bare hands gather; every new name is in all 17 languages;
 *   5. BREAD AND A WELL (#155): from bare hands, following the rules as a player would, a quern, flour, bread and a well
 *      are reached; only food is eaten, a meal never punishes, and the well is a placed piece with its own name;
 *   6. HUNTING (#156): a spear, a bow, arrows and a tanning rack are reached from bare hands; every species drops real
 *      items and lives in real biomes; cooked meat is food and raw meat is not; every name speaks 17 languages;
 *   7. MARKETS (#161): a trading stand is reached from bare hands and placed whole; a market is local (an offer is made
 *      within a few metres of a stand, seen within tens of metres, never world-wide) and keeps a small share.
 *
 * Run: node tests/test_the_land_grows_wild_food_and_its_soils_rule_a_field.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(ROOT, "static", "land-world.js")), M = await import(join(ROOT, "static", "land-mesher.js"));
const R = JSON.parse(readFileSync(join(ROOT, "static", "land-recipes.json"), "utf8"));
const L10N = JSON.parse(readFileSync(join(ROOT, "static", "i18n_games", "land.json"), "utf8"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const B = W.B;

// 1. wild food
const lit = {}, by = { grass: {}, forest: {} };
for (let du = 0; du < 600; du += 2) for (let dv = 0; dv < 600; dv += 2) {
  const u = 54800 + du, v = 79600 + dv, c = W.column(0, u, v), l = W.litterAt(0, u, v, c);
  if (!l) continue;
  lit[l] = (lit[l] || 0) + 1;
  if (by[c.biome]) by[c.biome][l] = (by[c.biome][l] || 0) + 1;
}
ok(lit[B.wheat] > 50 && lit[B.berrybush] > 50, `wild grain (${lit[B.wheat]}) and berry bushes (${lit[B.berrybush]}) grow on the land`);
ok(by.grass[B.wheat] > 0 && by.grass[B.berrybush] > 0 && (by.forest[B.berrybush] || 0) > 0 && !by.forest[B.wheat],
   "grain in the meadows, berry bushes in meadow and wood");
// the older litter is where it was: the new food is only where the older rule gave nothing (its hash case comes last)
const src = readFileSync(join(ROOT, "static", "land-world.js"), "utf8"), lf = src.slice(src.indexOf("export function litterAt"), src.indexOf("// ---- THE DEEP"));
ok(/FLOWERS\[hash32\(face \+ 67[^\n]*\n[^\n]*\n[^\n]*\n\s*: hash32\(face \+ 71[^\n]*B\.wheat : hh % 97 === 17 \? B\.berrybush : 0;/.test(lf)
   && /hh % 9 === 2 \? B\.twigs : hh % 71 === 13 \? B\.berrybush : 0/.test(lf), "…only where no older litter stood: pebbles, sticks, flax and flowers keep their places");
ok(W.SWEPT.has(B.wheat) && W.SWEPT.has(B.berrybush) && !W.SWEPT.has(B.wheatyoung), "wild food is swept up by a block put there; a sown crop is not");

// 2. soils
const soils = {};
let sea = null, high = null;
for (let i = 0; i < 6000; i++) {
  const f = i % 6, u = (i * 7919 * 13) % W.W, v = (i * 104729 * 7) % W.W, c = W.column(f, u, v);
  if (c.top <= W.SEA) continue;
  const s = W.soilOf(f, u, v, c); soils[s] = (soils[s] || 0) + 1;
  if (c.biome === "beach" && !sea) sea = s;
  if (c.biome === "rock" && !high) high = s;
}
ok(W.SOILS.every((s) => soils[s] > 20), `every soil occurs on the planet: ${JSON.stringify(soils)}`);
ok(sea === "sandy" && high === "stony", `sand by the sea (${sea}), stone on the heights (${high})`);
ok(W.SOILS.every((s) => R.farming.soil[s]) && R.farming.soil.stony.till === false
   && ["loam", "clay", "peat", "sandy"].every((s) => R.farming.soil[s].time > 0 && R.farming.soil[s].grain >= 1 && R.farming.soil[s].seed >= 1),
   "each soil has its farming rule; stony ground is not tilled");
ok(R.farming.soil.loam.time < R.farming.soil.clay.time && R.farming.soil.sandy.grain < R.farming.soil.loam.grain && R.farming.moist < 1,
   "loam is quickest, sand poorest, water near a field speeds it");
ok(W.soilOf(0, 55100, 79700) === W.soilOf(0, 55100, 79700, W.column(0, 55100, 79700)), "a soil is a pure function of the place");

// 3. drawn
const u = 3440 * 16 + 6, v = 4999 * 16 + 3, col = W.column(0, u, v), ch = Math.floor((col.top + 1) / 16);
const mesh = (ed) => M.meshChunk(0, Math.floor(u / 16), Math.floor(v / 16), ch, ed, null, 0);
const verts = (r, k) => (r && r[k] ? r[k].pos.length / 3 : 0);
const base = mesh(new Map());
for (const [b, name] of [[B.berrybush, "a berry bush"], [B.wheat, "wild grain"]]) {
  const r = mesh(new Map([[`0:${u}:${v}:${col.top + 1}`, b]]));
  ok(verts(r, "bark") > verts(base, "bark") + 30 && verts(r, "solid") === verts(base, "solid") && verts(r, "trees") === verts(base, "trees"), `${name} is drawn as its model, no cube`);
}
const field = new Map([[`0:${u}:${v}:${col.top}`, B.farmland]]), sown = new Map([...field, [`0:${u}:${v}:${col.top + 1}`, B.wheatyoung]]);
const rf = mesh(field), rs = mesh(sown), rr = mesh(new Map([...field, [`0:${u}:${v}:${col.top + 1}`, B.wheat]]));
ok(verts(rf, "solid") === verts(base, "solid") && W.NATURAL.has(B.farmland), "farmland is smooth ground, never a crisp cube");
ok(verts(rs, "bark") > verts(rf, "bark") && verts(rr, "bark") > verts(rs, "bark"), `a sown field shows its crop, and ripe wheat is more of it (${verts(rs, "bark") - verts(rf, "bark")} → ${verts(rr, "bark") - verts(rf, "bark")} vertices)`);
// the colour of the ground drawn over a tilled cell, measured: a loam field and a clay field, each a 3 x 3 patch
const fieldColour = (fu, fv) => {
  const c = W.column(0, fu, fv), ed = new Map();
  for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) ed.set(`0:${fu + a}:${fv + b}:${W.column(0, fu + a, fv + b).top}`, B.farmland);
  const r = M.meshChunk(0, Math.floor(fu / 16), Math.floor(fv / 16), Math.floor(c.top / 16), ed, null, 0), P = r.smooth.pos, C = r.smooth.col, A = r.anchor;
  const up = W.frameOf(0, fu + 0.5, fv + 0.5).up, R0 = W.R0, centre = W.posOf(0, fu + 0.5, fv + 0.5, c.top + 1);
  let rs = 0, bs = 0, n = 0;
  for (let i = 0; i < P.length; i += 3)
    if (Math.hypot(P[i] + A[0] - centre[0], P[i + 1] + A[1] - centre[1], P[i + 2] + A[2] - centre[2]) < 0.9) { rs += C[i]; bs += C[i + 2]; n++; }
  return n ? rs / bs : null;
};
const find = (want) => { for (let du = 0; du < 2000; du++) { const fu = 55100 + du, fv = 79720, c = W.column(0, fu, fv);
  if (c.top > W.SEA && Math.floor(c.top / 16) === Math.floor((c.top + 1) / 16) && [-1, 0, 1].every((a) => W.soilOf(0, fu + a, fv) === want && W.soilOf(0, fu + a, fv + 1) === want && W.soilOf(0, fu + a, fv - 1) === want)) return [fu, fv]; } };
const lo = find("loam"), cl = find("clay"), qL = lo && fieldColour(...lo), qC = cl && fieldColour(...cl);
ok(qL && qC && qC > qL * 1.15, `a field's earth is tinted by its soil: clay redder than loam (red/blue ${qL && qL.toFixed(2)} vs ${qC && qC.toFixed(2)})`);

// 4. nothing from nothing; names
const yields = (b) => (R.breaking[String(b)] || {}).yields || [];
ok(yields(B.berrybush).some(([i]) => i === "berries") && yields(B.wheat).some(([i]) => i === "grain") && yields(B.wheat).some(([i]) => i === "seed")
   && !R.breaking[String(B.berrybush)].needs && !R.breaking[String(B.wheat)].needs, "berries, grain and seed are gathered by hand from the planet");
const hoe = R.recipes.find((r) => r.makes[0][0] === "hoe");
ok(hoe && R.tools.hoe.class === "hoe" && hoe.uses.every(([i]) => ["sticks", "stone", "cordage"].includes(i)) && !(hoe.with || []).length,
   "the hoe is made from sticks, stone and cordage, by hand");
ok(R.items.seed.places === B.wheatyoung && !Object.values(R.items).some((it) => it.places === B.farmland || it.places === B.wheat),
   "seed sows a crop; nothing places farmland or ripe wheat (a hoe tills, time ripens)");
const keys = ["land.i.berries", "land.i.grain", "land.i.seed", "land.t.hoe", "land.b.berrybush", "land.b.wheat", "land.b.wheatyoung", "land.b.farmland",
  "land.soilLoam", "land.soilClay", "land.soilPeat", "land.soilSandy", "land.soilStony", "land.tillNeedsHoe", "land.tillOpen", "land.tilled", "land.tillMoist", "land.tillSow", "land.cAimSoil"];
const langs = Object.keys(L10N);
ok(langs.length === 17 && langs.every((l) => keys.every((k) => L10N[l][k])), `every new name and line is in all 17 languages (${langs.length})`);
ok(langs.every((l) => L10N[l]["land.tilled"].includes("{s}") && L10N[l]["land.cAimSoil"].includes("{s}")), "…with its placeholder kept");

// 5. bread and a well, reached from bare hands as the X fighter's parts are (its test's loop)
const have = new Set(), tools = new Set(), stations = new Set();
const hasClass = (c) => [...tools].some((t) => t === c || R.tools[t].class === c);
for (let grew = true, n = 0; grew && n++ < 60;) {
  grew = false;
  for (const [, rule] of Object.entries(R.breaking)) {
    if (typeof rule !== "object" || !rule.yields || (rule.needs && !hasClass(rule.needs))) continue;
    for (const [id] of rule.yields) if (!have.has(id)) { have.add(id); grew = true; }
  }
  for (const r of R.recipes) {
    if (!r.uses.every(([id]) => have.has(id)) || !(r.with || []).every((w) => stations.has(w) || hasClass(w))) continue;
    for (const [id] of r.makes) { const set = id in R.tools ? tools : id in R.stations ? stations : have; if (!set.has(id)) { set.add(id); grew = true; } }
  }
}
ok(stations.has("quern") && have.has("flour") && have.has("bread") && have.has("well"), "a quern, flour, bread and a well are reached from bare hands");
ok(Object.keys(R.food.items).every((i) => R.items[i]) && R.food.work < 1 && R.food.work > 0 && !("hunger" in R.food),
   "only real items are food, and a meal speeds work — there is no hunger to punish");
ok(R.items.well.places === B.well && R.items.well.unit && W.BLOCKS[B.well].solid, "a well is placed whole, as a piece");
const keys5 = ["land.i.flour", "land.i.bread", "land.i.well", "land.s.quern", "land.eatIt", "land.fedFor", "land.ate", "land.wellBucket"];
ok(langs.every((l) => keys5.every((k) => L10N[l][k])) && langs.every((l) => L10N[l]["land.eatIt"].includes("{i}") && L10N[l]["land.fedFor"].includes("{m}")),
   "bread, the quern, the well and eating speak all 17 languages, placeholders kept");

// 6. hunting
const Hn = R.hunting, biomes = new Set(["grass", "forest", "snow", "desert", "beach", "rock"]);
ok(tools.has("spear") && tools.has("bow") && have.has("arrow") && stations.has("tanning_rack"), "a spear, a bow, arrows and a tanning rack are reached from bare hands");
ok(Object.values(Hn.species).every((sp) => sp.hp > 0 && sp.speed > 0 && sp.drops.every(([i, n]) => R.items[i] && n > 0) && sp.biomes.every((b) => biomes.has(b))),
   "every species lives in real biomes and drops real items");
ok(R.food.items.cooked_meat > 0 && !R.food.items.meat && R.recipes.some((r) => r.makes[0][0] === "cooked_meat" && (r.with || []).includes("campfire"))
   && R.recipes.some((r) => r.makes[0][0] === "leather" && r.uses.some(([i]) => i === "hide")), "meat is cooked before it is eaten; hide tans into leather");
ok(Hn.weapons.spear.reach < Hn.weapons.bow.reach && Hn.weapons.bow.ammo === "arrow" && Hn.flee > Hn.weapons.spear.reach,
   "a spear is close work (an animal runs before it is that close), a bow reaches far and spends arrows");
const keys6 = ["land.i.meat", "land.i.cooked_meat", "land.i.hide", "land.i.bone", "land.i.leather", "land.i.arrow", "land.t.spear", "land.t.bow", "land.s.tanning_rack",
  ...Object.keys(Hn.species).map((k) => "land.a." + k), "land.huntNeeds", "land.huntFar", "land.huntArrows", "land.huntKilled", "land.huntHit"];
ok(langs.every((l) => keys6.every((k) => L10N[l][k])) && langs.every((l) => L10N[l]["land.huntKilled"].includes("{a}") && L10N[l]["land.huntHit"].includes("{a}")),
   "hunting speaks all 17 languages, placeholders kept");

// 7. markets
const MK = R.market;
ok(have.has("stand") && R.items.stand.places === B.stand && R.items.stand.unit && W.BLOCKS[B.stand].solid, "a trading stand is reached from bare hands and placed whole");
ok(MK.at > 0 && MK.at < 20 && MK.reach > MK.at && MK.reach <= 256 && MK.hand > 0 && MK.hand < 20 && MK.fee > 0 && MK.fee < 0.2,
   `a market is local: offers made within ${MK.at} m of a stand, seen within ${MK.reach} m, gifts in person (${MK.hand} m); it keeps ${MK.fee * 100}%`);
const keys7 = ["land.i.stand", "land.mkHere", "land.mkNoStand", "land.mkOld", "land.giftNear"];
ok(langs.every((l) => keys7.every((k) => L10N[l][k])) && langs.every((l) => L10N[l]["land.mkHere"].includes("{m}") && L10N[l]["land.mkHere"].includes("{p}")),
   "the market speaks all 17 languages, placeholders kept");

if (fails) { console.log(`${fails} FAILURES`); process.exit(1); }
console.log("ALL PASS");
