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
  const last = F.pw(gT, BigInt(T - 1));
  const xT = new Array(N);
  for (let j = 0; j < N; j++) xT[j] = F.pw(xLde[j], BigInt(T));
  const cp = new Array(N).fill(0n);
  let ai = 0;
  for (const con of transitions) {
    const a = alphas[ai++];
    for (let j = 0; j < N; j++) {
      const cur = new Array(W), nxt = new Array(W);
      const jn = (j + blowup) % N;
      for (let c = 0; c < W; c++) { cur[c] = colLde[c][j]; nxt[c] = colLde[c][jn]; }
      const per = perLde.map((pc) => pc[j]);
      const z = F.mul(F.sub(xT[j], 1n), F.inv(F.sub(xLde[j], last)));
      cp[j] = F.add(cp[j], F.mul(a, F.mul(con(cur, nxt, per), F.inv(z))));
    }
  }
  for (const [row, col, val] of boundaries) {
    const a = alphas[ai++];
    const pt = F.pw(gT, BigInt(row));
    for (let j = 0; j < N; j++) {
      const b = F.sub(colLde[col][j], BigInt(val));
      cp[j] = F.add(cp[j], F.mul(a, F.mul(b, F.inv(F.sub(xLde[j], pt)))));
    }
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
  const colLde = colPolys.map((p) => F.cosetEvaluate(p, N, OFF));
  const perLde = periodic.map((pc) => F.cosetEvaluate(F.interpolate(pc.map((x) => BigInt(x))), N, OFF));
  const xLde = F.domain(N, OFF);
  const degBound = nextPow2(maxDegree) * T;

  const t = new Transcript("nado-stark");
  const colRoots = [], colMlayers = [];
  for (let c = 0; c < W; c++) {
    const [root, ml] = merkle.commit(colLde[c]);
    colRoots.push(root); colMlayers.push(ml); t.absorb(root);
  }
  const alphas = [];
  for (let i = 0; i < transitions.length + boundaries.length; i++) alphas.push(t.challenge());
  const cp = composition(T, W, N, blowup, gT, colLde, perLde, xLde, transitions, boundaries, alphas);

  const friBlowup = N / degBound;
  const friProof = fri.prove(cp, OFF, friBlowup, numQueries, t);

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
