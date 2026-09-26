"""
WIDE field-native shielded pool (security review 2026-09-23, Z3; SHIELD_WIDE_HEIGHT) — shielded_field's pool
with every commitment, nullifier and tree node an alghash2 DIGEST (four field elements, ~128-bit collision
resistance) instead of one alghash element (~2^32). The join-split it verifies is joinsplit3.

A note is (value, owner, rho) with owner = znote.owner_of(nsk), a 4-lane digest; the commitment tree is a
fixed-depth rnode tree whose path folds to the root exactly as joinsplit3's MEMBERSHIP blocks do. Digests
travel as 64-hex strings (znote.to_hex) in transactions, bundles, snapshots and the wallet; in memory they
are CAPACITY-tuples. Live from block 1 of the next generation; the legacy pool (shielded_field) is frozen
from the same gate and stays only for the rerolled-away history.
"""
from execnode.stark import field as F, znote as Z
from execnode.stark.alghash2 import CAPACITY

TREE_DEPTH = 12                                   # 2^12 notes; joinsplit3 at depth 12 is T = 1024
EMPTY_LEAF = Z.EMPTY_LEAF
ANCHOR_WINDOW = 128


def _empty_roots(depth):
    e = [EMPTY_LEAF]
    for _ in range(depth):
        e.append(Z.merkle_node(e[-1], e[-1]))
    return e


_EMPTY = _empty_roots(TREE_DEPTH)
EMPTY_ROOT = _EMPTY[TREE_DEPTH]


def tree_root(leaves):
    """Root of the fixed-depth rnode tree over `leaves` (digests), padding short levels with the empty root."""
    if not leaves:
        return EMPTY_ROOT
    level = [Z._d(c) for c in leaves]
    for d in range(TREE_DEPTH):
        level = [Z.merkle_node(level[i], level[i + 1] if i + 1 < len(level) else _EMPTY[d])
                 for i in range(0, len(level), 2)]
    return level[0]


def tree_path(leaves, pos):
    """(siblings, dirs) for the leaf at `pos`: dirs[i] = bit i of pos (1 = the running node is the RIGHT child)."""
    sibs, dirs, idx = [], [], int(pos)
    level = [Z._d(c) for c in leaves]
    for d in range(TREE_DEPTH):
        sib = idx ^ 1
        sibs.append(level[sib] if sib < len(level) else _EMPTY[d])
        dirs.append(idx & 1)
        level = [Z.merkle_node(level[i], level[i + 1] if i + 1 < len(level) else _EMPTY[d])
                 for i in range(0, len(level), 2)]
        idx //= 2
    return sibs, dirs


class WideShieldedPool:
    """Append-only wide commitment tree + spent-nullifier set + bounded anchor window."""

    def __init__(self, commitments=None, nullifiers=None, anchors=None):
        self.commitments = [Z._d(c) for c in (commitments or [])]
        self._index = {c: i for i, c in enumerate(self.commitments)}
        self.nullifiers = set(Z._d(n) for n in (nullifiers or []))
        self.anchors = [Z._d(a) for a in (anchors or [])]
        self._remember(self.root())

    def root(self):
        return tree_root(self.commitments)

    def _remember(self, root):
        if root not in self.anchors:
            self.anchors.append(root)
            if len(self.anchors) > ANCHOR_WINDOW:
                del self.anchors[:-ANCHOR_WINDOW]

    def knows_root(self, root):
        try:
            return Z._d(root) in self.anchors
        except Exception:
            return False

    def append(self, cm):
        cm = Z._d(cm)
        self._index.setdefault(cm, len(self.commitments))
        self.commitments.append(cm)
        self._remember(self.root())

    def position(self, cm):
        """Leaf index of `cm` (the path witness needs it), or None if absent. O(1)."""
        try:
            return self._index.get(Z._d(cm))
        except Exception:
            return None

    def has_nullifier(self, nf):
        try:
            return Z._d(nf) in self.nullifiers
        except Exception:
            return False

    def spend(self, nf):
        self.nullifiers.add(Z._d(nf))

    def nullifier_digest(self):
        """One blake2b over the sorted spent set — what the settled root commits (O(1) in the set)."""
        from hashing import blake2b_hash
        return blake2b_hash(["wide_nfset", *sorted(Z.to_hex(n) for n in self.nullifiers)])

    def to_dict(self):
        return {"commitments": [Z.to_hex(c) for c in self.commitments],
                "nullifiers": [Z.to_hex(n) for n in sorted(self.nullifiers)],
                "anchors": [Z.to_hex(a) for a in self.anchors]}

    # A SNAPSHOT'S ANCHORS ARE NOT TRUSTED (zk audit 2026-09-26, F2): the exec state root commits the tree and the
    # nullifier set but not the anchor window, so a node adopting a peer's snapshot (bootstrap, repair, anchor adopt)
    # took the donor's anchors on faith — a donor could add the root of a fake tree and the joiner then accepted a real
    # proof against it (forged note, pool_value driven negative, a forged exit). Honest anchors are a pure function of
    # the append-only commitments, so they are REBUILT here and the snapshot's list is ignored.
    # Every append remembers its root (append -> _remember), so the window is exactly the roots of the last
    # ANCHOR_WINDOW prefixes (the empty root while fewer notes exist). At the 4096-leaf cap that is 128 tree roots, once
    # per load.
    @classmethod
    def from_dict(cls, d):
        cms = [Z._d(c) for c in (d.get("commitments") or [])]
        n = len(cms)
        anchors = [tree_root(cms[:k]) for k in range(max(0, n + 1 - ANCHOR_WINDOW), n + 1)]
        return cls(cms, d.get("nullifiers", []), anchors)


def prove_transfer2(pool, nsk, value_in, rho_in, cm_in_pos, v1, o1, r1, v2, o2, r2, public_value, fee,
                    withdraw_addr=None):
    """Build the path from the pool and prove the wide 2-output join-split. Returns (bundle, public) with
    digests as 64-hex — the same bundle shape the wallet's on-device prover (static/stark/joinsplit3.js)
    submits. Tests and tooling only: a node never sees a spend key (Z7)."""
    from execnode.stark import joinsplit3 as J3
    sibs, dirs = tree_path(pool.commitments, cm_in_pos)
    proof, root, nf, cm1, cm2 = J3.prove_transfer(nsk, value_in, rho_in, sibs, dirs, v1, o1, r1, v2, o2, r2,
                                                  public_value, fee, aux=withdraw_addr)
    bundle = {"stark": {"joinsplit3": {"proof": proof, "root": Z.to_hex(root), "nf": Z.to_hex(nf),
                                       "cm_out1": Z.to_hex(cm1), "cm_out2": Z.to_hex(cm2),
                                       "public_value": public_value, "fee": fee}}}
    if withdraw_addr:
        bundle["withdraw_addr"] = withdraw_addr
    public = {"root": Z.to_hex(root), "nullifiers": [Z.to_hex(nf)], "out_commitments": [Z.to_hex(cm1), Z.to_hex(cm2)],
              "public_value": public_value, "fee": fee}
    return bundle, public
