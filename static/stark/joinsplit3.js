/* WIDE 2-output join-split circuit in the browser — exact port of execnode/stark/joinsplit3.py (SHIELD_WIDE_HEIGHT,
 * security review 2026-09-23 Z3): the same statement as joinsplit2 over alghash2 digests. The trace is 5+D
 * permutation BLOCKS of BR = ROUNDS+1 rows (OWNER, COMMIT, D × MEMBERSHIP, NULLIFIER, OUTPUT1, OUTPUT2) followed
 * by the three 17-row C-3 range blocks; every hash is one permutation and every handoff pins the next block's row 0
 * from the sponge lanes of this block's last row. stark.js turns the trace + constraints + periodic columns into a
 * proof the Python joinsplit3.verify_transfer accepts. */
import * as F from "./field.js";
import * as A2 from "../alghash2.js";

const W_ST = A2.WIDTH, CAP = A2.CAPACITY, RATE = A2.RATE, R = A2.R_ROUNDS, BR = R + 1;
const mod = (x) => ((x % F.P) + F.P) % F.P;
export const [NSK, RHO, VIN, VOUT1, VOUT2, CONS] = [12, 13, 14, 15, 16, 17];
export const SIB = 18, DIR = 22, ACC = 23, RB0 = 24, RB1 = 25, RB2 = 26, RB3 = 27, NCOLS = 28;
export const MAX_DEGREE = 7n;
// Z1 (zero knowledge, joinsplit3.py): 8 randomizer columns close the trace and RANDOM_ROWS uniform rows follow
// the real ones; ACTIVE gates every constraint that would otherwise reach into them.
export const ZK_RANDOMIZERS = 8, NCOLS_TOTAL = NCOLS + ZK_RANDOMIZERS;
export const RANDOM_ROWS = 2 * 320 + 16;             // 2 * NUM_QUERIES + 16, as Python (stark.NUM_QUERIES)
const RNG_NIBBLES = 16, RNG_BLOCK = 17, RNG_VALUES = 3;
export const [RC0, ACT_R, A_COMMIT, A_MERK, A_NF, A_OUT1, A_OUT2, ROW0,
  RNG_ACC, RNG_START, RBIND_VIN, RBIND_VOUT1, RBIND_VOUT2, ACTIVE] = [0, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24];
const NPER = 25;
function randField() {                               // a uniform Goldilocks element from 16 CSPRNG bytes
  const b = new Uint8Array(16); globalThis.crypto.getRandomValues(b); let x = 0n;
  for (const by of b) x = (x << 8n) | BigInt(by);
  return x % F.P;
}
const randRow = (n) => Array.from({ length: n }, randField);
const LEN_OWNER = 2n, LEN_CM = 7n, LEN_NF = 3n;

function nextPow2(x) { let p = 1; while (p < x) p <<= 1; return p; }
function blocks(D) { return { owner: 0, commit: 1, memb: 2, nf: D + 2, out1: D + 3, out2: D + 4, count: D + 5 }; }
const lastRow = (b) => b * BR + R;
export function rows(D) {
  const b = blocks(D);
  const rs = b.count * BR;
  return { rootRow: lastRow(b.nf - 1), nfRow: lastRow(b.nf), cm1Row: lastRow(b.out1), spongeEnd: lastRow(b.out2),
           rangeStart: rs, total: rs + RNG_VALUES * RNG_BLOCK };
}
export const traceLength = (D) => nextPow2(rows(D).total + RANDOM_ROWS);

function ordered(cur, sib, d) {
  const left = d ? sib : cur, right = d ? cur : sib;
  return [...left.map(BigInt), ...right.map(BigInt), ...A2.ivLanes()];
}
function rangeFill(start, values) {
  const fill = new Map();
  values.forEach((val, b) => {
    let acc = 0n; const base = start + b * RNG_BLOCK;
    for (let i = 0; i < RNG_NIBBLES; i++) {
      const nib = (val >> BigInt(4 * (15 - i))) & 0xFn;
      fill.set(base + i, [acc, (nib >> 3n) & 1n, (nib >> 2n) & 1n, (nib >> 1n) & 1n, nib & 1n]);
      acc = 16n * acc + nib;
    }
    fill.set(base + RNG_NIBBLES, [acc, 0n, 0n, 0n, 0n]);
  });
  return fill;
}

