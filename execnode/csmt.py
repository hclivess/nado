"""THE COMPRESSED SPARSE MERKLE TREE of the BLAKE2s exec root (Goldilocks retirement G2, doc/stwo-migration.md 9.5).

Operator decision 2026-10-19 after the G1 measurement (doc/stwo/g1-tree-shape.md): the exec root moves from a
depth-256 sparse tree (512 compressions per path update) to a compressed one (~40 at a million leaves). This module is
the node-side definition — the Stwo settlement circuit (G4) proves exactly these functions — and it is FROZEN at the
generation-29 reroll with the root. Nothing here is consensus until a gate uses it (BLAKE_EXEC_HEIGHT, G2).

THE SHAPE (canonical: a function of the key/value set alone, never of insertion order). Keys are 32 bytes, read as 256
bits most-significant first. The node at a bit prefix p is
    EMPTY                         if no key starts with p
    LEAF(k, v)                    if exactly one key k starts with p — the leaf sits at the SHORTEST prefix it alone owns
    INTERNAL(node(p0), node(p1))  otherwise.
An internal node can have one EMPTY child (two keys sharing a long prefix pass through a chain of them); it can never
have an EMPTY child beside a LEAF child — that pair collapses to the leaf one level up.

THE HASHES: one BLAKE2s compression each (a 64-byte input is exactly one block), domain-separated by the BLAKE2s
personalization so a leaf can never be read as an internal node or the other way round:
    EMPTY            = 32 zero bytes (no hash: an empty subtree costs nothing in-circuit)
    LEAF(k, v)       = BLAKE2s-256(k || BLAKE2s-256(v, person=PERSON_VALUE), person=PERSON_LEAF)
    INTERNAL(l, r)   = BLAKE2s-256(l || r, person=PERSON_NODE)
The leaf commits its WHOLE key, so a leaf proven at a short prefix still says which key it is.

DEPTH IS NOT BOUNDED BY THE DATA, ONLY BY GRINDING (open point for G4). Random keys sit about log2(n) deep (measured:
100,000 leaves, median depth 18, max 28). But contract code influences storage keys, so an attacker can grind a key
sharing a long prefix with a victim's: each shared bit doubles the work, and every path through that prefix grows.
The settlement circuit proves paths up to a FIXED maximum depth; it must sit beyond feasible grinding (~2^80 work), not
near the typical depth, or a ground key makes a span unprovable. A deep path then costs its own span more hashes,
which is the attacker's own bill. MAX_DEPTH here stays 256 (the key length): the node accepts any canonical tree.

A PROOF for key k is (siblings, terminal): the sibling hashes from the root down to the depth where the walk ends, and
how it ends — at k's own leaf (membership), at an EMPTY node, or at another key's leaf that shares the prefix (both
non-membership). verify() recomputes the root AND refuses every non-canonical shape (see its docstring): a root match
alone would accept nothing false — the shape is canonical, so a non-canonical path cannot reach the true root — but the
explicit checks keep the rule independent of that argument, and the settlement circuit mirrors them.
"""
import hashlib

KEY_BYTES = 32
MAX_DEPTH = 256
EMPTY = bytes(32)
PERSON_LEAF = b"NADOcsL1"       # 8 bytes: BLAKE2s personalization is at most 8
PERSON_NODE = b"NADOcsN1"
PERSON_VALUE = b"NADOcsV1"


def _h(data, person):
    return hashlib.blake2s(data, digest_size=32, person=person).digest()


def value_hash(value: bytes) -> bytes:
    return _h(value, PERSON_VALUE)


def leaf_hash(key: bytes, value: bytes) -> bytes:
    return _h(key + value_hash(value), PERSON_LEAF)


def node_hash(left: bytes, right: bytes) -> bytes:
    return _h(left + right, PERSON_NODE)


def bit(key: bytes, depth: int) -> int:
    """bit `depth` of the key, most significant first"""
    return (key[depth >> 3] >> (7 - (depth & 7))) & 1


def _check_key(key):
    if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_BYTES:
        raise ValueError("a key is exactly 32 bytes")
    return bytes(key)


