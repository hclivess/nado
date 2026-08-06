"""An INERT block can still have moved records — the presence-dividend accrual.

WHAT THIS COST. The first records-bearing settle proof ever built was refused by L1:

    settle-with-proof span 3600->3664 carries a RECORDS half: 16d9366b… -> 4b77b159… (25 update(s))
    REFUSED … "Settle proof moves the records half but the span committed no records effects"

The prover derived 25 effects for the span; L1 derived 0. Both are reading the same chain.

WHY. `inert` is computed by block_summary() from a block's TRANSACTIONS, before core_loop's accrual hook
runs. The hook then appends the epoch accrual to the summary's `rec` and never revisits `inert`. A boundary
block with no records-moving transaction is therefore stored as

    inert = 1,  rd = 1,  rec = [25 accrual effects]

and verify_calls_bound_to_summaries only read `rec` inside `if not inert:` — so it skipped the one block in
the span that actually moved records. The module header had already said the tx scan "does NOT cover the
presence-dividend accrual, which fires on an EPOCH boundary with no transaction"; the collector just never
accounted for it.

WHY THE FIX IS IN THE VERIFIER AND NOT IN `inert`. `inert` lives in the `meta` sub-DB, which FEEDS THE L1
STATE ROOT. Marking accruing blocks non-inert would change the root on upgraded nodes only and fork the
fleet — exec_summary_put's own docstring says so, and a meta-write asymmetry is what corrupted the root at
h4260. Deriving the effects differently is verifier-side: no meta write, no root change.

These checks drive the real function with synthetic summaries — resolve and CALL, no grepping.

Run: python3 tests/test_accrual_effects_collected.py
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode.stark import calls_commit as CC, alghash, field as F  # noqa: E402

fails = 0
NS = "default"


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


ACCRUAL = [[2, ["miner%02d" % i], 1000 + i] for i in range(25)]     # tag 2 == T_DIV_BAL


def _summaries(spec):
    """spec: {height: dict}. Missing heights default to a clean inert block with no effects."""
    def get(h):
        if h in spec:
            return spec[h]
        return {"inert": 0 if False else 1, "rd": 1, "rec": [], "calls": {}}
    return get


def _proof(lo, hi):
    """A single segment covering (lo, hi] whose calls_commitment matches empty calldata everywhere."""
    node = alghash.IV
    for _ in range(lo + 1, hi + 1):
        node = CC.fold_leaves(node, [])
    return {"segments": [{"cursor": hi, "calls_commitment": int(node) % F.P}]}


def t_an_inert_block_with_accrual_effects_IS_collected():
    """THE DEFECT. Without this the span derives 0 effects and the proof is refused."""
    lo, hi, b = 3600, 3664, 3660
    out = []
    ok, why = CC.verify_calls_bound_to_summaries(
        _proof(lo, hi), NS, lo, hi,
        _summaries({b: {"inert": 1, "rd": 1, "rec": ACCRUAL, "calls": {}}}),
        1000, records_out=out)
    assert ok, f"an honest accrual span must bind: {why}"
    assert len(out) == len(ACCRUAL), (
        f"the accrual effects on the INERT boundary block were not collected: got {len(out)}, "
        f"expected {len(ACCRUAL)} — this is the 25-vs-0 mismatch that refused the first records proof")


def t_an_inert_block_with_no_effects_contributes_nothing():
    lo, hi = 100, 110
    out = []
    ok, why = CC.verify_calls_bound_to_summaries(_proof(lo, hi), NS, lo, hi, _summaries({}), 1000,
                                                 records_out=out)
    assert ok, why
    assert out == [], f"ordinary inert blocks must contribute no effects, got {out}"


def t_a_non_derivable_accrual_is_REFUSED_not_silently_dropped():
    """rd=0 means the node could not derive what the block moved. Collecting nothing would let the span
    settle while silently omitting real movement — the failure the rd check exists to prevent."""
    lo, hi, b = 3600, 3664, 3660
    out = []
    ok, why = CC.verify_calls_bound_to_summaries(
        _proof(lo, hi), NS, lo, hi,
        _summaries({b: {"inert": 1, "rd": 0, "rec": ACCRUAL, "calls": {}}}),
        1000, records_out=out)
    assert not ok, "a block whose effects this node cannot derive must refuse the span"
    assert "derive" in why, f"say why, got: {why}"


def t_a_records_FROZEN_proof_is_unaffected():
    """records_out is None = the proof pins one records root. That path must behave exactly as before:
    accruing blocks are still handled by transaction_ops' epoch-boundary assert, not here, and an inert
    block must not start refusing spans it always accepted."""
    lo, hi, b = 3600, 3664, 3660
    ok, why = CC.verify_calls_bound_to_summaries(
        _proof(lo, hi), NS, lo, hi,
        _summaries({b: {"inert": 1, "rd": 1, "rec": ACCRUAL, "calls": {}}}),
        1000, records_out=None)
    assert ok, f"the frozen path must be untouched by this change: {why}"


def t_a_non_inert_block_still_collects_as_before():
    lo, hi, b = 200, 210, 205
    eff = [[1, ["addr"], 7]]
    out = []
    ok, why = CC.verify_calls_bound_to_summaries(
        _proof(lo, hi), NS, lo, hi,
        _summaries({b: {"inert": 0, "rd": 1, "rec": eff, "calls": {}}}),
        1000, records_out=out)
    assert ok, why
    assert len(out) == 1, f"the pre-existing non-inert path must be unchanged, got {out}"


def t_effects_come_out_in_BLOCK_ORDER():
    """The carry chains in block order and records_bind derives in the same order, so a reordering here
    would produce a different post-root and refuse an honest proof."""
    lo, hi = 3600, 3664
    a = [[2, ["early"], 1]]
    z = [[2, ["late"], 2]]
    out = []
    ok, why = CC.verify_calls_bound_to_summaries(
        _proof(lo, hi), NS, lo, hi,
        _summaries({3620: {"inert": 1, "rd": 1, "rec": a, "calls": {}},
                    3660: {"inert": 1, "rd": 1, "rec": z, "calls": {}}}),
        1000, records_out=out)
    assert ok, why
    assert out == a + z, f"effects must be in block order, got {out}"


for nm, fn in [("an inert block WITH accrual effects is collected", t_an_inert_block_with_accrual_effects_IS_collected),
               ("an inert block with no effects contributes nothing", t_an_inert_block_with_no_effects_contributes_nothing),
               ("a non-derivable accrual is refused", t_a_non_derivable_accrual_is_REFUSED_not_silently_dropped),
               ("a records-frozen proof is unaffected", t_a_records_FROZEN_proof_is_unaffected),
               ("a non-inert block still collects as before", t_a_non_inert_block_still_collects_as_before),
               ("effects come out in block order", t_effects_come_out_in_BLOCK_ORDER)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
