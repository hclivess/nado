/*
 * test_the_human_body_is_makehumans_with_real_proportions_regions_and_a_gait.mjs — #172 ("the characters look total
 * garbage nobody is gonna play this", operator 2026-11-10). static/human/crew.bin + static/land-human-data.js, in node:
 *   1. the body file parses: the MakeHuman body on the 21-bone game skeleton, three builds, two LODs sharing one vertex
 *      buffer (LOD1's indices all within LOD0's vertices), four bone weights a vertex that sum to one;
 *   2. the builds have a person's proportions: 1.5–1.95 m tall, the neck joint to the crown 1/6–1/9 of the whole (the
 *      issue: "proportions from the MakeHuman base (head ≈ 1/7.5 of height)" — measured chin to crown; the neck joint
 *      sits below the chin, so this measure runs larger: male 1/6.9, female 1/6.3, heavy 1/6.9), the hips about half
 *      way up, arms that reach the thighs, legs with a thigh and a shank of a like length;
 *   3. every clothing region is present on the body, the hands and head are skin, the eyes are eyes, and a hem blends
 *      (some vertices mix a neighbouring region);
 *   4. the look maps onto the regions: a player's skin, top, legs and hair colours land where the issue says, in linear
 *      light; body 1 is the female build;
 *   5. the gait: standing, the feet are a stance apart and flat; walking, they alternate ahead and behind, lifted only
 *      in the swing, the hands swinging against the legs; the cycle repeats every WALK_CYCLE metres.
 * Run: node tests/test_the_human_body_is_makehumans_with_real_proportions_regions_and_a_gait.mjs
 */
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const Hd = await import(join(ROOT, "static", "land-human-data.js"));
let fails = 0;
const ok = (c, m) => { console.log((c ? "ok   " : "FAIL ") + m); if (!c) fails++; };
const raw = readFileSync(join(ROOT, "static", "human", "crew.bin"));
const D = Hd.parseHuman(raw.buffer.slice(raw.byteOffset, raw.byteOffset + raw.byteLength));

// 1. the file
ok(D.nV > 2000 && D.nV < 4000 && D.bones.length === Hd.NB && D.bones[0] === "hips" && D.bones[Hd.B.ft[1]] === "foot.R", `the body: ${D.nV} vertices on ${D.bones.length} bones (${D.bones[0]} … ${D.bones[Hd.NB - 1]})`);
ok(D.vars.length === 3 && D.lod0.length === 5200 * 3 && D.lod1.length === 1100 * 3, `three builds (${D.vars.map((v) => v.name).join(", ")}), LOD0 ${D.lod0.length / 3} and LOD1 ${D.lod1.length / 3} triangles`);
let lodOk = true; for (const i of D.lod1) if (i >= D.nV) lodOk = false;
ok(lodOk, "LOD1 indexes LOD0's own vertices (one vertex buffer)");
let wBad = 0; for (let i = 0; i < D.nV; i++) { let s = 0; for (let j = 0; j < 4; j++) s += D.skinW[i * 4 + j]; if (Math.abs(s - 255) > 2) wBad++; }
ok(wBad === 0, `four bone weights a vertex, summing to one (${wBad} do not)`);
ok(D.licence == null || /CC0/i.test(JSON.stringify(D.licence)), "the file carries its CC0 licence: " + JSON.stringify(D.licence).slice(0, 80));

// 2. proportions
for (const v of D.vars) {
  const H = v.heads, hips = H[Hd.B.hips], head = H[Hd.B.head], neck = H[Hd.B.neck], foot = H[Hd.B.ft[0]];
  const top = v.height, headH = top - neck[1];
  ok(top > 1.5 && top < 1.95, `${v.name}: ${top.toFixed(2)} m tall`);
  ok(top / headH > 6 && top / headH < 9, `…the head (neck joint to crown ${headH.toFixed(2)} m) is 1/${(top / headH).toFixed(1)} of the height`);
  ok(hips[1] / top > 0.45 && hips[1] / top < 0.6, `…the hips ${(hips[1] / top * 100).toFixed(0)} % of the way up`);
  const L = (a, b) => Math.hypot(H[a][0] - H[b][0], H[a][1] - H[b][1], H[a][2] - H[b][2]);
  const arm = L(Hd.B.ua[0], Hd.B.fa[0]) + L(Hd.B.fa[0], Hd.B.hd[0]), thigh = L(Hd.B.th[0], Hd.B.sn[0]), shank = L(Hd.B.sn[0], Hd.B.ft[0]);
  ok(arm > 0.4 && arm < 0.7 && thigh / shank > 0.8 && thigh / shank < 1.3, `…an arm of ${arm.toFixed(2)} m, a thigh of ${thigh.toFixed(2)} and a shank of ${shank.toFixed(2)}`);
  ok(foot[1] < 0.15 && head[1] > neck[1], "…the feet at the ground, the head over the neck");
}

