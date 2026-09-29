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

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_wide_pool_depth.py   (slow: real STARK proofs at depth 12 and 48)
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-wide-depth-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")   # ASSIGN: CWD-relative exec state
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")               # ASSIGN: CWD-relative DA dir
os.environ.setdefault("NADO_ALLOW_PYTHON_KERNELS", "1")
import sys, json, asyncio, random, traceback, copy
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.state import ExecState
from execnode.stark import znote as Z, joinsplit3 as J3, stark
from execnode import shielded_wide as SW, shielded

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


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


def t_the_transition_at_block_1_deepens_the_pool_and_refuses_the_old_tree():
    st = _state()
    assert _apply(st, 0, []) is True and st.wide_pool.depth == 12, "genesis (height 0) leaves the fresh depth-12 pool"
    empty12 = st.wide_pool.root()
    pre = st.state_root()
    assert _apply(st, G, []) is True                                               # block 1, empty
    assert st.wide_pool.depth == 48 and not st.wide_pool.commitments
    assert st.wide_pool.root() == SW.empty_root(48) and empty12 not in st.wide_pool.anchors
    assert st.state_root() == pre, "an EMPTY pool projects to nothing at either depth, so the exec root does not move"
    cm_a = _deposit(st, G + 1, NSK_A, 1000, 7)
    _deposit(st, G + 2, NSK_B, 50, 9)
    wp = st.wide_pool
    leaves = list(wp.commitments)
    assert wp.depth == 48 and wp.root() == SW.tree_root(leaves, 48), "deposits land in the depth-48 tree"
    assert wp.anchors == SW.WideShieldedPool.from_dict(json.loads(json.dumps(wp.to_dict()))).anchors
    # a proof built against a depth-12 tree over the same leaves is refused (its D, and a root no window holds)
    b12 = _prove(SW.WideShieldedPool(leaves, depth=12), NSK_A, cm_a, 1000, 7, 600, 11, 400, 12)
    assert b12["stark"]["joinsplit3"]["proof"]["D"] == 12
    n0 = len(wp.commitments)
    r = _last_result(st, G + 3, b12)
    assert r.startswith("skip") and "depth" in r, f"a depth-12 proof from block 1 must be refused: {r}"
    assert len(st.wide_pool.commitments) == n0 and not st.wide_pool.nullifiers
    # the same note, proven at depth 48, spends
    b48 = _prove(st.wide_pool, NSK_A, cm_a, 1000, 7, 600, 11, 400, 12)
    assert b48["stark"]["joinsplit3"]["proof"]["D"] == 48 and b48["stark"]["joinsplit3"]["proof"]["T"] == 4096
    _SHARED["pool48"] = SW.WideShieldedPool.from_dict(st.wide_pool.to_dict())   # before the spend moves the window
    _SHARED["b48"] = copy.deepcopy(b48)
    assert _apply(st, G + 4, [_transfer_tx(b48)]) is True
    js = b48["stark"]["joinsplit3"]
    assert st.wide_pool.has_nullifier(Z.from_hex(js["nf"])), "the note is spent at depth 48"
    assert len(st.wide_pool.commitments) == n0 + 2 and st.pool_value == 1050
    # save + load: the same depth, root, window and exec root
    st.save(); st2 = ExecState(path=st.path)
    assert (st2.wide_pool.depth, st2.wide_pool.root(), st2.wide_pool.anchors) == (48, st.wide_pool.root(), st.wide_pool.anchors)
    assert st2.state_root() == st.state_root()


_SHARED = {}          # the transition test's depth-48 proof and the pool it was built on (a proof costs minutes)


def t_the_verifier_pins_d_to_the_depth_in_force_never_the_proof():
    pool, b = _SHARED["pool48"], _SHARED["b48"]
    js = b["stark"]["joinsplit3"]
    pub = {"root": js["root"], "nullifiers": [js["nf"]], "out_commitments": [js["cm_out1"], js["cm_out2"]],
           "public_value": 0, "fee": 0}
    ok, why = shielded.verify_transfer(pub, b, pool.knows_root, wide_depth=48)
    assert ok, why
    ok, why = shielded.verify_transfer(pub, b, pool.knows_root, wide_depth=12)
    assert not ok and "depth" in why, why
    # no depth passed: the proof rules in force decide (rules_at(h) is what _apply_block sets)
    with stark.rules_at(0):
        assert not shielded.verify_transfer(pub, b, pool.knows_root)[0], "at height 0 a D=48 proof is refused"
    with stark.rules_at(G):
        ok, why = shielded.verify_transfer(pub, b, pool.knows_root)
        assert ok, why


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


