"""
END-TO-END tie: the fold-layer io binding (io_bind) attaches to a REAL exec proof's committed io table.

The binding's soundness rests on `exec_roots` being the exec proof's ACTUAL committed io-table roots (root
equality). This checks that against a real `prove_epoch_calls(commit_periodic=COMMIT_PERIODIC)` proof: the io
columns (PL_CTR/KIND/A/B/ACT) that build_periodic commits inside the exec proof are reproduced bit-for-bit by
io_bind's `commit_column` at the same geometry — so a settlement can bind the exec's committed io (which
verify_epoch_o1 never re-derives) to the state replay's io WITHOUT the verifier ever seeing the log.

Run: python3 tests/test_io_bind_exec.py   (one small committed-periodic epoch proof)
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import vm_circuit as VC, deep_eval as DE, io_bind as IB, field as F, backend as B, stark

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ = 4
IO_COLS = [VC.PL_CTR, VC.PL_KIND, VC.PL_A, VC.PL_B, VC.PL_ACT]     # the io-table periodic columns
CODE = {"main": [["MOVI", 0, 0, 7], ["SSTORE", 0, 0, 0], ["MOVI", 1, 0, 5], ["SSTORE", 1, 0, 0],
                 ["RET", 0, 0, 0]]}
CALLS = [{"code": CODE, "method": "main", "caller": 1, "args": [], "slots": {}}]


def _exec_io_columns_and_roots():
    """Prove the epoch with committed periodic columns; return (io_column_values, io_roots_from_proof)."""
    proof, io, _ = VC.prove_epoch_calls(CALLS, num_queries=NQ, commit_periodic=VC.COMMIT_PERIODIC)
    calls = [VC._norm_call(c) for c in CALLS]
    trace, T, blocks, progs, epoch_io, _pc = VC.build_epoch_trace(calls)
    periodic = VC.build_periodic(blocks, progs, epoch_io, T)
    io_values = [periodic[c] for c in IO_COLS]
    # map each committed column to its per_roots slot (per_roots align with sorted COMMIT_PERIODIC)
    order = VC.COMMIT_PERIODIC
    io_roots = [proof["per_roots"][order.index(c)] for c in IO_COLS]
    return proof, io_values, io_roots, proof["N"]


def t_commit_column_reproduces_exec_roots():
    """io_bind's commit_column, at the exec's geometry, reproduces the exec proof's committed io roots — the tie."""
    proof, io_values, io_roots, N = _exec_io_columns_and_roots()
    for c_idx, vals, want in zip(IO_COLS, io_values, io_roots):
        got = DE.commit_column(vals, N, offset=stark.OFF, backend=B.DEFAULT)
        assert got == want, f"commit_column(col {c_idx}) must equal the exec's committed per_root"


def t_binding_ties_to_real_exec_proof():
    """A replay that applies the SAME io binds to the exec proof's real committed io roots; a divergent replay io
    is rejected — the exec's committed io is bound to the replay WITHOUT the verifier re-deriving the log."""
    proof, io_values, io_roots, N = _exec_io_columns_and_roots()
    replay_values = [list(v) for v in io_values]               # replay applies the same io
    bundle = IB.prove_io_bind(io_values, replay_values, N, offset=stark.OFF, num_queries=NQ, backend=B.DEFAULT)
    ok, why = IB.verify_io_bind(bundle, io_roots, [DE.commit_column(v, N, offset=stark.OFF, backend=B.DEFAULT)
                                                   for v in replay_values], num_queries=NQ, backend=B.DEFAULT)
    assert ok, f"binding to the real exec io roots must verify: {why}"
    # a divergent replay io (one value changed) must fail
    bad = [list(v) for v in io_values]; bad[3][0] = (bad[3][0] + 1) % F.P
    bundle2 = IB.prove_io_bind(io_values, bad, N, offset=stark.OFF, num_queries=NQ, backend=B.DEFAULT)
    ok2, _ = IB.verify_io_bind(bundle2, io_roots, [DE.commit_column(v, N, offset=stark.OFF, backend=B.DEFAULT)
                                                   for v in bad], num_queries=NQ, backend=B.DEFAULT)
    assert not ok2, "a replay io that diverges from the exec's committed io must be rejected"


if __name__ == "__main__":
    check("commit_column reproduces the exec proof's committed io roots", t_commit_column_reproduces_exec_roots)
    check("binding ties to the real exec proof (divergent replay rejected)", t_binding_ties_to_real_exec_proof)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
