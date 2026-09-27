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
// THE SPEND KEY IS FOUR LANES (znote.nsk_lanes, review 2026-09-24): an array of four field elements; a single value
// is (nsk, 0, 0, 0), accepted for tests only — the wallet always derives four lanes.
export function nskLanes(nsk) {
  if (Array.isArray(nsk)) { if (nsk.length !== CAPACITY) throw new Error("a wide spend key has exactly 4 lanes"); return nsk.map((x) => mod(BigInt(x))); }
  return [mod(BigInt(nsk)), 0n, 0n, 0n];
}
export const ownerOf = (nsk) => hashn([DOM_ZOWNER, ...nskLanes(nsk)]);
export const commit = (value, owner, rho) => hashn([DOM_ZCM, BigInt(value), ...owner.map(BigInt), BigInt(rho)]);
export const nullifier = (nsk, rho) => hashn([DOM_ZNF, ...nskLanes(nsk), BigInt(rho)]);
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
// THE DEPTH IS THE EXEC NODE'S, NOT THIS FILE'S (ZK_HARDEN_HEIGHT, zk audit 2026-09-26): the pool grows from depth 12 to
// 48 at a height, and /exec/field_leaves reports the depth to build at. treeDepth(response) reads it; LEGACY_TREE_DEPTH
// is only what an exec node from before that field means (it never said, and it was 12). Never pass a constant here.
export const LEGACY_TREE_DEPTH = 12;
export function treeDepth(leavesResponse) {
  const d = leavesResponse && leavesResponse.depth;
  if (d === undefined || d === null) return LEGACY_TREE_DEPTH;
  const n = Number(d);
  // a sanity bound, not the protocol's list: the node's verifier decides which depth it accepts
  if (!Number.isInteger(n) || n < 1 || n > 64) throw new Error("the exec node reported a bad shielded tree depth: " + d);
  return n;
}
const _EMPTY = [EMPTY_LEAF];
function EMPTY(depth) {
  while (_EMPTY.length <= depth) { const e = _EMPTY[_EMPTY.length - 1]; _EMPTY.push(merkleNode(e, e)); }
  return _EMPTY;
}
export function treePath(leaves, pos, depth = LEGACY_TREE_DEPTH) {
  const em = EMPTY(depth);
  const sibs = [], dirs = [];
  let idx = pos, level = leaves.map((x) => (typeof x === "string" ? fromHex(x) : x.map(BigInt)));
  for (let d = 0; d < depth; d++) {
    const sib = idx ^ 1;
    sibs.push(sib < level.length ? level[sib] : em[d]);
    dirs.push(idx & 1);
    const nxt = [];
    for (let i = 0; i < level.length; i += 2) nxt.push(merkleNode(level[i], i + 1 < level.length ? level[i + 1] : em[d]));
    level = nxt; idx = Math.floor(idx / 2);
  }
  return { sibs, dirs };
}
export function treeRoot(leaves, depth = LEGACY_TREE_DEPTH) {
  if (!leaves.length) return EMPTY(depth)[depth];
  const em = EMPTY(depth);
  let level = leaves.map((x) => (typeof x === "string" ? fromHex(x) : x.map(BigInt)));
  for (let d = 0; d < depth; d++) {
    const nxt = [];
    for (let i = 0; i < level.length; i += 2) nxt.push(merkleNode(level[i], i + 1 < level.length ? level[i + 1] : em[d]));
    level = nxt;
  }
  return level[0];
}