def t_capacity_depth48_spends_at_5000_leaves():
    # (a FULL depth-12 tree cannot occur any more: the depth-12 pool exists only at height 0, where no wide deposit lands)
    st = _state(); st.cursor = G + 10
    st.wide_pool = SW.WideShieldedPool(LEAVES[:4096] + [tuple(rnd.randrange(1, Z.F.P) for _ in range(4)) for _ in range(903)],
                                       depth=48)
    cm = _deposit(st, G + 11, NSK_A, 1000, 7)
    assert len(st.wide_pool.commitments) == 5000 and st.wide_pool.position(cm) == 4999
    b = _prove(st.wide_pool, NSK_A, cm, 1000, 7, 600, 11, 400, 12)
    assert _apply(st, G + 12, [_transfer_tx(b)]) is True
    assert st.wide_pool.has_nullifier(Z.from_hex(b["stark"]["joinsplit3"]["nf"])), "the spend at 5,000 leaves applied"
    assert len(st.wide_pool.commitments) == 5002


def t_the_wallet_builds_at_the_depth_the_leaves_endpoint_reports():
    """The hop from the exec node to the wallet, read out the far side: /exec/field_leaves' real handler serves the
    depth, and the WALLET's own code (alghash2.js treeDepth + treePath, in node) builds from that response a path that
    folds to the pool's root — at 48 from genesis (cursor 0: the next block is 1), and at 12 for a response with no
    depth (an old exec node). A wide response at depth 12 no longer exists: the wide pool is served from cursor 0,
    where the next block is already 1."""
    import subprocess
    import execnode.execnode as EN
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    lv = [Z.to_hex(c) for c in LEAVES[:6]]
    cases = []
    for cursor, depth in ((0, 48), (G, 48), (G + 5, 48)):
        st = _state(); st.cursor = cursor
        st.wide_pool = SW.WideShieldedPool(LEAVES[:6], depth=SW.depth_at(cursor))
        saved = EN.state
        EN.state = st
        try:
            resp = json.loads(asyncio.new_event_loop().run_until_complete(EN.h_field_leaves(None)).body)
        finally:
            EN.state = saved
        assert resp["depth"] == depth and resp["leaves"] == lv, (cursor, resp.get("depth"))
        cases.append((resp, Z.to_hex(SW.tree_root(LEAVES[:6], depth))))
    cases.append(({"leaves": lv, "wide": True}, Z.to_hex(SW.tree_root(LEAVES[:6], 12))))   # an old exec node
    js = ("import * as A2 from '%s/static/alghash2.js';"
          "import { blake2b, bytesToHex } from '%s/static/vendor/nado-crypto.js';"
          "const canon = (d) => typeof d === 'bigint' ? d.toString() : typeof d === 'number' ? String(d) : typeof d === 'string'"
          " ? JSON.stringify(d) : '[' + d.map(canon).join(',') + ']';"
          "A2.initAlghash2((x, n = 32) => bytesToHex(blake2b(new TextEncoder().encode(canon(x)), { dkLen: n })));"
          "const cases = %s; const out = [];"
          "for (const [resp] of cases) { const d = A2.treeDepth(resp); const { sibs, dirs } = A2.treePath(resp.leaves, 4, d);"
          " out.push([d, A2.toHex(A2.foldPath(A2.fromHex(resp.leaves[4]), sibs, dirs))]); }"
          "console.log(JSON.stringify(out));" % (root_dir, root_dir, json.dumps(cases)))
    out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-600:]
    got = json.loads(out.stdout)
    want = [[resp.get("depth", 12), root] for resp, root in cases]
    assert got == want, f"the wallet's path did not fold to the pool's root at the reported depth: {got} != {want}"


check("the wallet builds its path at the depth /exec/field_leaves reports (48 from genesis, and 12 when absent)",
      t_the_wallet_builds_at_the_depth_the_leaves_endpoint_reports)
check("depth 12: roots and paths are byte-identical to the old tree (sizes 0..300 and up to the 4,096 cap)",
      t_depth12_roots_and_paths_are_byte_identical_to_the_old_tree)
check("depth 12: the live and rebuilt anchor windows are byte-identical to the old pool's",
      t_depth12_live_and_rebuilt_anchor_windows_are_byte_identical)
check("depth 48: the frontier root is the root every path folds to", t_depth48_frontier_root_is_the_root_every_path_folds_to)
check("a snapshot's depth is checked against its cursor", t_a_snapshots_depth_is_checked_against_its_cursor)
check("a DA stall at block 1 puts the depth-12 pool back", t_a_da_stall_at_block_1_puts_the_depth12_pool_back)
check("the transition at block 1 deepens the pool and refuses the depth-12 tree",
      t_the_transition_at_block_1_deepens_the_pool_and_refuses_the_old_tree)
check("the verifier pins D to the depth in force, never the proof's", t_the_verifier_pins_d_to_the_depth_in_force_never_the_proof)
check("capacity: depth 48 spends at 5,000 leaves", t_capacity_depth48_spends_at_5000_leaves)
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
