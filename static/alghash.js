/*
 * STARK-friendly hash for the browser (doc/privacy.md) — the exact counterpart of execnode/stark/alghash.py,
 * so field-hash notes made in the wallet match what the exec node (and the zk-STARK) compute. A Poseidon-lite
 * sponge over the Goldilocks field p = 2^64 - 2^32 + 1: x^7 S-box, round constants, a 2×2 MDS, width-2 state
 * with a binding capacity. Field arithmetic is exact via BigInt; round constants reuse the byte-verified
 * blake2bHash (injected) so they equal Python's exactly.
 */
export const P = 18446744069414584321n;         // 2^64 - 2^32 + 1
const ALPHA = 7n, ROUNDS = 8;
const MDS = [[2n, 1n], [1n, 3n]];

const mod = (x) => ((x % P) + P) % P;
const add = (a, b) => mod(a + b);
const mul = (a, b) => mod(a * b);
function pw(a, e) {                                // a^e mod P (square-and-multiply)
  a = mod(a); let r = 1n;
  while (e > 0n) { if (e & 1n) r = mul(r, a); a = mul(a, a); e >>= 1n; }
  return r;
}
const sbox = (x) => pw(x, ALPHA);

let RC = null, IV = null;
export function initAlghash(blake2bHash) {
  // RC[r][j] = int(blake2b_hash(["poseidon","rc",str(r),str(j)]),16) % P ; IV = int(H(["poseidon","iv"]),16)%P
  const c = (...parts) => mod(BigInt("0x" + blake2bHash(["poseidon", ...parts.map(String)])));
  RC = []; for (let r = 0; r < ROUNDS; r++) RC.push([c("rc", r, 0), c("rc", r, 1)]);
  IV = c("iv");
}

export const DOM_OWNER = 1n, DOM_CM = 2n, DOM_NF = 3n, DOM_NODE = 4n;
// exposed for the in-browser circuit (joinsplit2.js) — must match execnode/stark/alghash.py
export const ALPHA_EXP = ALPHA, R_ROUNDS = ROUNDS;
export const sboxFn = (x) => sbox(x);
export const rcAt = (r, j) => RC[r][j];
export const ivVal = () => IV;

export function permute(state) {
  let [s0, s1] = state;
  for (let r = 0; r < ROUNDS; r++) {
    const t0 = sbox(add(s0, RC[r][0])), t1 = sbox(add(s1, RC[r][1]));
    s0 = add(mul(MDS[0][0], t0), mul(MDS[0][1], t1));
    s1 = add(mul(MDS[1][0], t0), mul(MDS[1][1], t1));
  }
  return [s0, s1];
}

export function hashn(elements) {
  let s = [0n, IV];
  for (const m of elements) s = permute([add(s[0], mod(BigInt(m))), s[1]]);
  return s[0];
}

export const ownerOf = (nsk) => hashn([DOM_OWNER, BigInt(nsk)]);
export const commit = (value, owner, rho) => hashn([DOM_CM, BigInt(value), BigInt(owner), BigInt(rho)]);
export const nullifier = (nsk, rho) => hashn([DOM_NF, BigInt(nsk), BigInt(rho)]);
export const merkleNode = (left, right) => hashn([DOM_NODE, BigInt(left), BigInt(right)]);
