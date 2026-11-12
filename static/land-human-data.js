// land-human-data.js — THE HUMAN BODY'S DATA (#172; operator 2026-11-10: "the characters look total garbage nobody is
// gonna play this"; 2026-11-12: "you still havent swapped the character models"). Pure: no three.js, so node reads it
// (the test) and the page's renderer (land-human.js) builds its geometry from it.
//
// The body is MakeHuman's (CC0 1.0): the hm08 base mesh, its default skeleton and skin weights and three macro targets
// (caucasian male/female young, african male young), decimated to a 5,200-triangle LOD0 and a 1,100-triangle LOD1 on a
// 21-bone game skeleton by the operator's own converter (True Wind tools/human/build_crew.py, mirrored at
// /root/land-research/human/truewind-build_crew.py) into static/human/crew.bin — the very file True Wind's crew is drawn
// from (mirror: /root/land-research/human/truewind-crew.bin, sha256 6d17ea09061fc2c2d8c7…; provenance and the CC0
// licence text: truewind-SOURCES-makehuman.md there; the MakeHuman commit a8bc2d54ff0ac92e78ff71431b1023eda42bf482).
// Every vertex carries a CLOTHING REGION (skin, jacket, trousers, boots, crown, hair, hands, eye, trim) the renderer
// colours from the player's own look — the clothes are the body's own surface pushed out by the cloth's thickness.
//
// File layout (little-endian): 'TWH1', u32 json length, the json, then the buffers at the offsets it gives; vertex
// positions as int16 × posScale per variant; LOD1's index is a subset of LOD0's vertices (one vertex buffer).
export const MAGIC = 0x31485754;             // 'TWH1'
export const NB = 21;
/** The game skeleton's bones, by index (crew.bin "bones"): hips, spine, chest, neck, head, then per side L/R. */
export const B = { hips: 0, spine: 1, chest: 2, neck: 3, head: 4, sh: [5, 6], ua: [7, 8], fa: [9, 10], hd: [11, 12], fg: [13, 14], th: [15, 16], sn: [17, 18], ft: [19, 20] };
export const REGIONS = ["skin", "jacket", "trousers", "boots", "crown", "hair", "hands", "eye", "trim"];
/** The texture row a figure owns: 21 bones × 3 texels (the rows of a 3×4 matrix), one texel of info (the variant), then
 *  nine region colours (rgb + roughness). */
export const ROW_TEXELS = NB * 3 + 1 + REGIONS.length;

/** The parsed body: { nV, lod0, lod1 (Uint16 indices), skinI (4 bone indices a vertex), skinW (4 weights, 0..255),
 *  region (a byte a vertex), reg2 / mix (the neighbouring region blended in across a hem), vars[3] { name, pos, nrm, heads,
 *  tails, height, eyes, toes }, bones, parents, licence }. The hem blend and the normals are computed here, once. */
