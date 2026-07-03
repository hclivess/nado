/* 2-output join-split circuit in the browser — exact port of execnode/stark/joinsplit2.py. Builds the trace +
 * constraints + periodic columns; stark.js turns them into a proof the Python verify_transfer accepts. */
import * as F from "./field.js";
import * as A from "../alghash.js";

const R = 8;                     // A.R_ROUNDS
// …, ACC + 4 nibble-bit columns for the C-3 in-circuit range proof (must match execnode/stark/joinsplit2.py)
export const [S0, S1, AB, CARRY, SIB, DIR, NSK, RHO, OWN, NFREG, VIN, VOUT1, VOUT2, CONS, ROOTREG, CMOUT1,
  ACC, RB0, RB1, RB2, RB3] = Array.from({ length: 21 }, (_, i) => i);
const RPL = 3 * R;
const OWN_END = 2 * R, COM_END = 6 * R, NUL_END = 9 * R, MERK = NUL_END;
export const MAX_DEGREE = 7n;
const RNG_NIBBLES = 16, RNG_BLOCK = RNG_NIBBLES + 1, RNG_VALUES = 3;   // C-3 range gadget geometry

const rc = (r, j) => A.rcAt(r % R, j);
function _round(s0, s1, r) {
  const t0 = A.sboxFn(F.add(s0, rc(r, 0))), t1 = A.sboxFn(F.add(s1, rc(r, 1)));
  return [F.add(F.mul(2n, t0), t1), F.add(t0, F.mul(3n, t1))];
}
// bounds()[2] = spongeEnd, the row where root/nf/cm_out are captured (the boundary row). The range region
// follows; totalRows adds it for the trace length.
export function bounds(D) { const out1 = MERK + D * RPL, out2 = out1 + 4 * R, spongeEnd = out2 + 4 * R; return [out1, out2, spongeEnd]; }
function totalRows(D) { const [, , spongeEnd] = bounds(D); return spongeEnd + RNG_VALUES * RNG_BLOCK; }

export function transfer(nsk, vIn, rhoIn, sibs, dirs, v1, o1, r1, v2, o2, r2) {
  const owner = A.ownerOf(nsk), cmIn = A.commit(vIn, owner, rhoIn), nf = A.nullifier(nsk, rhoIn);
  let node = cmIn;
  for (let i = 0; i < sibs.length; i++) {
    const [l, r] = dirs[i] === 0 ? [node, BigInt(sibs[i]) % F.P] : [BigInt(sibs[i]) % F.P, node];
    node = A.merkleNode(l, r);
  }
  return { owner, cmIn, nf, root: node, cm1: A.commit(v1, o1, r1), cm2: A.commit(v2, o2, r2) };
}

