"""A state that still owes a dividend accrual must not be settled against.

THE RACE. The exec accrual loop advances the cursor FIRST and applies the dividend AFTER, with two HTTP
awaits in between:

    cur_epoch = state.cursor // EPOCH_LENGTH
    while state.last_div_epoch < cur_epoch - 1:
        inf = await _get_json(".../get_dividend_inflow?epoch=E")     # cursor already on the boundary
        ow  = await _get_json(".../get_open_weights?epoch=E")        # still not applied
        state.accrue_dividend_epoch(inflow, weights)                 # applied only here

Anything that reads the records root inside that window sees a root that is true for NO block.

HOW IT WAS FOUND. The records DIFF diagnostic on span (4064, 4080]:

    records DIFF at 4080: 25 key(s) disagree (derived 35 entries vs actual 35)
        …512…  89276075280 vs 87914257097   Δ 1361818183
        …331…   6538626417 vs  6266262781   Δ  272363636
        …749…  11197358394 vs 10924994758   Δ  272363636

25 keys — exactly the present-miner count — the SAME key set on both sides, values only, and the derived
side uniformly HIGHER by one epoch's share. That shape rules out the two hypotheses I would otherwise have
chased: a missing effect would change the KEY SET, and a wrong carry would not move every miner by an equal
share. The prover was right about which epoch, too: epoch_accrual_due(4080) and the loop condition agree on
67. Only the timing was wrong.

WHY A WATERMARK AND NOT A HEURISTIC. `last_div_epoch` is the deterministic record of the highest epoch
already accrued, so "cursor has passed epoch E and last_div_epoch < E" is exactly the unsettled window —
no sleeping, no retry counting, no guessing at how long the awaits take.

Run: python3 tests/test_accrual_pending_guard.py
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

fails = 0
L = 60


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


class S:
    def __init__(self, last_div_epoch):
        self.last_div_epoch = last_div_epoch


def _owes():
    """Resolve the REAL function from the module under test — never a copy of it here."""
    import importlib.util
    path = os.path.join(ROOT, "execnode", "execnode.py")
    src = open(path).read()
    # execnode.py has heavy imports; lift just this function, which depends on nothing else.
    import ast
    tree = ast.parse(src)
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "state_owes_accrual":
            mod = ast.Module(body=[n], type_ignores=[])
            g = {}
            exec(compile(mod, path, "exec"), g)
            return g["state_owes_accrual"]
    raise AssertionError("state_owes_accrual not found in execnode.py")


owes = _owes()


def t_the_exact_live_case_is_refused():
    """cursor 4080, epoch 68 begun so epoch 67 is owed, but the state has only accrued 66."""
    assert owes(S(66), 4080, L) == 67, "the state that produced the 25-key diff must be refused"


def t_a_settled_state_is_allowed():
    assert owes(S(67), 4080, L) is None, "once epoch 67 is accrued the state is settle-consistent"
    assert owes(S(68), 4080, L) is None, "being AHEAD is not a reason to refuse"


def t_mid_epoch_cursors_are_allowed_once_caught_up():
    """Most spans sit inside an epoch; they must not be blocked by this."""
    for cur in (4081, 4100, 4139):
        assert owes(S(67), cur, L) is None, f"cursor {cur} with epoch 67 accrued must pass"


def t_the_window_closes_only_when_the_owed_epoch_lands():
    """Walking the boundary: at 4140 epoch 68 comes due and must block until accrued."""
    assert owes(S(67), 4140, L) == 68, "a new boundary opens a new debt"
    assert owes(S(68), 4140, L) is None, "and closes when that epoch lands"


def t_before_the_first_boundary_nothing_is_owed():
    """Below cursor L the arithmetic yields epoch -1, i.e. no debt — a fresh chain must settle freely.

    (My first cut of this test also asserted cursor 60 owes nothing. It does not, and the CODE was right:
    at cursor 60 epoch 0 has fully passed and is due — matching the live line "dividend epoch 0 … at
    cursor 60 = 1*60". Thirteenth checker wrong before the code.)"""
    assert owes(S(-1), 0, L) is None
    assert owes(S(-1), 59, L) is None
    assert owes(S(-1), 60, L) == 0, "cursor 60 has fully passed epoch 0, so epoch 0 is due"
    assert owes(S(0), 60, L) is None, "and once epoch 0 is accrued, cursor 60 is settle-consistent"


def t_a_state_missing_the_attribute_is_treated_as_owing():
    """A state object without the watermark cannot be shown settle-consistent, so it must refuse rather
    than be assumed current — the safe direction is a skipped span, not a wrong proof."""
    class Bare:
        pass
    assert owes(Bare(), 4080, L) == 67


def t_garbage_inputs_do_not_invent_a_refusal():
    """This runs on the hot settle path; it must never raise, and must not refuse when it cannot tell."""
    assert owes(S(67), None, L) is None
    assert owes(S(67), 4080, 0) is None
    assert owes(S(67), "x", L) is None


for nm, fn in [("the exact live case is refused", t_the_exact_live_case_is_refused),
               ("a settled state is allowed", t_a_settled_state_is_allowed),
               ("mid-epoch cursors are allowed once caught up", t_mid_epoch_cursors_are_allowed_once_caught_up),
               ("the window closes only when the owed epoch lands", t_the_window_closes_only_when_the_owed_epoch_lands),
               ("before the first boundary nothing is owed", t_before_the_first_boundary_nothing_is_owed),
               ("a state missing the watermark is treated as owing", t_a_state_missing_the_attribute_is_treated_as_owing),
               ("garbage inputs do not invent a refusal", t_garbage_inputs_do_not_invent_a_refusal)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