export function parseHuman(buf) {
  const dv = new DataView(buf);
  if (dv.getUint32(0, true) !== MAGIC) throw new Error("crew.bin: bad magic");
  const n = dv.getUint32(4, true), hdr = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 8, n))), o = 8 + n;
  const view = (T, [off, len]) => new T(buf, o + off, len / T.BYTES_PER_ELEMENT);
  const nV = hdr.nV, lod0 = view(Uint16Array, hdr.buf.lod0), lod1 = view(Uint16Array, hdr.buf.lod1);
  const vars = hdr.variants.map((v) => {
    const q = view(Int16Array, v.pos), p = new Float32Array(nV * 3);
    for (let i = 0; i < p.length; i++) p[i] = q[i] * hdr.posScale;
    const nr = new Float32Array(nV * 3);                      // area-weighted over LOD0's faces
    for (let k = 0; k < lod0.length; k += 3) {
      const i = lod0[k] * 3, j = lod0[k + 1] * 3, l = lod0[k + 2] * 3;
      const ux = p[j] - p[i], uy = p[j + 1] - p[i + 1], uz = p[j + 2] - p[i + 2], vx = p[l] - p[i], vy = p[l + 1] - p[i + 1], vz = p[l + 2] - p[i + 2];
      const cx = uy * vz - uz * vy, cy = uz * vx - ux * vz, cz = ux * vy - uy * vx;
      for (const t of [i, j, l]) { nr[t] += cx; nr[t + 1] += cy; nr[t + 2] += cz; }
    }
    for (let i = 0; i < nV; i++) { const L = Math.hypot(nr[i * 3], nr[i * 3 + 1], nr[i * 3 + 2]) || 1; nr[i * 3] /= L; nr[i * 3 + 1] /= L; nr[i * 3 + 2] /= L; }
    return { name: v.name, pos: p, nrm: nr, heads: v.heads, tails: v.tails, height: v.height, eyes: v.eyes, toes: v.toes };
  });
  // soft clothing borders: each vertex also carries the region most of its other neighbours are in, and how much of it
  // to mix in (up to half, at a vertex whose whole ring is the other region) — the colours blend across a hem
  const region = view(Uint8Array, hdr.buf.region), reg2 = new Uint8Array(nV), mix = new Float32Array(nV);
  const cnt = new Float32Array(nV * 16), tot = new Float32Array(nV);
  for (let k = 0; k < lod0.length; k += 3) for (let a = 0; a < 3; a++) for (let c = 0; c < 3; c++) if (a !== c) { const i = lod0[k + a], j = lod0[k + c]; cnt[i * 16 + region[j]]++; tot[i]++; }
  for (let i = 0; i < nV; i++) {
    let best = region[i], bc = 0;
    for (let r = 0; r < 16; r++) if (r !== region[i] && cnt[i * 16 + r] > bc) { bc = cnt[i * 16 + r]; best = r; }
    reg2[i] = best; mix[i] = region[i] === 7 || best === 7 ? 0 : (0.5 * bc) / Math.max(1, tot[i]);   // (an eye keeps its own colour)
  }
  return { nV, lod0, lod1, skinI: view(Uint8Array, hdr.buf.skinI), skinW: view(Uint8Array, hdr.buf.skinW), region, reg2, mix, vars,
    bones: hdr.bones, parents: hdr.parents, licence: hdr.licence || null };
}

// ---- WEAR (#172 step 2): hair and eyebrows as meshes — MakeHuman's CC0 proxies fitted to the body's three builds by
// tools/human/build_wear.py into static/human/wear.bin ('NHW1', u32 json length, json, buffers). Each item: vertices
// split by (vertex, uv), positions per build (int16 × posScale, the body's own frame), normals per build, four bone
// indices and weights on the same 21 bones, a triangle index, its texture's file. The page draws an item for every
// figure wearing it in one instanced draw, skinned from the figure's own texture row like the body.
export const WEAR_MAGIC = 0x3157484e;        // 'NHW1'
export function parseWear(buf) {
  const dv = new DataView(buf);
  if (dv.getUint32(0, true) !== WEAR_MAGIC) throw new Error("wear.bin: bad magic");
  const n = dv.getUint32(4, true), hdr = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 8, n))), o = 8 + n;
  const view = (T, [off, len]) => new T(buf, o + off, len / T.BYTES_PER_ELEMENT);
  const items = hdr.items.map((it) => ({
    kind: it.kind, name: it.name, nV: it.nV, nT: it.nT, tex: it.tex, lum: it.lum || 0.5,
    pos: it.variants.map((v) => { const q = view(Int16Array, v.pos), p = new Float32Array(it.nV * 3); for (let i = 0; i < p.length; i++) p[i] = q[i] * it.posScale; return p; }),
    nrm: it.variants.map((v) => view(Float32Array, v.nrm)),
    uv: view(Float32Array, it.uv), skinI: view(Uint8Array, it.skinI), skinW: view(Uint8Array, it.skinW),
    idx: view(it.idx32 ? Uint32Array : Uint16Array, it.idx),
  }));
  return { items, bones: hdr.bones, licence: hdr.licence || null };
}
/** The hair a look wears: one of the hair items by the look's face choice (the wardrobe picks faces 0..5: the face is the
 *  mesh's own now, so the choice names the hair style — the wardrobe will say so, #172), bald for none. */
