"""
The wide shielded pool is depth 48 from block 1 and exactly the depth-12 pool at height 0 (zk audit 2026-09-26; gen 27's
ZK_HARDEN_HEIGHT, 1 from gen 28 and deleted).

Depth 12 held 4,096 notes, fillable for ~0.0004 NADO; a spend always appends two leaves, so a full tree locked every note
in it while deposits kept landing and were lost (reproduced). From block 1 the pool is a depth-48 tree (2^48 notes) at
depth 20's proving cost (joinsplit3 T = 4096 for every depth 20..48). Height 0 still reaches the depth-12 tree: a fresh
exec state (cursor -1) holds it and applies genesis at 0, and a cursor-0 snapshot is checked against it. It is always
EMPTY there — a field shield before block 1 goes to the legacy field pool (rules_shield_wide), so the below-gate cases
with notes in a depth-12 pool (deposits before the gate, a full depth-12 tree) no longer exist and are not pinned.
Properties pinned here:

  * THE DEPTH-12 TREE IS UNCHANGED: the incremental frontier's roots, the paths and the live and rebuilt anchor windows
    are byte-identical to a verbatim copy of the depth-12 functions they replaced, for every size 0..300 and at the
    4,096-leaf cap;
  * the depth-48 frontier root equals the root every depth-48 path folds to (two independent computations agree);
  * at depth 48 a real joinsplit3 proof verifies and the pool applies the spend, through the real _apply_block;
  * THE TRANSITION AT BLOCK 1: the fresh depth-12 pool becomes the depth-48 pool, a proof built against a depth-12 tree
    is refused from block 1 (its D and its root), and a DA stall at block 1 puts the depth-12 pool back;
  * the verifier's D pin reads the depth in force (the pool's, or the proof rules'), never the proof;
  * a snapshot carries the depth and it is CHECKED against the cursor: depth 12 at cursor >= 1, or 48 at cursor 0, is
    refused; an empty (absent) pool takes the cursor's depth;
  * CAPACITY: at depth 48 a spend at 5,000 leaves applies.

RETIRED IN G9 (generation 28's rules): every pin that reaches the wide pool THROUGH THE EXEC STATE (deposits, transfers,
L1 admission of a wide owner, the depth transition, capacity) — STWO_POOL_HEIGHT and WIDE_DEPOSIT_CLOSE_HEIGHT are
inlined as block 1, so from block 1 the exec state routes every deposit and spend to the Stwo pool. The module- and
circuit-level pins above that do not need that routing stay until the wide pool's code is deleted.

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_wide_pool_depth.py   (slow: real STARK proofs at depth 12 and 48)
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-wide-depth-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")   # ASSIGN: CWD-relative exec state
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")               # ASSIGN: CWD-relative DA dir
os.environ.setdefault("NADO_ALLOW_PYTHON_KERNELS", "1")
import sys, json, asyncio, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# THE WIDE POOL IS GENERATION 28's (closed there at 175000, never open on gen 29, retired at G9): this file runs under gen
# 28's gates explicitly — the wide close, the Stwo gate and the Goldilocks exec root its exits verify against (the gen-29
# rehearsal read the shipped values, all block 1, and every deposit landed in the Stwo pool against a BLAKE2s root).
import protocol as _Pg, _harness as _hg
# (WIDE_DEPOSIT_CLOSE_HEIGHT and STWO_POOL_HEIGHT were pinned here too until G9 inlined them as block 1: the exec state
#  no longer routes to the wide pool, and the pins that drove it there are retired below)
for _g in ("BLAKE_EXEC_HEIGHT",):
    setattr(_Pg, _g, _hg.gate_at(_g, 28))

from execnode.state import ExecState
from execnode.stark import znote as Z, joinsplit3 as J3
from execnode import shielded_wide as SW

import _harness
_report = _harness.Report()
check = _report.run


# ---- the depth-12 functions this replaced, VERBATIM (execnode/shielded_wide.py at ec83847c) --------------------------
OLD_DEPTH = 12


def _old_empty_roots(depth):
    e = [Z.EMPTY_LEAF]
    for _ in range(depth):
        e.append(Z.merkle_node(e[-1], e[-1]))
    return e


_OLD_EMPTY = _old_empty_roots(OLD_DEPTH)
OLD_EMPTY_ROOT = _OLD_EMPTY[OLD_DEPTH]


def old_tree_root(leaves):
    if not leaves:
        return OLD_EMPTY_ROOT
    level = [Z._d(c) for c in leaves]
    for d in range(OLD_DEPTH):
        level = [Z.merkle_node(level[i], level[i + 1] if i + 1 < len(level) else _OLD_EMPTY[d])
                 for i in range(0, len(level), 2)]
    return level[0]


def old_tree_path(leaves, pos):
    sibs, dirs, idx = [], [], int(pos)
    level = [Z._d(c) for c in leaves]
    for d in range(OLD_DEPTH):
        sib = idx ^ 1
        sibs.append(level[sib] if sib < len(level) else _OLD_EMPTY[d])
        dirs.append(idx & 1)
        level = [Z.merkle_node(level[i], level[i + 1] if i + 1 < len(level) else _OLD_EMPTY[d])
                 for i in range(0, len(level), 2)]
        idx //= 2
    return sibs, dirs


class OldPool:
    """The old WideShieldedPool's tree + anchor window (nullifiers left out: unchanged code)."""

    def __init__(self, commitments=None, anchors=None):
        self.commitments = [Z._d(c) for c in (commitments or [])]
        self.anchors = [Z._d(a) for a in (anchors or [])]
        self._remember(self.root())

    def root(self):
        return old_tree_root(self.commitments)

    def _remember(self, root):
        if root not in self.anchors:
            self.anchors.append(root)
            if len(self.anchors) > SW.ANCHOR_WINDOW:
                del self.anchors[:-SW.ANCHOR_WINDOW]

    def append(self, cm):
        self.commitments.append(Z._d(cm))
        self._remember(self.root())

    @classmethod
    def from_dict(cls, d):
        cms = [Z._d(c) for c in (d.get("commitments") or [])]
        n = len(cms)
        anchors = [old_tree_root(cms[:k]) for k in range(max(0, n + 1 - SW.ANCHOR_WINDOW), n + 1)]
        return cls(cms, anchors)


