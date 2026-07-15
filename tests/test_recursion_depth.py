"""
Recursion DEPTH — fold-of-folds (execnode/stark/recursion_depth.py). A fold proof built with
out_backend=RECURSION is itself rleaf/rnode-committed, so its own embedded FRI is exactly the shape prove_fold
folds — a fold can be folded, and one ROOT proof attests every proof beneath it, verified in O(1) regardless of
depth (measured: the root of a fold-of-folds verifies in ~0.2 s).

DEFAULT (fast, ~1 min): validate the ENABLER + FOLDABILITY — a RECURSION-committed fold proof verifies, and
fri_verify accepts its embedded FRI as a foldable inner proof (the exact first step the next level performs);
plus soundness (a tampered inner root is rejected).

NADO_HEAVY=1 (~20 min): the actual DEPTH STEP — fold TWO fold proofs into one root and verify it (measured:
level-1 fold trace N=131072, proven in ~19 min in pure Python — the recursion-LDE throughput wall, the same one
the W=106 settlement bundle hits; the Rust prover is the prerequisite to make deep trees fast, but the VERIFY
is already O(1)).
(Run: python3 tests/test_recursion_depth.py  — fast enabler+foldability;  NADO_HEAVY=1 python3 … — depth step.)
"""
import os, sys, copy, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import fri, field as F, backend as B, fri_verify, recursion_depth as RD

HEAVY = os.environ.get("NADO_HEAVY") == "1"

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

N, DEG, NQ, NQO = 8, 4, 1, 1


def _lowdeg(seed):
    random.seed(seed)
    c = [random.randrange(F.P) for _ in range(DEG)] + [0] * (N - DEG)
    off = F.GENERATOR
    ev = [F.poly_eval(c, x) for x in F.domain(N, off)]
    return fri.prove(ev, off, blowup=N // DEG, num_queries=NQ, backend=B.RECURSION)


# ONE level-0 fold proof, committed under RECURSION (=> foldable again). Built once.
_INNER = _lowdeg(1)
_FOLD, _PUB = fri_verify.prove_fold([_INNER], num_queries_inner=NQ, num_queries_outer=NQO,
                                    out_backend=B.RECURSION)
_MK = RD._fold_proof_fs(_FOLD)


def t_recursion_committed_fold_verifies():
    ok, why = fri_verify.verify_fold(_FOLD, _PUB, expect_inner=NQ, expect_outer=NQO, out_backend=B.RECURSION)
    assert ok, f"a RECURSION-committed fold proof must verify: {why}"


def t_fold_proof_is_foldable():
    """The DEPTH enabler: the fold proof's OWN embedded FRI is a valid foldable inner proof — fri_verify
    natively re-derives its schedule (out_backend=RECURSION => rleaf/rnode) and extracts its witness, which is
    exactly the first thing the next tree level does. This is 'a fold can be folded' without paying the full
    ~19-min level-1 proof."""
    canon = fri_verify._canonical_public(
        {"roots": _FOLD["fri"]["roots"], "N": _FOLD["fri"]["N"], "offset": _FOLD["fri"]["offset"],
         "blowup": _FOLD["fri"]["blowup"], "final": _FOLD["fri"]["final"], "pow": _FOLD["fri"].get("pow")},
        NQO, _MK)
    assert canon is not None, "the fold proof's FRI must pass native verification (be foldable)"
    wit = fri_verify._witness_of(_FOLD["fri"], NQO, _MK)
    assert wit is not None, "the fold proof's FRI witness must align to Fiat-Shamir (foldable)"


def t_tampered_inner_root_rejected():
    bad = copy.deepcopy(_PUB)
    bad["publics"][0]["roots"][0] = ("00" * 8,)
    ok, _ = fri_verify.verify_fold(_FOLD, bad, expect_inner=NQ, expect_outer=NQO, out_backend=B.RECURSION)
    assert not ok, "a fold whose declared inner roots aren't the committed ones must be rejected"


def t_depth_step_fold_of_folds():
    """HEAVY: the real depth step. Build a SECOND level-0 fold proof, fold the two fold proofs into ONE root,
    and verify the root proves BOTH low-degree — a recursion proof verifying recursion proofs."""
    f1, p1 = fri_verify.prove_fold([_lowdeg(2)], num_queries_inner=NQ, num_queries_outer=NQO,
                                   out_backend=B.RECURSION)
    mk1 = RD._fold_proof_fs(f1)
    root, rpub = fri_verify.prove_fold([_FOLD["fri"], f1["fri"]], num_queries_inner=NQO, num_queries_outer=NQO,
                                       mk_transcripts=[_MK, mk1], out_backend=B.RECURSION)
    ok, why = fri_verify.verify_fold(root, rpub, mk_transcripts=[_MK, mk1], expect_inner=NQO, expect_outer=NQO,
                                     out_backend=B.RECURSION)
    assert ok, f"the fold-of-folds root must verify: {why}"


if __name__ == "__main__":
    check("RECURSION-committed fold proof verifies", t_recursion_committed_fold_verifies)
    check("a fold proof is itself foldable (depth enabler)", t_fold_proof_is_foldable)
    check("tampered inner root rejected", t_tampered_inner_root_rejected)
    if HEAVY:
        check("DEPTH STEP: fold-of-folds proves + verifies (~19 min)", t_depth_step_fold_of_folds)
    else:
        print("SKIP  fold-of-folds depth step: the level-1 fold is ~19 min in pure Python (N=131072 recursion "
              "LDE, the throughput wall). Set NADO_HEAVY=1 to run it; the VERIFY side is already O(1) (~0.2 s).")
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
