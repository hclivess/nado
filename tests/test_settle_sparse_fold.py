"""
RECURSIVE FOLDING WIRED INTO THE LIVE (SPARSE-ROOT) SETTLEMENT PATH — the money path L1 actually verifies
(execnode.stark.settlement_sparse.prove/verify_settlement_sparse, called by ops/transaction_ops' settle branch).

A multi-segment sparse settlement (each segment a bound epoch: the W=106 two-phase execution AIR, ROW-COMMITTED,
RECURSION backend, plus the sparse state-transition binding) is folded so that verify_settlement_sparse checks
ONE recursion bundle (fold + row-mode composition) in place of the K per-segment exec stark.verify calls, while
the sparse transition binding + calls-commitment + pre-state pin + kv chain still run per segment. The settled
root (kv_pre/kv_post) is BYTE-IDENTICAL to the non-recursive proof of the same span — folding is a
verification-strategy change, never a settled-root change.

By DEFAULT this proves the SEGMENTED + SPARSE-BOUND row-committed path and verifies it the classic K-segment way
(~seconds/segment, native NTT) — the sound base the fold rides, and it exercises ALL the new code except the
RV.prove/RV.verify call (whose W=106 bundle is ~15 GB / minutes and is the SAME wiring already proven by
tests/test_settlement_o1.py + tests/test_recursive_row.py). NADO_HEAVY=1 additionally builds + verifies the real
fold and runs the tamper/weak-policy rejections against it.

Run: python3 tests/test_settle_sparse_fold.py           (fast: segmentation + sparse binding + K-path)
     NADO_HEAVY=1 python3 tests/test_settle_sparse_fold.py   (+ the real K->1 recursion bundle end-to-end)
"""
import os, sys, copy, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_sparsefold_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()

from execnode import zkvmasm
from execnode.stark import settlement_sparse as SS, storage_tree as ST
import protocol
protocol.SETTLE_PROOF_RECURSIVE = True     # this test exercises the fold ACCEPTANCE path (flipped on at a reroll)

HEAVY = os.environ.get("NADO_HEAVY") == "1"

fails = 0
def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

D8 = 8                                       # toy sparse depth (protocol is 256; verify pins depth per segment)
NQ = 2                                        # reduced inner/outer query strength (protocol NUM_QUERIES stays high)
CID = "c" * 32
ALICE = "ndoAAAA" + "A" * 41
COUNTER = {"bump": zkvmasm.assemble("""
    movi r1 0
    sload r2 r1
    movi r3 1
    add r2 r3
    sstore r1 r2
    ret r2
""")}
REC = ST.digest_hex(ST.SparseStore(D8, {}).root())        # opaque records half (verify chains only the KV half)


def _pre():
    return {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}


# a span across 3 blocks (2 calls each) — per-call cursor = block height, so recursive segmentation yields
# ONE block-aligned segment per block (>=2 segments to exercise the fold).
CALLS = [{"cid": CID, "method": "bump", "caller": ALICE, "args": [], "cursor": h} for h in (1, 2, 3) for _ in range(2)]
SPAN_CURSOR = 3


# reference roots: the NON-recursive single-epoch proof of the same span (the settled root the fold must match)
_REF = SS.prove_settlement_sparse(_pre(), CALLS, cursor=SPAN_CURSOR, rec_hex=REC, num_queries=NQ, depth=D8)
KV_PRE, KV_POST = _REF["kv_pre"], _REF["kv_post"]

# the SEGMENTED + sparse-bound proof (fold not attached) — the fast base; one row-committed RECURSION segment/block
_SEG = SS.prove_settlement_sparse(_pre(), CALLS, cursor=SPAN_CURSOR, rec_hex=REC, num_queries=NQ, depth=D8,
                                  recursive=True, fold=False)


def t_reference_single_epoch():
    ok, why, kp, kq = SS.verify_settlement_sparse(_REF, num_queries=NQ, depth=D8)
    assert ok, f"reference single-epoch settlement must verify: {why}"
    assert (kp, kq) == (KV_PRE, KV_POST)
    assert "recursive" not in _REF, "non-recursive proof must carry no recursion bundle"


def t_segments_multi():
    assert len(_SEG["segments"]) >= 2, f"expected a multi-segment span, got {len(_SEG['segments'])}"
    assert all("row_roots" in s["proof"] for s in _SEG["segments"]), "segments must be ROW-COMMITTED"
    assert "recursive" not in _SEG, "fold=False must attach no recursion bundle"


def t_segments_verify_kpath_same_root():
    """The segmented, sparse-bound proof verifies the classic K-segment way and reaches the SAME settled root as
    the single-epoch reference — segmentation + the per-segment sparse binding are sound and root-preserving."""
    ok, why, kp, kq = SS.verify_settlement_sparse(_SEG, num_queries=NQ, depth=D8)
    assert ok, f"segmented sparse settlement must verify (K-path): {why}"
    assert kp == KV_PRE and kq == KV_POST, "segmented proof must reach the reference settled root"


