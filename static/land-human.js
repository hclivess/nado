// land-human.js — PEOPLE DRAWN AS PEOPLE (#172; operator 2026-11-10: "the characters look total garbage nobody is
// gonna play this"; 2026-11-12: "you still havent swapped the character models"). Until this file a person was a ball
// head with a painted face on capsule limbs (land.js avatar). Now every figure — the other players and the townspeople —
// is the MakeHuman body of land-human-data.js (CC0; 5,200 triangles near, 1,100 far), skinned on a 21-bone skeleton
// posed by two-bone IK every frame: standing on its feet, walking in a gait when it moves, breathing, looking at the
// player who comes near. ALL the figures are ONE instanced draw a LOD (the bones' matrices and the colours in a data
// texture, a row a figure), so a square full of people costs two draw calls.
//
// The renderer is the operator's own True Wind crew renderer (js/crew-render.js there) carried over to Land's stack
// (the same three.js, the same TSL idiom): the skinning from texture rows, the rest frames, the IK solver and the gait are
// its, cut down to what a townsperson does — stand, walk, look. Hands with nothing to hold hang by the thighs and swing
// against the legs when walking.
// NOT yet (owed, #172): hair as a shaped mesh and faces beyond the mesh's own (a nose, a brow and a jaw it has; no
// eyebrows or lips painted), clothes as meshes (a dress, a cloak), the wardrobe's 3D preview, sitting, a run cycle.
import * as THREE from "three/webgpu";
import * as TSL from "three/tsl";
import { parseHuman, B, NB, REGIONS, ROW_TEXELS, kitOf, variantOf, gait, WALK_CYCLE, KNEE_GAIT } from "./land-human-data.js";

export const MAXF = 128;                                   // figures drawn at once (a texture row each)
const NEAR = 60, FAR = 350;                                // m: LOD0 within NEAR of the eye, LOD1 to FAR, none beyond
const V3 = () => new THREE.Vector3();
const X_ = new THREE.Vector3(1, 0, 0), Y_ = new THREE.Vector3(0, 1, 0), Z_ = new THREE.Vector3(0, 0, 1);
const _q = new THREE.Quaternion(), _q2 = new THREE.Quaternion(), _q3 = new THREE.Quaternion(), _m = new THREE.Matrix4(), _m2 = new THREE.Matrix4();
const _a = V3(), _b = V3(), _c = V3(), _d = V3(), _e = V3(), _f = V3();
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));

// ---- rest frames of the limb bones (the skeleton's rest orientation is the identity: a bone's matrix is its rotation
// from the rest pose and the move of its head)
function frameQ(d, p, out) {                 // the rotation whose x axis is d, y axis p (made perpendicular to d)
  _e.copy(p).addScaledVector(d, -p.dot(d)).normalize(); _f.crossVectors(d, _e);
  _m.makeBasis(d, _e, _f); return out.setFromRotationMatrix(_m);
}
function restOf(v) {
  const H = v.heads.map((a) => new THREE.Vector3(...a)), T = v.tails.map((a) => new THREE.Vector3(...a));
  const R = { H, T, height: v.height, ua: [], fa: [], th: [], sn: [], ft: [], curlAx: [], L1a: [], L2a: [], L1l: [], L2l: [] };
  for (let s = 0; s < 2; s++) {
    const d = (a, b) => b.clone().sub(a).normalize();
    const back = new THREE.Vector3(0, 0, -1), fwd = new THREE.Vector3(0, 0, 1);
    R.ua[s] = frameQ(d(H[B.ua[s]], H[B.fa[s]]), back, new THREE.Quaternion()).invert();
    R.fa[s] = frameQ(d(H[B.fa[s]], H[B.hd[s]]), back, new THREE.Quaternion()).invert();
    R.th[s] = frameQ(d(H[B.th[s]], H[B.sn[s]]), fwd, new THREE.Quaternion()).invert();
    R.sn[s] = frameQ(d(H[B.sn[s]], H[B.ft[s]]), fwd, new THREE.Quaternion()).invert();
    R.ft[s] = frameQ(d(H[B.ft[s]], T[B.ft[s]]), Y_, new THREE.Quaternion()).invert();
    R.L1a[s] = H[B.ua[s]].distanceTo(H[B.fa[s]]); R.L2a[s] = H[B.fa[s]].distanceTo(H[B.hd[s]]);
    R.L1l[s] = H[B.th[s]].distanceTo(H[B.sn[s]]); R.L2l[s] = H[B.sn[s]].distanceTo(H[B.ft[s]]);
    const hd = d(H[B.hd[s]], T[B.hd[s]]), palm = new THREE.Vector3(s ? 1 : -1, -0.3, 0);   // the fingers curl toward the palm
    palm.addScaledVector(hd, -palm.dot(hd)).normalize();
    R.curlAx[s] = new THREE.Vector3().crossVectors(hd, palm).normalize();
  }
  R.ankle = H[B.ft[0]].y;
  R.footD = T[B.ft[0]].clone().sub(H[B.ft[0]]).setX(0).normalize();     // (the foot's own slope, heel to ball)
  R.hipJ = H[B.hips].y - H[B.th[0]].y;
  R.legH = Math.sqrt(R.L1l[0] * R.L1l[0] + R.L2l[0] * R.L2l[0] + 2 * R.L1l[0] * R.L2l[0] * Math.cos(KNEE_GAIT));
  return R;
}