export function buildTrace(nsk, vIn, rhoIn, sibs, dirs, v1, o1, r1, v2, o2, r2) {
  const m = (x) => ((BigInt(x) % F.P) + F.P) % F.P;
  nsk = m(nsk); vIn = m(vIn); rhoIn = m(rhoIn); v1 = m(v1); o1 = m(o1); r1 = m(r1); v2 = m(v2); o2 = m(o2); r2 = m(r2);
  const D = sibs.length, [out1, out2, spongeEnd] = bounds(D);
  const total = totalRows(D);
  let T = 1; while (T < total + 1) T <<= 1;
  const cons = F.sub(F.sub(vIn, v1), v2);
  // C-3 range fill: row -> [acc, b0, b1, b2, b3] for the range region (acc = accumulator before this nibble).
  const rfill = new Map();
  [vIn, v1, v2].forEach((val, b) => {
    let acc = 0n; const base = spongeEnd + b * RNG_BLOCK;
    for (let i = 0; i < RNG_NIBBLES; i++) {
      const nib = (val >> BigInt(4 * (15 - i))) & 0xFn;
      rfill.set(base + i, [acc, (nib >> 3n) & 1n, (nib >> 2n) & 1n, (nib >> 1n) & 1n, nib & 1n]);
      acc = 16n * acc + nib;
    }
    rfill.set(base + RNG_NIBBLES, [acc, 0n, 0n, 0n, 0n]);      // bind row: acc == val
  });
  const tr = [];
  let s0 = A.DOM_OWNER, s1 = A.ivVal(), ab = A.DOM_OWNER;
  let carry = 0n, sib = 0n, dr = 0n, own = 0n, nfreg = 0n, rootreg = 0n, cmout1 = 0n, lvl = 0;
  for (let r = 0; r < T; r++) {
    const [racc, rb0, rb1, rb2, rb3] = rfill.get(r) || [0n, 0n, 0n, 0n, 0n];
    tr.push([s0, s1, ab, carry, sib, dr, nsk, rhoIn, own, nfreg, vIn, v1, v2, cons, rootreg, cmout1,
             racc, rb0, rb1, rb2, rb3]);
    const [r0, r1r] = _round(s0, s1, r);
    const last = (r % R === R - 1);
    if (r < OWN_END) {                                     // OWNER [DOM_OWNER, nsk]
      if (r === OWN_END - 1) { own = r0; s0 = A.DOM_CM; s1 = A.ivVal(); ab = A.DOM_CM; }
      else if (last) { s0 = F.add(r0, nsk); s1 = r1r; ab = nsk; }
      else { s0 = r0; s1 = r1r; }
    } else if (r < COM_END) {                              // COMMIT [DOM_CM, vIn, owner, rhoIn]
      if (r === COM_END - 1) { carry = r0; s0 = A.DOM_NF; s1 = A.ivVal(); ab = A.DOM_NF; }
      else if (last) { const msg = r === 3 * R - 1 ? vIn : (r === 4 * R - 1 ? own : rhoIn); s0 = F.add(r0, msg); s1 = r1r; ab = msg; }
      else { s0 = r0; s1 = r1r; }
    } else if (r < NUL_END) {                              // NULLIFIER [DOM_NF, nsk, rhoIn]
      if (r === NUL_END - 1) { nfreg = r0; sib = m(sibs[0]); dr = BigInt(dirs[0]); s0 = A.DOM_NODE; s1 = A.ivVal(); ab = A.DOM_NODE; }
      else if (last) { const msg = r === 7 * R - 1 ? nsk : rhoIn; s0 = F.add(r0, msg); s1 = r1r; ab = msg; }
      else { s0 = r0; s1 = r1r; }
    } else if (r < out1) {                                 // MEMBERSHIP
      const pos = (r - MERK) % RPL, block = Math.floor(pos / R);
      if (last && block === 0) { const left = F.add(carry, F.mul(dr, F.sub(sib, carry))); s0 = F.add(r0, left); s1 = r1r; ab = left; }
      else if (last && block === 1) { const right = F.add(sib, F.mul(dr, F.sub(carry, sib))); s0 = F.add(r0, right); s1 = r1r; ab = right; }
      else if (last && block === 2) {
        lvl += 1;
        if (lvl < D) { carry = r0; sib = m(sibs[lvl]); dr = BigInt(dirs[lvl]); s0 = A.DOM_NODE; s1 = A.ivVal(); ab = A.DOM_NODE; }
        else { rootreg = r0; s0 = A.DOM_CM; s1 = A.ivVal(); ab = A.DOM_CM; }
      } else { s0 = r0; s1 = r1r; }
    } else if (r < out2) {                                 // OUTPUT1 [DOM_CM, v1, o1, r1]
      if (r === out2 - 1) { cmout1 = r0; s0 = A.DOM_CM; s1 = A.ivVal(); ab = A.DOM_CM; }
      else if (last) { const oi = Math.floor((r - out1) / R); const msg = oi === 0 ? v1 : (oi === 1 ? o1 : r1); s0 = F.add(r0, msg); s1 = r1r; ab = msg; }
      else { s0 = r0; s1 = r1r; }
    } else if (r < spongeEnd) {                            // OUTPUT2 [DOM_CM, v2, o2, r2]
      if (last && r < spongeEnd - 1) { const oi = Math.floor((r - out2) / R); const msg = oi === 0 ? v2 : (oi === 1 ? o2 : r2); s0 = F.add(r0, msg); s1 = r1r; ab = msg; }
      else { s0 = r0; s1 = r1r; }
    } else {                                               // range region + padding: the sponge idles
      s0 = r0; s1 = r1r;
    }
  }
  return { tr, T, D, root: tr[spongeEnd][ROOTREG], nf: tr[spongeEnd][NFREG], cm1: tr[out2][CMOUT1], cm2: tr[spongeEnd][S0] };
}

export const [RC0, RC1, ANSK, ARHO, AOWN, AVIN, AVOUT1, AVOUT2, AFREE, B0, B1, RCM, RNF, RNODE,
  ROUT1, ROUT2, CAPOWN, CAPCARRY, CAPNF, CAPROOT, CAPCM1, INMERK,
  RNG_ACC, RNG_START, RBIND_VIN, RBIND_VOUT1, RBIND_VOUT2] = Array.from({ length: 27 }, (_, i) => i);

