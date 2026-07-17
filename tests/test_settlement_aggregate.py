"""
SETTLEMENT single-bundle AGGREGATION (execnode/stark/settlement_aggregate.py) — the O(1) finalization: fold every
io_replay merkle-update AND every slot_key derivation into ONE recursion bundle (one FRI fold + one comp per AIR),
so the settlement crypto is O(1) in #io.

depth=4 makes the merkle-update trace length match the slot_key length (both 128), so the two AIRs fold together.

Checks: a real replay's merkle-updates + their slot_key derivations fold into one bundle that verifies from public
parts; a tampered fold seam is rejected.

Run: python3 tests/test_settlement_aggregate.py   (a handful of small proofs + one fold)
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import (settlement_aggregate as AGG, io_replay as IR, state_io_tie as ST,
                            storage_tree as STree, exec_state_bind as ESB, field as F)
from execnode import zkvm

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

D, NQ, NQO = 4, 4, 4                                # depth 4 ⇒ merkle-update trace == slot_key trace (128)
CID = "e" * 64
CID_IO = [(CID, zkvm.IO_SSTORE, 0, 111)]            # 1 storage entry ⇒ 1 merkle-update + 1 slot_key folded

# build the proofs + the ONE bundle ONCE (folding real T=128 recursion proofs is the Python throughput wall)
_STORE = STree.SparseStore(D, {ESB.slot_key(CID, 0, D): 100})
_REPLAY = IR.prove_io_replay(_STORE, CID_IO, D, num_queries=NQ)
_POS = ST.prove_positions(CID_IO, D, num_queries=NQ, pad_to=ST.mu_trace_len(D))   # pad to fold with merkle-updates
BUNDLE, PUBS, AIRS = AGG.prove_settlement_bundle(_REPLAY["steps"], _POS, D, num_queries_outer=NQO)


def t_aggregate_verifies():
    assert BUNDLE is not None and len(PUBS) == len(_REPLAY["steps"]) + len(_POS), "all proofs folded"
    ok, why = AGG.verify_settlement_bundle(BUNDLE, PUBS, AIRS, num_queries_inner=NQ, num_queries_outer=NQO)
    assert ok, f"the single settlement bundle must verify: {why}"


def t_tampered_seam_rejected():
    bad = copy.deepcopy(PUBS)
    bad[0]["layer0"][0] = (int(bad[0]["layer0"][0]) + 1) % F.P
    ok, _ = AGG.verify_settlement_bundle(BUNDLE, bad, AIRS, num_queries_inner=NQ, num_queries_outer=NQO)
    assert not ok, "a tampered layer-0 seam must be rejected"


if __name__ == "__main__":
    check("merkle-update + slot_key derivation fold into ONE bundle", t_aggregate_verifies)
    check("tampered fold seam rejected", t_tampered_seam_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
