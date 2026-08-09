/* FRI prover — exact port of execnode/stark/fri.py (prove side). Produces a proof the Python fri.verify accepts.
 * Supports the GF(p^DEGREE) extension-challenge path (fri.EXT_CHALLENGES): the fold challenge is drawn from the
 * extension field, ext layers commit an ext leaf digest (merkle.leafExt), and `final` absorbs the FLATTENED
 * limbs. Layer-0 ext-ness is DATA-DRIVEN (ext0): when the input evals are already extension-valued (the STARK's
 * composition under ext alphas), every layer is ext. Base-field proving (ext=false) is byte-identical to before. */
import * as F from "./field.js";
import * as merkle from "./merkle.js";
import { Transcript } from "./transcript.js";

const INV2 = F.inv(2n);

function fold(evals, dom, alpha) {
  const half = evals.length / 2, out = new Array(half);
  for (let i = 0; i < half; i++) {
    const fx = evals[i], fmx = evals[i + half], x = dom[i];
    const fe = F.mul(F.add(fx, fmx), INV2);
    const fo = F.mul(F.sub(fx, fmx), F.mul(INV2, F.inv(x)));
    out[i] = F.add(fe, F.mul(alpha, fo));
  }
  return out;
}

// One FRI fold with a GF(p^DEGREE) challenge — same identity as fold(), in the extension field. `evals` may be
// base ints (an ext0=false layer 0) or ext arrays; `dom` is base; `alpha` is an ext array. fe/fo scale by BASE
// constants (scalarMul), so only the single alpha*fo is a full extension multiply. Mirrors fri._fold_ext.
function foldExt(evals, dom, alpha) {
  const half = evals.length / 2, out = new Array(half);
  for (let i = 0; i < half; i++) {
    const fx = F.extLift(evals[i]), fmx = F.extLift(evals[i + half]), x = dom[i];
    const fe = F.extScalarMul(F.extAdd(fx, fmx), INV2);
    const fo = F.extScalarMul(F.extSub(fx, fmx), F.mul(INV2, F.inv(x)));
    out[i] = F.extAdd(fe, F.extMul(alpha, fo));
  }
  return out;
}

// Merkle-commit a layer of EXTENSION values: one ext-leaf digest per value, then a tree over the digests.
// Mirrors fri._commit_ext for the blake2b backend (merkle.commit_digests([leaf_ext(lift(v)) for v in values])).
function commitExt(values) {
  return merkle.commitDigests(values.map((v) => merkle.leafExt(F.extLift(v))));
}

export const NUM_QUERIES = 320;  // protocol query count (C-1) — MUST match execnode/stark/fri.py (was a stale 64)
export const GRIND_BITS = 18;    // proof-of-work bits (C-1) — must match execnode/stark/fri.py
export const EXT_CHALLENGES = true;  // draw the folding challenge from GF(p^DEGREE) — MUST match execnode/stark/fri.py

export function prove(evals, offset, blowup = 4, numQueries = NUM_QUERIES, transcript = null, ext = null) {
  const t = transcript || new Transcript("fri");
  const useExt = ext === null ? EXT_CHALLENGES : !!ext;
  const N = evals.length;
  const layers = [], roots = [];
  let cur = evals.slice(), off = offset;
  let dom = F.domain(N, off);
  // Layer-0 ext-ness is DATA-DRIVEN (fri.prove): the composition under ext alphas is already ext-valued, so
  // cur[0] is an array rather than a bigint; committing those as base ints would corrupt the leaves.
  const ext0 = useExt && cur.length > 0 && Array.isArray(cur[0]);
  let depth = 0;
  while (cur.length > blowup) {
    const isExtLayer = useExt && (depth > 0 || ext0);
    const [root, mlayers] = isExtLayer ? commitExt(cur) : merkle.commit(cur);
    roots.push(root); t.absorb(root);
    layers.push({ evals: cur, mlayers, dom, off });
    cur = useExt ? foldExt(cur, dom, t.challengeExt()) : fold(cur, dom, t.challenge());
    off = F.mul(off, off);
    dom = F.domain(cur.length, off);
    depth++;
  }
  const final = cur;
  t.absorb("final", ...(useExt ? F.extFlatten(final) : final));
  const pow = t.grind(GRIND_BITS);              // C-1: proof-of-work before deriving query positions
  const queries = [];
  for (let q = 0; q < numQueries; q++) {
    const idx = t.challengeIndex(N);
    const steps = [];
    let a = idx;
    for (const L of layers) {
      const n = L.evals.length, half = n >> 1;
      a %= n; const lo = a % half;
      steps.push({ lo: L.evals[lo], lo_path: merkle.openAt(L.mlayers, lo),
                   hi: L.evals[lo + half], hi_path: merkle.openAt(L.mlayers, lo + half) });
      a = lo;
    }
    queries.push({ idx, steps });
  }
  return { N, offset, blowup, roots, final, pow, queries, ext: useExt, ext0 };
}
