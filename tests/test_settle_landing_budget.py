"""The submit budget, the landing margin and the publish hold must fit inside one another.

WHY IT EXISTS. On 2026-08-07 a records-bearing settle for span 8383->8400 was proved, serialised (63.41
MiB), accepted for its KV half in 10.0 s — and then discarded, because the RECORDS verification ran past the
1200 s submit budget and the client disconnected:

    09:56:45  serialised 0.8s (63.41 MiB) — POSTing
    09:57:07  [settle-verify] KV half 10.0s ok=True
    10:16:46  settle submit FAILED after 1201.0s (budget 1200s) — TimeoutError

Nothing logged the records half at all, because its timing print only runs on COMPLETION — so a verification
cancelled at the budget is indistinguishable in the log from one that never started. It cost most of a night
to tell those two apart, and the thing that finally did it was that L1 kept producing blocks at a steady
6.0 s while averaging 86% CPU: the Rust verify releases the GIL, so a healthy-looking node proves nothing.

THE INVARIANT NOBODY CHECKED. These four constants form a chain, and each link has to fit in the next:

    verification  <  submit budget  <  margin x block time  <  TX_LANDING_WINDOW x block time
                                       and  submit budget  <  SETTLE_HOLD_MAX_S

A settle is an EXACT-LANDING transaction: it enters the pool only AFTER L1 finishes verifying it, and must
then be included at max_block = tip_at_build + margin. So the margin is a HARD ceiling on how long
verification may take, and the submit budget must sit under it — otherwise the node waits for a deadline
that has already passed. Every one of these was set from a separate measurement at a separate time, and
nothing ever checked them against each other.

Run: python3 tests/test_settle_landing_budget.py
"""
import ast
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

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


def _const(path, name):
    """Read a module-level `NAME = int(os.environ.get(..., "N"))` or `NAME = N` without importing.

    execnode.py must NOT be imported here: importing node modules against the live chain opens a WRITE
    transaction on the production LMDB and has wedged this box before.
    """
    src = open(os.path.join(ROOT, path)).read()
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name):
            continue
        v = node.value
        if isinstance(v, ast.Constant) and isinstance(v.value, int):
            return v.value
        # int(os.environ.get("X", "N")) -> N, the shipped default
        if isinstance(v, ast.Call):
            for arg in ast.walk(v):
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.isdigit():
                    return int(arg.value)
        # NAME = OTHER + N
        if isinstance(v, ast.BinOp) and isinstance(v.op, ast.Add):
            return None
    raise AssertionError(f"{name} not found in {path}")


BLOCK_S = 6.0          # MEASURED over 60 s on a healthy node. 3.74 s was timed during a RESYNC and was wrong.

BUDGET = _const("execnode/execnode.py", "SETTLE_SUBMIT_TIMEOUT_PROOF")
MARGIN = _const("execnode/execnode.py", "SETTLE_PROOF_RECORDS_TX_MARGIN")
KV_MARGIN = _const("execnode/execnode.py", "SETTLE_PROOF_TX_MARGIN")
WINDOW = _const("protocol.py", "TX_LANDING_WINDOW")


def t_margin_fits_in_the_landing_window():
    """max_block is stamped `margin` blocks ahead; TX_LANDING_WINDOW is the furthest L1 will accept, and the
    tx still has to be built, serialised and propagated inside the difference."""
    assert MARGIN < WINDOW, f"records margin {MARGIN} must be under TX_LANDING_WINDOW {WINDOW}"
    assert WINDOW - MARGIN >= 20, (
        f"only {WINDOW - MARGIN} blocks left to build/serialise/propagate a ~63 MiB tx — too tight")


def t_the_submit_budget_fits_under_the_margin():
    """THE DEFECT. Waiting longer than the deadline you are waiting FOR is waiting for nothing: the tx can no
    longer land by the time the budget expires."""
    ceiling = MARGIN * BLOCK_S
    assert BUDGET < ceiling, (
        f"submit budget {BUDGET}s must be under the margin's {ceiling:.0f}s "
        f"({MARGIN} blocks x {BLOCK_S}s) or the settle cannot land even when it verifies")


def t_the_budget_leaves_room_to_be_included():
    """Verification consumes the margin; what is left is the only room the tx has to reach a block."""
    left_blocks = MARGIN - (BUDGET / BLOCK_S)
    assert left_blocks >= 20, (
        f"only {left_blocks:.0f} blocks between a worst-case verify and max_block — a settle that verifies "
        f"just under budget would still expire unincluded")


