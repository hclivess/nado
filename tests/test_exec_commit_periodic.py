"""
EXEC AIR with COMMITTED periodic columns (vm_circuit COMMIT_PERIODIC) — the last O(epoch) term in the
settlement verifier. The exec verify normally poly_evals ~28 dense length-T periodic columns (program/io/args
tables + per-row context/args) PER QUERY; committing them turns that into an O(log N) opening.

Differential validation (money-path): the committed-periodic exec proof must (a) verify, and (b) accept iff the
public-periodic proof accepts on the SAME call — and its committed roots must equal an honest commit of the
tables (so a caller can bind them to io_commitment/calls_commitment). commit_periodic=None stays the live path.

Run: python3 tests/test_exec_commit_periodic.py   (a couple of small epoch proofs — a few minutes)
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import vm_circuit as VC, stark, field as F, backend as B, merkle
from execnode import zkvm

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ = 4
# a tiny program that writes a slot then returns — exercises the io + args + fetch tables
CODE = {"main": [["MOVI", 0, 0, 7], ["SSTORE", 0, 0, 0], ["RET", 0, 0, 0]]}
CALLS = [{"code": CODE, "method": "main", "caller": 1, "args": [], "slots": {}}]


def t_committed_exec_verifies_and_matches_public():
    proof_pub, io_pub, _ = VC.prove_epoch_calls(CALLS, num_queries=NQ)
    ok_pub, why_pub = VC.verify_epoch_calls(proof_pub, CALLS, io_pub, num_queries=NQ)
    assert ok_pub, f"public exec proof must verify: {why_pub}"

    proof_com, io_com, _ = VC.prove_epoch_calls(CALLS, num_queries=NQ, commit_periodic=VC.COMMIT_PERIODIC)
    assert "per_roots" in proof_com and len(proof_com["per_roots"]) == len(VC.COMMIT_PERIODIC)
    ok_com, why_com = VC.verify_epoch_calls(proof_com, CALLS, io_com, num_queries=NQ,
                                            commit_periodic=VC.COMMIT_PERIODIC)
    assert ok_com, f"committed-periodic exec proof must verify: {why_com}"
    assert io_com == io_pub, "same call ⇒ same io log"


def t_committed_roots_bind_to_tables():
    """Each committed per-root equals an honest commit of that periodic column's LDE, so a caller CAN bind them
    to the epoch's commitments (the O(1) binding is a chain proof; the recompute here is the correctness check)."""
    proof, io, _ = VC.prove_epoch_calls(CALLS, num_queries=NQ, commit_periodic=VC.COMMIT_PERIODIC)
    ok, why, periodic, _bnds = VC.epoch_statement(proof, CALLS, io)
    assert ok, why
    b = B.DEFAULT
    N, OFF, T = proof["N"], stark.OFF, proof["T"]
    for k, idx in enumerate(VC.COMMIT_PERIODIC):
        lde = stark._coset_evaluate(F.interpolate(stark._per_expand(periodic[idx], T)), N, OFF)
        root, _ = merkle.commit(lde, b)
        assert root == proof["per_roots"][k], f"per-root {idx} must equal the honest table commit"
    ok2, why2 = VC.verify_epoch_calls(proof, CALLS, io, num_queries=NQ, commit_periodic=VC.COMMIT_PERIODIC,
                                      periodic_roots=proof["per_roots"])
    assert ok2, f"binding the recomputed roots must still verify: {why2}"


def t_structured_periodic_bit_identity():
    """The range tables + boundary selectors now go out structured; _per_expand must rebuild them to the EXACT
    dense columns the prover used before — the guarantee that the live money-path proof is byte-identical."""
    calls = [VC._norm_call(c) for c in CALLS]
    trace, T, blocks, progs, epoch_io, _pc = VC.build_epoch_trace(calls)
    per = VC.build_periodic(blocks, progs, epoch_io, T)
    # PB / PS are the fixed range tables
    assert stark._per_expand(per[VC.PB], T) == [i if i < 256 else 0 for i in range(T)], "PB dense mismatch"
    assert stark._per_expand(per[VC.PS], T) == [i if i < 128 else 0 for i in range(T)], "PS dense mismatch"
    # P_START / P_END are the block-boundary selectors
    exp_start = [0] * T
    exp_end = [0] * T
    for bi, (s, n, _p, _c) in enumerate(blocks):
        exp_start[s] = 1
        if bi + 1 < len(blocks):
            exp_end[s + n - 1] = 1
    assert stark._per_expand(per[VC.P_START], T) == exp_start, "P_START dense mismatch"
    assert stark._per_expand(per[VC.P_END], T) == exp_end, "P_END dense mismatch"


def t_o1_verify_no_io_log():
    """verify_epoch_o1 checks the proof from ONLY the committed roots + the block schedule — it never sees the
    calls or the io log (no O(#io) rebuild). A wrong root is rejected (the caller's binding hook)."""
    proof, io, _ = VC.prove_epoch_calls(CALLS, num_queries=NQ, commit_periodic=VC.COMMIT_PERIODIC)
    ok, why = VC.verify_epoch_o1(proof, proof["per_roots"], num_queries=NQ)
    assert ok, f"O(1)-shaped verify must accept with the statement's roots: {why}"
    bad = list(proof["per_roots"]); bad[0] = proof["col_roots"][0]   # a root that isn't the committed io/prog one
    if bad[0] != proof["per_roots"][0]:
        ok2, _ = VC.verify_epoch_o1(proof, bad, num_queries=NQ)
        assert not ok2, "a wrong committed root must be rejected"


def t_default_path_untouched():
    """commit_periodic=None ⇒ no per_roots, the live proof format."""
    proof, io, _ = VC.prove_epoch_calls(CALLS, num_queries=NQ)
    assert "per_roots" not in proof
    ok, why = VC.verify_epoch_calls(proof, CALLS, io, num_queries=NQ)
    assert ok, why


if __name__ == "__main__":
    check("committed-periodic exec proof verifies + matches public", t_committed_exec_verifies_and_matches_public)
    check("committed roots bind to the honest tables", t_committed_roots_bind_to_tables)
    check("structured range/selector columns are bit-identical", t_structured_periodic_bit_identity)
    check("O(1)-shaped verify accepts from roots, no io log", t_o1_verify_no_io_log)
    check("default (commit_periodic=None) path untouched", t_default_path_untouched)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
