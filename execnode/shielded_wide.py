"""
WIDE field-native shielded pool (security review 2026-09-23, Z3; SHIELD_WIDE_HEIGHT) — shielded_field's pool
with every commitment, nullifier and tree node an alghash2 DIGEST (four field elements, ~128-bit collision
resistance) instead of one alghash element (~2^32). The join-split it verifies is joinsplit3.

A note is (value, owner, rho) with owner = znote.owner_of(nsk), a 4-lane digest; the commitment tree is a
fixed-depth rnode tree whose path folds to the root exactly as joinsplit3's MEMBERSHIP blocks do. Digests
travel as 64-hex strings (znote.to_hex) in transactions, bundles, snapshots and the wallet; in memory they
are CAPACITY-tuples. Live from block 1 of the next generation; the legacy pool (shielded_field) is frozen
from the same gate and stays only for the rerolled-away history.

THE DEPTH IS A PROPERTY OF THE POOL (zk audit 2026-09-26). Depth 12 is 4,096 notes, fillable for ~0.0004 NADO of
deposits; a spend always appends two leaves, so once the tree was full every note in it was locked for good (the spend
is refused as "full") while deposits kept being admitted and were lost. From ZK_HARDEN_HEIGHT the pool is depth 48
(2^48 notes). joinsplit3's trace length is next_pow2(rows(D) + RANDOM_ROWS), the same for every depth 20..48, so 48
costs a prover exactly what 20 does. depth_at(height) is the one place the rule is written; the exec state deepens its
pool when it applies the first block at or past the gate (ExecState.wide_enter), a snapshot carries the depth and
ExecState._restore checks it against the snapshot's cursor, and the verifier pins a proof's D to the depth in force.
Below the gate every root, path and anchor window is byte-identical to the depth-12 code this replaced
(tests/test_wide_pool_depth.py pins them against a verbatim copy of the old functions).
"""
from execnode.stark import field as F, znote as Z
from execnode.stark.alghash2 import CAPACITY

TREE_DEPTH = 12                                   # below ZK_HARDEN_HEIGHT (and an exec node that reports no depth)
DEPTH_HARDENED = 48                               # from ZK_HARDEN_HEIGHT: 2^48 notes
DEPTHS = (TREE_DEPTH, DEPTH_HARDENED)             # the only depths a pool, or a snapshot of one, may declare
EMPTY_LEAF = Z.EMPTY_LEAF
ANCHOR_WINDOW = 128


def depth_at(height):
    """The wide tree's depth in force for the block at `height` — a pure function of height, so a replay years later
    builds the tree that was in force. Every consumer (the pool switch, the snapshot check, the verifier's D pin, the
    depth /exec/field_leaves reports to wallets) reads it here."""
    from protocol import ZK_HARDEN_HEIGHT
    return DEPTH_HARDENED if int(height) >= ZK_HARDEN_HEIGHT else TREE_DEPTH


def _check_depth(depth):
    if isinstance(depth, bool) or not isinstance(depth, int) or depth not in DEPTHS:
        raise ValueError(f"a wide pool's depth is one of {DEPTHS}, not {depth!r}")
    return depth


def _empty_roots(depth):
    e = [EMPTY_LEAF]
    for _ in range(depth):
        e.append(Z.merkle_node(e[-1], e[-1]))
    return e


_EMPTY = _empty_roots(max(DEPTHS))                # _EMPTY[d]: the root of an empty depth-d subtree (a prefix of the old list)
EMPTY_ROOT = _EMPTY[TREE_DEPTH]                   # the depth-12 empty root, as it always was


def empty_root(depth=TREE_DEPTH):
    return _EMPTY[_check_depth(depth)]