const _perCache = new Map();
export function periodic(T, D) {
  const ck = T + "," + D;
  const hit = _perCache.get(ck);
  if (hit) return hit;                         // periodic columns depend only on (T, D) — same every proof
  const [out1, out2, spongeEnd] = bounds(D);
  const total = totalRows(D);
  const col = (fn) => Array.from({ length: T }, (_, r) => (fn(r) ? 1 : 0));
  const lvlEnd = (r, upto) => MERK <= r && r < out1 && (r - MERK) % RPL === RPL - 1 && Math.floor((r - MERK) / RPL) < upto && Math.floor((r - MERK) / RPL) >= 0;
  const rng = (r) => spongeEnd <= r && r < total;
  const p = new Array(27);
  p[RC0] = Array.from({ length: T }, (_, r) => rc(r, 0));
  p[RC1] = Array.from({ length: T }, (_, r) => rc(r, 1));
  p[ANSK] = col((r) => r === R - 1 || r === 7 * R - 1);
  p[ARHO] = col((r) => r === 5 * R - 1 || r === 8 * R - 1);
  p[AOWN] = col((r) => r === 4 * R - 1);
  p[AVIN] = col((r) => r === 3 * R - 1);
  p[AVOUT1] = col((r) => r === out1 + R - 1);
  p[AVOUT2] = col((r) => r === out2 + R - 1);
  p[AFREE] = col((r) => r === out1 + 2 * R - 1 || r === out1 + 3 * R - 1 || r === out2 + 2 * R - 1 || r === out2 + 3 * R - 1);
  p[B0] = col((r) => MERK <= r && r < out1 && (r - MERK) % RPL === R - 1);
  p[B1] = col((r) => MERK <= r && r < out1 && (r - MERK) % RPL === 2 * R - 1);
  p[RCM] = col((r) => r === OWN_END - 1);
  p[RNF] = col((r) => r === COM_END - 1);
  p[RNODE] = col((r) => r === NUL_END - 1 || lvlEnd(r, D - 1));
  p[ROUT1] = col((r) => r === out1 - 1);
  p[ROUT2] = col((r) => r === out2 - 1);
  p[CAPOWN] = col((r) => r === OWN_END - 1);
  p[CAPCARRY] = col((r) => r === COM_END - 1 || lvlEnd(r, D - 1));
  p[CAPNF] = col((r) => r === NUL_END - 1);
  p[CAPROOT] = col((r) => r === out1 - 1);
  p[CAPCM1] = col((r) => r === out2 - 1);
  p[INMERK] = col((r) => MERK <= r && r < out1);
  // C-3 range region selectors
  p[RNG_ACC] = col((r) => rng(r) && (r - spongeEnd) % RNG_BLOCK < RNG_NIBBLES);
  p[RNG_START] = col((r) => rng(r) && (r - spongeEnd) % RNG_BLOCK === 0);
  p[RBIND_VIN] = col((r) => r === spongeEnd + 0 * RNG_BLOCK + RNG_NIBBLES);
  p[RBIND_VOUT1] = col((r) => r === spongeEnd + 1 * RNG_BLOCK + RNG_NIBBLES);
  p[RBIND_VOUT2] = col((r) => r === spongeEnd + 2 * RNG_BLOCK + RNG_NIBBLES);
  _perCache.set(ck, p);
  return p;
}