def t_depth_pin():
    """A proof's segments carry depth D8; the L1 caller pins its protocol depth — a mismatch is rejected."""
    ok, _, _, _ = SS.verify_settlement_sparse(_SEG, num_queries=NQ, depth=D8 + 1)
    assert not ok, "a segment built at a different tree depth must be rejected"


def t_tampered_transition_rejected():
    """Corrupt a segment's sparse post-root: the per-segment state-transition binding (which the fold does NOT
    replace) must reject it even on the fast K-path."""
    bad = copy.deepcopy(_SEG)
    bad["segments"][0]["sparse_post_root"] = tuple((int(x) + 1) % (2**61) for x in bad["segments"][0]["sparse_post_root"])
    ok, _, _, _ = SS.verify_settlement_sparse(bad, num_queries=NQ, depth=D8)
    assert not ok, "a tampered sparse post-root must be rejected"


# ---- HEAVY: the real K->1 recursion bundle over the W=106 exec AIR --------------------------------------------
_FOLD = None
if HEAVY:
    _FOLD = SS.prove_settlement_sparse(_pre(), CALLS, cursor=SPAN_CURSOR, rec_hex=REC, num_queries=NQ, depth=D8,
                                       recursive=True, fold=True, outer_queries=NQ, comp_points_per_proof=1)


def t_fold_settles():
    assert "recursive" in _FOLD, "fold=True must attach a recursion bundle"
    assert len(_FOLD["segments"]) >= 2
    ok, why, kp, kq = SS.verify_settlement_sparse(_FOLD, num_queries=NQ, depth=D8, outer_queries=NQ)
    assert ok, f"folded settlement must verify via the ONE recursion bundle: {why}"
    assert kp == KV_PRE and kq == KV_POST, "folded proof must reach the reference settled root (fold != divergence)"


def t_fold_matches_kpath():
    """The SAME folded proof also passes the classic K-segment path (its row-committed exec proofs verify
    natively too) and reaches the same root — the fold replaces the K verifications, it does not diverge."""
    ok, why, kp, kq = SS.verify_settlement_sparse(_FOLD, num_queries=NQ, depth=D8, allow_recursive=False)
    assert ok, f"folded proof must also verify K-path: {why}"
    assert kp == KV_PRE and kq == KV_POST


def t_fold_tampered_io_rejected():
    bad = copy.deepcopy(_FOLD)
    for e in bad["segments"][0]["io"]:
        if e[0] == 2:                                     # IO_SSTORE: claim a different stored value
            e[2] = 99
    ok, _, _, _ = SS.verify_settlement_sparse(bad, num_queries=NQ, depth=D8, outer_queries=NQ)
    assert not ok, "a tampered io log must be rejected by the recursion bundle"


def t_fold_tampered_layer0_rejected():
    bad = copy.deepcopy(_FOLD)
    q = bad["segments"][0]["proof"]["fri"]["queries"][0]
    q["steps"][0]["lo"] = (int(q["steps"][0]["lo"]) + 1) % (2**61)
    ok, _, _, _ = SS.verify_settlement_sparse(bad, num_queries=NQ, depth=D8, outer_queries=NQ)
    assert not ok, "a tampered layer-0 seam value must be rejected by in-circuit membership"


def t_fold_default_policy_demands_protocol_strength():
    """verify_settlement_sparse with num_queries/outer_queries None pins the PROTOCOL query counts — this
    reduced-strength (NQ=2) bundle must be rejected, never trusted at its declared counts. This is exactly how
    the L1 settle branch calls it (SS.verify_settlement_sparse(proof, depth=EXEC_TREE_DEPTH))."""
    ok, _, _, _ = SS.verify_settlement_sparse(_FOLD, depth=D8)
    assert not ok, "default (protocol-strength) policy must reject the reduced-strength fold"


if __name__ == "__main__":
    check("reference single-epoch sparse settlement verifies", t_reference_single_epoch)
    check("recursive=True,fold=False yields >=2 row-committed segments", t_segments_multi)
    check("segmented sparse proof verifies (K-path) and reaches the reference root", t_segments_verify_kpath_same_root)
    check("protocol tree-depth pin rejects a wrong-depth proof", t_depth_pin)
    check("tampered sparse post-root rejected", t_tampered_transition_rejected)
    if not HEAVY:
        print("SKIP  the real K->1 recursion BUNDLE (RV.prove/RV.verify over the W=106 exec AIR): it COMPLETES + "
              "VERIFIES with the native prover (~15 GB, minutes) but is opt-in for speed. Set NADO_HEAVY=1 to run "
              "the fold end-to-end. Its MECHANISM is the SAME wiring proven by test_settlement_o1.py and "
              "test_recursive_row.py; the fast checks above exercise all the new sparse-path code around it.")
        print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
        sys.exit(1 if fails else 0)
    check("multi-segment span settles via ONE recursion bundle (no per-segment exec stark.verify)", t_fold_settles)
    check("folded proof also verifies K-path (same root) — replaces, doesn't diverge", t_fold_matches_kpath)
    check("tampered io log rejected by the fold", t_fold_tampered_io_rejected)
    check("tampered layer-0 seam rejected by the fold", t_fold_tampered_layer0_rejected)
    check("default policy demands protocol query strength", t_fold_default_policy_demands_protocol_strength)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