class _Frontier:
    """INCREMENTAL root of the fixed-depth tree (the deposit-contract construction): left[d] is the completed left
    subtree at level d still waiting for its right sibling. append is O(1) hashes amortized and root O(depth), and the
    root equals the level-by-level tree over the same leaves because an absent right subtree is _EMPTY[d] in both.
    The previous pool recomputed the whole tree per append (O(n) per note: 2^48 notes is not a tree that can be
    rebuilt on each deposit). `full` holds the root of a COMPLETE tree (2^depth leaves), which the bit walk in root()
    cannot see — the depth-12 pool reaches that state (4,096 leaves is admitted, the 4,097th is not)."""
    __slots__ = ("depth", "n", "left", "full")

    def __init__(self, depth):
        self.depth, self.n, self.left, self.full = depth, 0, [None] * depth, None

    def append(self, leaf):
        if self.n >= (1 << self.depth):
            raise ValueError("the wide tree is full")
        node, size = Z._d(leaf), self.n + 1
        self.n = size
        for d in range(self.depth):
            if size & 1:
                self.left[d] = node
                return
            node = Z.merkle_node(self.left[d], node)
            size >>= 1
        self.full = node                                  # size == 2^depth: the tree is complete

    def root(self):
        if self.n == (1 << self.depth):
            return self.full
        node, size = _EMPTY[0], self.n
        for d in range(self.depth):
            node = Z.merkle_node(self.left[d], node) if size & 1 else Z.merkle_node(node, _EMPTY[d])
            size >>= 1
        return node


def tree_root(leaves, depth=TREE_DEPTH):
    """Root of the fixed-depth rnode tree over `leaves` (digests), padding short levels with the empty root."""
    f = _Frontier(_check_depth(depth))
    for c in leaves:
        f.append(c)
    return f.root()


def tree_path(leaves, pos, depth=TREE_DEPTH):
    """(siblings, dirs) for the leaf at `pos`: dirs[i] = bit i of pos (1 = the running node is the RIGHT child).
    O(len(leaves) + depth): once a level is a single node, each higher sibling is the empty subtree's root."""
    _check_depth(depth)
    sibs, dirs, idx = [], [], int(pos)
    level = [Z._d(c) for c in leaves]
    for d in range(depth):
        sib = idx ^ 1
        sibs.append(level[sib] if sib < len(level) else _EMPTY[d])
        dirs.append(idx & 1)
        level = [Z.merkle_node(level[i], level[i + 1] if i + 1 < len(level) else _EMPTY[d])
                 for i in range(0, len(level), 2)]
        idx //= 2
    return sibs, dirs