export const hairStyleOf = (look, nHair) => (nHair ? Math.abs(((look && look.face) || 0) + ((look && look.body) || 0) * 2) % nHair : -1);
// (face * 7 + body was the first form: seven styles, so every face gave style `body` — the test counts the styles six faces reach)

// ---- the look: a player's colours onto the regions --------------------------------------------------------------------
// Land's wardrobe gives skin, top, legs, hair, a cap and a cloak (land.js lookColours); the body's regions take them:
// the jacket is the top, the trousers the legs, the boots a dark leather, the crown the cap or the hair, the hands skin,
// the eyes dark, the trim (collar, cuffs) the top darkened. [r, g, b, roughness] × 9, linear rgb.
const srgb = (hex) => [16, 8, 0].map((s) => { const c = ((hex >> s) & 255) / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });
export const BOOTS = 0x3a2e2a, EYE = 0x14100e;
export function kitOf(c) {
  const put = (out, k, hex, rough) => { const [r, g, b] = srgb(hex); out[k * 4] = r; out[k * 4 + 1] = g; out[k * 4 + 2] = b; out[k * 4 + 3] = rough; };
  const out = new Float32Array(REGIONS.length * 4), top = c.top, dark = ((top >> 16 & 255) * 0.72 << 16) | ((top >> 8 & 255) * 0.72 << 8) | ((top & 255) * 0.72);
  put(out, 0, c.skin, 0.6); put(out, 1, top, 0.55); put(out, 2, c.legs, 0.6); put(out, 3, c.boots ?? BOOTS, 0.45);
  put(out, 4, c.cap != null ? c.cap : c.hair, c.cap != null ? 0.8 : 0.7); put(out, 5, c.hair, 0.7); put(out, 6, c.skin, 0.55); put(out, 7, EYE, 0.2); put(out, 8, dark, 0.5);
  return out;
}
/** The body variant for a look: body 1 (the wardrobe's second body) is the female build, else the male; `heavy` the third. */
export const variantOf = (look) => (look && look.body === 1 ? 1 : look && look.body === 2 ? 2 : 0);

// ---- the gait: where the feet go (as True Wind's crew walks, from published measurements — its #340) -------------------
// step width 0.13 m between the feet (Donelan, Kram & Kuo 2001, Proc. R. Soc. B 268:1985-1992, preferred walking);
// stance width 0.17 m standing; the knee bent 18° in a gait's loading response. A full gait cycle (two steps) per
// WALK_CYCLE m of travel: 0.7 m is True Wind's (unsourced there — a DESIGN CHOICE carried over); the stride's reach
// 0.2·speed-share each way, the foot lifted 7 cm at mid-swing (the same, design choices).
export const STEP_W = 0.13, STANCE_W = 0.17, KNEE_GAIT = (18 * Math.PI) / 180, WALK_CYCLE = 0.7, STRIDE = 0.2, LIFT = 0.07;
/** The two feet in a gait at phase `ph` (radians, advancing 2π per WALK_CYCLE m walked) and movement share `mv` 0..1:
 *  [along (m ahead of the hips), lateral (m to the figure's left, + for foot 0), lift (m)] for feet 0 and 1 — and the
 *  arms swing against them: hand k's reach ahead. */
export function gait(ph, mv) {
  const out = [];
  for (let k = 0; k < 2; k++) {
    const psi = ph + k * Math.PI;
    out.push({ along: STRIDE * mv * Math.sin(psi), lat: (k ? -1 : 1) * (mv > 0.05 ? STEP_W : STANCE_W) / 2, lift: LIFT * mv * Math.max(0, Math.cos(psi)),
      hand: -0.25 * mv * Math.sin(psi) });   // (the arm swings opposite its own leg)
  }
  return out;
}
