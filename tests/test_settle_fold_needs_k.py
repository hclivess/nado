"""The K->1 fold must not fire when K == 1.

The recursion bundle REPLACES the K per-segment exec-proof verifications with ONE bundle verification
(verify_settlement_sparse's own docstring). With a SINGLE segment that replaces one stark.verify with one
bundle verify — no win — while costing a full extra STARK prove and its bytes on the wire. It is not a size
optimisation either: `segments` are KEPT and `recursive` is ADDED on top.

Measured 2026-08-06: every settle on this chain emits "1 segment(s)" (14 of 14 that day), so the fold had
only ever folded ONE proof. That is what made a folded prove spend prove_transition=782-884 s against
prove_epoch=8.9 s, and what pushed the first successful folded prove past SETTLE_PROVE_TIMEOUT — it
finished at 1156.9 s and was abandoned 43 s later.

Skipping the fold is always SAFE: a proof without `recursive` takes the classic per-segment verification
path, which every verifier still implements. So this is a PROVER-side choice, not a consensus rule.

Run: python3 tests/test_settle_fold_needs_k.py
"""
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


SRC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "execnode", "stark", "settlement_sparse.py")
SRC = open(SRC_PATH).read()


def t_fold_is_gated_on_k_gt_1():
    assert "if fold and len(exec_proofs) > 1:" in SRC, \
        "the fold must be gated on there being MORE THAN ONE proof to fold"


def t_no_bare_if_fold_remains():
    """A stray `if fold:` would reintroduce the single-proof fold silently."""
    assert not re.search(r"^\s+if fold:\s*($|#)", SRC, re.M), \
        "an ungated `if fold:` is still present — the K==1 fold would fire again"


def t_recursive_and_comp_points_stay_together():
    """`comp_points_per_proof` is only meaningful alongside `recursive`; the verifier reads it from the
    same proof. They must be written under the SAME condition or a verifier sees one without the other."""
    blk = SRC[SRC.index("if fold and len(exec_proofs) > 1:"):]
    blk = blk[:blk.index("\n    return out")]
    assert 'out["recursive"]' in blk, "recursive must be set inside the gated block"
    assert 'out["comp_points_per_proof"]' in blk, "comp_points_per_proof must be set in the SAME block"


def t_segments_are_still_emitted():
    """Whatever happens to the fold, the per-segment proofs remain — they ARE the settlement."""
    assert '"segments": segments' in SRC, "segments must always be emitted"


def t_verifier_treats_recursive_as_optional():
    """The safety argument for skipping the fold: the verifier's recursive branch is conditional, so a
    proof without `recursive` is still verifiable by the classic per-segment path."""
    vsrc = SRC[SRC.index("def verify_settlement_sparse"):]
    assert "fold_exec" in vsrc, "the verifier must gate its recursive path on the field being present"
    assert "allow_recursive" in vsrc, "the verifier must allow the non-recursive path"


for nm, fn in [("the fold is gated on K > 1", t_fold_is_gated_on_k_gt_1),
               ("no ungated `if fold:` remains", t_no_bare_if_fold_remains),
               ("recursive + comp_points_per_proof stay in one block", t_recursive_and_comp_points_stay_together),
               ("segments are always emitted", t_segments_are_still_emitted),
               ("the verifier treats `recursive` as optional", t_verifier_treats_recursive_as_optional)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
