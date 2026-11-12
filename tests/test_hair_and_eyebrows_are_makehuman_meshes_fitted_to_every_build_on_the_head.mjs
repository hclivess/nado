/*
 * test_hair_and_eyebrows_are_makehuman_meshes_fitted_to_every_build_on_the_head.mjs — #172 step 2 ("the characters look
 * total garbage"; step 1 left the hair a colour on the scalp). static/human/wear.bin as tools/human/build_wear.py writes
 * it from MakeHuman's CC0 proxies, read by static/land-human-data.js parseWear, held against crew.bin's body:
 *   1. the file parses: seven hair styles and an eyebrow, each with a texture file that exists beside it, uv in 0..1,
 *      a triangle index within its vertices, four bone weights a vertex summing to one;
 *   2. fitted to EVERY build: in each of the three builds a hair's crown is on the head (its top within 0.2 m over the
 *      head joint, a vertex within 0.1 m of it), a short style lies within 0.45 m of the joint, a long one (long01,
 *      braid01, ponytail01) hangs down the back no lower than 0.6 m under the neck (MakeHuman's long01 reaches the
 *      waist) — and the eyebrow sits over the eyes, in front of the head joint;
 *   3. skinned to the head: nearly all of a short style's weight is on the head and neck bones, a long style's on the
 *      head-to-spine chain (the strands lie on the back), so it turns with the look and bends with the body;
 *   4. the look picks a style: hairStyleOf is in range for every face and body choice and the same choice gives the same
 *      style on every page.
 * Run: node tests/test_hair_and_eyebrows_are_makehuman_meshes_fitted_to_every_build_on_the_head.mjs
 */
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Hd = await import(join(ROOT, "static", "land-human-data.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const load = (f) => { const r = readFileSync(join(ROOT, "static", "human", f)); return r.buffer.slice(r.byteOffset, r.byteOffset + r.byteLength); };
const W = Hd.parseWear(load("wear.bin")), D = Hd.parseHuman(load("crew.bin"));

// 1. the file
const hair = W.items.filter((it) => it.kind === "hair"), brows = W.items.filter((it) => it.kind === "eyebrows");
ok(hair.length === 7 && brows.length === 1, `${hair.length} hair styles and ${brows.length} eyebrow: ${W.items.map((i) => i.name).join(", ")}`);
ok(W.items.every((it) => existsSync(join(ROOT, "static", "human", it.tex))), "every item's texture file exists beside it");
ok(W.items.every((it) => it.uv.every((u) => u >= -1e-6 && u <= 1 + 1e-6)), "uv within 0..1");
ok(W.items.every((it) => it.idx.every((i) => i < it.nV) && it.idx.length === it.nT * 3), "the triangle index stays within the vertices");
let wBad = 0;
for (const it of W.items) for (let i = 0; i < it.nV; i++) { let s = 0; for (let j = 0; j < 4; j++) s += it.skinW[i * 4 + j]; if (Math.abs(s - 255) > 3) wBad++; }
ok(wBad === 0, `four bone weights a vertex summing to one (${wBad} do not)`);
ok(/CC0/.test(W.licence || ""), "the file names its licence: " + (W.licence || "").slice(0, 60));

// 2. fitted to every build
const LONG = new Set(["long01", "braid01", "ponytail01"]);
const dist = (p, i, q) => Math.hypot(p[i * 3] - q[0], p[i * 3 + 1] - q[1], p[i * 3 + 2] - q[2]);
for (let v = 0; v < 3; v++) {
  const head = D.vars[v].heads[Hd.B.head], neck = D.vars[v].heads[Hd.B.neck];
  for (const it of hair) {
    let far = 0, top = -9, low = 9, near = 9;
    for (let i = 0; i < it.nV; i++) { const d = dist(it.pos[v], i, head), y = it.pos[v][i * 3 + 1]; if (d > 0.45) far++; top = Math.max(top, y); low = Math.min(low, y); near = Math.min(near, d); }
    const long = LONG.has(it.name);
    ok(top > head[1] && top < head[1] + 0.2 && near < 0.1 && (long ? low > neck[1] - 0.6 : far / it.nV < 0.05),
      `${D.vars[v].name}: ${it.name} sits on the head (top ${(top - head[1]).toFixed(2)} m over the joint, nearest ${near.toFixed(2)} m; ${long ? `hangs to ${(neck[1] - low).toFixed(2)} m under the neck` : `${far} of ${it.nV} vertices farther than 0.45 m`})`);
  }
  const b = brows[0];
  let front = 0, up = 0;
  for (let i = 0; i < b.nV; i++) { if (b.pos[v][i * 3 + 2] > head[2]) front++; if (b.pos[v][i * 3 + 1] > head[1]) up++; }
  ok(front === b.nV && up === b.nV && (() => { let d = 0; for (let i = 0; i < b.nV; i++) d = Math.max(d, dist(b.pos[v], i, head)); return d < 0.2; })(), `${D.vars[v].name}: the eyebrow sits in front of and above the head joint, within 0.2 m`);
}

// 3. skinned to the head
for (const it of W.items) {
  const chain = LONG.has(it.name) ? [Hd.B.head, Hd.B.neck, Hd.B.chest, Hd.B.spine] : [Hd.B.head, Hd.B.neck];
  let headW = 0, total = 0;
  for (let i = 0; i < it.nV; i++) for (let j = 0; j < 4; j++) { const w = it.skinW[i * 4 + j]; total += w; if (chain.includes(it.skinI[i * 4 + j])) headW += w; }
  ok(headW / total > (chain.length > 2 ? 0.85 : 0.9), `${it.name}: ${(100 * headW / total).toFixed(0)} % of its weight is on the ${chain.length > 2 ? "head-to-spine chain" : "head and neck bones"}`);
}

// 4. the look picks a style
let inRange = true;
for (let face = 0; face < 6; face++) for (let body = 0; body < 3; body++) { const s = Hd.hairStyleOf({ face, body }, hair.length); if (!(s >= 0 && s < hair.length)) inRange = false; }
ok(inRange && Hd.hairStyleOf({ face: 2, body: 1 }, 7) === Hd.hairStyleOf({ face: 2, body: 1 }, 7) && Hd.hairStyleOf(null, 0) === -1, "every face and body choice names a style, the same on every page; no styles, no hair");
const styles = new Set(); for (let face = 0; face < 6; face++) styles.add(Hd.hairStyleOf({ face, body: 0 }, 7));
ok(styles.size >= 5, `the six face choices reach ${styles.size} different styles`);

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
