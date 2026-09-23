"""
WIDE note algebra for the shielded pool (security review 2026-09-23, Z3; SHIELD_WIDE_HEIGHT).

The pool's note commitment was ONE Goldilocks element — alghash's 64-bit digest, "~2^32 collision" by its own
docstring — so ~2^33 sponge evaluations find two openings of one leaf and unshield up to the whole escrow
with no victim. alghash2 (width 12, capacity 4 = a 256-bit digest, ~128-bit collision resistance) existed and
the pool did not use it. From the gate every commitment, owner id, nullifier and tree node is an alghash2
DIGEST (a CAPACITY-tuple of four field elements), and the join-split circuit (joinsplit3) proves the same
functions in-circuit, one permutation per hash:

    owner      = hashn([DOM_ZOWNER, nsk])                      3 elements incl. the length prefix
    cm         = hashn([DOM_ZCM, value, *owner, rho])          8 elements = exactly RATE: one permutation
    nf         = hashn([DOM_ZNF, nsk, rho])
    node(a, b) = rnode(a, b)                                   [a | b | IV] permuted, no prefix (fixed arity)

The domain tags live above alghash2's own (1..7) so a pool hash can never be read as a leaf, node, absorb,
challenge, index or grind frame, and above alghash's (1..4) so the legacy pool's frames are disjoint too.
Everything here is pure; the hex form (storage_tree.digest_hex, 64 chars) is how a digest travels in a
transaction, a bundle, a snapshot and a wallet.
"""
from execnode.stark import field as F, alghash2 as A2
from execnode.stark.storage_tree import digest_hex, digest_from_hex

DOM_ZOWNER, DOM_ZCM, DOM_ZNF = 21, 22, 23
CAP = A2.CAPACITY                                   # 4 lanes per digest
EMPTY_LEAF = (0, 0, 0, 0)                           # an empty tree slot


def _d(x):
    """Coerce a digest given as a tuple/list of lanes or a 64-hex string into a CAPACITY-tuple of ints."""
    if isinstance(x, str):
        return digest_from_hex(x)
    t = tuple(int(v) % F.P for v in x)
    if len(t) != CAP:
        raise ValueError("a wide digest has exactly %d lanes" % CAP)
    return t


def owner_of(nsk):
    """Spend-key binding: owner = hashn([DOM_ZOWNER, nsk])."""
    return A2.hashn([DOM_ZOWNER, int(nsk) % F.P])


def commit(value, owner, rho):
    """Note commitment cm = hashn([DOM_ZCM, value, owner (4 lanes), rho]) — one alghash2 permutation."""
    return A2.hashn([DOM_ZCM, int(value) % F.P, *_d(owner), int(rho) % F.P])


def nullifier(nsk, rho):
    """Nullifier nf = hashn([DOM_ZNF, nsk, rho]) — deterministic per note, unlinkable to cm without nsk."""
    return A2.hashn([DOM_ZNF, int(nsk) % F.P, int(rho) % F.P])


def merkle_node(left, right):
    """Tree-node digest: the recursion tree's rnode (one permutation over [left | right | IV])."""
    return A2.rnode(_d(left), _d(right))


def fold_path(leaf, siblings, dirs):
    """Fold a membership path to a root — exactly what joinsplit3's MEMBERSHIP blocks compute in-circuit
    (dirs[i] = 1 means the running node is the RIGHT child at level i)."""
    acc = _d(leaf)
    for sib, d in zip(siblings, dirs):
        acc = merkle_node(sib, acc) if int(d) & 1 else merkle_node(acc, sib)
    return acc


def to_hex(d):
    return digest_hex(_d(d))


def from_hex(h):
    return digest_from_hex(h)


def eq(a, b):
    return _d(a) == _d(b)
