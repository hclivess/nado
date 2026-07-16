"""
FOLD-LAYER io BINDING (execnode/stark/io_bind.py) — bind an exec proof's io to a state replay's io at a random
OOD point drawn AFTER both commitments (DEEP evaluation). Sound, O(polylog), no public io, no shared prover
transcript, no combined mega-AIR.

Checks: matching io on both sides binds (the paired evaluations agree); ANY difference in the replay's io is
rejected (the eval at the shared z diverges — the prover cannot adapt because z post-dates both commitments); a
root that doesn't match the real proof's io commitment is rejected (the tie); and a tampered z is rejected (z is
recomputed from both roots).

Run: python3 tests/test_io_bind.py
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import io_bind as IB, deep_eval as DE, field as F, backend as B

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

T, N, NQ = 8, 32, 6
b = B.DEFAULT
# the exec's io table as columns (e.g. kind, slot, value) — 3 columns of T entries
EXEC = [[(i * 3 + 1) % F.P for i in range(T)],
        [(i * 5 + 2) % F.P for i in range(T)],
        [(i * i + 7) % F.P for i in range(T)]]


def _roots(cols):
    return [DE.commit_column(c, N, backend=b) for c in cols]


def t_matching_binds():
    replay = [list(c) for c in EXEC]                       # the replay applies the SAME io
    bundle = IB.prove_io_bind(EXEC, replay, N, num_queries=NQ, backend=b)
    ok, why = IB.verify_io_bind(bundle, _roots(EXEC), _roots(replay), num_queries=NQ, backend=b)
    assert ok, f"matching io must bind: {why}"


def t_any_difference_rejected():
    """A prover who applies a DIFFERENT io in the replay cannot bind it — z post-dates both commitments, so the
    replay io is already fixed when z is drawn and the eval at z diverges."""
    for col, row in [(0, 0), (1, 4), (2, 7)]:
        replay = [list(c) for c in EXEC]
        replay[col][row] = (replay[col][row] + 12345) % F.P
        bundle = IB.prove_io_bind(EXEC, replay, N, num_queries=NQ, backend=b)
        ok, _ = IB.verify_io_bind(bundle, _roots(EXEC), _roots(replay), num_queries=NQ, backend=b)
        assert not ok, f"a replay io differing at col {col} row {row} must be rejected"


def t_root_tie_enforced():
    replay = [list(c) for c in EXEC]
    bundle = IB.prove_io_bind(EXEC, replay, N, num_queries=NQ, backend=b)
    wrong = _roots(EXEC); wrong[0] = DE.commit_column([(v + 1) % F.P for v in EXEC[0]], N, backend=b)
    ok, _ = IB.verify_io_bind(bundle, wrong, _roots(replay), num_queries=NQ, backend=b)
    assert not ok, "a root that isn't the exec proof's committed io must be rejected"


def t_tampered_z_rejected():
    replay = [list(c) for c in EXEC]
    bundle = IB.prove_io_bind(EXEC, replay, N, num_queries=NQ, backend=b)
    bad = copy.deepcopy(bundle); bad["z"] = (int(bundle["z"]) + 1) % F.P
    ok, _ = IB.verify_io_bind(bad, _roots(EXEC), _roots(replay), num_queries=NQ, backend=b)
    assert not ok, "a z not drawn from both roots must be rejected"


if __name__ == "__main__":
    check("matching io on both sides binds", t_matching_binds)
    check("ANY replay-io difference rejected (z post-dates both)", t_any_difference_rejected)
    check("root tie to the real proof enforced", t_root_tie_enforced)
    check("tampered z rejected", t_tampered_z_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
