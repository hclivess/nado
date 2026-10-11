"""
The Stwo shielded pool (doc/stwo-migration.md §5.1) — the pool whose join-split is proved by the Stwo circuit
(native/stwo_js) instead of joinsplit3. NOT LIVE: nothing in the exec layer constructs it until STWO_POOL_HEIGHT, and
until its first note the exec root does not see it ("empty is absent", exec_root.records_projection).

THE HASH IS THE CIRCUIT'S, BYTE FOR BYTE. H = BLAKE2s-256 of ONE 64-byte block: sixteen little-endian u32 words, the
first a domain tag where the circuit has one —
    owner = H(21, nsk[0..8])                       nsk: a 256-bit spend key, eight u32 words
    cm    = H(22, lo(v), hi(v), owner[0..8], lo(rho), hi(rho))
    nf    = H(23, nsk[0..8], lo(rho), hi(rho))
    node  = H(left[0..8], right[0..8])             no tag: fixed arity, as the circuit's membership rows
and an empty leaf is the all-zero digest, an empty level node(empty, empty). Digests travel as 64-hex (the 32 bytes
in word order). tests/test_stwo_pool_hashes_match_the_circuit.py pins these against vectors the prototype's Rust
reference functions printed; a change here without the circuit is a pool nobody can spend from.

The tree has ONE depth, 48, from its first note — no 12 -> 48 switch like the wide pool's, because this pool never
existed at height 0.
"""
import hashlib
import struct

DEPTH = 48
ANCHOR_WINDOW = 128
DOM_OWNER, DOM_CM, DOM_NF = 21, 22, 23
_MASK64 = (1 << 64) - 1


def _words(d):
    """A 64-hex digest (or 32 bytes) -> its eight little-endian u32 words."""
    b = bytes.fromhex(d) if isinstance(d, str) else bytes(d)
    if len(b) != 32:
        raise ValueError("a digest is 32 bytes")
    return list(struct.unpack("<8I", b))


def _h(words16):
    if len(words16) != 16:
        raise ValueError("one BLAKE2s block is sixteen u32 words")
    return hashlib.blake2s(struct.pack("<16I", *[int(w) & 0xFFFFFFFF for w in words16]), digest_size=32).hexdigest()


def _u64(x):
    x = int(x)
    if not 0 <= x <= _MASK64:
        raise ValueError("a value or rho is a u64")
    return [x & 0xFFFFFFFF, x >> 32]


def owner_of(nsk):
    """nsk: 32 bytes / 64-hex (the spend key, eight u32 words)."""
    return _h([DOM_OWNER, *_words(nsk), *([0] * 7)])


def commit(value, owner, rho):
    return _h([DOM_CM, *_u64(value), *_words(owner), *_u64(rho), 0, 0, 0])


def nullifier(nsk, rho):
    return _h([DOM_NF, *_words(nsk), *_u64(rho), *([0] * 5)])


def node(left, right):
    return _h([*_words(left), *_words(right)])


EMPTY_LEAF = "00" * 32
_EMPTY = [EMPTY_LEAF]
for _ in range(DEPTH):
    _EMPTY.append(node(_EMPTY[-1], _EMPTY[-1]))
EMPTY_ROOT = _EMPTY[DEPTH]


class _Frontier:
    """Incremental append-only Merkle tree: O(DEPTH) per append, the root without the leaves."""

    def __init__(self):
        self.n = 0
        self.left = [None] * DEPTH          # left[i]: the pending left sibling at level i

    def append(self, leaf):
        i, cur, n = 0, leaf, self.n
        while n & 1:
            cur = node(self.left[i], cur)
            n >>= 1
            i += 1
        self.left[i] = cur
        self.n += 1

    def root(self):
        if self.n == 0:
            return EMPTY_ROOT
        cur, n = None, self.n
        for i in range(DEPTH):
            if n & 1:
                cur = node(self.left[i], cur if cur is not None else _EMPTY[i])
            elif cur is not None:
                cur = node(cur, _EMPTY[i])
            n >>= 1
        return cur


def tree_root(leaves):
    f = _Frontier()
    for x in leaves:
        f.append(x)
    return f.root()


def tree_path(leaves, pos):
    """(siblings, dirs) for leaf `pos` — dirs[i] = 1 when the node is the RIGHT child at level i, the circuit's rule."""
    level, i, sibs, dirs = list(leaves), int(pos), [], []
    for d in range(DEPTH):
        sib = i ^ 1
        sibs.append(level[sib] if sib < len(level) else _EMPTY[d])
        dirs.append(i & 1)
        level = [node(level[2 * k], level[2 * k + 1] if 2 * k + 1 < len(level) else _EMPTY[d])
                 for k in range((len(level) + 1) // 2)]
        i >>= 1
    return sibs, dirs


class StwoShieldedPool:
    """Commitments (append-only), the nullifier set and a window of recent roots a spend may anchor to."""

    def __init__(self, commitments=None, nullifiers=None):
        self.commitments, self.nullifiers = [], set()
        self._f = _Frontier()
        self.anchors = [EMPTY_ROOT]
        for cm in commitments or []:
            self.append(cm)
        for nf in nullifiers or []:
            self.nullifiers.add(str(nf))

    def root(self):
        return self._f.root()

    def append(self, cm):
        cm = str(cm).lower()
        _words(cm)
        if self._f.n >= (1 << DEPTH):
            raise ValueError("the pool is full")
        self.commitments.append(cm)
        self._f.append(cm)
        self.anchors.append(self.root())
        del self.anchors[:-ANCHOR_WINDOW]

    def knows_root(self, root):
        return str(root).lower() in self.anchors

    def has_nullifier(self, nf):
        return str(nf).lower() in self.nullifiers

    def spend(self, nf):
        nf = str(nf).lower()
        if nf in self.nullifiers:
            raise ValueError("nullifier already spent")
        self.nullifiers.add(nf)

    def nullifier_digest(self):
        """One digest of the spent set, order-independent (sorted) — what the exec root's record carries."""
        return hashlib.blake2b(("stwo_nfset|" + "|".join(sorted(self.nullifiers))).encode(), digest_size=32).hexdigest()

    def to_dict(self):
        return {"commitments": list(self.commitments), "nullifiers": sorted(self.nullifiers)}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("commitments") or [], d.get("nullifiers") or [])