// ---- the material: skinned from the texture (a bone's 3 texels are the rows of its 3×4 matrix; the weighted sum of
// the four bones' rows is the skin matrix, and both the position and the normal are linear in it). The shadow pass
// copies the positionNode, so the figures' shadows are skinned the same way.
function skinRows(T, row) {
  const { attribute, vec4, int, ivec2 } = TSL;
  const bi = attribute("aBoneI", "vec4"), bw = attribute("aBoneW", "vec4");
  let rows = [vec4(0.0), vec4(0.0), vec4(0.0)];
  for (const k of ["x", "y", "z", "w"]) {
    const c = int(bi[k].add(0.5)).mul(3);
    rows = rows.map((r, j) => r.add(T.load(ivec2(c.add(j), row)).mul(bw[k])));
  }
  return rows;
}
const skinned = (T, normal) => TSL.Fn(() => {
  const { attribute, vec3, vec4, int, ivec2, select, dot, normalize, positionGeometry, normalGeometry } = TSL;
  const row = int(attribute("aFig", "float").add(0.5)).toVar();
  const info = T.load(ivec2(NB * 3, row)).toVar();
  const [r0, r1, r2] = skinRows(T, row).map((r) => r.toVar());
  const v1 = info.x.lessThan(0.5), v2 = info.x.lessThan(1.5);
  if (normal) {
    const n = select(v1, normalGeometry, select(v2, attribute("n1", "vec3"), attribute("n2", "vec3"))).toVar();
    return normalize(vec3(dot(r0.xyz, n), dot(r1.xyz, n), dot(r2.xyz, n)));
  }
  const p4 = vec4(select(v1, positionGeometry, select(v2, attribute("p1", "vec3"), attribute("p2", "vec3"))), 1.0).toVar();
  return vec3(dot(r0, p4), dot(r1, p4), dot(r2, p4));
})();
function humanMaterial(tex) {
  const { attribute, texture, int, ivec2, mix, select, float, varying, vec3, vec4, sin, cos, normalize, positionGeometry, normalLocal, normalView, materialColor } = TSL;
  const m = new THREE.MeshStandardNodeMaterial({ roughness: 0.6, metalness: 0 });
  const T = texture(tex);
  m.positionNode = skinned(T, false);
  const nrm = skinned(T, true);
  m.setupPosition = function (builder) { normalLocal.assign(nrm); return Object.getPrototypeOf(this).setupPosition.call(this, builder); };
  // the figure's colours: its row's region colour, mixed across a hem with the neighbour region's (rgb, a roughness)
  const row = int(attribute("aFig", "float").add(0.5)), aRegion = attribute("aRegion", "float");
  const col = mix(T.load(ivec2(int(aRegion.add(0.5)).add(NB * 3 + 1), row)), T.load(ivec2(int(attribute("aRegion2", "float").add(0.5)).add(NB * 3 + 1), row)), attribute("aMix", "float"));
  const rg = aRegion.add(0.5);
  const cloth = select(rg.greaterThan(1.0).and(rg.lessThan(3.0)).or(rg.greaterThan(8.0).and(rg.lessThan(9.0))), float(1.0), select(rg.greaterThan(3.0).and(rg.lessThan(4.0)), float(0.4), float(0.0)));
  const vCol = varying(col.rgb, "vHumCol"), vRough = varying(col.a, "vHumRough"), vP = varying(positionGeometry, "vHumP"), vCloth = varying(cloth, "vHumCloth");
  // the fabric: soft creases from a few crossed sine bands over the body's rest position, bending the normal and
  // darkening the cloth a little in them; the skin left smooth
  const cp = vP.mul(vec3(23.0, 9.0, 23.0));
  const fold = sin(cp.y.add(sin(cp.x.mul(0.8).add(cp.z.mul(0.6))).mul(1.7))).mul(sin(cp.x.mul(0.5).sub(cp.z.mul(0.7)).add(cp.y.mul(0.3))));
  m.colorNode = vec4(materialColor.rgb.mul(vCol).mul(float(1.0).sub(vCloth.mul(fold.mul(0.07).add(0.07)))), 1.0);
  m.normalNode = normalize(normalView.add(vec3(cos(cp.y.mul(1.3).add(cp.x)), sin(cp.x.mul(0.9).sub(cp.z)), cos(cp.z.mul(1.1).add(cp.y.mul(0.7)))).mul(vCloth.mul(0.14))));
  m.roughnessNode = vRough;
  return m;
}

