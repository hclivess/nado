"""
Sparse Merkle STORAGE tree (state-root binding, doc/zk-recursion.md §5b piece (a)) — the SETTLED state root.

A fixed-depth SPARSE Merkle tree over ALGHASH2 (the wide sponge: RATE 8 / CAPACITY 4 → 256-bit capacity ⇒
~128-bit collision resistance), keyed by slot. The digest is a CAPACITY-tuple (4 field elements); a leaf is
alghash2.rleaf(value) and an inner node is alghash2.rnode(left, right) — exactly the one-permutation-per-level
tree the recursion membership AIR (recursion.py) arithmetizes, so the in-circuit update (merkle_update) folds it
directly. (The earlier width-2 alghash root was ~32-bit — fine as a mechanism, forgeable as a live state root;
this is the secure version wired as THE settled root.)

A touched slot updates in O(depth) folds; the verifier confirms a transition by APPLYING the epoch's io as sparse
updates (a SLOAD's value is a member; an SSTORE advances the root) — O(touched·depth) native folds, or in-circuit
(merkle_update) for O(1). Root/paths are CAPACITY-tuples throughout.
"""
from execnode.stark import field as F, alghash2 as A2

DIGEST = A2.CAPACITY                              # a node digest is CAPACITY field elements


def _leaf(value):
    return A2.rleaf(int(value) % F.P)


def _empty_roots(depth):
    """e[i] = digest of an all-empty subtree of height i (e[0] = rleaf(0); e[depth] = empty-tree root)."""
    e = [_leaf(0)]
    for _ in range(depth):
        e.append(A2.rnode(e[-1], e[-1]))
    return e


def fold(leaf_value, key, siblings):
    """Root (a CAPACITY-tuple) obtained by folding value `leaf_value` at position `key` up through `siblings`
    (siblings[i] = the sibling digest at level i; bit i of key = 0 ⇒ leaf-side is LEFT). In-clear; the AIR
    (merkle_update) reproduces this."""
    node = _leaf(leaf_value)
    for i, sib in enumerate(siblings):
        s = tuple(int(x) % F.P for x in sib)
        left, right = (node, s) if ((key >> i) & 1) == 0 else (s, node)
        node = A2.rnode(left, right)
    return node


class SparseStore:
    """A sparse alghash2 Merkle tree over {key: value} at fixed `depth`. Missing keys read 0. Deterministic root
    + authentication paths (all CAPACITY-tuples), so a verifier can check/apply single-slot updates without the
    whole tree."""

    def __init__(self, depth, values=None):
        self.depth = depth
        self.e = _empty_roots(depth)
        self.values = {int(k) & ((1 << depth) - 1): int(v) % F.P for k, v in (values or {}).items()}

    def _node(self, level, index):
        """Digest of the subtree of height `level` rooted at horizontal `index` — recursion memoized by
        emptiness: an all-empty subtree is e[level], so only the O(#nonempty·depth) populated spine is hashed."""
        if level == 0:
            return _leaf(self.values.get(index, 0))
        lo = index << level
        hi = lo + (1 << level)
        if not any(lo <= k < hi for k in self.values):
            return self.e[level]
        left = self._node(level - 1, index * 2)
        right = self._node(level - 1, index * 2 + 1)
        return A2.rnode(left, right)

    def root(self):
        return self._node(self.depth, 0)

    def path(self, key):
        """Authentication siblings for `key` (level 0 .. depth-1), bottom-up — each a CAPACITY-tuple."""
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


def _eq(a, b):
    return tuple(int(x) % F.P for x in a) == tuple(int(x) % F.P for x in b)


def verify_read(root, key, value, siblings):
    """True iff `value` is the committed value at `key` under `root` (a membership fold). Digests are tuples."""
    return _eq(fold(value, key, siblings), root)


def apply_update(root, key, old_value, new_value, siblings):
    """Verify `old_value` sits at `key` under `root`, then return the NEW root after writing `new_value` there
    (same siblings — only the leaf changes). Raises if the old value / path do not authenticate `root`."""
    if not _eq(fold(old_value, key, siblings), root):
        raise ValueError("update: old value/path does not authenticate the pre-root")
    return fold(new_value, key, siblings)


def verify_transition(pre_root, ops):
    """Apply an ordered list of storage ops to `pre_root` and return post_root — WITHOUT the whole state. Each
    op carries its own authentication path (from the CURRENT root at that point in the sequence):
      {"kind": "read",  "key", "val", "siblings"}   — a SLOAD: `val` must be the committed value; or
      {"kind": "write", "key", "old", "new", "siblings"} — an SSTORE: verify `old`, advance the root to `new`.
    Raises on any inconsistency (a read that isn't a member, a write whose old value doesn't authenticate)."""
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