export function transitions() {
  const { add, sub, mul, pw, inv } = F;
  const ALPHA = A.ALPHA_EXP, IVv = A.ivVal();
  const rnd = (cur, per) => {
    const t0 = pw(add(cur[S0], per[RC0]), ALPHA), t1 = pw(add(cur[S1], per[RC1]), ALPHA);
    return [add(mul(2n, t0), t1), add(t0, mul(3n, t1))];
  };
  const parts = (cur, per) => {
    const left = add(cur[CARRY], mul(cur[DIR], sub(cur[SIB], cur[CARRY])));
    const right = add(cur[SIB], mul(cur[DIR], sub(cur[CARRY], cur[SIB])));
    const reset = add(add(add(per[RCM], per[RNF]), per[RNODE]), add(per[ROUT1], per[ROUT2]));
    const resetDom = add(add(mul(per[RCM], A.DOM_CM), mul(per[RNF], A.DOM_NF)),
      add(mul(per[RNODE], A.DOM_NODE), add(mul(per[ROUT1], A.DOM_CM), mul(per[ROUT2], A.DOM_CM))));
    return [left, right, reset, resetDom];
  };
  const sumAll = (arr) => arr.reduce((a, b) => add(a, b), 0n);
  const c_s1 = (cur, nxt, per) => { const [, r1] = rnd(cur, per); const [, , reset] = parts(cur, per); return sub(nxt[S1], add(mul(reset, IVv), mul(sub(1n, reset), r1))); };
  const c_s0 = (cur, nxt, per) => {
    const [r0] = rnd(cur, per); const [left, right, reset, resetDom] = parts(cur, per);
    const absorbed = sumAll([mul(per[ANSK], cur[NSK]), mul(per[ARHO], cur[RHO]), mul(per[AOWN], cur[OWN]),
      mul(per[AVIN], cur[VIN]), mul(per[AVOUT1], cur[VOUT1]), mul(per[AVOUT2], cur[VOUT2]),
      mul(per[AFREE], nxt[AB]), mul(per[B0], left), mul(per[B1], right)]);
    return sub(nxt[S0], add(resetDom, mul(sub(1n, reset), add(r0, absorbed))));
  };
  const c_ab = (cur, nxt, per) => {
    const [left, right] = parts(cur, per);
    const setm = sumAll([per[RCM], per[RNF], per[RNODE], per[ROUT1], per[ROUT2], per[ANSK], per[ARHO],
      per[AOWN], per[AVIN], per[AVOUT1], per[AVOUT2], per[B0], per[B1]]);
    const hold = sub(sub(1n, setm), per[AFREE]);
    return sumAll([
      mul(per[RCM], sub(nxt[AB], A.DOM_CM)), mul(per[RNF], sub(nxt[AB], A.DOM_NF)),
      mul(per[RNODE], sub(nxt[AB], A.DOM_NODE)), mul(per[ROUT1], sub(nxt[AB], A.DOM_CM)), mul(per[ROUT2], sub(nxt[AB], A.DOM_CM)),
      mul(per[ANSK], sub(nxt[AB], cur[NSK])), mul(per[ARHO], sub(nxt[AB], cur[RHO])),
      mul(per[AOWN], sub(nxt[AB], cur[OWN])), mul(per[AVIN], sub(nxt[AB], cur[VIN])),
      mul(per[AVOUT1], sub(nxt[AB], cur[VOUT1])), mul(per[AVOUT2], sub(nxt[AB], cur[VOUT2])),
      mul(per[B0], sub(nxt[AB], left)), mul(per[B1], sub(nxt[AB], right)),
      mul(hold, sub(nxt[AB], cur[AB])),
    ]);
  };
  const cap = (cur, nxt, per, reg, sel) => { const [r0] = rnd(cur, per); return sub(nxt[reg], add(mul(per[sel], r0), mul(sub(1n, per[sel]), cur[reg]))); };
  const hold = (reg) => (c, n) => sub(n[reg], c[reg]);
  // C-3 range constraints (mirror execnode/stark/joinsplit2.py)
  const nib = (c) => add(add(mul(8n, c[RB0]), mul(4n, c[RB1])), add(mul(2n, c[RB2]), c[RB3]));
  const bit = (reg) => (c, n, p) => mul(p[RNG_ACC], mul(c[reg], sub(1n, c[reg])));
  const bind = (sel, val) => (c, n, p) => mul(p[sel], sub(c[ACC], c[val]));
  return [
    c_s1, c_s0, c_ab,
    (c, n, p) => cap(c, n, p, CARRY, CAPCARRY), (c, n, p) => cap(c, n, p, OWN, CAPOWN),
    (c, n, p) => cap(c, n, p, NFREG, CAPNF), (c, n, p) => cap(c, n, p, ROOTREG, CAPROOT),
    (c, n, p) => cap(c, n, p, CMOUT1, CAPCM1),
    hold(NSK), hold(RHO), hold(VIN), hold(VOUT1), hold(VOUT2),
    (c, n, p) => mul(sub(1n, p[RNODE]), sub(n[SIB], c[SIB])),
    (c, n, p) => mul(sub(1n, p[RNODE]), sub(n[DIR], c[DIR])),
    (c, n, p) => mul(p[INMERK], mul(c[DIR], sub(1n, c[DIR]))),
    (c, n) => sub(c[CONS], sub(sub(c[VIN], c[VOUT1]), c[VOUT2])),
    (c, n, p) => mul(p[RNG_ACC], sub(n[ACC], add(mul(16n, c[ACC]), nib(c)))),   // acc' = 16·acc + nibble
    (c, n, p) => mul(p[RNG_START], c[ACC]),                                     // acc resets to 0 at block start
    (c, n, p) => mul(p[RNG_START], add(c[RB0], c[RB1])),                        // top 2 bits = 0 -> value < 2^62
    bit(RB0), bit(RB1), bit(RB2), bit(RB3),
    bind(RBIND_VIN, VIN), bind(RBIND_VOUT1, VOUT1), bind(RBIND_VOUT2, VOUT2),
  ];
}
