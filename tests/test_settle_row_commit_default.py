"""The non-recursive settle proof must be ROW-COMMITTED with the RECURSION backend.

WHY THIS IS THE SINGLE BIGGEST NUMBER IN THE SETTLEMENT PATH. The settle proof measured 120.31 MiB on
chain, and that entire figure came from ONE producer-side default: ALGHASH2 in COLUMN mode. In column mode
each of the NUM_QUERIES=320 FRI queries opens EVERY column with its own authentication path — W=167
columns x 2 (cur+nxt) = 334 paths per query. row_commit commits ONE recursion-Merkle tree over LDE ROWS
per phase, so a query carries 2 paths.

MEASURED 2026-08-06 on production state (25 zkVM contracts, 9,016 slots), empty span, full
prove_settlement_sparse -> verify_settlement_sparse round trip:

    ALGHASH2 column (old default) : prove 140.9s   126.56 MiB   verify 19.6s   -> (True, 'ok')
    RECURSION row   (new default) : prove   7.3s     9.73 MiB   verify  6.4s   -> (True, 'ok')

13x smaller, 19x faster to prove, 3x faster to verify, and kv_pre/kv_post BYTE-IDENTICAL between the two
forms — which is the only thing consensus sees. Openings were 95.6% of the old proof (118.97 of 124.43
MiB), so this is essentially all of the size.

Isolated at the same time: one opening is 389,845 bytes in column mode against 7,008 in row mode.

The checks below are structural rather than a prove, because proving here needs the native arena and a
minute of CPU on a box that also runs the L1 (a prove starved it into 4 NODE UNHEALTHY earlier today).
What they pin is the thing that would silently regress: the DEFAULTS, the fact that row_commit tracks the
backend rather than defaulting to a bare False, and that the verifier still RECOVERS both knobs from the
proof so the two formats stay interchangeable on the wire.

Run: python3 tests/test_settle_row_commit_default.py
"""
import inspect
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "execnode", "stark", "settlement_sparse.py")).read()

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


def t_row_commit_defaults_to_none():
    """A bare `row_commit=False` default would silently give up the win for every caller that omits it —
    which is every caller, including the exec node (execnode.py passes neither knob)."""
    from execnode.stark import settlement_sparse as SS
    sig = inspect.signature(SS.prove_settlement_sparse)
    assert sig.parameters["row_commit"].default is None, \
        "row_commit must default to None (= match the backend), not False"


def t_backend_defaults_to_recursion():
    assert "backend = backend or _bk_default.RECURSION" in SRC, \
        "the non-recursive settle prove must default to the RECURSION backend"
    assert "_bk_default.ALGHASH2" not in SRC, \
        "the old ALGHASH2 default is still present — column mode would come back"


def t_row_commit_tracks_the_backend():
    """row_commit REQUIRES the RECURSION backend (stark.py raises otherwise), so resolving it from the
    backend is what keeps the pair consistent for a caller that passes only one of them."""
    # the resolution now lives in ONE place, stark.row_commit_default(backend), shared by every prover
    assert "if row_commit is None:" in SRC and "row_commit = _stark_default.row_commit_default(backend)" in SRC, \
        "row_commit must be resolved from the backend when the caller left it unset"
    src = open(os.path.join(ROOT, "execnode", "stark", "stark.py")).read()
    _fn = src[src.index("def row_commit_default(backend"):]
    _fn = _fn[:_fn.index("\ndef ")]
    assert 'return getattr(backend, "name", "") == "recursion"' in _fn, \
        "row_commit_default must key on the RECURSION backend"
    assert 'row_commit requires the RECURSION backend' in src, \
        "stark.prove must still reject row_commit on a non-recursion backend"


def t_verifier_recovers_both_knobs_from_the_proof():
    """The safety argument for changing a PRODUCER default: nothing on the wire has to agree with us."""
    assert SRC.count('row_commit = "row_roots" in bundle["proof"]') >= 2, \
        "verify_bound_epoch must infer row_commit from the proof, not from the caller"
    tx = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    assert "SS.verify_settlement_sparse(\n" in tx or "SS.verify_settlement_sparse(" in tx, \
        "L1 must call verify_settlement_sparse"
    i = tx.index("SS.verify_settlement_sparse(")
    call = tx[i:i + 200]
    assert "backend" not in call and "row_commit" not in call, \
        "L1 must pass NEITHER backend nor row_commit — it recovers both from the proof"


def t_recursive_path_unchanged():
    """The fold path already proved RECURSION + row-committed; this change only caught the other branch up."""
    assert "backend=_bk.RECURSION, row_commit=True" in SRC, \
        "the recursive path must still pin RECURSION + row_commit"


def t_exec_node_passes_neither():
    ex = open(os.path.join(ROOT, "execnode", "execnode.py")).read()
    i = ex.index("SS.prove_settlement_sparse(")
    call = ex[i:i + 400]
    assert "row_commit" not in call, \
        "the exec node must not pin row_commit — it takes the resolved default"


for nm, fn in [("row_commit defaults to None", t_row_commit_defaults_to_none),
               ("backend defaults to RECURSION", t_backend_defaults_to_recursion),
               ("row_commit tracks the backend", t_row_commit_tracks_the_backend),
               ("the verifier recovers both knobs from the proof", t_verifier_recovers_both_knobs_from_the_proof),
               ("the recursive path is unchanged", t_recursive_path_unchanged),
               ("the exec node pins neither knob", t_exec_node_passes_neither)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
