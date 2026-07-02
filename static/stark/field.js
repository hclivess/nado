/*
 * Goldilocks field + NTT for the browser STARK prover (doc/wasm-prover.md) — the exact counterpart of
 * execnode/stark/field.py, so a proof generated on-device is accepted by the unchanged Python verifier.
 * p = 2^64 - 2^32 + 1. BigInt arithmetic (Tier A); the hot loops move to WASM later (Tier B) without changing
 * any values. The NTT butterfly order + bit-reversal + roots mirror field.py exactly.
 */
export const P = 18446744069414584321n;
export const GEN = 7n;

const mod = (x) => ((x % P) + P) % P;
export const add = (a, b) => mod(a + b);
export const sub = (a, b) => mod(a - b);
export const mul = (a, b) => mod(a * b);
export function pw(a, e) {
  if (e < 0n) { a = inv(a); e = -e; }
  a = mod(a); let r = 1n;
  while (e > 0n) { if (e & 1n) r = mul(r, a); a = mul(a, a); e >>= 1n; }
  return r;
}
export const inv = (a) => pw(mod(a), P - 2n);
export const div = (a, b) => mul(a, inv(b));

// Montgomery batch inversion: invert a whole vector with ONE modular inversion + ~3N muls (instead of N invs).
// Assumes no zero entries (true for the STARK's coset-vs-trace-domain denominators).
export function batchInverse(vals) {
  const n = vals.length, out = new Array(n), prefix = new Array(n);
  let acc = 1n;
  for (let i = 0; i < n; i++) { prefix[i] = acc; acc = mul(acc, vals[i]); }
  let invAcc = inv(acc);
  for (let i = n - 1; i >= 0; i--) { out[i] = mul(prefix[i], invAcc); invAcc = mul(invAcc, vals[i]); }
  return out;
}

export function primitiveRootOfUnity(n) { return pw(GEN, (P - 1n) / BigInt(n)); }

export function domain(n, offset = 1n) {
  const w = primitiveRootOfUnity(n), out = new Array(n);
  out[0] = mod(offset);
  for (let i = 1; i < n; i++) out[i] = mul(out[i - 1], w);
  return out;
}

function bitrev(a) {
  const n = a.length; let j = 0;
  for (let i = 1; i < n; i++) {
    let bit = n >> 1;
    while (j & bit) { j ^= bit; bit >>= 1; }
    j ^= bit;
    if (i < j) { const t = a[i]; a[i] = a[j]; a[j] = t; }
  }
}

// Twiddle table w^0..w^(n/2-1) for a given size+direction, computed once and reused across every NTT of that
// size (all 16 column LDEs + 22 periodic LDEs + FRI layers share it). Removes the per-butterfly twiddle mul.
const _twCache = new Map();
function twiddles(n, inverse) {
  const key = (inverse ? "i" : "f") + n;
  let tw = _twCache.get(key);
  if (!tw) {
    const w = inverse ? inv(primitiveRootOfUnity(n)) : primitiveRootOfUnity(n);
    const h = n >> 1; tw = new Array(h); tw[0] = 1n;
    for (let j = 1; j < h; j++) tw[j] = mul(tw[j - 1], w);
    _twCache.set(key, tw);
  }
  return tw;
}

let _fw = null;   // optional WASM Goldilocks backend {ntt, scale, view, NMAX}
export function setFieldWasm(fw) { _fw = fw; }

export function ntt(coeffs, inverse = false) {
  const n = coeffs.length;
  if (n & (n - 1)) throw new Error("length must be a power of two");
  if (_fw && n <= _fw.NMAX) {
    const v = _fw.view;
    for (let i = 0; i < n; i++) v[i] = BigInt.asUintN(64, mod(BigInt(coeffs[i])));
    const root = inverse ? inv(primitiveRootOfUnity(n)) : primitiveRootOfUnity(n);
    _fw.ntt(n, BigInt.asUintN(64, root), inverse ? 1 : 0, inverse ? BigInt.asUintN(64, inv(BigInt(n))) : 0n);
    const out = new Array(n);
    for (let i = 0; i < n; i++) out[i] = v[i];
    return out;
  }
  const a = coeffs.map((c) => mod(BigInt(c)));
  bitrev(a);
  const tw = twiddles(n, inverse);
  let length = 2;
  while (length <= n) {
    const half = length >> 1, stride = n / length;
    for (let i = 0; i < n; i += length) {
      for (let m = 0; m < half; m++) {
        const t = tw[m * stride], k = i + m;
        const u = a[k], v = mul(a[k + half], t);
        a[k] = add(u, v);
        a[k + half] = sub(u, v);
      }
    }
    length <<= 1;
  }
  if (inverse) { const ni = inv(BigInt(n)); for (let i = 0; i < n; i++) a[i] = mul(a[i], ni); }
  return a;
}

export const interpolate = (evals) => ntt(evals, true);   // evals on the subgroup -> coefficients
export const evaluate = (coeffs) => ntt(coeffs, false);   // coefficients -> evals on the subgroup

export function polyEval(coeffs, x) {
  let acc = 0n;
  for (let i = coeffs.length - 1; i >= 0; i--) acc = add(mul(acc, x), coeffs[i]);
  return acc;
}

// evaluate a coefficient polynomial (len <= N) on the size-N coset {offset·w^i}
export function cosetEvaluate(coeffs, N, offset) {
  if (_fw && N <= _fw.NMAX) {
    const v = _fw.view, c = coeffs;
    for (let i = 0; i < N; i++) v[i] = i < c.length ? BigInt.asUintN(64, mod(BigInt(c[i]))) : 0n;
    _fw.scale(N, BigInt.asUintN(64, mod(offset)));
    _fw.ntt(N, BigInt.asUintN(64, primitiveRootOfUnity(N)), 0, 0n);
    const out = new Array(N);
    for (let i = 0; i < N; i++) out[i] = v[i];
    return out;
  }
  const c = coeffs.slice(); while (c.length < N) c.push(0n);
  let scale = 1n;
  const g = new Array(N);
  for (let j = 0; j < N; j++) { g[j] = mul(mod(BigInt(c[j])), scale); scale = mul(scale, offset); }
  return evaluate(g);
}
