"""OFF-CHAIN TRANSACTION BULKING WITH ON-CHAIN REUPTAKE — the end-to-end claim, on the live settle path.

The pitch for this whole line is "prove work off-chain, merge it, settle once". Every piece has its own
test; nothing tested the SENTENCE. This runs a burst of off-chain exec-layer transactions across many
blocks, merges them into ONE settlement object, and checks the two things that make the claim true rather
than merely plausible:

  * REUPTAKE IS FAITHFUL — the merged proof reaches EXACTLY the settled root the same traffic reaches when
    proven the plain way. Merging is a verification-strategy change; if it could shift the root by one
    limb it would be a consensus fork dressed up as an optimisation.
  * REUPTAKE IS BINDING — drop one of the N off-chain transactions, or alter one, and the settlement no
    longer verifies against the honest root. A bulking scheme that cannot detect a dropped transaction is
    a compression scheme, not a settlement scheme.

WHAT "SPAM" MEANS HERE, and why the shape matters. The calls are spread across MANY BLOCKS, because
recursive segmentation is BLOCK-ALIGNED (L1's DA binding requires each segment's cursor to be its block
height and to cover contiguous whole blocks). A hundred calls in one block is not the interesting case —
it is one segment. The interesting case is many blocks each carrying traffic, because that is what
produces K segments for the K->1 merge to actually collapse, and it is what real usage looks like.

Toy depth + reduced query strength (D8/NQ) keep this in CI range: this test is about the SETTLEMENT
STRUCTURE (segmentation, merge, root fidelity, tamper detection), and the cryptographic strength of the
underlying proofs is pinned at protocol constants and tested by the recursion suite. By default it proves
the segmented + sparse-bound path and verifies it the classic K-segment way, which exercises everything
except the RV.prove/RV.verify call; NADO_HEAVY=1 additionally builds the real K->1 recursion bundle (whose
W=106 fold is minutes and many GB) and verifies the merged settlement through it.

Run: python3 tests/test_offchain_bulk_reuptake.py
     NADO_HEAVY=1 python3 tests/test_offchain_bulk_reuptake.py    (+ the real K->1 bundle)
"""
import os
import sys
import copy
import time
import tempfile
import traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_bulk_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()

from execnode import zkvmasm
from execnode.stark import settlement_sparse as SS, storage_tree as ST
import protocol
protocol.SETTLE_PROOF_RECURSIVE = True     # the fold ACCEPTANCE path (flipped on at a reroll)

HEAVY = os.environ.get("NADO_HEAVY") == "1"

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


D8 = 8                       # toy sparse depth (protocol is 256; verify pins depth per segment)
NQ = 2                       # reduced query strength (protocol NUM_QUERIES stays high)
CID = "c" * 32
ALICE = "ndoAAAA" + "A" * 41

# A counter contract: each off-chain transaction is a state-changing call, so N transactions must produce a
# DIFFERENT settled root than N-1 — which is what makes the drop/tamper checks below meaningful. A read-only
# workload would settle to the same root either way and prove nothing.
COUNTER = {"bump": zkvmasm.assemble("""
    movi r1 0
    sload r2 r1
    movi r3 1
    add r2 r3
    sstore r1 r2
    ret r2
""")}
REC = ST.digest_hex(ST.SparseStore(D8, {}).root())     # opaque records half (this path chains the KV half)

# Sized so the whole file is one CI run. Each distinct call-set proven costs a full proving pass, so the
# drop tests below SHARE one short proof rather than each building their own — four passes is what pushed
# an earlier version past ten minutes.
BLOCKS = 5                   # blocks of off-chain traffic
PER_BLOCK = 3                # transactions per block
SPAM = [{"cid": CID, "method": "bump", "caller": ALICE, "args": [], "cursor": h}
        for h in range(1, BLOCKS + 1) for _ in range(PER_BLOCK)]
SPAN_CURSOR = BLOCKS
N = len(SPAM)


def _pre():
    return {CID: {"code": COUNTER, "storage": {"slots": {}}, "runtime": "zkvm"}}


print(f"\noff-chain burst: {N} transactions across {BLOCKS} blocks ({PER_BLOCK}/block)\n")

# The reference: the SAME traffic proven as one plain epoch. This is the honest settled root.
_t0 = time.time()
_REF = SS.prove_settlement_sparse(_pre(), SPAM, cursor=SPAN_CURSOR, rec_hex=REC, num_queries=NQ, depth=D8)
_t_ref = time.time() - _t0
KV_PRE, KV_POST = _REF["kv_pre"], _REF["kv_post"]

# The merged form: block-aligned segments, row-committed, ready for the K->1 fold.
_t0 = time.time()
_MERGED = SS.prove_settlement_sparse(_pre(), SPAM, cursor=SPAN_CURSOR, rec_hex=REC, num_queries=NQ, depth=D8,
                                     recursive=True, fold=False)
_t_merge = time.time() - _t0
print(f"proved reference in {_t_ref:.1f}s; merged form in {_t_merge:.1f}s; "
      f"segments={len(_MERGED['segments'])}\n")


