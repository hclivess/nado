"""
Field-native shielded pool (doc/privacy.md) — the Phase-2 pool whose notes ARE what the zk-STARK proves.

Notes use the STARK-friendly hash (alghash) over the Goldilocks field, and the commitment tree is a fixed-depth
alghash Merkle tree, so a membership path folds to the root EXACTLY as joinsplit_circuit's membership region
does. A shielded key is a single field element `nsk`; owner = alghash.owner_of(nsk); a note is (value, owner,
rho). Spending is a delegated STARK proof: the wallet hands the exec node the witness, the exec node builds the
path from this tree and proves the whole join-split (execnode/stark/joinsplit_circuit), and L1 verifies that
one proof (via verify_transfer's Phase-2 seam). Works on any phone today; a blind/WASM prover is the private
endgame.
"""
from execnode.stark import field as F, alghash, membership as MB, joinsplit_circuit as JC

TREE_DEPTH = 12                                   # 2^12 = 4096 notes (alpha); proving cost scales with depth
EMPTY_LEAF = 0                                     # field element for an empty slot


def _empty_roots(depth):
    e = [EMPTY_LEAF]
    for _ in range(depth):
        e.append(alghash.merkle_node(e[-1], e[-1]))
    return e


_EMPTY = _empty_roots(TREE_DEPTH)
EMPTY_ROOT = _EMPTY[TREE_DEPTH]


def tree_root(leaves):
    if not leaves:
        return EMPTY_ROOT
    level = list(leaves)
    for d in range(TREE_DEPTH):
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else _EMPTY[d]
            nxt.append(alghash.merkle_node(left, right))
        level = nxt
    return level[0]


def tree_path(leaves, pos):
    """(siblings, dirs) for the leaf at `pos`: dirs[i] = bit i of pos (0 = leaf is the left child)."""
    sibs, dirs, idx = [], [], pos
    level = list(leaves)
    for d in range(TREE_DEPTH):
        sib = idx ^ 1
        sibs.append(level[sib] if sib < len(level) else _EMPTY[d])
        dirs.append(idx & 1)
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else _EMPTY[d]
            nxt.append(alghash.merkle_node(left, right))
        level = nxt
        idx //= 2
    return sibs, dirs


class FieldShieldedPool:
    """Append-only field-hash commitment tree + spent-nullifier set + bounded anchor window."""

    def __init__(self, commitments=None, nullifiers=None, anchors=None):
        self.commitments = [int(c) % F.P for c in (commitments or [])]
        self.nullifiers = set(int(n) % F.P for n in (nullifiers or []))
        self.anchors = list(anchors or [])
        self._remember(self.root())

    def root(self):
        return tree_root(self.commitments)

    def _remember(self, root):
        if root not in self.anchors:
            self.anchors.append(root)
            if len(self.anchors) > 128:
                del self.anchors[:-128]

    def knows_root(self, root):
        return int(root) % F.P in self.anchors

    def append(self, cm):
        self.commitments.append(int(cm) % F.P)
        self._remember(self.root())

    def position(self, cm):
        try:
            return self.commitments.index(int(cm) % F.P)
        except ValueError:
            return None

    def has_nullifier(self, nf):
        return int(nf) % F.P in self.nullifiers

    def to_dict(self):                                # big field ints -> strings (JSON-safe)
        return {"commitments": [str(c) for c in self.commitments],
                "nullifiers": [str(n) for n in sorted(self.nullifiers)],
                "anchors": [str(a) for a in self.anchors]}

    @classmethod
    def from_dict(cls, d):
        return cls([int(c) for c in d.get("commitments", [])],
                   [int(n) for n in d.get("nullifiers", [])],
                   [int(a) for a in d.get("anchors", [])])


# --- delegated proving: build the witness path from the pool + prove the full join-split ---
def prove_transfer(pool, nsk, value_in, rho_in, cm_in_pos, out_value, out_owner, out_rho, public_value, fee,
                   num_queries=32):
    """Given the SECRET spend witness + the input note's position, build the Merkle path from the pool and
    produce the full join-split STARK proof. Returns (bundle, public) ready for verify_transfer. The caller
    (exec node) sees the witness — this is the delegated-prover model (private endgame = a blind/WASM prover)."""
    sibs, dirs = tree_path(pool.commitments, cm_in_pos)
    proof, root, nf, cm_out = JC.prove_transfer(nsk, value_in, rho_in, sibs, dirs, out_value, out_owner, out_rho,
                                                public_value, fee, num_queries=num_queries)
    bundle = {"stark": {"joinsplit": {"proof": proof, "root": root, "nf": nf, "cm_out": cm_out,
                                      "public_value": public_value, "fee": fee}}}
    public = {"root": root, "nullifiers": [nf], "out_commitments": [cm_out],
              "public_value": public_value, "fee": fee}
    return bundle, public
