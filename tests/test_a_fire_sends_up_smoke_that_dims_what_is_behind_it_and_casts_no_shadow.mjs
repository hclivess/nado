/*
 * test_a_fire_sends_up_smoke_that_dims_what_is_behind_it_and_casts_no_shadow.mjs — fire (#124) was to be "rendered as
 * flames + smoke + light"; flames and light shipped and smoke was left open. Here:
 *   1. the real mesher (static/land-mesher.js) gives a burning cell its smoke: two crossed cards rising from the flames'
 *      tips, wider at the top than at the base, SMOKE_H metres tall; a chunk with no fire has none (and is still empty);
 *   2. the page draws them in a grey smoke material that is NOT additive (smoke dims what is behind it; a flame lights
 *      it), see-through, both sides, drawn after the flames — and, like the flames, it casts and takes no shadow;
 *   3. the material count the /tris command reports names the smoke.
 * Run: node tests/test_a_fire_sends_up_smoke_that_dims_what_is_behind_it_and_casts_no_shadow.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const W = await import(join(ROOT, "static", "land-world.js"));
const M = await import(join(ROOT, "static", "land-mesher.js"));
const page = readFileSync(join(ROOT, "static", "land.js"), "utf8");
const mesher = readFileSync(join(ROOT, "static", "land-mesher.js"), "utf8");
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };

// 1
const sp = W.plotCoords(W.plotId(0, W.SPAWN_PLOT_ROW, W.SPAWN_PLOT_COL)), u = sp.u0 + 8, v = sp.v0 + 8, h = W.column(0, u, v).top + 1;
const at = [0, Math.floor(u / 16), Math.floor(v / 16), Math.floor(h / 16)];
const lit = M.meshChunk(...at, new Map([[`0:${u}:${v}:${h}`, W.B.fire]]), null, 0);
const cold = M.meshChunk(...at, new Map(), null, 0);
const sm = lit.smoke;
ok(sm && sm.pos.length / 3 === 8 && sm.idx.length === 12, "a burning cell sends up smoke: two crossed cards (8 corners, 4 triangles) — " + (sm ? sm.pos.length / 3 : "none"));
ok(!cold.smoke || cold.empty || cold.smoke.pos.length === 0, "…and a chunk with no fire has none");
const H = Number((mesher.match(/const SMOKE_H = (\d+(?:\.\d+)?);/) || [])[1]);
if (sm) {
  // corners in order base, base, top, top per card; uv.y is 0 at the base and 1 at the top
  const uvy = []; for (let i = 0; i < sm.pos.length / 3; i++) uvy.push(sm.uv[i * 2 + 1]);
  // the planet's up is not one axis of the chunk's frame: the rise is the distance from the base's middle to the top's
  const mid = (i, j) => [0, 1, 2].map((k) => (sm.pos[i * 3 + k] + sm.pos[j * 3 + k]) / 2), b0 = mid(0, 1), t0 = mid(2, 3);
  const rise = Math.hypot(t0[0] - b0[0], t0[1] - b0[1], t0[2] - b0[2]);
  ok(H > 0 && Math.abs(rise - H) < 0.05, `…rising SMOKE_H metres over the flames (SMOKE_H ${H}; the column rises ${rise.toFixed(2)})`);
  const span = (i, j) => Math.hypot(sm.pos[i * 3] - sm.pos[j * 3], sm.pos[i * 3 + 1] - sm.pos[j * 3 + 1], sm.pos[i * 3 + 2] - sm.pos[j * 3 + 2]);
  ok(span(2, 3) > span(0, 1) * 1.5, `…and wider at the top than over the flames (${span(0, 1).toFixed(2)} → ${span(2, 3).toFixed(2)})`);
  ok(uvy[0] === 0 && uvy[2] === 1, "…its uv running from 0 at the base to 1 at the top, for the material's fade");
}
// 2
const mat = (page.match(/matSmoke = new THREE\.MeshBasicNodeMaterial\(\{([^}]*)\}\)/) || [])[1] || "";
ok(/transparent: true/.test(mat) && /depthWrite: false/.test(mat) && /side: THREE\.DoubleSide/.test(mat), "smoke is see-through, seen from both sides, and writes no depth");
ok(!/AdditiveBlending/.test(mat), "…and NOT additive: smoke dims what is behind it, where a flame lights it");
{ const g = (page.match(/matSmoke\.colorNode = TSL\.mix\(TSL\.vec3\(([\d.]+), ([\d.]+), ([\d.]+)\), TSL\.vec3\(([\d.]+), ([\d.]+), ([\d.]+)\)/) || []).slice(1).map(Number);
  ok(g.length === 6 && g.every((x) => x > 0.25 && x < 0.8) && Math.max(...g.slice(0, 3)) - Math.min(...g.slice(0, 3)) < 0.05 && g[3] > g[0],
    "…grey (no colour cast), never black, darker at the fire and paler as it rises: " + g.join(", ")); }
ok(page.includes("if (m.smoke) { const me = new THREE.Mesh(geom(m.smoke), matSmoke); me.renderOrder = 3;") && page.includes("me.renderOrder = 2; c.meshes.push(me); }"),
  "the page draws a chunk's smoke after its flames (render order 3 over 2)");
ok(page.includes("const glow = me.material === matFlame || me.material === matSmoke;") && page.includes("!glow && !me.isInstancedMesh; me.receiveShadow = !glow;"),
  "…and, like the flames, it casts no shadow and takes none");
// 3
ok(page.includes('[matSmoke, "smoke"]'), "the /tris count names the smoke");

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
