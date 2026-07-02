/*
 * NADO shielded-pool CLIENT crypto (doc/privacy.md) — the exact browser counterpart of execnode/shielded.py.
 *
 * Every hash here is byte-identical to the Python exec node, so a note committed / nullifier revealed / spend
 * authorised in the browser is accepted by the pool. That identity rests on ONE dependency: `blake2bHash`,
 * which is already byte-verified against Python vectors (see miner.js). We compose it exactly as Python's
 * _h does — blake2b_hash(["nado.shield", *map(str, parts)]) — and keep every scalar a STRING so there is no
 * language-specific number/list formatting to diverge on.
 *
 * The blake2bHash primitive is INJECTED via initShielded(...) so this same module runs unchanged in the
 * browser (miner.js passes its CDN-backed blake2bHash) and under node (the cross-check harness passes one
 * built from the vendored @noble blake2b) — proving the two agree.
 */
export const SHIELD_DEPTH = 32;

let _blake2bHash = null;
export function initShielded(blake2bHashFn) { _blake2bHash = blake2bHashFn; }

// domain-separated pool hash over canonical JSON — mirrors Python _h(*parts) exactly (every part -> string)
function _h(...parts) {
  if (!_blake2bHash) throw new Error("shielded.js not initialised (call initShielded)");
  return _blake2bHash(["nado.shield", ...parts.map((p) => String(p))]);
}

// --- empty-subtree roots (e[i] = root of an all-empty subtree of height i) ---
function _emptyRoots(depth) {
  const e = [_h("empty-leaf")];
  for (let i = 0; i < depth; i++) e.push(_h("node", e[e.length - 1], e[e.length - 1]));
  return e;
}
let _EMPTY = null;
function EMPTY() { if (!_EMPTY) _EMPTY = _emptyRoots(SHIELD_DEPTH); return _EMPTY; }
export function emptyRoot() { return EMPTY()[SHIELD_DEPTH]; }

// --- note commitment + nullifier + owner (value is ALWAYS a decimal string, like Python str(int(value))) ---
export function ownerId(pubkey) { return _h("owner", pubkey); }
export function noteCommitment(value, owner, rho) { return _h("cm", _dec(value), owner, rho); }
export function noteNullifier(pubkey, rho) { return _h("nf", pubkey, rho); }

function _dec(v) {
  // reproduce Python str(int(value)): accept number | string | bigint, emit an exact decimal string
  if (typeof v === "bigint") return v.toString();
  if (typeof v === "string") return BigInt(v).toString();   // normalises "007" etc.; throws on non-integer
  return BigInt(Math.trunc(v)).toString();
}

// the message an input's owner ML-DSA-signs — lists sorted + '|'-joined (matches transfer_sighash in Python)
export function transferSighash(pub) {
  const nfs = (pub.nullifiers || []).slice().sort();
  const cms = (pub.out_commitments || []).slice().sort();
  return _h("sighash", nfs.join("|"), cms.join("|"), _dec(pub.public_value || 0), _dec(pub.fee || 0));
}

// --- fixed-depth Merkle commitment tree ---
export function merkleRoot(leaves) {
  if (!leaves.length) return emptyRoot();
  let level = leaves.slice();
  for (let d = 0; d < SHIELD_DEPTH; d++) {
    const nxt = [];
    for (let i = 0; i < level.length; i += 2) {
      const left = level[i];
      const right = i + 1 < level.length ? level[i + 1] : EMPTY()[d];
      nxt.push(_h("node", left, right));
    }
    level = nxt;
  }
  return level[0];
}

export function merklePath(leaves, pos) {
  const path = [];
  let idx = pos, level = leaves.slice();
  for (let d = 0; d < SHIELD_DEPTH; d++) {
    const sib = idx ^ 1;
    path.push(sib < level.length ? level[sib] : EMPTY()[d]);
    const nxt = [];
    for (let i = 0; i < level.length; i += 2) {
      const left = level[i];
      const right = i + 1 < level.length ? level[i + 1] : EMPTY()[d];
      nxt.push(_h("node", left, right));
    }
    level = nxt; idx = Math.floor(idx / 2);
  }
  return path;
}

export function verifyPath(leaf, pos, path, root) {
  let h = leaf, idx = pos;
  for (let d = 0; d < SHIELD_DEPTH; d++) {
    h = idx % 2 === 0 ? _h("node", h, path[d]) : _h("node", path[d], h);
    idx = Math.floor(idx / 2);
  }
  return h === root;
}
