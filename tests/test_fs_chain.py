"""
In-circuit Fiat-Shamir CHAIN (execnode/stark/fs_chain.py) — derive ALL FRI fold challenges α_0..α_{L-1} from the
layer roots inside one proof. Guards: the in-circuit α's equal a real backend Transcript replay (bit-identical
derivation); the proof verifies. This is the full in-circuit transcript for the fold-challenge schedule — the
verifier no longer re-derives α out of circuit (the O(1)-verify keystone).
(Run: python3 tests/test_fs_chain.py — a slow alghash2 proof.)
"""
import os, sys, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import alghash2 as a2, field as F, fs_chain as FC, backend as B
from execnode.stark.transcript import Transcript

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def t_chain_matches_and_verifies():
    random.seed(11)
    L = 3
    roots = [tuple(random.randrange(F.P) for _ in range(a2.DIGEST)) for _ in range(L)]
    t = Transcript("fri", backend=B.RECURSION)
    ref = []
    for r in roots:
        t.absorb(r); ref.append(t.challenge())
    proof, alphas = FC.prove_alphas(roots, label="fri", num_queries=4)
    assert [int(a) for a in alphas] == [int(a) for a in ref], "in-circuit alphas must equal Transcript replay"
    ok, why = FC.verify_alphas(proof, num_queries=4)
    assert ok, f"honest FS-chain proof must verify: {why}"


if __name__ == "__main__":
    check("in-circuit FRI fold-challenge chain matches Transcript + verifies", t_chain_matches_and_verifies)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
