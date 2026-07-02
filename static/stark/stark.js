/* STARK prover — exact port of execnode/stark/stark.py (prove side): interpolate columns -> LDE -> composition
 * (with periodic columns) -> FRI -> trace openings. Produces a proof the Python stark.verify accepts. */
import * as F from "./field.js";
import * as merkle from "./merkle.js";
import * as fri from "./fri.js";
import { Transcript } from "./transcript.js";

export const OFF = F.GEN;

function nextPow2(x) { let p = 1; while (p < x) p <<= 1; return p; }
function blowupOf(maxDegree) { return 2 * nextPow2(maxDegree); }

function composition(T, W, N, blowup, gT, colLde, perLde, xLde, transitions, boundaries, alphas) {
  const { add, sub, mul, pw, batchInverse } = F;
  const last = pw(gT, BigInt(T - 1)), Tb = BigInt(T);
  // Transition vanishing is the SAME for every constraint: invZ[j] = (xLde[j]-last) / (xLde[j]^T - 1).
  // One Montgomery batch inversion for the whole vector instead of an inv() per (constraint, point).
  const xTm1 = new Array(N);
  for (let j = 0; j < N; j++) xTm1[j] = sub(pw(xLde[j], Tb), 1n);
  const invXTm1 = batchInverse(xTm1);
  const invZ = new Array(N);
  for (let j = 0; j < N; j++) invZ[j] = mul(sub(xLde[j], last), invXTm1[j]);
  // Per-row column + periodic slices, shared across all transitions (built once, not per constraint).
  const Pn = perLde.length, curRow = new Array(N), nxtRow = new Array(N), perRow = new Array(N);
  for (let j = 0; j < N; j++) {
    const jn = (j + blowup) % N, cur = new Array(W), nxt = new Array(W), per = new Array(Pn);
    for (let c = 0; c < W; c++) { cur[c] = colLde[c][j]; nxt[c] = colLde[c][jn]; }
    for (let k = 0; k < Pn; k++) per[k] = perLde[k][j];
    curRow[j] = cur; nxtRow[j] = nxt; perRow[j] = per;
  }
  const cp = new Array(N).fill(0n);
  let ai = 0;
  for (const con of transitions) {
    const a = alphas[ai++];
    for (let j = 0; j < N; j++) cp[j] = add(cp[j], mul(a, mul(con(curRow[j], nxtRow[j], perRow[j]), invZ[j])));
  }
  for (const [row, col, val] of boundaries) {
    const a = alphas[ai++], pt = pw(gT, BigInt(row)), v = BigInt(val), den = new Array(N);
    for (let j = 0; j < N; j++) den[j] = sub(xLde[j], pt);
    const invDen = batchInverse(den);
    for (let j = 0; j < N; j++) cp[j] = add(cp[j], mul(a, mul(sub(colLde[col][j], v), invDen[j])));
  }
  return cp;
}

export function prove(trace, transitions, boundaries, periodic = [], maxDegree = 2, numQueries = 32) {
  const T = trace.length, W = trace[0].length;
  const blowup = blowupOf(maxDegree), N = blowup * T;
  const gT = F.primitiveRootOfUnity(T);
  const colPolys = [];
  for (let c = 0; c < W; c++) {
    const col = new Array(T);
    for (let i = 0; i < T; i++) col[i] = BigInt(trace[i][c]);   // NTT reduces mod p on input
    colPolys.push(F.interpolate(col));
  }
  const _pf = typeof globalThis !== "undefined" && globalThis.STARK_PROFILE;
  let _t = _pf ? Date.now() : 0; const _mk = (n) => { if (_pf) { console.error("  " + n + ": " + (Date.now() - _t) + "ms"); _t = Date.now(); } };
  const colLde = colPolys.map((p) => F.cosetEvaluate(p, N, OFF));
  _mk("colLde (16 coset NTT)");
  const perLde = periodic.map((pc) => F.cosetEvaluate(F.interpolate(pc.map((x) => BigInt(x))), N, OFF));
  _mk("perLde (22 coset NTT)");
  const xLde = F.domain(N, OFF);
  const degBound = nextPow2(maxDegree) * T;

  const t = new Transcript("nado-stark");
  const colRoots = [], colMlayers = [];
  for (let c = 0; c < W; c++) {
    const [root, ml] = merkle.commit(colLde[c]);
    colRoots.push(root); colMlayers.push(ml); t.absorb(root);
  }
  _mk("merkle.commit x16 (blake2b)");
  const alphas = [];
  for (let i = 0; i < transitions.length + boundaries.length; i++) alphas.push(t.challenge());
  const cp = composition(T, W, N, blowup, gT, colLde, perLde, xLde, transitions, boundaries, alphas);
  _mk("composition (17 constraints)");

  const friBlowup = N / degBound;
  const friProof = fri.prove(cp, OFF, friBlowup, numQueries, t);
  _mk("fri.prove");

  const openings = [];
  for (const q of friProof.queries) {
    const lo = q.idx % (N >> 1);
    const nxt = (lo + blowup) % N;
    const cols = [];
    for (let c = 0; c < W; c++) {
      cols.push({ cur: colLde[c][lo], cur_path: merkle.openAt(colMlayers[c], lo),
                  nxt: colLde[c][nxt], nxt_path: merkle.openAt(colMlayers[c], nxt) });
    }
    openings.push({ lo, cols });
  }
  return { T, W, N, blowup, deg_bound: degBound, col_roots: colRoots, boundaries, fri: friProof, openings };
}