export function transfer(nsk, vIn, rhoIn, sibs, dirs, v1, o1, r1, v2, o2, r2) {
  const owner = A2.ownerOf(nsk), cmIn = A2.commit(vIn, owner, rhoIn);
  return { owner, cmIn, nf: A2.nullifier(nsk, rhoIn), root: A2.foldPath(cmIn, sibs, dirs),
           cm1: A2.commit(v1, o1, r1), cm2: A2.commit(v2, o2, r2) };
}

export function buildTrace(nsk, vIn, rhoIn, sibs, dirs, v1, o1, r1, v2, o2, r2) {
  const m = (x) => ((BigInt(x) % F.P) + F.P) % F.P;
  nsk = m(nsk); vIn = m(vIn); rhoIn = m(rhoIn); v1 = m(v1); r1 = m(r1); v2 = m(v2); r2 = m(r2);
  o1 = o1.map(m); o2 = o2.map(m);
  const D = sibs.length, IV = A2.ivLanes();
  const blks = [];
  let b = A2.permuteSnapshots([LEN_OWNER, A2.DOM_ZOWNER, nsk, 0n, 0n, 0n, 0n, 0n, ...IV]); blks.push(b);
  const owner = b[R].slice(0, CAP);
  b = A2.permuteSnapshots([LEN_CM, A2.DOM_ZCM, vIn, ...owner, rhoIn, ...IV]); blks.push(b);
  let cur = b[R].slice(0, CAP);
  for (let k = 0; k < D; k++) { b = A2.permuteSnapshots(ordered(cur, sibs[k].map(m), Number(dirs[k]) & 1)); blks.push(b); cur = b[R].slice(0, CAP); }
  const root = cur;
  b = A2.permuteSnapshots([LEN_NF, A2.DOM_ZNF, nsk, rhoIn, 0n, 0n, 0n, 0n, ...IV]); blks.push(b);
  const nf = b[R].slice(0, CAP);
  b = A2.permuteSnapshots([LEN_CM, A2.DOM_ZCM, v1, ...o1, r1, ...IV]); blks.push(b);
  const cm1 = b[R].slice(0, CAP);
  b = A2.permuteSnapshots([LEN_CM, A2.DOM_ZCM, v2, ...o2, r2, ...IV]); blks.push(b);
  const cm2 = b[R].slice(0, CAP);
  const bl = blocks(D), rw = rows(D), T = traceLength(D);
  const cons = F.sub(F.sub(vIn, v1), v2);
  const rfill = rangeFill(rw.rangeStart, [vIn, v1, v2]);
  const pathFor = (bi) => { const k = bi < bl.memb ? 0 : bi - bl.memb + 1; return k < D ? [sibs[k].map(m), BigInt(Number(dirs[k]) & 1)] : [[0n, 0n, 0n, 0n], 0n]; };
  const tr = [];
  for (let bi = 0; bi < blks.length; bi++) {
    const [sib, d] = pathFor(bi);
    for (let rr = 0; rr < BR; rr++) {
      const [acc, b0, b1, b2, b3] = rfill.get(bi * BR + rr) || [0n, 0n, 0n, 0n, 0n];
      tr.push([...blks[bi][rr], nsk, rhoIn, vIn, v1, v2, cons, ...sib, d, acc, b0, b1, b2, b3, ...randRow(ZK_RANDOMIZERS)]);
    }
  }
  const lastLanes = tr[tr.length - 1].slice(0, W_ST);
  while (tr.length < rw.total) {                     // the range region: the sponge idles, registers hold
    const [acc, b0, b1, b2, b3] = rfill.get(tr.length) || [0n, 0n, 0n, 0n, 0n];
    tr.push([...lastLanes, nsk, rhoIn, vIn, v1, v2, cons, 0n, 0n, 0n, 0n, 0n, acc, b0, b1, b2, b3, ...randRow(ZK_RANDOMIZERS)]);
  }
  while (tr.length < T) tr.push(randRow(NCOLS_TOTAL));   // Z1: uniform rows, no constraint reaches them
  return { tr, T, D, root, nf, cm1, cm2 };
}