// ---- the pose solver (figure space: the rest skeleton's own — metres, y up, +z the way it faces, +x its left)
class Pose {
  constructor() {
    this.lean = 0; this.roll = 0; this.breath = 0; this.lookYaw = 0; this.lookPitch = 0;
    this.foot = [V3(), V3()]; this.footFwd = [V3(), V3()]; this.footUp = [V3(), V3()]; this.knee = [V3(), V3()];
    this.hand = [V3(), V3()]; this.handOn = [false, false]; this.elbow = [V3(), V3()]; this.curl = [0.3, 0.3];
  }
}
// two-bone IK: from root S to target T with lengths L1, L2, the middle joint bent toward pole; the middle joint into M,
// the reached end into T (pulled in when out of reach)
function ik(S, T, L1, L2, pole, M) {
  _a.subVectors(T, S); let d = _a.length();
  const dmax = (L1 + L2) * 0.999, dmin = Math.abs(L1 - L2) * 1.01 + 1e-3;
  if (d < 1e-6) { _a.set(0, -1, 0); d = 1e-6; }
  _a.multiplyScalar(1 / d);
  d = clamp(d, dmin, dmax); T.copy(S).addScaledVector(_a, d);
  const x = (L1 * L1 - L2 * L2 + d * d) / (2 * d), h = Math.sqrt(Math.max(0, L1 * L1 - x * x));
  _b.copy(pole).addScaledVector(_a, -pole.dot(_a));
  if (_b.lengthSq() < 1e-8) _b.set(0, 0, 1).addScaledVector(_a, -_a.z);
  _b.normalize();
  M.copy(S).addScaledVector(_a, x).addScaledVector(_b, h);
  return _b;
}
const WQ = Array.from({ length: NB }, () => new THREE.Quaternion()), WP = Array.from({ length: NB }, () => V3());
const _bend = V3(), _S = V3(), _T = V3(), _M = V3(), _dir = V3();
function solve(R, P) {
  const H = R.H;
  _q.setFromAxisAngle(X_, -P.lean * 0.55); _q2.setFromAxisAngle(Z_, P.roll); _q.premultiply(_q2);
  WQ[B.hips].copy(_q); WP[B.hips].copy(H[B.hips]);
  const chain = (b, p, q) => { WQ[b].multiplyQuaternions(WQ[p], q); WP[b].copy(H[b]).sub(H[p]).applyQuaternion(WQ[p]).add(WP[p]); };
  chain(B.spine, B.hips, _q.setFromAxisAngle(X_, -P.lean * 0.25));
  chain(B.chest, B.spine, _q.setFromAxisAngle(X_, -P.lean * 0.2 - P.breath));
  chain(B.neck, B.chest, _q.setFromAxisAngle(X_, P.lean * 0.3 + P.breath * 0.5));
  _q.setFromAxisAngle(X_, P.lean * 0.45 + P.lookPitch); _q2.setFromAxisAngle(Y_, P.lookYaw); _q.premultiply(_q2);
  chain(B.head, B.neck, _q);
  for (let s = 0; s < 2; s++) {
    WP[B.th[s]].copy(H[B.th[s]]).sub(H[B.hips]).applyQuaternion(WQ[B.hips]).add(WP[B.hips]);
    _S.copy(WP[B.th[s]]); _T.copy(P.foot[s]);
    const bl = _bend.copy(ik(_S, _T, R.L1l[s], R.L2l[s], P.knee[s], _M));
    frameQ(_dir.subVectors(_M, _S).normalize(), bl, WQ[B.th[s]]).multiply(R.th[s]);
    WP[B.sn[s]].copy(_M);
    frameQ(_dir.subVectors(_T, _M).normalize(), bl, WQ[B.sn[s]]).multiply(R.sn[s]);
    WP[B.ft[s]].copy(_T);
    frameQ(P.footFwd[s], P.footUp[s], WQ[B.ft[s]]).multiply(R.ft[s]);
    WQ[B.sh[s]].copy(WQ[B.chest]); WP[B.sh[s]].copy(H[B.sh[s]]).sub(H[B.chest]).applyQuaternion(WQ[B.chest]).add(WP[B.chest]);
    _S.copy(H[B.ua[s]]).sub(H[B.sh[s]]).applyQuaternion(WQ[B.sh[s]]).add(WP[B.sh[s]]);
    WP[B.ua[s]].copy(_S);
    if (P.handOn[s]) _T.copy(P.hand[s]);
    else _T.copy(WP[B.th[s]]).lerp(WP[B.sn[s]], 0.72).addScaledVector(Y_, 0.08).addScaledVector(X_, s ? -0.05 : 0.05);   // the hand by the thigh
    const ba = _bend.copy(ik(_S, _T, R.L1a[s], R.L2a[s], P.elbow[s], _M));
    frameQ(_dir.subVectors(_M, _S).normalize(), ba, WQ[B.ua[s]]).multiply(R.ua[s]);
    WP[B.fa[s]].copy(_M);
    frameQ(_dir.subVectors(_T, _M).normalize(), ba, WQ[B.fa[s]]).multiply(R.fa[s]);
    WP[B.hd[s]].copy(_T); WQ[B.hd[s]].copy(WQ[B.fa[s]]);
    _q.setFromAxisAngle(_dir.copy(R.curlAx[s]).applyQuaternion(WQ[B.hd[s]]), P.curl[s]);
    WQ[B.fg[s]].multiplyQuaternions(_q, WQ[B.hd[s]]);
    WP[B.fg[s]].copy(H[B.fg[s]]).sub(H[B.hd[s]]).applyQuaternion(WQ[B.hd[s]]).add(WP[B.hd[s]]);
  }
}

