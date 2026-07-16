"""
EXEC-AIR io FINGERPRINT column (vm_circuit bind_io=True) — piece 2 of the O(1) settlement binding
(doc/zk-recursion.md §5c). An appended aux column accumulates an ordered RLC of the epoch's io under a public
challenge γ_fp; FIO[T-1] (pinned as a boundary) is a single field element that a settlement matches against the
state replay's fingerprint — binding the transition to THIS epoch's exact io without re-checking the whole log.

Validation (money-path discipline): with bind_io the proof verifies AND its claimed fingerprint equals an
independent native RLC of the trace's io; a tampered claimed fingerprint fails the boundary; and bind_io=False
is byte-identical to the live proof (the column is opt-in, appended after Z).

Run: python3 tests/test_io_fingerprint.py   (a couple of small epoch proofs)
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import vm_circuit as VC, field as F

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ = 4
GAMMA_FP = 123456789
# writes two slots then returns — several io rows (SSTORE + RET) for the fingerprint to accumulate
CODE = {"main": [["MOVI", 0, 0, 7], ["SSTORE", 0, 0, 0], ["MOVI", 1, 0, 5], ["SSTORE", 1, 0, 0],
                 ["RET", 0, 0, 0]]}
CALLS = [{"code": CODE, "method": "main", "caller": 1, "args": [], "slots": {}}]


def t_bind_io_verifies_and_fingerprint_correct():
    proof, io, _ = VC.prove_epoch_calls(CALLS, num_queries=NQ, bind_io=True, gamma_fp=GAMMA_FP)
    assert "io_fingerprint" in proof, "bind_io proof must expose io_fingerprint"
    ok, why = VC.verify_epoch_calls(proof, CALLS, io, num_queries=NQ, bind_io=True, gamma_fp=GAMMA_FP)
    assert ok, f"bind_io proof must verify: {why}"
    # independent native fingerprint of the SAME trace must match the proven one
    calls = [VC._norm_call(c) for c in CALLS]
    trace, T, *_ = VC.build_epoch_trace(calls)
    assert proof["io_fingerprint"] == VC._io_fingerprint(trace, GAMMA_FP), "fingerprint != native RLC"
    assert proof["io_fingerprint"] != 0, "a non-empty io log has a non-zero fingerprint"


def t_tampered_fingerprint_rejected():
    proof, io, _ = VC.prove_epoch_calls(CALLS, num_queries=NQ, bind_io=True, gamma_fp=GAMMA_FP)
    bad = dict(proof); bad["io_fingerprint"] = (int(proof["io_fingerprint"]) + 1) % F.P
    ok, _ = VC.verify_epoch_calls(bad, CALLS, io, num_queries=NQ, bind_io=True, gamma_fp=GAMMA_FP)
    assert not ok, "a wrong claimed fingerprint must fail the FIO boundary"


def t_wrong_gamma_rejected():
    """The verifier must use the SAME γ_fp — a different challenge rebuilds a different accumulator constraint."""
    proof, io, _ = VC.prove_epoch_calls(CALLS, num_queries=NQ, bind_io=True, gamma_fp=GAMMA_FP)
    ok, _ = VC.verify_epoch_calls(proof, CALLS, io, num_queries=NQ, bind_io=True, gamma_fp=GAMMA_FP + 1)
    assert not ok, "a different γ_fp must reject (fingerprint challenge is public + fixed)"


def t_default_byte_identical():
    a, io_a, _ = VC.prove_epoch_calls(CALLS, num_queries=NQ)
    b, _, _ = VC.prove_epoch_calls(CALLS, num_queries=NQ, bind_io=False, gamma_fp=GAMMA_FP)
    assert repr(a) == repr(b), "bind_io=False must be byte-identical to omitting it"
    assert "io_fingerprint" not in a, "no fingerprint column ⇒ no io_fingerprint key"
    okd, whyd = VC.verify_epoch_calls(a, CALLS, io_a, num_queries=NQ)
    assert okd, f"default (non-bind) proof still verifies: {whyd}"


if __name__ == "__main__":
    check("bind_io proof verifies + fingerprint == native RLC", t_bind_io_verifies_and_fingerprint_correct)
    check("tampered claimed fingerprint rejected", t_tampered_fingerprint_rejected)
    check("wrong γ_fp rejected", t_wrong_gamma_rejected)
    check("bind_io=False byte-identical + default still verifies", t_default_byte_identical)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
