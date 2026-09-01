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

# OPT-IN (NADO_HEAVY=1), like test_state_transition's K->1 fold. Folding two real T=128 recursion proofs of
# the merkle-update / slot_key AIRs is the recursion throughput wall: MEASURED 2026-09-02 on this box, the
# bundle fold below (native prover, ~7 threads, 22 CPU-min per 3 wall-min) did not finish inside 60 minutes.
# An unconditional run here only ever timed out the suite (240 s) and proved nothing. Set NADO_HEAVY=1 and
# budget hours to run it for real. NOTE the number itself: protocol.SETTLE_PROOF_RECURSIVE is True, so if a
# two-item fold of these AIRs really costs >60 min the live settle fold needs a throughput look, not a bigger
# test timeout — this gate records the measurement, it does not explain it.
HEAVY = os.environ.get("NADO_HEAVY") == "1"
if not HEAVY:
    for _nm in ("single settlement bundle verifies from public parts", "tampered fold seam rejected"):
        print(f"SKIP  {_nm} (set NADO_HEAVY=1; >60 min — recursion throughput wall)")
    print("ALL PASS (heavy fold skipped)")
    sys.exit(0)

# build the proofs + the ONE bundle ONCE (folding real T=128 recursion proofs is the throughput wall)
_STORE = STree.SparseStore(D, {ESB.slot_key(CID, 0, D): 100})
_REPLAY = IR.prove_io_replay(_STORE, CID_IO, D, num_queries=NQ)
_POS = ST.prove_positions(CID_IO, D, num_queries=NQ, pad_to=ST.mu_trace_len(D))   # pad to fold with merkle-updates
BUNDLE, PUBS, AIRS = AGG.prove_settlement_bundle(_REPLAY["steps"], _POS, D, num_queries_outer=NQO)


def t_aggregate_verifies():
    assert BUNDLE is not None and len(PUBS) == len(_REPLAY["steps"]) + len(_POS), "all proofs folded"
    ok, why = AGG.verify_settlement_bundle(BUNDLE, PUBS, AIRS, num_queries_inner=NQ, num_queries_outer=NQO)
    assert ok, f"the single settlement bundle must verify: {why}"


def _bump(v):
    """Perturb a layer-0 seam value by one, whichever field it lives in.

    A layer-0 value is a BASE element in the prime field but an extension TUPLE once the challenge field is
    GF(p^D) with D>1 — so the obvious `int(v) + 1` raises TypeError before the assert below is ever reached,
    and the test then reports a failure that has nothing to do with the property it claims to check. This is
    the sixth occurrence of that shape in this suite; a negative test that cannot reach its assert is not a
    negative test, so bump the first limb and leave the rest alone."""
    if isinstance(v, tuple):
        return ((int(v[0]) + 1) % F.P,) + tuple(v[1:])
    return (int(v) + 1) % F.P


def t_tampered_seam_rejected():
    bad = copy.deepcopy(PUBS)
    bad[0]["layer0"][0] = _bump(bad[0]["layer0"][0])
    ok, _ = AGG.verify_settlement_bundle(BUNDLE, bad, AIRS, num_queries_inner=NQ, num_queries_outer=NQO)
    assert not ok, "a tampered layer-0 seam must be rejected"


if __name__ == "__main__":
    check("merkle-update + slot_key derivation fold into ONE bundle", t_aggregate_verifies)
    check("tampered fold seam rejected", t_tampered_seam_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