def t_traffic_segments_per_block():
    """K segments for K blocks of traffic — the thing the merge collapses. Without this the fold has
    nothing to do and the test would be asserting compression of a single item."""
    segs = _MERGED["segments"]
    assert len(segs) == BLOCKS, f"expected one segment per block ({BLOCKS}), got {len(segs)}"
    assert all("row_roots" in s["proof"] for s in segs), "segments must be ROW-COMMITTED to be foldable"


def t_reuptake_is_faithful():
    """N off-chain transactions, merged, settle to EXACTLY the root the plain proof reaches."""
    ok, why, kp, kq = SS.verify_settlement_sparse(_MERGED, num_queries=NQ, depth=D8)
    assert ok, f"merged settlement must verify: {why}"
    assert kp == KV_PRE and kq == KV_POST, "merging must not move the settled root"


# ONE proof of the burst-minus-one-transaction, shared by both drop checks below.
_SHORT = SS.prove_settlement_sparse(_pre(), SPAM[:-1], cursor=SPAN_CURSOR, rec_hex=REC, num_queries=NQ,
                                    depth=D8, recursive=True, fold=False)


def t_one_settlement_carries_every_transaction():
    """The reuptake really is ONE object for N transactions: a single {cursor, kv_pre, kv_post, rec,
    segments} settles the whole burst, and its post-root reflects all N (not N-1, not one block's worth)."""
    assert _MERGED["cursor"] == SPAN_CURSOR
    assert _SHORT["kv_post"] != KV_POST, \
        "dropping one transaction must change the settled root — else the root does not commit to the traffic"


def t_dropped_transaction_is_detectable():
    """THE binding property. A prover that quietly omits one of the N off-chain transactions produces a
    settlement that does not match the honest root. Compression that cannot catch this is not settlement."""
    ok, _why, _kp, kq = SS.verify_settlement_sparse(_SHORT, num_queries=NQ, depth=D8)
    # It is internally consistent — it just settles a DIFFERENT root, which L1 compares against its tip.
    assert ok, "the short proof is internally valid (it proves the traffic it actually ran)"
    assert kq != KV_POST, "a settlement missing a transaction must not reach the honest settled root"


def t_tampered_segment_rejected():
    """Corrupt one merged segment's sparse post-root: the per-segment transition binding — which the fold
    does NOT replace — rejects it."""
    bad = copy.deepcopy(_MERGED)
    bad["segments"][0]["sparse_post_root"] = tuple(
        (int(x) + 1) % (2 ** 61) for x in bad["segments"][0]["sparse_post_root"])
    ok, _, _, _ = SS.verify_settlement_sparse(bad, num_queries=NQ, depth=D8)
    assert not ok, "a tampered segment post-root must be rejected"


def t_reordered_segments_rejected():
    """Segment j's post must be segment j+1's pre. Shuffling the burst's blocks breaks the chain."""
    if len(_MERGED["segments"]) < 2:
        raise AssertionError("need >= 2 segments to test ordering")
    bad = copy.deepcopy(_MERGED)
    bad["segments"][0], bad["segments"][1] = bad["segments"][1], bad["segments"][0]
    ok, _, _, _ = SS.verify_settlement_sparse(bad, num_queries=NQ, depth=D8)
    assert not ok, "reordered segments must break the kv chain and be rejected"


# ---- HEAVY: the real K->1 merge over the W=106 exec AIR -----------------------------------------------
_FOLD = None
if HEAVY:
    _t0 = time.time()
    _FOLD = SS.prove_settlement_sparse(_pre(), SPAM, cursor=SPAN_CURSOR, rec_hex=REC, num_queries=NQ,
                                       depth=D8, recursive=True, fold=True, outer_queries=NQ,
                                       comp_points_per_proof=1)
    print(f"built the real K->1 bundle over {BLOCKS} segments in {time.time() - _t0:.1f}s\n")


def t_folded_reuptake():
    """The whole burst verified through ONE recursion bundle instead of K per-segment checks, reaching the
    same settled root. This is the sentence: prove off-chain, merge, settle once."""
    assert "recursive" in _FOLD, "fold=True must attach a recursion bundle"
    ok, why, kp, kq = SS.verify_settlement_sparse(_FOLD, num_queries=NQ, depth=D8, outer_queries=NQ)
    assert ok, f"folded settlement must verify via the ONE bundle: {why}"
    assert kp == KV_PRE and kq == KV_POST, "folding must not move the settled root"


if __name__ == "__main__":
    check(f"{BLOCKS} blocks of traffic -> {BLOCKS} foldable segments", t_traffic_segments_per_block)
    check(f"reuptake is faithful: {N} off-chain txs settle to the reference root", t_reuptake_is_faithful)
    check("one settlement object commits to every transaction", t_one_settlement_carries_every_transaction)
    check("a DROPPED off-chain transaction is detectable", t_dropped_transaction_is_detectable)
    check("a tampered segment is rejected", t_tampered_segment_rejected)
    check("reordered segments are rejected", t_reordered_segments_rejected)
    if HEAVY:
        check(f"the real K->1 merge settles all {N} txs through ONE bundle", t_folded_reuptake)
    else:
        print("SKIP  the real K->1 recursion bundle (set NADO_HEAVY=1)")
    print()
    print(f"ALL PASS — {N} off-chain transactions bulked into ONE on-chain settlement"
          if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
