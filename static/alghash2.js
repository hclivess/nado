/*
 * alghash2 for the browser — the exact counterpart of execnode/stark/alghash2.py (the WIDE sponge the
 * shielded pool uses from SHIELD_WIDE_HEIGHT, security review 2026-09-23 Z3) and of execnode/stark/znote.py
 * (the note algebra over it). Width 12, rate 8, capacity 4 (a 256-bit digest), x^7 S-box, 54 rounds, a 12×12
 * Cauchy MDS. Round constants and the capacity IV reuse the byte-verified blake2bHash (injected) so they equal
 * Python's exactly; the MDS is 1/((i) − (12 + j)) mod p. A digest is an array of four BigInt lanes; its wire
 * form is 64 hex chars (16 per lane, big-endian per lane — storage_tree.digest_hex).
 */
export const P = 18446744069414584321n;         // 2^64 - 2^32 + 1
export const WIDTH = 12, RATE = 8, CAPACITY = 4;
const ALPHA = 7n, ROUNDS = 54;   // MUST match execnode/stark/alghash2.py (7^54 ≈ 2^151.6 ≥ the 2^128 collision bound)

const mod = (x) => ((x % P) + P) % P;
const add = (a, b) => mod(a + b);
const mul = (a, b) => mod(a * b);
function pw(a, e) {
  a = mod(a); let r = 1n;
  while (e > 0n) { if (e & 1n) r = mul(r, a); a = mul(a, a); e >>= 1n; }
  return r;
}
const inv = (a) => pw(a, P - 2n);
const sbox = (x) => pw(x, ALPHA);

let RC = null, IV = null;
export let MDS = null;
export function initAlghash2(blake2bHash) {
  // RC[r][i] = int(blake2b_hash(["alghash2","rc",str(r),str(i)]),16) % P ; IV[i] = H(["alghash2","iv",str(i)]) % P
  const c = (...parts) => mod(BigInt("0x" + blake2bHash(["alghash2", ...parts.map(String)])));
  RC = []; for (let r = 0; r < ROUNDS; r++) { const row = []; for (let i = 0; i < WIDTH; i++) row.push(c("rc", r, i)); RC.push(row); }
  IV = []; for (let i = 0; i < CAPACITY; i++) IV.push(c("iv", i));
  MDS = []; for (let i = 0; i < WIDTH; i++) { const row = []; for (let j = 0; j < WIDTH; j++) row.push(inv(mod(BigInt(i) - BigInt(WIDTH + j)))); MDS.push(row); }
}
export const ready = () => RC !== null;
export const ALPHA_EXP = ALPHA, R_ROUNDS = ROUNDS;
export const sboxFn = (x) => sbox(x);
export const rcAt = (r, i) => RC[r][i];
export const ivLanes = () => IV.slice();

export function permute(state) {
  let s = state.map((x) => mod(BigInt(x)));
  for (let r = 0; r < ROUNDS; r++) {
    const t = new Array(WIDTH);
    for (let i = 0; i < WIDTH; i++) t[i] = sbox(add(s[i], RC[r][i]));
    const n = new Array(WIDTH);
    for (let i = 0; i < WIDTH; i++) { let acc = 0n; const row = MDS[i]; for (let j = 0; j < WIDTH; j++) acc += row[j] * t[j]; n[i] = mod(acc); }
    s = n;
  }
  return s;
}

// [state, after round 0, …, after round ROUNDS-1] — the per-round witness the joinsplit3 trace needs.
export function permuteSnapshots(state) {
  let s = state.map((x) => mod(BigInt(x)));
  const rows = [s.slice()];
  for (let r = 0; r < ROUNDS; r++) {
    const t = new Array(WIDTH);
    for (let i = 0; i < WIDTH; i++) t[i] = sbox(add(s[i], RC[r][i]));
    const n = new Array(WIDTH);
    for (let i = 0; i < WIDTH; i++) { let acc = 0n; const row = MDS[i]; for (let j = 0; j < WIDTH; j++) acc += row[j] * t[j]; n[i] = mod(acc); }
    s = n; rows.push(s.slice());
  }
  return rows;
}

