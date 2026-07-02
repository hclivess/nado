/* Fixed-depth alghash Merkle tree in the browser — exact port of execnode/shielded_field.py's tree, so the
 * membership path built here folds to the same root the circuit's membership region does. */
import * as A from "../alghash.js";

export const TREE_DEPTH = 12;
const EMPTY_LEAF = 0n;
let _EMPTY = null;
function EMPTY() {
  if (!_EMPTY) { _EMPTY = [EMPTY_LEAF]; for (let i = 0; i < TREE_DEPTH; i++) _EMPTY.push(A.merkleNode(_EMPTY[_EMPTY.length - 1], _EMPTY[_EMPTY.length - 1])); }
  return _EMPTY;
}

export function treePath(leaves, pos) {
  const em = EMPTY();
  const sibs = [], dirs = [];
  let idx = pos, level = leaves.map((x) => BigInt(x));
  for (let d = 0; d < TREE_DEPTH; d++) {
    const sib = idx ^ 1;
    sibs.push(sib < level.length ? level[sib] : em[d]);
    dirs.push(idx & 1);
    const nxt = [];
    for (let i = 0; i < level.length; i += 2) {
      const left = level[i], right = i + 1 < level.length ? level[i + 1] : em[d];
      nxt.push(A.merkleNode(left, right));
    }
    level = nxt; idx = Math.floor(idx / 2);
  }
  return { sibs, dirs };
}
