/* FRI prover — exact port of execnode/stark/fri.py (prove side). Produces a proof the Python fri.verify accepts. */
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

export function prove(evals, offset, blowup = 4, numQueries = 32, transcript = null) {
  const t = transcript || new Transcript("fri");
  const N = evals.length;
  const layers = [], roots = [];
  let cur = evals.slice(), off = offset;
  let dom = F.domain(N, off);
  while (cur.length > blowup) {
    const [root, mlayers] = merkle.commit(cur);
    roots.push(root); t.absorb(root);
    const alpha = t.challenge();
    layers.push({ evals: cur, mlayers, dom, off });
    cur = fold(cur, dom, alpha);
    off = F.mul(off, off);
    dom = F.domain(cur.length, off);
  }
  const final = cur;
  t.absorb("final", ...final);
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
  return { N, offset, blowup, roots, final, queries };
}