class WideShieldedPool:
    """Append-only wide commitment tree + spent-nullifier set + bounded anchor window, at the pool's `depth`."""

    def __init__(self, commitments=None, nullifiers=None, anchors=None, depth=TREE_DEPTH):
        self.depth = _check_depth(depth)
        self.commitments = [Z._d(c) for c in (commitments or [])]
        self._index = {c: i for i, c in enumerate(self.commitments)}
        self.nullifiers = set(Z._d(n) for n in (nullifiers or []))
        self._front = _Frontier(self.depth)
        for c in self.commitments:
            self._front.append(c)
        self._root = self._front.root()
        self.anchors = [Z._d(a) for a in (anchors or [])]
        self._remember(self._root)

    def root(self):
        return self._root

    def capacity(self):
        """How many notes the tree holds (the Z4 bound the state checks before every append)."""
        return 1 << self.depth

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
        self._front.append(cm)                        # raises past 2^depth; the state refuses before that (Z4)
        self._index.setdefault(cm, len(self.commitments))
        self.commitments.append(cm)
        self._root = self._front.root()
        self._remember(self._root)

    def path(self, pos):
        """The membership path of leaf `pos` in THIS pool's tree, at its depth."""
        return tree_path(self.commitments, pos, self.depth)

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
        # "depth" rides the snapshot so a loaded pool is the tree it was — and ExecState._restore refuses one whose depth
        # is not depth_at(cursor), so a donor cannot hand a joiner a tree the protocol does not put at that height.
        return {"commitments": [Z.to_hex(c) for c in self.commitments],
                "nullifiers": [Z.to_hex(n) for n in sorted(self.nullifiers)],
                "anchors": [Z.to_hex(a) for a in self.anchors],
                "depth": self.depth}

    # A SNAPSHOT'S ANCHORS ARE NOT TRUSTED (zk audit 2026-09-26, F2): the exec state root commits the tree and the
    # nullifier set but not the anchor window, so a node adopting a peer's snapshot (bootstrap, repair, anchor adopt)
    # took the donor's anchors on faith — a donor could add the root of a fake tree and the joiner then accepted a real
    # proof against it (forged note, pool_value driven negative, a forged exit). Honest anchors are a pure function of
    # the append-only commitments, so they are REBUILT here and the snapshot's list is ignored.
    # Every append remembers its root (append -> _remember), so the window is exactly the roots of the last
    # ANCHOR_WINDOW prefixes (the empty root while fewer notes exist).
    # REBUILT THROUGH THE FRONTIER, ONCE: the first n+1-ANCHOR_WINDOW leaves are appended, then each remaining leaf is
    # appended and its prefix root recorded — O(n) + ANCHOR_WINDOW·depth. The old per-prefix tree_root was O(128·n):
    # fine at 4,096 leaves, not at the scale a depth-48 tree exists for. The list is the per-prefix roots in order and
    # NOT deduplicated, as the old comprehension built it (byte-identical; tests/test_wide_pool_depth.py).
    @classmethod
    def from_dict(cls, d):
        depth = _check_depth(d.get("depth", TREE_DEPTH))    # a snapshot written before the field existed is depth 12
        return cls._rebuilt(d.get("commitments") or [], d.get("nullifiers", []), depth)

    @classmethod
    def _rebuilt(cls, commitments, nullifiers, depth):
        cms = [Z._d(c) for c in commitments]
        m = max(0, len(cms) + 1 - ANCHOR_WINDOW)
        pool = cls(cms[:m], nullifiers, None, depth)          # anchors = [root of the first m leaves]
        for c in cms[m:]:
            pool._front.append(c)
            pool.anchors.append(pool._front.root())          # the window: prefixes m..n, oldest first
        pool.commitments = cms
        pool._index = {c: i for i, c in enumerate(cms)}     # as __init__ builds it (the old from_dict went through it)
        pool._root = pool.anchors[-1]
        return pool

    def deepened(self, depth):
        """The same leaves and spent set in a tree of `depth` (at ZK_HARDEN_HEIGHT, 12 -> 48). The anchor window is
        rebuilt AT THE NEW DEPTH, exactly as from_dict would build it, so it holds no depth-12 root: a proof built
        against the old tree is refused from the switch (its D is refused too — joinsplit_transfer pins D to the depth
        in force). It is the depth-48 roots of the last ANCHOR_WINDOW prefixes and not the new root alone because the
        window must be what a RESTART rebuilds (from_dict): a node that restarted after the switch and one that did not
        would otherwise accept different anchors, and an anchor decides whether a transfer applies — a fork. Every root
        in it is a real prefix root of the committed leaves, so a proof against one is a proof of a real note."""
        return type(self)._rebuilt(self.commitments, self.nullifiers, _check_depth(depth))


def prove_transfer2(pool, nsk, value_in, rho_in, cm_in_pos, v1, o1, r1, v2, o2, r2, public_value, fee,
                    withdraw_addr=None):
    """Build the path from the pool and prove the wide 2-output join-split. Returns (bundle, public) with
    digests as 64-hex — the same bundle shape the wallet's on-device prover (static/stark/joinsplit3.js)
    submits. Tests and tooling only: a node never sees a spend key (Z7)."""
    from execnode.stark import joinsplit3 as J3
    sibs, dirs = pool.path(cm_in_pos)                  # at the POOL's depth (48 from ZK_HARDEN_HEIGHT)
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
