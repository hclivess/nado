"""A PARTIAL compressed tree: the part of an execnode/csmt.py tree that a set of membership/absence proofs reveals, updated
in place to the root the full tree would have after the same writes (G4, the gen-29 settlement verifier; execnode/settle_b2.py).

Why it exists. The settlement verifier never holds the exec state. It holds the pre root, a proof for every key the span
read or wrote, and the writes it derived itself by replaying the span. A stateless client computes the post root from
exactly that: every key's path is known from its proof, and every other subtree is an opaque hash that no write touches.

THE ONE AMBIGUITY. csmt is canonical: a leaf sits at the shortest prefix it alone owns, so deleting a key can collapse its
sibling upward, but only when that sibling is a LEAF. A sibling hash does not say whether it is a leaf or an internal
node, so the prover supplies its preimage (`opens`: hash -> ("leaf", k, v) or ("node", l, r)), checked here by hashing.
An EMPTY subtree needs no opening: it is 32 zero bytes, and no leaf or node hash is.

Soundness. Every proof is checked by csmt.verify against the ONE pre root before it is merged, and merging checks that
proofs agree wherever their paths overlap, so the partial tree is the true tree with some subtrees left opaque. Writes
then follow csmt's canonical shape rules; a write that needs an opaque subtree's contents raises Missing (the verifier
reports the span as not provable from this witness, never guesses). The result is order-independent because the
canonical tree is a function of the key set (csmt.py's module docstring), and the test fuzzes it against csmt.Tree.
"""
from execnode import csmt
from execnode.csmt import EMPTY, bit, leaf_hash, node_hash


class Missing(Exception):
    """The witness does not reveal enough of the tree for this write."""


class _Opaque:
    __slots__ = ("h", "depth", "prefix")

    def __init__(self, h, depth, prefix):
        self.h, self.depth, self.prefix = h, depth, prefix     # position: so a prover can find what to open


class _Leaf:
    __slots__ = ("k", "v")

    def __init__(self, k, v):
        self.k, self.v = k, v


class _Node:
    __slots__ = ("l", "r", "_h")

    def __init__(self, l, r):
        self.l, self.r, self._h = l, r, None


_EMPTY = None          # the empty subtree


def _hash(n):
    if n is _EMPTY:
        return EMPTY
    if isinstance(n, _Opaque):
        return n.h
    if isinstance(n, _Leaf):
        return leaf_hash(n.k, n.v)
    if n._h is None:
        n._h = node_hash(_hash(n.l), _hash(n.r))
    return n._h


def _opaque(h, depth, prefix):
    return _EMPTY if h == EMPTY else _Opaque(h, depth, prefix)