// 3. regions
const counts = new Array(Hd.REGIONS.length).fill(0);
for (let i = 0; i < D.nV; i++) if (D.region[i] < counts.length) counts[D.region[i]]++;
ok(counts.every((c) => c > 0), `every region is on the body: ${Hd.REGIONS.map((r, i) => r + " " + counts[i]).join(", ")}`);
const regionOfBone = (bone) => { const c = new Map(); for (let i = 0; i < D.nV; i++) { let w = 0; for (let j = 0; j < 4; j++) if (D.skinI[i * 4 + j] === bone) w += D.skinW[i * 4 + j]; if (w > 200) c.set(D.region[i], (c.get(D.region[i]) || 0) + 1); } return [...c.entries()].sort((a, b) => b[1] - a[1])[0][0]; };
ok(Hd.REGIONS[regionOfBone(Hd.B.hd[0])] === "hands" && Hd.REGIONS[regionOfBone(Hd.B.sn[0])] !== "skin", `the hands are the hands region, the shins are clothed (${Hd.REGIONS[regionOfBone(Hd.B.sn[0])]})`);
let mixed = 0; for (let i = 0; i < D.nV; i++) if (D.mix[i] > 0.1) mixed++;
ok(mixed > 50, `${mixed} vertices blend a neighbouring region across a hem`);

// 4. the look
const kit = Hd.kitOf({ skin: 0xe0ac86, top: 0x7c2b2b, legs: 0x22262d, hair: 0x3b2617, cap: null, cloak: null });
const lin = (hex, s) => { const c = ((hex >> s) & 255) / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
ok(Math.abs(kit[0] - lin(0xe0ac86, 16)) < 1e-6 && Math.abs(kit[6 * 4] - lin(0xe0ac86, 16)) < 1e-6, "the skin colour goes to the skin and the hands, in linear light");
ok(Math.abs(kit[1 * 4] - lin(0x7c2b2b, 16)) < 1e-6 && Math.abs(kit[2 * 4 + 2] - lin(0x22262d, 0)) < 1e-6 && Math.abs(kit[5 * 4 + 1] - lin(0x3b2617, 8)) < 1e-6, "the top is the jacket, the legs the trousers, the hair the hair");
ok(Math.abs(kit[4 * 4] - kit[5 * 4]) < 1e-9 && Math.abs(Hd.kitOf({ skin: 1, top: 1, legs: 1, hair: 0x3b2617, cap: 0xd8d6cf })[4 * 4] - lin(0xd8d6cf, 16)) < 1e-6, "the crown is the hair, or the cap when one is worn");
ok(Hd.variantOf({ body: 1 }) === 1 && Hd.variantOf({ body: 0 }) === 0 && Hd.variantOf(null) === 0 && D.vars[1].name.includes("f"), `body 1 is the female build (${D.vars[1].name})`);

// 5. the gait
const stand = Hd.gait(0, 0);
ok(stand.every((g) => g.lift === 0 && g.along === 0) && Math.abs(stand[0].lat - stand[1].lat - Hd.STANCE_W) < 1e-9, `standing: the feet ${Hd.STANCE_W} m apart, flat, side by side`);
const w1 = Hd.gait(Math.PI / 2, 1), w2 = Hd.gait((3 * Math.PI) / 2, 1);
ok(w1[0].along > 0.15 && w1[1].along < -0.15 && w2[0].along < -0.15 && w2[1].along > 0.15, "walking: one foot ahead, the other behind, and they change over half a cycle later");
const mid = Hd.gait(0, 1);                       // mid-swing of foot 0 (its reach changing fastest), mid-stance of foot 1
ok(mid[0].lift > 0.05 && mid[1].lift === 0 && w1[0].lift < 1e-9, `…the foot in its swing lifted (${mid[0].lift.toFixed(2)} m at mid-swing, down again as it reaches ahead), the stance foot flat`);
ok(Math.sign(w1[0].hand) === -Math.sign(w1[0].along) && Math.abs(w1[0].hand) > 0.15, "…the hand swings against its own leg");
const g0 = Hd.gait(1.234, 1), g1 = Hd.gait(1.234 + 2 * Math.PI, 1);
ok(Math.abs(g0[0].along - g1[0].along) < 1e-9 && Math.abs(g0[1].lift - g1[1].lift) < 1e-9, `the cycle repeats every ${Hd.WALK_CYCLE} m (2π of phase)`);
ok(Math.abs(w1[0].lat - w1[1].lat - Hd.STEP_W) < 1e-9, `…with the feet ${Hd.STEP_W} m apart (Donelan, Kram & Kuo 2001)`);

console.log(fails ? `${fails} FAILED` : "all passed");
process.exit(fails ? 1 : 0);
