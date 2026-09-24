/* STARK prover — exact port of execnode/stark/stark.py (prove side): interpolate columns -> LDE -> composition
 * (with periodic columns) -> FRI -> trace openings. Produces a proof the Python stark.verify accepts. */
import * as F from "./field.js";
import * as merkle from "./merkle.js";
import * as fri from "./fri.js";
import { Transcript, DOMAIN_STARK } from "./transcript.js";
import { b2b32, i8le, hexToBytes } from "./bhash.js";   // round-2 prologue (airDigest / aux lanes)

export const OFF = F.GEN;
export const NUM_QUERIES = fri.NUM_QUERIES;   // protocol query count (C-1), single source of truth = fri.js

const _perLdeCache = new WeakMap();   // periodic array -> {N, lde}; the periodic LDE is witness-independent

function nextPow2(x) { let p = 1; while (p < x) p <<= 1; return p; }
function blowupOf(maxDegree) { return 2 * nextPow2(maxDegree); }

function composition(T, W, N, blowup, gT, colLde, perLde, xLde, transitions, boundaries, alphas, useExt) {
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
  // EXTENSION alphas (stark.EXT_ALPHAS): the constraint VALUES stay base-field (this circuit has no ext aux
  // columns), so each term is extScalarMul(alpha, base_value * invZ) and cp becomes GF(p^DEGREE)-valued —
  // exactly _composition._combine(a, v, iz) = ext.mul(a, ext.scalar_mul(lift(v), iz)) for a base v. FRI carries
  // the ext-ness from layer 0 via ext0.
  if (useExt) {
    const cp = new Array(N); for (let j = 0; j < N; j++) cp[j] = F.EXT_ZERO;
    let ai = 0;
    for (const con of transitions) {
      const a = alphas[ai++];
      for (let j = 0; j < N; j++) cp[j] = F.extAdd(cp[j], F.extScalarMul(a, mul(con(curRow[j], nxtRow[j], perRow[j]), invZ[j])));
    }
    for (const [row, col, val] of boundaries) {
      const a = alphas[ai++], pt = pw(gT, BigInt(row)), v = BigInt(val), den = new Array(N);
      for (let j = 0; j < N; j++) den[j] = sub(xLde[j], pt);
      const invDen = batchInverse(den);
      for (let j = 0; j < N; j++) cp[j] = F.extAdd(cp[j], F.extScalarMul(a, mul(sub(colLde[col][j], v), invDen[j])));
    }
    return cp;
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

// REVIEW ROUND 2 (2026-09-23, execnode/stark/stark.py absorb_aux / air_digest / absorb_air). Under `rules.round2`
// the transcript prologue is: aux as the 8 u32 lanes of blake2b(aux) (never the raw string — the node's alghash2
// backend hashed a string by its byte SUM), then the AIR identity: blake2b("nado-air-v1" ‖ T ‖ W ‖ maxDegree ‖
// #transitions ‖ #boundaries ‖ #periodic ‖ each boundary (row, col, val) ‖ each periodic column (len ‖ values)),
// every number a little-endian u64, absorbed as 8 u32 lanes. Byte-for-byte the Python layout; a proof made with
// the wrong prologue is refused by the node at the gate, so the caller reads the gate height from /status.
function lanes32(hex) {                       // stark.statement_lanes: 32 digest bytes -> 8 little-endian u32 ints
  const b = hexToBytes(hex), out = [];
  for (let i = 0; i < 32; i += 4) out.push(BigInt(b[i] | (b[i + 1] << 8) | (b[i + 2] << 16)) + (BigInt(b[i + 3]) << 24n));
  return out;
}
export function airDigest(T, W, blowup, nTransitions, boundaries, periodic) {   // blowup = 2·nextPow2(maxDegree), as Python
  const parts = [_TE.encode("nado-air-v1"), i8le(T), i8le(W), i8le(blowup), i8le(nTransitions), i8le(boundaries.length),
                 i8le(periodic ? periodic.length : 0)];
  for (const [row, col, val] of boundaries) parts.push(i8le(row), i8le(col), i8le(val));
  if (periodic) for (const pc of periodic) { parts.push(i8le(pc.length)); for (const v of pc) parts.push(i8le(v)); }
  return b2b32(...parts);
}
const _TE = new TextEncoder();
function _salts(n) {                                 // n hex salts of 32 bytes, from the platform CSPRNG
  const out = new Array(n), buf = new Uint8Array(32 * 1024);
  for (let i = 0; i < n; i += 1024) {
    globalThis.crypto.getRandomValues(buf);
    for (let k = 0; k < 1024 && i + k < n; k++) { let s = ""; for (let b = 0; b < 32; b++) s += buf[k * 32 + b].toString(16).padStart(2, "0"); out[i + k] = s; }
  }
  return out;
}

export function prove(trace, transitions, boundaries, periodic = [], maxDegree = 2, numQueries = NUM_QUERIES, aux = null, rules = {}) {  // NUM_QUERIES from fri.js (C-1)
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
  // The periodic LDE is witness-independent (columns depend only on T,D) — cache it by the periodic array
  // (joinsplit2.periodic returns the same array per T,D), so it's computed once and reused every proof.
  const _pc = _perLdeCache.get(periodic);
  let perLde;
  if (_pc && _pc.N === N) perLde = _pc.lde;
  else { perLde = periodic.map((pc) => F.cosetEvaluate(F.interpolate(pc.map((x) => BigInt(x))), N, OFF)); _perLdeCache.set(periodic, { N, lde: perLde }); }
  _mk("perLde (22 coset NTT)");
  const xLde = F.domain(N, OFF);
  const degBound = nextPow2(maxDegree) * T;

  const t = new Transcript(DOMAIN_STARK);
  if (aux !== null && aux !== undefined) {                              // H-4: bind the unshield withdraw_addr
    if (rules.round2) t.absorb("aux", ...lanes32(b2b32(_TE.encode(String(aux)))));   // P2: digest lanes, exact
    else t.absorb("aux", String(aux));
  }
  // The AIR identity hashes the LDE BLOWUP (stark.air_digest's third field), not max_degree: they differ for
  // every real circuit (7 vs 16 for the join-splits), and passing maxDegree here diverged the transcript from
  // the node's under round 2 — found by the cross-check the day before the gate.
  if (rules.round2) t.absorb("air", ...lanes32(airDigest(T, W, blowup, transitions.length, boundaries, periodic)));
  // Z1 (stark.prove zk=): the last `zk` columns are randomizers, every leaf is salted, and their combination
  // R(x) = sum x^(iT) r_i(x) masks the FRI input. Salts are 32 random bytes per leaf per column.
  const zk = rules.zk ? Number(rules.zk) : 0;
  const salts = zk ? Array.from({ length: W }, () => _salts(N)) : null;
  const colRoots = [], colMlayers = [];
  for (let c = 0; c < W; c++) {
    const [root, ml] = zk ? merkle.commitSalted(colLde[c], salts[c]) : merkle.commit(colLde[c]);
    colRoots.push(root); colMlayers.push(ml); t.absorb(root);
  }
  _mk("merkle.commit x16 (blake2b)");
  // CONSTRAINT ALPHAS from GF(p^DEGREE) (stark.EXT_ALPHAS) — a base-field alpha caps the STARK's commit phase
  // far below what FRI buys, so the Python verifier draws them from the extension field and rejects a
  // base-field proof. Draw them the same way; the aux (LogUp) challenges do not apply — this circuit has none.
  const useExt = fri.EXT_CHALLENGES;
  const alphas = [];
  for (let i = 0; i < transitions.length + boundaries.length; i++) alphas.push(useExt ? t.challengeExt() : t.challenge());
  const cp = composition(T, W, N, blowup, gT, colLde, perLde, xLde, transitions, boundaries, alphas, useExt);
  _mk("composition (17 constraints)");
  // P1 (PROOF_TRACE_LDT_HEIGHT, stark.trace_batch_add): the trace columns ride into FRI with the composition as
  // sum_c beta^(c+1) f_c(x), beta drawn right after the alphas. The node adds the same term at every query
  // point, so a proof made without it is refused at the gate (and one made with it, below the gate).
  if (rules.traceLdt) {
    const beta = useExt ? t.challengeExt() : t.challenge();
    // PROOF_QUERY_FULL_HEIGHT (stark.trace_batch_shift): the summed batch is multiplied by x^(degBound - T) on the
    // coset, which forces every column below degree T inside FRI's bound. Accumulate first, shift once — the same
    // order as stark.trace_batch_add and the native sp_batch_add_shift, so all three agree bit for bit.
    const shift = rules.fullQuery ? BigInt(degBound - T) : 0n;
    const acc = new Array(N);
    for (let j = 0; j < N; j++) acc[j] = useExt ? F.extLift(0n) : 0n;
    let pw = beta;
    for (let c = 0; c < W; c++) {
      const col = colLde[c];
      if (useExt) { for (let j = 0; j < N; j++) acc[j] = F.extAdd(acc[j], F.extScalarMul(pw, col[j])); pw = F.extMul(pw, beta); }
      else { for (let j = 0; j < N; j++) acc[j] = F.add(acc[j], F.mul(pw, col[j])); pw = F.mul(pw, beta); }
    }
    for (let j = 0; j < N; j++) {
      const k = shift ? F.pw(xLde[j], shift) : 1n;
      cp[j] = useExt ? F.extAdd(cp[j], F.extScalarMul(acc[j], k)) : F.add(cp[j], F.mul(k, acc[j]));
    }
    _mk("trace batch (P1)");
  }
  if (zk) {                                          // Z1: the randomizer polynomial (stark.zk_randomizer_add)
    const Tb = BigInt(T);
    for (let j = 0; j < N; j++) {
      const xT = F.pw(xLde[j], Tb); let pw = 1n, acc = 0n;
      for (let i = 0; i < zk; i++) { acc = F.add(acc, F.mul(pw, colLde[W - zk + i][j])); pw = F.mul(pw, xT); }
      cp[j] = useExt ? F.extAdd(cp[j], F.extLift(acc)) : F.add(cp[j], acc);
    }
    _mk("zk randomizer (Z1)");
  }

  const friBlowup = N / degBound;
  const friProof = fri.prove(cp, OFF, friBlowup, numQueries, t, useExt);
  _mk("fri.prove");

  const openings = [];
  for (const q of friProof.queries) {
    // PROOF_QUERY_FULL_HEIGHT (stark.query_pos): open the trace where the query really lands, over the whole domain.
    const lo = rules.fullQuery ? q.idx : q.idx % (N >> 1);
    const nxt = (lo + blowup) % N;
    const cols = [];
    for (let c = 0; c < W; c++) {
      const col = { cur: colLde[c][lo], cur_path: merkle.openAt(colMlayers[c], lo),
                    nxt: colLde[c][nxt], nxt_path: merkle.openAt(colMlayers[c], nxt) };
      if (zk) { col.cur_salt = salts[c][lo]; col.nxt_salt = salts[c][nxt]; }
      cols.push(col);
    }
    openings.push({ lo, cols });
  }
  return { T, W, N, blowup, deg_bound: degBound, col_roots: colRoots, boundaries, fri: friProof, openings };
}
