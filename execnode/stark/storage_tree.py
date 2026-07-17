"""
Sparse Merkle STORAGE tree (state-root binding, doc/zk-recursion.md §5b piece (a)) — the SETTLED state root.

A fixed-depth SPARSE Merkle tree over ALGHASH2 (the wide sponge: RATE 8 / CAPACITY 4 → 256-bit capacity ⇒
~128-bit collision resistance), keyed by slot. The digest is a CAPACITY-tuple (4 field elements); a leaf is
alghash2.rleaf(value) and an inner node is alghash2.rnode(left, right) — exactly the one-permutation-per-level
tree the recursion membership AIR (recursion.py) arithmetizes, so the in-circuit update (merkle_update) folds it
directly. Empty leaf = rleaf(0); a zero write deletes.

PRODUCTION GEOMETRY: depth 256 (the full digest — position security saturates the hash itself, so the scheme
never needs a depth bump). That forces the implementation to be sparse-SMART, not just sparse-correct:
  * populated keys kept sorted → subtree occupancy by BISECT (O(log N)), never an O(N) scan;
  * a subtree holding exactly ONE leaf folds straight up against the canonical empty roots (no recursion);
  * branching nodes are MEMOIZED, and set() invalidates exactly the changed key's ancestor chain —
    so root() is incremental (O(depth) work per write) and path() costs O(depth · log N).
The ROOT VALUE is defined by the plain tree (leaf/rnode folds) — these are pure optimizations; provers/verifiers
at any depth get byte-identical roots.

`pack_path`/`unpack_path` compress an authentication path to only its NON-empty siblings (everything else is the
canonical e[level]) — a depth-256 exit proof is ~log N real siblings instead of 256 (a few hundred bytes, not 16KB).
"""
import bisect
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


_E_CACHE = {}


def empty_roots(depth):
    """The canonical empty-subtree digests for `depth`, cached (256 permutations once, not per store/proof)."""
    r = _E_CACHE.get(depth)
    if r is None:
        r = _empty_roots(depth)
        _E_CACHE[depth] = r
    return r


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
    """A sparse alghash2 Merkle tree over {key: value} at fixed `depth`. Missing keys read 0; writing 0 deletes.
    Deterministic root + authentication paths (all CAPACITY-tuples). Incremental: writes invalidate only their
    ancestor chain, so successive root()/path() calls reuse every untouched subtree."""

    def __init__(self, depth, values=None):
        self.depth = depth
        self.e = empty_roots(depth)
        mask = (1 << depth) - 1
        vals = {}
        for k, v in (values or {}).items():
            kk = int(k) & mask
            vv = int(v) % F.P
            if vv:
                vals[kk] = vv
        self.values = vals
        self._keys = sorted(vals)
        self._memo = {}                            # (level, index) -> digest, level >= 1

    # -- occupancy ------------------------------------------------------------------------------------
    def _count(self, lo, hi):
        return bisect.bisect_left(self._keys, hi) - bisect.bisect_left(self._keys, lo)

    def _singleton_fold(self, key, level):
        """Digest of the height-`level` subtree whose ONLY populated leaf sits at absolute `key` — fold the leaf
        straight up against the canonical empty roots (bits 0..level-1 of key give the order at each step)."""
        node = _leaf(self.values[key])
        for i in range(level):
            if (key >> i) & 1:
                node = A2.rnode(self.e[i], node)
            else:
                node = A2.rnode(node, self.e[i])
        return node

    def _node(self, level, index):
        """Digest of the subtree of height `level` rooted at horizontal `index`: empty → e[level]; one leaf →
        singleton fold; else memoized recursion (invalidated per-write along the changed ancestor chain)."""
        if level == 0:
            v = self.values.get(index, 0)
            return _leaf(v) if v else self.e[0]
        m = self._memo.get((level, index))
        if m is not None:
            return m
        lo = index << level
        n = self._count(lo, lo + (1 << level))
        if n == 0:
            return self.e[level]
        if n == 1:
            k = self._keys[bisect.bisect_left(self._keys, lo)]
            d = self._singleton_fold(k, level)
        else:
            d = A2.rnode(self._node(level - 1, index * 2), self._node(level - 1, index * 2 + 1))
        self._memo[(level, index)] = d
        return d

    def root(self):
        return self._node(self.depth, 0)

    def path(self, key):
        """Authentication siblings for `key` (level 0 .. depth-1), bottom-up — each a CAPACITY-tuple."""
        key &= (1 << self.depth) - 1
        sibs, index = [], key
        for level in range(self.depth):
            sibs.append(self._node(level, index ^ 1))
            index >>= 1
        return sibs

    def get(self, key):
        return self.values.get(int(key) & ((1 << self.depth) - 1), 0)

    def set(self, key, value):
        key = int(key) & ((1 << self.depth) - 1)
        value = int(value) % F.P
        present = key in self.values
        if value:
            if not present:
                bisect.insort(self._keys, key)
            self.values[key] = value
        elif present:
            del self.values[key]
            del self._keys[bisect.bisect_left(self._keys, key)]
        else:
            return                                             # writing 0 to an empty slot: nothing changed
        idx = key
        for level in range(1, self.depth + 1):                 # invalidate exactly the changed ancestor chain
            idx >>= 1
            self._memo.pop((level, idx), None)


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


# -- compressed authentication paths (wire format for exit proofs) ------------------------------------
def pack_path(siblings, depth):
    """Compress a bottom-up sibling list: only levels whose sibling differs from the canonical empty root are
    carried ({"d": depth, "s": {level: [DIGEST hex lanes]}}); everything else is implicitly e[level]. A sparse
    tree's typical path is ~log N real siblings, so a depth-256 proof is a few hundred bytes, not 16KB."""
    e = empty_roots(depth)
    s = {}
    for i, sib in enumerate(siblings):
        t = tuple(int(x) % F.P for x in sib)
        if t != e[i]:
            s[str(i)] = [format(x, "016x") for x in t]
    return {"d": int(depth), "s": s}


def unpack_path(packed, depth):
    """Expand a packed path back to the full sibling list for `depth`. Returns None (never raises) on anything
    malformed — wrong depth, bad level, bad lane count, out-of-field lanes — so verifiers can reject cleanly."""
    try:
        if not isinstance(packed, dict) or int(packed.get("d")) != int(depth):
            return None
        e = empty_roots(depth)
        out = list(e[:depth])
        for k, lanes in (packed.get("s") or {}).items():
            i = int(k)
            if not (0 <= i < depth) or not isinstance(lanes, list) or len(lanes) != DIGEST:
                return None
            t = tuple(int(x, 16) for x in lanes)
            if any(not (0 <= v < F.P) for v in t):
                return None
            out[i] = t
        return out
    except Exception:
        return None