# THE LAST MEASURED RECORDS VERIFICATION, and a LOWER BOUND: the 2026-08-07 run was cancelled at the budget
# before it finished, so the true cost is >1179 s. Earlier completed runs: 1017 s and 1073 s at 27-29
# updates, 878.9 s on a memo-miss re-verify. The trend is upward because the update count IS the fleet's
# miner count (19 -> 29 in one session), so this number must be re-read from [records-bind], never assumed.
MEASURED_VERIFY_S = 1179


def t_the_budget_clears_the_measured_verification():
    """THE CHECK THAT WOULD ACTUALLY HAVE CAUGHT IT.

    The mutual-consistency checks above all PASS on the broken configuration (budget 1200 s against a
    280-block margin is 1200 < 1680), because the thing that failed was not the constants disagreeing with
    each other — it was the constants disagreeing with REALITY. A budget is only meaningful next to the cost
    it is budgeting for, and that cost grows with the fleet.
    """
    assert BUDGET > MEASURED_VERIFY_S, (
        f"submit budget {BUDGET}s does not even cover the last measured verification {MEASURED_VERIFY_S}s "
        f"— this is exactly the 1200-vs-1179 failure")
    headroom = BUDGET / MEASURED_VERIFY_S
    assert headroom >= 1.25, (
        f"only {headroom:.2f}x headroom over a cost that tracks fleet size; the previous setting had 1.02x "
        f"and lost the whole span")


def t_the_margin_also_clears_the_measured_verification():
    """The margin is the harder ceiling: verification is spent BEFORE the tx is even in the pool, so a
    margin that merely matches it leaves nothing to be included in."""
    assert MARGIN * BLOCK_S > MEASURED_VERIFY_S, (
        f"margin {MARGIN} blocks ({MARGIN * BLOCK_S:.0f}s) does not cover verification {MEASURED_VERIFY_S}s")
    left = MARGIN - (MEASURED_VERIFY_S / BLOCK_S)
    assert left >= 40, f"only {left:.0f} blocks between a measured verify and max_block"


def t_the_publish_hold_outlives_the_submit():
    """SETTLE_HOLD_MAX_S suppresses bare settles across publish+submit. If it lapses first, a bare settle
    advances the justified tip and the finished proof is refused for aiming at a tip we moved ourselves."""
    src = open(os.path.join(ROOT, "execnode/execnode.py")).read()
    assert "SETTLE_HOLD_MAX_S = SETTLE_SUBMIT_TIMEOUT_PROOF + 900" in src, (
        "the hold must be DERIVED from the submit budget, not set independently — they drifted apart once "
        "already (420s ceiling over a 439s pipeline)")


def t_the_kv_margin_stays_small():
    """A KV-only settle verifies in 7-152 s and should NOT wait 330 blocks to land — the two margins exist
    precisely so the cheap case is not punished for the expensive one."""
    assert KV_MARGIN < MARGIN, f"KV margin {KV_MARGIN} should stay well under the records margin {MARGIN}"


def t_verification_cost_is_recorded_where_the_constant_is():
    """These constants have a MOVING TARGET underneath them (verification tracks the update count, which is
    the fleet's miner count: 19 -> 29 in one session). Whoever raises one next must find the measurement."""
    src = open(os.path.join(ROOT, "execnode/execnode.py")).read()
    assert "1179" in src, "the measured records-verification cost must be recorded beside the constants"


def t_records_bind_splits_derive_from_stark():
    """The two phases call for OPPOSITE fixes — the K->1 fold only addresses `stark` — so the log has to say
    which one dominates instead of reporting one number that cannot be acted on."""
    src = open(os.path.join(ROOT, "execnode/stark/records_bind.py")).read()
    assert "[records-bind]" in src, "bind_and_verify_records must report its phase split"
    for phase in ("derive", "stark"):
        assert f"{phase} " in src, f"the phase split must name {phase}"


for nm, fn in [("margin fits in the landing window", t_margin_fits_in_the_landing_window),
               ("submit budget fits under the margin", t_the_submit_budget_fits_under_the_margin),
               ("budget leaves room to be included", t_the_budget_leaves_room_to_be_included),
               ("budget clears the MEASURED verification", t_the_budget_clears_the_measured_verification),
               ("margin clears the MEASURED verification", t_the_margin_also_clears_the_measured_verification),
               ("publish hold outlives the submit", t_the_publish_hold_outlives_the_submit),
               ("kv margin stays small", t_the_kv_margin_stays_small),
               ("verification cost recorded", t_verification_cost_is_recorded_where_the_constant_is),
               ("records-bind splits derive from stark", t_records_bind_splits_derive_from_stark)]:
    check(nm, fn)

print()
print(f"budget={BUDGET}s  margin={MARGIN} blocks ({MARGIN * BLOCK_S:.0f}s)  "
      f"window={WINDOW} blocks  kv_margin={KV_MARGIN}")
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