const _perCache = new Map();
export function periodic(T, D) {
  const ck = T + "," + D;
  const hit = _perCache.get(ck);
  if (hit) return hit;
  const bl = blocks(D), rw = rows(D);
  const p = []; for (let i = 0; i < NPER; i++) p.push(new Array(T).fill(0n));
  for (let row = 0; row < Math.min(T, bl.count * BR); row++) {
    const bi = Math.floor(row / BR), rr = row % BR;
    if (rr < R) { for (let lane = 0; lane < W_ST; lane++) p[RC0 + lane][row] = A2.rcAt(rr, lane); p[ACT_R][row] = 1n; }
    else if (bi === 0) p[A_COMMIT][row] = 1n;
    else if (bi >= 1 && bi <= D) p[A_MERK][row] = 1n;
    else if (bi === D + 1) p[A_NF][row] = 1n;
    else if (bi === bl.out1 - 1) p[A_OUT1][row] = 1n;
    else if (bi === bl.out2 - 1) p[A_OUT2][row] = 1n;
  }
  p[ROW0][0] = 1n;
  for (let row = 0; row < Math.min(T, rw.total - 1); row++) p[ACTIVE][row] = 1n;   // Z1: real-to-real transitions only
  for (let row = rw.rangeStart; row < Math.min(T, rw.total); row++) {
    const off = (row - rw.rangeStart) % RNG_BLOCK;
    if (off < RNG_NIBBLES) p[RNG_ACC][row] = 1n;
    if (off === 0) p[RNG_START][row] = 1n;
  }
  [[RBIND_VIN, 0], [RBIND_VOUT1, 1], [RBIND_VOUT2, 2]].forEach(([sel, b]) => { const row = rw.rangeStart + b * RNG_BLOCK + RNG_NIBBLES; if (row < T) p[sel][row] = 1n; });
  _perCache.set(ck, p);
  return p;
}

export function boundaries(D, root, nf, cm1, cm2, publicValue, fee) {
  const rw = rows(D), IV = A2.ivLanes();
  const consPub = F.sub(mod(BigInt(fee)), mod(BigInt(publicValue)));
  const bnd = [[0, 0, LEN_OWNER], [0, 1, A2.DOM_ZOWNER]];
  for (let k = 3; k < RATE; k++) bnd.push([0, k, 0n]);
  for (let i = 0; i < CAP; i++) bnd.push([0, RATE + i, IV[i]]);
  bnd.push([0, CONS, consPub]);
  for (const [row, dig] of [[rw.rootRow, root], [rw.nfRow, nf], [rw.cm1Row, cm1], [rw.spongeEnd, cm2]])
    for (let i = 0; i < CAP; i++) bnd.push([row, i, BigInt(dig[i])]);
  return bnd;
}

