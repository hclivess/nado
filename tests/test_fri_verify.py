"""
SOUNDNESS of the verifier-authoritative in-circuit FRI verifier + fold (execnode/stark/fri_verify.py). The
verifier re-derives the whole statement from the committed roots (Fiat-Shamir challenges, query indices, final-
layer low-degree, grinding) and controls the AIR schedule, so a prover controls only the witness. Guards that:
an honest low-degree FRI proof folds + verifies; a FRI proof over high-degree data (which native fri.verify
rejects) is refused and rejected; and tampered roots / stripped grinding / a corrupted final are rejected.
(Run: python3 tests/test_fri_verify.py — a few slow alghash2 proofs.)
"""
import os, sys, random, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import fri, field as F, backend as B, fri_verify as V

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

N, DEG, NQ = 32, 4, 3
def _lowdeg(seed):
    random.seed(seed)
    c = [random.randrange(F.P) for _ in range(DEG)] + [0] * (N - DEG)
    off = F.GENERATOR
    ev = [F.poly_eval(c, x) for x in F.domain(N, off)]
    return fri.prove(ev, off, blowup=N // DEG, num_queries=NQ, backend=B.RECURSION)


def t_honest_verifies():
    p = _lowdeg(5)
    assert fri.verify(p, num_queries=NQ, expected_blowup=N // DEG, backend=B.RECURSION)[0]
    rp, pub = V.prove_fold([p], num_queries_inner=NQ, num_queries_outer=8)
    ok, why = V.verify_fold(rp, pub)
    assert ok, f"honest low-degree fold must verify: {why}"


def t_high_degree_rejected():
    """A real fri.prove over HIGH-DEGREE (random) data: native fri.verify rejects it (final layer not low-
    degree), so the fold must refuse to build it AND the verifier must reject its public statement."""
    random.seed(6)
    off = F.GENERATOR
    p = fri.prove([random.randrange(F.P) for _ in range(N)], off, blowup=N // DEG, num_queries=NQ, backend=B.RECURSION)
    assert not fri.verify(p, num_queries=NQ, expected_blowup=N // DEG, backend=B.RECURSION)[0], "native must reject"
    try:
        V.prove_fold([p], num_queries_inner=NQ, num_queries_outer=8)
        assert False, "prove_fold must refuse a non-low-degree proof"
    except ValueError:
        pass
    # a verifier handed the lying public statement must reject (build honest rp only to reuse the STARK object)
    good = _lowdeg(5)
    rp, _ = V.prove_fold([good], num_queries_inner=NQ, num_queries_outer=8)
    lying = {"publics": [{"roots": p["roots"], "N": N, "offset": off, "blowup": N // DEG,
                          "final": p["final"], "pow": p.get("pow")}],
             "num_queries_inner": NQ, "num_queries_outer": 8}
    assert not V.verify_fold(rp, lying)[0], "verifier must reject a high-degree public statement"


def t_tampers_rejected():
    p = _lowdeg(7)
    rp, pub = V.prove_fold([p], num_queries_inner=NQ, num_queries_outer=8)
    assert V.verify_fold(rp, pub)[0]
    for mut, label in [
        (lambda x: x["publics"][0].__setitem__("roots", [("11" * 8,)] + x["publics"][0]["roots"][1:]), "tampered root"),
        (lambda x: x["publics"][0].__setitem__("pow", 0), "stripped grinding PoW"),
        (lambda x: x["publics"][0].__setitem__("final", [(v + 1) % F.P for v in x["publics"][0]["final"]]), "corrupted final layer"),
    ]:
        bad = copy.deepcopy(pub); mut(bad)
        ok, _ = V.verify_fold(rp, bad)
        assert not ok, f"{label} must be rejected"


if __name__ == "__main__":
    check("honest low-degree FRI proof folds + verifies", t_honest_verifies)
    check("high-degree (audit-attack) proof is REFUSED and rejected", t_high_degree_rejected)
    check("tampered root / stripped grind / corrupted final all rejected", t_tampers_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