// ---- the view: every figure in one instanced mesh a LOD, a texture row each
export class HumanView {
  constructor(scene, url = "/static/human/crew.bin") {
    this.scene = scene; this.ready = false; this.figs = new Map(); this.free = []; this.pose = new Pose(); this.meshes = null;
    this.data = new Float32Array(ROW_TEXELS * MAXF * 4);
    this.tex = new THREE.DataTexture(this.data, ROW_TEXELS, MAXF, THREE.RGBAFormat, THREE.FloatType);
    this.tex.minFilter = this.tex.magFilter = THREE.NearestFilter; this.tex.generateMipmaps = false; this.tex.needsUpdate = true;
    for (let i = MAXF - 1; i >= 0; i--) this.free.push(i);
    this.load = fetch(url, { cache: "force-cache" }).then((r) => { if (!r.ok) throw new Error("crew.bin " + r.status); return r.arrayBuffer(); })
      .then((b) => this.build(parseHuman(b))).catch((e) => { console.error("human", e); throw e; });
  }
  build(D) {
    this.D = D; this.rest = D.vars.map(restOf);
    // the eleven static per-vertex attributes in ONE interleaved buffer shared by both LODs (WebGPU allows 8 vertex
    // buffers a pipeline; as separate buffers these were 12 with aFig)
    const nV = D.nV, lay = [["position", D.vars[0].pos, 3], ["normal", D.vars[0].nrm, 3], ["p1", D.vars[1].pos, 3], ["n1", D.vars[1].nrm, 3], ["p2", D.vars[2].pos, 3], ["n2", D.vars[2].nrm, 3],
      ["aBoneI", D.skinI, 4], ["aBoneW", D.skinW, 4], ["aRegion", D.region, 1], ["aRegion2", D.reg2, 1], ["aMix", D.mix, 1]];
    const stride = lay.reduce((s, l) => s + l[2], 0), arr = new Float32Array(nV * stride), ib = new THREE.InterleavedBuffer(arr, stride), attrs = {};
    let off = 0;
    for (const [name, src, k] of lay) {
      const norm = name === "aBoneW" ? 255 : 1;
      for (let i = 0; i < nV; i++) for (let j = 0; j < k; j++) arr[i * stride + off + j] = src[i * k + j] / norm;
      attrs[name] = new THREE.InterleavedBufferAttribute(ib, k, off); off += k;
    }
    const mat = humanMaterial(this.tex);
    this.meshes = [D.lod0, D.lod1].map((idx) => {
      const g = new THREE.InstancedBufferGeometry();
      for (const [n, a] of Object.entries(attrs)) g.setAttribute(n, a);
      g.setIndex(new THREE.BufferAttribute(idx, 1));
      const fig = new THREE.InstancedBufferAttribute(new Float32Array(MAXF), 1); fig.setUsage(THREE.DynamicDrawUsage);
      g.setAttribute("aFig", fig); g.instanceCount = 0;
      const m = new THREE.Mesh(g, mat); m.frustumCulled = false; m.castShadow = true; m.receiveShadow = true; m.matrixAutoUpdate = false;
      this.scene.add(m); return m;
    });
    this.ready = true;
  }
  /** A figure: `look` the wardrobe's, `colours` land.js lookColours' { skin, top, legs, hair, cap, cloak }. */
  add(id, look, colours) {
    if (this.figs.has(id)) return this.figs.get(id);
    const row = this.free.pop();
    if (row === undefined) return null;                        // (more than MAXF people in view: the rest are not drawn)
    const f = { row, variant: variantOf(look), kit: kitOf(colours), scale: 1, ph: 0, mv: 0, phase: (row * 0.618) % 1 * 10, yaw: 0, dist: Infinity, placed: false, breath: 0 };
    this.figs.set(id, f); return f;
  }
  remove(id) { const f = this.figs.get(id); if (!f) return; this.figs.delete(id); this.free.push(f.row); }
  /** Place a figure for this frame: `pos` its feet (metres, camera-relative world), `fr` { east, north, up } there,
   *  `yaw` where it faces (from north toward east), `speed` m/s along the ground, `dt` s, `t` s, `lookAt` an optional
   *  camera-relative point it looks at. */
  place(id, pos, fr, yaw, speed, dt, t, lookAt) {
    const f = this.figs.get(id);
    if (!f || !this.ready) return;
    const R = this.rest[f.variant], P = this.pose, s = f.scale;
    f.dist = Math.hypot(pos[0], pos[1], pos[2]); f.placed = f.dist < FAR;
    if (!f.placed) return;
    // the gait: the phase advances with the ground covered; the movement share eases in and out
    const mv = clamp(speed / 1.2, 0, 1);
    f.mv += (mv - f.mv) * Math.min(1, 6 * dt);
    f.ph += (speed * dt * 2 * Math.PI) / WALK_CYCLE;
    const G = gait(f.ph, f.mv);
    // the figure's frame in the world: x its left, y up, z the way it faces
    const fwd = [0, 1, 2].map((i) => Math.sin(yaw) * fr.east[i] + Math.cos(yaw) * fr.north[i]);
    const up = fr.up, left = [up[1] * fwd[2] - up[2] * fwd[1], up[2] * fwd[0] - up[0] * fwd[2], up[0] * fwd[1] - up[1] * fwd[0]];
    _m2.makeBasis(_a.set(...left), _b.set(...up), _c.set(...fwd));
    // the hips over the feet, at the gait's standing height (the knee a little bent), bobbing a little as it walks
    const hipY = R.ankle + R.hipJ + R.legH + 0.015 * f.mv * Math.cos(2 * f.ph);
    P.lean = -0.06 - 0.08 * f.mv; P.roll = 0; P.breath = 0.025 * Math.sin(t * 1.5 + f.phase);
    // looking: at the given point (a player near), else ahead with a little drift
    if (lookAt) {
      _d.set(lookAt[0] - pos[0], lookAt[1] - pos[1], lookAt[2] - pos[2]);
      const lx = _d.dot(_a), ly = _d.dot(_b), lz = _d.dot(_c);
      P.lookYaw = clamp(Math.atan2(-lx, lz), -1.1, 1.1); P.lookPitch = clamp(Math.atan2(ly - hipY * 0.9, Math.hypot(lx, lz)), -0.6, 0.6);
    } else { P.lookYaw = 0.12 * Math.sin(t * 0.37 + f.phase); P.lookPitch = 0.04 * Math.sin(t * 0.23 + f.phase * 2); }
    for (let k = 0; k < 2; k++) {
      // feet in figure space: x left, y up (the ground at y = 0 - hipY under the hips at H[hips]), z ahead
      P.foot[k].set(G[k].lat, R.H[B.hips].y - hipY + R.ankle + G[k].lift, G[k].along);
      P.footFwd[k].copy(R.footD); P.footUp[k].set(0, 1, 0);
      P.knee[k].set(k ? -0.1 : 0.1, 0.35, 1);
      // the hands swing against the legs when walking; standing, they hang by the thighs
      P.handOn[k] = f.mv > 0.05;
      P.hand[k].set((k ? -1 : 1) * 0.19, R.H[B.hips].y - 0.02, G[k].hand).lerp(P.foot[k], 0).setY(R.H[B.hips].y - 0.04 + 0.1 * Math.abs(G[k].hand));
      P.elbow[k].set(k ? -0.6 : 0.6, -1, -0.4);
      P.curl[k] = 0.35;
    }
    solve(R, P);
    // into the texture: world = (feet, basis, scale) · (the hips at H[hips] over the feet) · bone
    _m2.setPosition(pos[0], pos[1], pos[2]);
    _m2.multiply(_m.makeScale(s, s, s)).multiply(_m.makeTranslation(-R.H[B.hips].x, hipY - R.H[B.hips].y, -R.H[B.hips].z));
    const o = f.row * ROW_TEXELS * 4, dd = this.data;
    for (let k = 0; k < NB; k++) {
      _m.makeRotationFromQuaternion(WQ[k]);
      _d.copy(R.H[k]).applyQuaternion(WQ[k]);
      _m.setPosition(WP[k].x - _d.x, WP[k].y - _d.y, WP[k].z - _d.z);
      _m.premultiply(_m2);
      const e = _m.elements, j = o + k * 12;
      dd[j] = e[0]; dd[j + 1] = e[4]; dd[j + 2] = e[8]; dd[j + 3] = e[12];
      dd[j + 4] = e[1]; dd[j + 5] = e[5]; dd[j + 6] = e[9]; dd[j + 7] = e[13];
      dd[j + 8] = e[2]; dd[j + 9] = e[6]; dd[j + 10] = e[10]; dd[j + 11] = e[14];
    }
    dd[o + NB * 12] = f.variant;
    dd.set(f.kit, o + NB * 12 + 4);
  }
  /** After every figure is placed: the LODs' instance lists and the texture upload. Returns how many are drawn. */
  flush() {
    if (!this.ready) return 0;
    const near = [], far = [];
    this.walking = 0;
    for (const f of this.figs.values()) if (f.placed) { (f.dist < NEAR ? near : far).push(f.row); if (f.mv > 0.2) this.walking++; }
    [near, far].forEach((rows, i) => {
      const m = this.meshes[i], a = m.geometry.getAttribute("aFig");
      a.array.set(rows); a.needsUpdate = true; m.geometry.instanceCount = rows.length; m.visible = rows.length > 0;
    });
    this.tex.needsUpdate = true;
    return near.length + far.length;
  }
}