export function transitions() {
  const { add, sub, mul, pw } = F;
  const IV = A2.ivLanes(), MDS = A2.MDS, ALPHA = A2.ALPHA_EXP;
  // one S-box vector per row, shared by the twelve lane constraints (the composition passes the same `cur`
  // object to every constraint at a point, and rows live for the whole composition, so a WeakMap is exact)
  const sboxMemo = new WeakMap();
  const sboxes = (cur, per) => {
    let t = sboxMemo.get(cur);
    if (!t) { t = new Array(W_ST); for (let j = 0; j < W_ST; j++) t[j] = pw(add(cur[j], per[RC0 + j]), ALPHA); sboxMemo.set(cur, t); }
    return t;
  };
  const cons = [];
  for (let i = 0; i < W_ST; i++) cons.push((cur, nxt, per) => {
    const t = sboxes(cur, per); let acc = 0n; const row = MDS[i];
    for (let j = 0; j < W_ST; j++) acc += row[j] * t[j];
    return mul(per[ACT_R], sub(nxt[i], mod(acc)));
  });
  const pin = (sel, lane, want) => (cur, nxt, per) => mul(per[sel], sub(nxt[lane], want(cur)));
  const konst = (v) => () => v, reg = (col) => (cur) => cur[col], lane = (k) => (cur) => cur[k];
  cons.push(pin(A_COMMIT, 0, konst(LEN_CM)), pin(A_COMMIT, 1, konst(A2.DOM_ZCM)), pin(A_COMMIT, 2, reg(VIN)), pin(A_COMMIT, 7, reg(RHO)));
  for (let i = 0; i < CAP; i++) cons.push(pin(A_COMMIT, 3 + i, lane(i)));
  for (let i = 0; i < CAP; i++) cons.push(pin(A_COMMIT, RATE + i, konst(IV[i])));
  const left = (i) => (cur) => add(mul(sub(1n, cur[DIR]), cur[i]), mul(cur[DIR], cur[SIB + i]));
  const right = (i) => (cur) => add(mul(sub(1n, cur[DIR]), cur[SIB + i]), mul(cur[DIR], cur[i]));
  for (let i = 0; i < CAP; i++) cons.push(pin(A_MERK, i, left(i)));
  for (let i = 0; i < CAP; i++) cons.push(pin(A_MERK, CAP + i, right(i)));
  for (let i = 0; i < CAP; i++) cons.push(pin(A_MERK, RATE + i, konst(IV[i])));
  cons.push(pin(A_NF, 0, konst(LEN_NF)), pin(A_NF, 1, konst(A2.DOM_ZNF)), pin(A_NF, 2, reg(NSK)), pin(A_NF, 3, reg(RHO)));
  for (let i = 0; i < 4; i++) cons.push(pin(A_NF, 4 + i, konst(0n)));
  for (let i = 0; i < CAP; i++) cons.push(pin(A_NF, RATE + i, konst(IV[i])));
  for (const [sel, vreg] of [[A_OUT1, VOUT1], [A_OUT2, VOUT2]]) {
    cons.push(pin(sel, 0, konst(LEN_CM)), pin(sel, 1, konst(A2.DOM_ZCM)), pin(sel, 2, reg(vreg)));
    for (let i = 0; i < CAP; i++) cons.push(pin(sel, RATE + i, konst(IV[i])));
  }
  cons.push((cur, nxt, per) => mul(per[ROW0], sub(cur[2], cur[NSK])));
  for (const col of [NSK, RHO, VIN, VOUT1, VOUT2]) cons.push((cur, nxt, per) => mul(per[ACTIVE], sub(nxt[col], cur[col])));
  for (let i = 0; i < CAP; i++) cons.push((cur, nxt, per) => mul(per[ACTIVE], mul(sub(1n, per[A_MERK]), sub(nxt[SIB + i], cur[SIB + i]))));
  cons.push((cur, nxt, per) => mul(per[ACTIVE], mul(sub(1n, per[A_MERK]), sub(nxt[DIR], cur[DIR]))));
  cons.push((cur, nxt, per) => mul(per[A_MERK], mul(cur[DIR], sub(1n, cur[DIR]))));
  cons.push((cur, nxt, per) => mul(per[ACTIVE], sub(cur[CONS], sub(sub(cur[VIN], cur[VOUT1]), cur[VOUT2]))));
  const nib = (c) => add(add(mul(8n, c[RB0]), mul(4n, c[RB1])), add(mul(2n, c[RB2]), c[RB3]));
  cons.push((c, n, p) => mul(p[RNG_ACC], sub(n[ACC], add(mul(16n, c[ACC]), nib(c)))));
  cons.push((c, n, p) => mul(p[RNG_START], c[ACC]));
  cons.push((c, n, p) => mul(p[RNG_START], add(add(c[RB0], c[RB1]), c[RB2])));
  for (const col of [RB0, RB1, RB2, RB3]) cons.push((c, n, p) => mul(p[RNG_ACC], mul(c[col], sub(1n, c[col]))));
  for (const [sel, vreg] of [[RBIND_VIN, VIN], [RBIND_VOUT1, VOUT1], [RBIND_VOUT2, VOUT2]]) cons.push((c, n, p) => mul(p[sel], sub(c[ACC], c[vreg])));
  return cons;
}
