"""The merkle-update prove must commit ROWS, not 29 separate columns.

MEASURED on the live box, one records update at EXEC_TREE_DEPTH=256 (T=16384, W=29, N=131072), with every
arena entry point timed by call:

    commit_col        29 calls    146.5 s   79.6% of the prove
    compose_ext        1 call      15.6 s    8.5%
    fri_prove_native   1 call      14.7 s    8.0%
    lde_column        43 calls      5.3 s    2.9%
    open_at        18560 calls      1.2 s    0.6%
    PYTHON (unaccounted)            0.5 s    0.3%

So the cost was never Python and never the witness — build_trace measured 0.3 s. It was W=29 SEPARATE
column Merkle trees over N=131072 leaves, ~2N alghash2 permutations each, 7.6M permutations per update.
Row mode commits ONE tree whose leaves are whole rows: ~655k permutations, an order of magnitude less.

THE ASYMMETRY THAT HID IT: settlement_sparse.py defaults row_commit=True whenever the backend is RECURSION,
so the KV settle half already ran in row mode and proved a whole span in ~15 s. merkle_update.prove_update
never passed the flag, so the RECORDS half — the same arena, the same backend — paid 29 column trees per
update and came out at ~200 s. Two halves of one settle, one of them a Merkle-commit order of magnitude
slower, because a default was set in one file and not the other. That is what made records-bearing spans
unprovable: every live span logged

    records half DECLINED … 18 updates exceeds SETTLE_RECORDS_MAX_UPDATES=6

ROW MODE IS NOT PROVER'S CHOICE OF SECURITY: both modes commit the same LDE under the same transcript; row
mode simply hashes each row once instead of hashing each column into its own tree. The verifier must not be
TOLD which mode — it must READ it off the proof (`"row_roots" in proof`), the same detection
settlement_sparse.py:139 already does, or a column-mode proof and a row-mode proof would need two callers.

These checks RESOLVE and CALL. Every earlier regression in this area was caught late because the checker
matched text: a textual test passes just as happily when prove_update raises AttributeError.

Run: python3 tests/test_merkle_update_row_commit.py
"""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from execnode.stark import merkle_update as MU, backend as B, field as F  # noqa: E402

fails = 0

# Small depth so this runs in seconds: T = _next_pow2((D+1)*BR). The mode is a property of the commitment,
# not of the depth, so D=6 exercises exactly what D=256 does.
D = 6
NQ = 12
SIBS = [tuple((7 * i + j + 1) % F.P for j in range(MU.CAP)) for i in range(D)]
DIRS = [(0b101101 >> i) & 1 for i in range(D)]
OLD, NEW = 11, 12


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _prove(backend):
    return MU.prove_update(OLD, NEW, SIBS, DIRS, num_queries=NQ, backend=backend)


def t_recursion_proofs_are_row_committed():
    """The whole point. If this regresses, the records half silently goes back to ~200 s per update and the
    only symptom is a DECLINED line in the log."""
    proof, _, _ = _prove(B.RECURSION)
    assert "row_roots" in proof, (
        "a RECURSION merkle-update proof must be ROW-committed — 29 column trees is 79.6% of the prove")
    assert "col_roots" not in proof or not proof.get("col_roots"), \
        "row mode must not also emit per-column roots"


def t_row_proof_verifies_without_being_told_the_mode():
    """verify_update must READ the mode off the proof. L1 calls it through bind_and_verify_records with no
    mode argument to pass."""
    proof, pre, post = _prove(B.RECURSION)
    ok, why = MU.verify_update(proof, OLD, NEW, pre, post, DIRS, num_queries=NQ, backend=B.RECURSION)
    assert ok, f"row-committed proof must verify with no mode hint: {why}"


def t_column_mode_still_verifies():
    """row_commit REQUIRES the RECURSION backend (stark.py:377). ALGHASH2 must keep working in column mode,
    and the SAME verify_update must accept it — otherwise the detection is a one-way door."""
    proof, pre, post = _prove(B.ALGHASH2)
    assert "row_roots" not in proof, "ALGHASH2 cannot be row-committed; it must stay column-mode"
    ok, why = MU.verify_update(proof, OLD, NEW, pre, post, DIRS, num_queries=NQ, backend=B.ALGHASH2)
    assert ok, f"column-mode proof must still verify: {why}"


def t_row_mode_still_binds_the_public_statement():
    """A faster proof that accepts a wrong statement is worse than a slow one. Tamper with each public input
    in turn; every one must be rejected."""
    proof, pre, post = _prove(B.RECURSION)

    def bump(root):
        return tuple((x + 1) % F.P for x in root)

    cases = [
        ("wrong post_root", (OLD, NEW, pre, bump(post), DIRS)),
        ("wrong pre_root", (OLD, NEW, bump(pre), post, DIRS)),
        ("wrong old_val", ((OLD + 1) % F.P, NEW, pre, post, DIRS)),
        ("wrong new_val", (OLD, (NEW + 1) % F.P, pre, post, DIRS)),
        ("wrong position", (OLD, NEW, pre, post, [1 - d for d in DIRS])),
    ]
    for label, (o, n, pr, po, ds) in cases:
        ok, _ = MU.verify_update(proof, o, n, pr, po, ds, num_queries=NQ, backend=B.RECURSION)
        assert not ok, f"row mode accepted a proof with {label} — the speedup cost soundness"


def t_there_is_ONE_authority_for_the_default():
    """The defect was one question answered TWICE — settlement_sparse derived row mode from the backend,
    merkle_update never asked. Both now resolve stark.row_commit_default, so they cannot drift.

    RESOLVE AND CALL, do not grep. The first cut of this check did `inspect.getsource` on a function and
    asserted a substring; it failed against correct code because it read the wrong scope. A textual check
    passes just as happily when the function it claims to guard does not exist."""
    from execnode.stark import stark as S, settlement_sparse as SS
    fn = getattr(S, "row_commit_default", None)
    assert callable(fn), "stark.row_commit_default must exist as the single authority"
    assert fn(B.RECURSION) is True, "RECURSION must row-commit — that is the 4.1x"
    assert fn(B.ALGHASH2) is False, "ALGHASH2 cannot row-commit (stark.py refuses it)"
    # settlement_sparse must reach the authority, not keep a private copy of the predicate.
    assert getattr(SS, "stark", None) is S, "sanity: same stark module object"
    import inspect
    body = inspect.getsource(SS.prove_settlement_sparse) if hasattr(SS, "prove_settlement_sparse") else ""
    if body:
        assert "row_commit_default" in body, \
            "settlement_sparse must call the shared authority, not re-derive the predicate inline"


for nm, fn in [("recursion proofs are row-committed", t_recursion_proofs_are_row_committed),
               ("row proof verifies without a mode hint", t_row_proof_verifies_without_being_told_the_mode),
               ("column mode still verifies", t_column_mode_still_verifies),
               ("row mode still binds the public statement", t_row_mode_still_binds_the_public_statement),
               ("there is ONE authority for the default", t_there_is_ONE_authority_for_the_default)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