class PartialTree:
    """Build with the pre root, add proofs (csmt.Tree.prove's format), then set/delete and read root()."""

    def __init__(self, root: bytes, opens=None, on_open=None):
        self._root0 = bytes(root)
        self.root_node = _opaque(self._root0, 0, 0)
        self.opens = dict(opens or {})          # hash -> ("leaf", k, v) | ("node", l, r): the prover's openings
        self.on_open = on_open                  # prover side: called with an _Opaque it needs opened, returns the preimage

    # ---- building from proofs
    def add_proof(self, key: bytes, value, proof):
        """Merge one proof (verified here against the pre root). `value` is the claimed value (None = absent)."""
        if not csmt.verify(self._root0, key, value, proof):
            raise ValueError("a proof does not verify against the pre root")
        sibs, term = proof
        sibs = [bytes(s) for s in sibs]
        d = len(sibs)
        if term[0] == "leaf":
            bottom = _Leaf(bytes(term[1]), bytes(term[2]))
        else:
            bottom = _EMPTY
        # the path's hashes bottom-up: hs[i] = the node at depth i on key's path
        hs = [None] * (d + 1)
        hs[d] = _hash(bottom)
        for i in range(d - 1, -1, -1):
            hs[i] = node_hash(sibs[i], hs[i + 1]) if bit(key, i) else node_hash(hs[i + 1], sibs[i])
        self.root_node = self._merge(self.root_node, key, 0, 0, sibs, bottom, hs)

    def _merge(self, n, key, i, prefix, sibs, bottom, hs):
        d = len(sibs)
        if i == d:
            if isinstance(n, _Opaque):
                if n.h != hs[d]:
                    raise ValueError("proofs disagree")
                return bottom
            if _hash(n) != hs[d]:
                raise ValueError("proofs disagree")
            return n
        b = bit(key, i)
        if isinstance(n, _Opaque):
            if n.h != hs[i]:
                raise ValueError("proofs disagree")
            sib = _opaque(sibs[i], i + 1, (prefix << 1) | (1 - b))
            on = _Opaque(hs[i + 1], i + 1, (prefix << 1) | b) if hs[i + 1] != EMPTY else _EMPTY
            n = _Node(on, sib) if b == 0 else _Node(sib, on)
        elif not isinstance(n, _Node):
            raise ValueError("proofs disagree")          # a leaf or EMPTY above where another proof still descends
        if _hash(n.r if b == 0 else n.l) != sibs[i]:
            raise ValueError("proofs disagree")
        child = n.l if b == 0 else n.r
        child = self._merge(child, key, i + 1, (prefix << 1) | b, sibs, bottom, hs)
        if b == 0:
            n.l = child
        else:
            n.r = child
        n._h = None
        return n

    # ---- writes
    def apply(self, changes):
        """Apply {key: value or None (delete)} in SORTED KEY ORDER. The root does not depend on the order (the shape is
        canonical), but WHICH siblings a delete needs opened does, so prover and verifier must walk the same order:
        this one, always."""
        for k in sorted(changes):
            if changes[k] is None:
                self.delete(k)
            else:
                self.set(k, changes[k])

    def set(self, key: bytes, value: bytes):
        self.root_node = self._set(self.root_node, bytes(key), bytes(value), 0)

    def _set(self, n, key, value, i):
        if n is _EMPTY:
            return _Leaf(key, value)
        if isinstance(n, _Leaf):
            if n.k == key:
                return _Leaf(key, value)
            return self._split(n, _Leaf(key, value), i)
        if isinstance(n, _Opaque):
            raise Missing(f"the walk to a written key ends in an unrevealed subtree at depth {i}")
        if bit(key, i):
            n.r = self._set(n.r, key, value, i + 1)
        else:
            n.l = self._set(n.l, key, value, i + 1)
        n._h = None
        return n

    @staticmethod
    def _split(a, b, i):
        """two leaves that share the prefix down to depth i: a chain of one-EMPTY-child nodes to their first
        differing bit (csmt's canonical shape)"""
        if i >= csmt.MAX_DEPTH:
            raise ValueError("two equal keys")
        ba, bb = bit(a.k, i), bit(b.k, i)
        if ba == bb:
            inner = PartialTree._split(a, b, i + 1)
            return _Node(inner, _EMPTY) if ba == 0 else _Node(_EMPTY, inner)
        return _Node(a, b) if ba == 0 else _Node(b, a)

    def delete(self, key: bytes):
        self.root_node = self._del(self.root_node, bytes(key), 0)

    def _del(self, n, key, i):
        if n is _EMPTY:
            return n
        if isinstance(n, _Leaf):
            return _EMPTY if n.k == key else n
        if isinstance(n, _Opaque):
            raise Missing(f"the walk to a deleted key ends in an unrevealed subtree at depth {i}")
        if bit(key, i):
            n.r = self._del(n.r, key, i + 1)
        else:
            n.l = self._del(n.l, key, i + 1)
        n._h = None
        return self._canon(n)

    def _canon(self, n):
        """csmt's shape after a delete below n: two EMPTY children are EMPTY, an EMPTY beside a LEAF collapses to the
        leaf; an EMPTY beside anything else stays. An opaque sibling is opened to tell a leaf from an internal node."""
        l, r = n.l, n.r
        if l is _EMPTY and r is _EMPTY:
            return _EMPTY
        if l is _EMPTY or r is _EMPTY:
            other = r if l is _EMPTY else l
            if isinstance(other, _Opaque):
                other = self._open(other)
                if l is _EMPTY:
                    n.r = other
                else:
                    n.l = other
            if isinstance(other, _Leaf):
                return other
        return n

    def _open(self, o):
        pre = self.opens.get(o.h)
        if pre is None and self.on_open is not None:
            pre = self.on_open(o)
            self.opens[o.h] = pre
        if pre is None:
            raise Missing("a delete needs a sibling opened (leaf or node) that the witness does not open")
        if pre[0] == "leaf" and len(pre) == 3 and leaf_hash(bytes(pre[1]), bytes(pre[2])) == o.h:
            k = bytes(pre[1])
            # the leaf must sit on the prefix it is found under, or the opening names some other subtree's leaf
            if any(bit(k, j) != ((o.prefix >> (o.depth - 1 - j)) & 1) for j in range(o.depth)):
                raise ValueError("an opened leaf is not under its position")
            return _Leaf(k, bytes(pre[2]))
        if pre[0] == "node" and len(pre) == 3 and node_hash(bytes(pre[1]), bytes(pre[2])) == o.h:
            return _Node(_opaque(bytes(pre[1]), o.depth + 1, o.prefix << 1),
                         _opaque(bytes(pre[2]), o.depth + 1, (o.prefix << 1) | 1))
        raise ValueError("an opening does not hash to its node")

    def root(self) -> bytes:
        return _hash(self.root_node)


def opener_for(tree: "csmt.Tree"):
    """The prover's on_open: the preimage of the subtree at an _Opaque's position in the FULL tree."""
    def on_open(o):
        import bisect
        lo = o.prefix << (256 - o.depth) if o.depth else 0
        hi = lo + (1 << (256 - o.depth))
        a = bisect.bisect_left(tree._sorted, lo.to_bytes(32, "big"))
        b = bisect.bisect_left(tree._sorted, hi.to_bytes(32, "big")) if hi < (1 << 256) else len(tree._sorted)
        keys = tree._sorted[a:b]
        if len(keys) == 1:
            return ("leaf", keys[0], tree.get(keys[0]))
        split = [k for k in keys if not bit(k, o.depth)]
        rest = [k for k in keys if bit(k, o.depth)]
        return ("node", tree._node(o.depth + 1, o.prefix << 1, split), tree._node(o.depth + 1, (o.prefix << 1) | 1, rest))
    return on_open
