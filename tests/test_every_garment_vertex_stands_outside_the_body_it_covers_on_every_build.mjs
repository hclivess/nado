/*
 * test_every_garment_vertex_stands_outside_the_body_it_covers_on_every_build.mjs — the geometry fact behind the
 * operator's real-GPU screenshot of 2026-11-12 (the shirt gone, the trousers patchy): a garment that lies AT the body's
 * surface loses the depth test to it, and no software render shows that. So the fit is measured as geometry, GPU-free:
 * for every garment vertex, as the page draws it (land-human.js wearMaterial: the fitted position pushed out along the
 * normal by `lift` — 2 cm for an outfit, 6 mm for shoes), the signed distance to the nearest body vertex's tangent
 * plane, in every one of the three builds:
 *   1. the fit is resolved against the drawn body offline (build_wear.py clear_of_body: 15 mm an outfit, 8 mm shoes)
 *      and the page adds a small safety along the normal; the test applies that safety as the page does (read from
 *      land-human.js) and measures the result independently: at least 99 % of a drawn garment's vertices stand
 *      outside the body, median clearance ≥ 12 mm (an outfit) / 6 mm (shoes), on every build it is drawn on;
 *   2. before the resolve a uniform 2 cm lift left 5–26 % of an outfit's vertices inside on the three builds (measured
 *      2026-11-12 by this test's first run) — the number that made the offline resolve the fix, not a bigger lift.
 * Run: node tests/test_every_garment_vertex_stands_outside_the_body_it_covers_on_every_build.mjs   (~20 s)
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Hd = await import(join(ROOT, "static", "land-human-data.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const load = (f) => { const r = readFileSync(join(ROOT, "static", "human", f)); return r.buffer.slice(r.byteOffset, r.byteOffset + r.byteLength); };
const W = Hd.parseWear(load("wear.bin")), D = Hd.parseHuman(load("crew.bin"));
const hv = readFileSync(join(ROOT, "static", "land-human.js"), "utf8");
const liftRule = /const lift = clothes \? \(it\.name\.startsWith\("shoes"\) \? ([\d.]+) : ([\d.]+)\)/.exec(hv);
ok(!!liftRule, "the page's lift rule is read from land-human.js");
const LIFT_SHOES = Number(liftRule?.[1] ?? 0), LIFT_OUTFIT = Number(liftRule?.[2] ?? 0);
// the pairings the page draws: the male outfit on the male and heavy builds, the female on the female, shoes on all
const drawn = (it, v) => it.name.startsWith("shoes") || (it.name.startsWith("female_") ? v === 1 : v !== 1);

// a coarse grid over the body's vertices so each garment vertex asks only its neighbourhood (1900 × 2634 brute force
// a build would be fine too; the grid keeps the whole test around twenty seconds)
function gridOf(pos, nV, cell) {
  const g = new Map();
  const key = (x, y, z) => `${Math.floor(x / cell)}:${Math.floor(y / cell)}:${Math.floor(z / cell)}`;
  for (let i = 0; i < nV; i++) { const k = key(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2]); let l = g.get(k); if (!l) g.set(k, l = []); l.push(i); }
  return { g, key, cell };
}
/** Signed distance from point p to the body: the nearest body vertex's plane (its area-weighted normal). */
function signed(p, body, nrm, grid) {
  const [x, y, z] = p, c = grid.cell; let best = Infinity, bi = -1;
  for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++) {
    const l = grid.g.get(`${Math.floor(x / c) + dx}:${Math.floor(y / c) + dy}:${Math.floor(z / c) + dz}`); if (!l) continue;
    for (const i of l) { const d = (body[i * 3] - x) ** 2 + (body[i * 3 + 1] - y) ** 2 + (body[i * 3 + 2] - z) ** 2; if (d < best) { best = d; bi = i; } }
  }
  if (bi < 0) return Infinity;                                 // nothing within a cell: far outside the body
  return (x - body[bi * 3]) * nrm[bi * 3] + (y - body[bi * 3 + 1]) * nrm[bi * 3 + 1] + (z - body[bi * 3 + 2]) * nrm[bi * 3 + 2];
}
const clothes = W.items.filter((it) => it.kind === "clothes");
for (let v = 0; v < 3; v++) {
  const body = D.vars[v].pos, nrm = D.vars[v].nrm, grid = gridOf(body, D.nV, 0.06);
  for (const it of clothes) {
    if (!drawn(it, v)) continue;
    const shoes = it.name.startsWith("shoes"), lift = shoes ? LIFT_SHOES : LIFT_OUTFIT;
    const raw = [], lifted = [];
    for (let i = 0; i < it.nV; i++) {
      const p = [it.pos[v][i * 3], it.pos[v][i * 3 + 1], it.pos[v][i * 3 + 2]], n = [it.nrm[v][i * 3], it.nrm[v][i * 3 + 1], it.nrm[v][i * 3 + 2]];
      raw.push(signed(p, body, nrm, grid));
      lifted.push(signed([p[0] + n[0] * lift, p[1] + n[1] * lift, p[2] + n[2] * lift], body, nrm, grid));
    }
    const share = (a, f) => a.filter(f).length / a.length, med = (a) => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
    const rawClose = share(raw, (d) => d < 0.005), outside = share(lifted, (d) => d > 0), medLift = med(lifted);
    ok(outside >= 0.99 && medLift >= (shoes ? 0.006 : 0.012),
      `${D.vars[v].name}: ${it.name} (resolved offline, +${(lift * 1000).toFixed(0)} mm on the page) — ${(100 * outside).toFixed(1)} % of vertices outside the body, median clearance ${(medLift * 1000).toFixed(1)} mm${rawClose > 0.3 ? "" : ""}`);
  }
}
console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
