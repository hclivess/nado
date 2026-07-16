"""
Sparse Merkle STORAGE tree (state-root binding, doc/zk-recursion.md §5b piece (a)).

The settled state root today is a FLAT blake2b merkle over EVERY storage leaf (settlement_proofs.zkvm_root), so
verify_epoch re-merkleizes the WHOLE state and REPLAYS the io per segment — O(state)·O(K). This module is the
foundation for binding pre_root → post_root WITHOUT that: a fixed-depth SPARSE Merkle tree over alghash (the
arithmetization-friendly, blake2b-free hash membership.py already folds in-circuit), keyed by slot, so a touched
slot updates in O(depth) folds. The verifier then confirms a state transition by APPLYING the epoch's io as
sparse updates (verify a SLOAD's value is a member; apply an SSTORE and advance the root) — O(touched·depth)
native folds instead of O(state) — and, later, those same folds move IN-CIRCUIT (membership.py) for O(1).

alghash (not blake2b) so the transition is provable in the recursion layer; leaf = value, empty leaf = 0,
position = the low `depth` bits of key(cid, slot). This is the mechanism; wiring it as THE settled root (in
place of zkvm_root, and in the bridge/dividend/unshield Merkle proofs) is the settlement integration on top.
"""
from execnode.stark import field as F, alghash


def _empty_roots(depth):
    """e[i] = root of an all-empty subtree of height i (e[0] = empty leaf = 0; e[depth] = empty-tree root)."""
    e = [0]
    for _ in range(depth):
        e.append(alghash.merkle_node(e[-1], e[-1]))
    return e


def fold(leaf, key, siblings):
    """Root obtained by folding `leaf` at position `key` up through `siblings` (siblings[i] = the sibling at
    level i, bit i of key = 0 ⇒ leaf-side is LEFT). In-clear; the AIR (membership.py) reproduces this."""
    node = int(leaf) % F.P
    for i, sib in enumerate(siblings):
        left, right = (node, int(sib) % F.P) if ((key >> i) & 1) == 0 else (int(sib) % F.P, node)
        node = alghash.merkle_node(left, right)
    return node


class SparseStore:
    """A sparse alghash Merkle tree over {key: value} at fixed `depth`. Missing keys read 0. Deterministic root
    + authentication paths, so a verifier can check/apply single-slot updates without the whole tree."""

    def __init__(self, depth, values=None):
        self.depth = depth
        self.e = _empty_roots(depth)
        self.values = {int(k) & ((1 << depth) - 1): int(v) % F.P for k, v in (values or {}).items()}

    def _node(self, level, index):
        """Root of the subtree of height `level` rooted at horizontal `index` — recursion memoized by emptiness:
        an all-empty subtree is e[level], so only the O(#nonempty·depth) populated spine is ever hashed."""
        if level == 0:
            return self.values.get(index, 0)
        # if no populated key lies under this subtree, it's the canonical empty root (the sparse shortcut)
        lo = index << level
        hi = lo + (1 << level)
        if not any(lo <= k < hi for k in self.values):
            return self.e[level]
        left = self._node(level - 1, index * 2)
        right = self._node(level - 1, index * 2 + 1)
        return alghash.merkle_node(left, right)

    def root(self):
        return self._node(self.depth, 0)

    def path(self, key):
        """Authentication siblings for `key` (level 0 .. depth-1), bottom-up."""
        key &= (1 << self.depth) - 1
        sibs, index = [], key
        for level in range(self.depth):
            sib_index = index ^ 1
            sibs.append(self._node(level, sib_index))
            index >>= 1
        return sibs

    def get(self, key):
        return self.values.get(int(key) & ((1 << self.depth) - 1), 0)

    def set(self, key, value):
        self.values[int(key) & ((1 << self.depth) - 1)] = int(value) % F.P


def verify_read(root, key, value, siblings):
    """True iff `value` is the committed value at `key` under `root` (a membership fold)."""
    return fold(value, key, siblings) == root


def apply_update(root, key, old_value, new_value, siblings):
    """Verify `old_value` sits at `key` under `root`, then return the NEW root after writing `new_value` there
    (same siblings — only the leaf changes). Raises if the old value / path do not authenticate `root`."""
    if fold(old_value, key, siblings) != root:
        raise ValueError("update: old value/path does not authenticate the pre-root")
    return fold(new_value, key, siblings)


def verify_transition(pre_root, ops):
    """Apply an ordered list of storage ops to `pre_root` and return post_root — WITHOUT the whole state. Each
    op carries its own authentication path (from the CURRENT root at that point in the sequence):
      {"kind": "read",  "key", "val", "siblings"}   — a SLOAD: `val` must be the committed value; or
      {"kind": "write", "key", "old", "new", "siblings"} — an SSTORE: verify `old`, advance the root to `new`.
    This is the O(#ops · depth) transition check that REPLACES verify_epoch's whole-state re-merkleize + io
    replay (O(state)): the verifier confirms pre_root → post_root touching only the accessed slots. Raises on
    any inconsistency (a read that isn't a member, a write whose old value doesn't authenticate)."""
    root = pre_root
    for op in ops:
        if op["kind"] == "read":
            if not verify_read(root, op["key"], op["val"], op["siblings"]):
                raise ValueError("transition: a read does not authenticate the current root")
        elif op["kind"] == "write":
            root = apply_update(root, op["key"], op["old"], op["new"], op["siblings"])
        else:
            raise ValueError(f"transition: unknown op kind {op.get('kind')!r}")
    return root