rnd = random.Random(20260926)
LEAVES = [tuple(rnd.randrange(1, Z.F.P) for _ in range(4)) for _ in range(4096)]


def t_depth12_roots_and_paths_are_byte_identical_to_the_old_tree():
    for n in list(range(0, 301)) + [511, 512, 513, 1000, 2047, 2048, 2049, 4095, 4096]:
        lv = LEAVES[:n]
        assert SW.tree_root(lv) == old_tree_root(lv), f"root differs at n={n}"
        assert SW.tree_root(lv, 12) == old_tree_root(lv)
        positions = range(n) if n <= 40 else sorted({0, 1, n // 3, n // 2, n - 2, n - 1, rnd.randrange(n)})
        if n > 300:
            positions = [0, n // 2, n - 1]
        for p in positions:
            assert SW.tree_path(lv, p) == old_tree_path(lv, p), f"path differs at n={n} pos={p}"
    assert SW.EMPTY_ROOT == OLD_EMPTY_ROOT and SW._EMPTY[:OLD_DEPTH + 1] == _OLD_EMPTY


def t_depth12_live_and_rebuilt_anchor_windows_are_byte_identical():
    new, old = SW.WideShieldedPool(), OldPool()
    assert new.root() == old.root() and new.anchors == old.anchors
    for i in range(300):
        new.append(LEAVES[i]); old.append(LEAVES[i])
        assert new.root() == old.root(), f"live root differs after {i + 1} appends"
        assert new.anchors == old.anchors, f"live anchor window differs after {i + 1} appends"
    for n in (0, 1, 2, 5, 127, 128, 129, 200, 300, 1000):
        d = {"commitments": [Z.to_hex(c) for c in LEAVES[:n]]}                 # an OLD snapshot: no "depth" key
        a, b = SW.WideShieldedPool.from_dict(d), OldPool.from_dict(d)
        assert a.depth == 12 and a.root() == b.root() and a.anchors == b.anchors, f"rebuilt window differs at n={n}"
    # the snapshot shape: the old keys are unchanged, "depth" is the one addition
    snap = new.to_dict()
    assert set(snap) == {"commitments", "nullifiers", "anchors", "depth"} and snap["depth"] == 12


def t_depth48_frontier_root_is_the_root_every_path_folds_to():
    for n in (0, 1, 2, 3, 7, 64, 65, 300, 1025):
        lv = LEAVES[:n]
        root = SW.tree_root(lv, 48)
        pool = SW.WideShieldedPool(lv, depth=48)
        assert pool.root() == root
        if n == 0:
            assert root == SW.empty_root(48)
            continue
        for p in sorted({0, n // 2, n - 1}):
            sibs, dirs = SW.tree_path(lv, p, 48)
            assert len(sibs) == 48 and Z.fold_path(lv[p], sibs, dirs) == root, f"n={n} pos={p}"
    assert SW.tree_root(LEAVES[:5], 48) != SW.tree_root(LEAVES[:5], 12), "the depth-48 root must differ from depth 12's"


# ---- the exec state, through the real _apply_block -------------------------------------------------------------------
from ops.address_ops import make_checksum as _mk


def _addr(ch):
    body = ch * 45
    return body + _mk(body)


ALICE, BOB = _addr("a"), _addr("b")
NSK_A, NSK_B = 0xCAFE, 0xB0B
G = 1                                                # the widening: depth 12 at height 0, 48 from block 1


def _state():
    return ExecState(os.path.join(os.environ["HOME"], f"s{os.urandom(4).hex()}.json"))


def _block(h, txs):
    return {"block_number": h, "block_hash": "ab" * 32, "block_timestamp": 0, "block_transactions": txs}


def _apply(st, h, txs):
    from execnode.execnode import _apply_block
    return asyncio.new_event_loop().run_until_complete(
        _apply_block(None, {"default": st}, st, _block(h, txs), verbose=False))


def _shield_tx(amount, owner_hex, rho):
    return {"recipient": "shield", "sender": ALICE, "amount": amount, "fee": 1, "txid": os.urandom(8).hex(),
            "data": {"field": True, "owner": owner_hex, "rho": str(rho)}}


def _transfer_blob(bundle):
    return {"op": "field_transfer", "bundle_json": json.dumps(bundle, default=str)}


def _transfer_tx(bundle):
    return {"recipient": "blob", "sender": ALICE, "txid": os.urandom(8).hex(), "data": _transfer_blob(bundle)}


def _deposit(st, h, nsk, amount, rho):
    owner = Z.owner_of(nsk)
    assert _apply(st, h, [_shield_tx(amount, Z.to_hex(owner), rho)]) is True
    cm = Z.commit(amount, owner, rho)
    assert st.wide_pool.position(cm) is not None, "the deposit must land in the wide pool"
    return cm


def _prove(pool, nsk, cm, v_in, rho_in, v1, r1, v2, r2):
    oa, ob = Z.owner_of(nsk), Z.owner_of(NSK_B)
    bundle, _pub = SW.prove_transfer2(pool, nsk, v_in, rho_in, pool.position(cm), v1, ob, r1, v2, oa, r2, 0, 0)
    return bundle


def _last_result(st, h, bundle):
    """Apply one transfer at h through apply_blob with the applying height set as _apply_block sets it."""
    st._applying = h
    try:
        return st.apply_blob(_transfer_blob(bundle), ALICE, os.urandom(4).hex())
    finally:
        st._applying = None


# t_the_transition_at_block_1_deepens_the_pool_and_refuses_the_old_tree: retired in G9: generation 28's rules (the wide pool reached through the exec state; STWO_POOL_HEIGHT is block 1)


_SHARED = {}          # the transition test's depth-48 proof and the pool it was built on (a proof costs minutes)


# t_the_verifier_pins_d_to_the_depth_in_force_never_the_proof: retired in G9: generation 28's rules (the wide pool reached through the exec state; STWO_POOL_HEIGHT is block 1)


def t_a_da_stall_at_block_1_puts_the_depth12_pool_back():
    import execnode.execnode as EN
    st = _state()
    assert _apply(st, 0, []) is True and st.wide_pool.depth == 12
    before = (st.cursor, st.wide_pool, st.wide_pool.root(), st.state_root())
    real = EN.da_fetch

    async def _unavailable(session, commitment):
        return None
    EN.da_fetch = _unavailable
    try:
        stalled = _apply(st, G, [{"recipient": "blob", "sender": ALICE, "txid": "t1",
                                  "data": {"op": "field_transfer", "proof_da": "ab" * 32}}])
    finally:
        EN.da_fetch = real
    assert stalled is False, "the block must stall on the unavailable proof"
    assert (st.cursor, st.wide_pool, st.wide_pool.root(), st.state_root()) == before, "nothing of block 1 applied"
    assert _apply(st, G, []) is True and st.wide_pool.depth == 48


def _snap_with(cursor, depth, leaves=3):
    st = _state()
    d = json.loads(json.dumps(st._snapshot(), default=str))
    d["cursor"] = cursor
    if leaves:
        d["wide_pool"] = {"commitments": [Z.to_hex(c) for c in LEAVES[:leaves]], "nullifiers": [], "anchors": [],
                          "depth": depth}
    p = os.path.join(os.environ["HOME"], f"snap{os.urandom(4).hex()}.json")
    json.dump(d, open(p, "w"))
    return p


def _refused(path):
    try:
        ExecState(path)
    except ValueError as e:
        return "wide pool" in str(e)
    return False


def t_a_snapshots_depth_is_checked_against_its_cursor():
    assert ExecState(_snap_with(0, 12)).wide_pool.depth == 12, "depth 12 at cursor 0 loads"
    assert ExecState(_snap_with(G, 48)).wide_pool.depth == 48, "depth 48 at block 1 loads"
    assert _refused(_snap_with(G, 12)), "depth 12 at cursor 1 is refused"
    assert _refused(_snap_with(G + 500, 12)), "depth 12 far past block 1 is refused"
    assert _refused(_snap_with(0, 48)), "depth 48 at cursor 0 is refused"
    assert _refused(_snap_with(0, 20)), "a depth that is not 12 or 48 is refused"
    # an old snapshot has no "depth" key: depth 12, fine at cursor 0, refused from cursor 1
    p = _snap_with(0, 12); d = json.load(open(p)); del d["wide_pool"]["depth"]; json.dump(d, open(p, "w"))
    assert ExecState(p).wide_pool.depth == 12
    p = _snap_with(G + 1, 12); d = json.load(open(p)); del d["wide_pool"]["depth"]; json.dump(d, open(p, "w"))
    assert _refused(p), "a depth-less (old-code) snapshot past block 1 is refused"
    # empty is absent: the pool takes the cursor's depth
    assert ExecState(_snap_with(G + 1, None, leaves=0)).wide_pool.depth == 48
    assert ExecState(_snap_with(0, None, leaves=0)).wide_pool.depth == 12
    # a fresh state (cursor -1) is depth 12 until it applies block 1
    assert _state().wide_pool.depth == 12


# t_capacity_depth48_spends_at_5000_leaves: retired in G9: generation 28's rules (the wide pool reached through the exec state; STWO_POOL_HEIGHT is block 1)


# t_the_wallet_builds_at_the_depth_the_leaves_endpoint_reports: retired in G9: generation 28's rules (the wide pool reached through the exec state; STWO_POOL_HEIGHT is block 1)


check("depth 12: roots and paths are byte-identical to the old tree (sizes 0..300 and up to the 4,096 cap)",
      t_depth12_roots_and_paths_are_byte_identical_to_the_old_tree)
check("depth 12: the live and rebuilt anchor windows are byte-identical to the old pool's",
      t_depth12_live_and_rebuilt_anchor_windows_are_byte_identical)
check("depth 48: the frontier root is the root every path folds to", t_depth48_frontier_root_is_the_root_every_path_folds_to)
check("a snapshot's depth is checked against its cursor", t_a_snapshots_depth_is_checked_against_its_cursor)
check("a DA stall at block 1 puts the depth-12 pool back", t_a_da_stall_at_block_1_puts_the_depth12_pool_back)
print("ALL PASS" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