export function hashn(elements) {
  // length-prefixed sponge: state = [0]*RATE + IV; absorb RATE lanes at a time; digest = the first CAPACITY lanes
  const els = [BigInt(elements.length), ...elements.map((m) => mod(BigInt(m)))];
  let state = new Array(RATE).fill(0n).concat(IV);
  for (let off = 0; off < els.length; off += RATE) {
    const chunk = els.slice(off, off + RATE);
    for (let i = 0; i < chunk.length; i++) state[i] = add(state[i], chunk[i]);
    state = permute(state);
  }
  return state.slice(0, CAPACITY);
}

export function rnode(a, b) {   // one permutation over [a | b | IV], no length prefix (fixed arity)
  return permute([...a.map((x) => mod(BigInt(x))), ...b.map((x) => mod(BigInt(x))), ...IV]).slice(0, CAPACITY);
}

// ---- the wide note algebra (execnode/stark/znote.py) ----
export const DOM_ZOWNER = 21n, DOM_ZCM = 22n, DOM_ZNF = 23n;
export const EMPTY_LEAF = [0n, 0n, 0n, 0n];
export const ownerOf = (nsk) => hashn([DOM_ZOWNER, BigInt(nsk)]);
export const commit = (value, owner, rho) => hashn([DOM_ZCM, BigInt(value), ...owner.map(BigInt), BigInt(rho)]);
export const nullifier = (nsk, rho) => hashn([DOM_ZNF, BigInt(nsk), BigInt(rho)]);
export const merkleNode = (left, right) => rnode(left, right);
export function foldPath(leaf, sibs, dirs) {
  let acc = leaf.map(BigInt);
  for (let i = 0; i < sibs.length; i++) acc = (Number(dirs[i]) & 1) ? merkleNode(sibs[i], acc) : merkleNode(acc, sibs[i]);
  return acc;
}
export function toHex(d) { return d.map((x) => mod(BigInt(x)).toString(16).padStart(16, "0")).join(""); }
export function fromHex(h) {
  if (typeof h !== "string" || h.length !== 16 * CAPACITY) throw new Error("bad digest hex length");
  const out = [];
  for (let i = 0; i < CAPACITY; i++) { const v = BigInt("0x" + h.slice(i * 16, (i + 1) * 16)); if (v >= P) throw new Error("digest lane out of field"); out.push(v); }
  return out;
}
export const eq = (a, b) => a.length === b.length && a.every((x, i) => mod(BigInt(x)) === mod(BigInt(b[i])));

// The fixed-depth wide tree — execnode/shielded_wide.py's tree_path, so the path folds to the pool's root
// exactly as joinsplit3's MEMBERSHIP blocks do.
export const TREE_DEPTH = 12;
let _EMPTY = null;
function EMPTY() {
  if (!_EMPTY) { _EMPTY = [EMPTY_LEAF]; for (let i = 0; i < TREE_DEPTH; i++) _EMPTY.push(merkleNode(_EMPTY[i], _EMPTY[i])); }
  return _EMPTY;
}
export function treePath(leaves, pos) {
  const em = EMPTY();
  const sibs = [], dirs = [];
  let idx = pos, level = leaves.map((x) => (typeof x === "string" ? fromHex(x) : x.map(BigInt)));
  for (let d = 0; d < TREE_DEPTH; d++) {
    const sib = idx ^ 1;
    sibs.push(sib < level.length ? level[sib] : em[d]);
    dirs.push(idx & 1);
    const nxt = [];
    for (let i = 0; i < level.length; i += 2) nxt.push(merkleNode(level[i], i + 1 < level.length ? level[i + 1] : em[d]));
    level = nxt; idx = Math.floor(idx / 2);
  }
  return { sibs, dirs };
}
export function treeRoot(leaves) {
  if (!leaves.length) return EMPTY()[TREE_DEPTH];
  const em = EMPTY();
  let level = leaves.map((x) => (typeof x === "string" ? fromHex(x) : x.map(BigInt)));
  for (let d = 0; d < TREE_DEPTH; d++) {
    const nxt = [];
    for (let i = 0; i < level.length; i += 2) nxt.push(merkleNode(level[i], i + 1 < level.length ? level[i + 1] : em[d]));
    level = nxt;
  }
  return level[0];
}