class Tree:
    """The tree over a {key: value} map. Hashes are cached per subtree and recomputed only along the paths an update
    touches, so a span of K updates costs O(K x depth) hashes, the same count the circuit proves."""

    def __init__(self, items=None):
        self._kv = {}
        self._cache = {}                  # (depth, prefix-int) -> hash, for subtrees with >= 2 keys
        for k, v in (items or {}).items():
            self._kv[_check_key(k)] = bytes(v)
        self._sorted = sorted(self._kv)

    # ---- reads
    def get(self, key):
        return self._kv.get(_check_key(key))

    def __len__(self):
        return len(self._kv)

    def root(self) -> bytes:
        return self._node(0, 0, self._sorted)

    def _node(self, depth, prefix, keys):
        """hash of the node at (depth, prefix) holding exactly `keys` (sorted, all sharing the prefix)"""
        if not keys:
            return EMPTY
        if len(keys) == 1:
            return leaf_hash(keys[0], self._kv[keys[0]])
        ck = (depth, prefix)
        hit = self._cache.get(ck)
        if hit is not None:
            return hit
        if depth >= MAX_DEPTH:
            raise ValueError("two equal keys")             # unreachable: keys are distinct 256-bit strings
        split = _first_with_bit(keys, depth)
        h = node_hash(self._node(depth + 1, prefix << 1, keys[:split]),
                      self._node(depth + 1, (prefix << 1) | 1, keys[split:]))
        self._cache[ck] = h
        return h

    # ---- writes
    def set(self, key, value):
        key = _check_key(key)
        if key not in self._kv:
            _insort(self._sorted, key)
        self._kv[key] = bytes(value)
        self._invalidate(key)

    def delete(self, key):
        key = _check_key(key)
        if key in self._kv:
            del self._kv[key]
            self._sorted.remove(key)
            self._invalidate(key)

    def apply(self, projection):
        """make the tree hold exactly `projection` ({key: value}): delete what vanished, write what changed — the
        exec node keeps one Tree per half and diff-applies each block's projection, O(changed x depth) hashing"""
        for k in [k for k in self._kv if k not in projection]:
            self.delete(k)
        for k, v in projection.items():
            if self._kv.get(k) != v:
                self.set(k, v)

    def _invalidate(self, key):
        """drop the cached hash of every subtree on the key's path (the only ones whose content changed)"""
        prefix = 0
        for d in range(MAX_DEPTH + 1):
            self._cache.pop((d, prefix), None)
            if d < MAX_DEPTH:
                prefix = (prefix << 1) | bit(key, d)

    # ---- proofs
    def prove(self, key):
        """(siblings, terminal) for `key`: siblings from the root down; terminal is ("leaf", k, value) when the walk
        ends at a leaf (k == key: membership; otherwise the leaf that proves key absent) or ("empty",)"""
        key = _check_key(key)
        keys, prefix, sibs = self._sorted, 0, []
        for d in range(MAX_DEPTH + 1):
            if not keys:
                return sibs, ("empty",)
            if len(keys) == 1:
                return sibs, ("leaf", keys[0], self._kv[keys[0]])
            split = _first_with_bit(keys, d)
            b = bit(key, d)
            if b:
                sibs.append(self._node(d + 1, prefix << 1, keys[:split]))
                keys, prefix = keys[split:], (prefix << 1) | 1
            else:
                sibs.append(self._node(d + 1, (prefix << 1) | 1, keys[split:]))
                keys, prefix = keys[:split], prefix << 1
        raise AssertionError("unreachable")


def verify(root: bytes, key: bytes, value, proof) -> bool:
    """True iff `proof` shows key -> value in the tree with this root (value None: the key is ABSENT).

    Refused, before any hashing: a malformed proof; more than MAX_DEPTH siblings; a terminal that does not decide the
    claim (a leaf of another key claimed as membership, k's own leaf claimed as absence, an "other" leaf that does not
    share the walked prefix with k). Refused as NON-CANONICAL: a terminal leaf whose deepest sibling is EMPTY (it should
    sit one level up), and an EMPTY terminal whose sibling is EMPTY (two empty children are one empty node). An EMPTY
    child is canonical only beside a subtree of two or more keys; beside a single LEAF the pair would have collapsed.
    That last case cannot be told from the sibling hash alone (a leaf hash and an internal hash are both 32 opaque
    bytes), so it is enforced by the root: the canonical tree has no such pair, and the personalizations keep a leaf
    hash from ever equalling an internal one."""
    try:
        key = _check_key(key)
        sibs, term = proof
        sibs = [bytes(s) for s in sibs]
        if len(sibs) > MAX_DEPTH or any(len(s) != 32 for s in sibs) or not isinstance(root, (bytes, bytearray)):
            return False
        d = len(sibs)
        if term[0] == "leaf":
            k2, v2 = _check_key(term[1]), bytes(term[2])
            if value is None:
                if k2 == key or any(bit(k2, i) != bit(key, i) for i in range(d)):
                    return False                         # absence needs ANOTHER key's leaf on k's own path
            elif k2 != key or v2 != bytes(value):
                return False
            if d and sibs[-1] == EMPTY:
                return False                             # a leaf beside EMPTY collapses one level up: not canonical
            h = leaf_hash(k2, v2)
        elif term[0] == "empty" and len(term) == 1:
            if value is not None:
                return False
            if d == 0:
                h = EMPTY                                # the empty tree
            else:
                if sibs[-1] == EMPTY:
                    return False                         # two EMPTY children would be one EMPTY node
                h = EMPTY
        else:
            return False
        for i in range(d - 1, -1, -1):
            h = node_hash(sibs[i], h) if bit(key, i) else node_hash(h, sibs[i])
        return h == bytes(root)
    except (ValueError, TypeError, IndexError):
        return False


def root_of(items) -> bytes:
    """the root of a {key: value} map — the reference the carry and the tests use"""
    return Tree(items).root()


def _first_with_bit(keys, depth):
    """index of the first key (sorted) whose bit `depth` is 1 — sorted order groups the 0s before the 1s"""
    lo, hi = 0, len(keys)
    while lo < hi:
        mid = (lo + hi) // 2
        if bit(keys[mid], depth):
            hi = mid
        else:
            lo = mid + 1
    return lo


def _insort(lst, x):
    import bisect
    bisect.insort(lst, x)
