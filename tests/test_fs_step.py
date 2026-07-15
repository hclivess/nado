"""
In-circuit Fiat-Shamir STEP (execnode/stark/fs_step.py) — derive a fold challenge α = challenge(absorb(state,
root)) entirely in field constraints. Guards: the in-circuit α equals the real backend Transcript's challenge
(the derivation is bit-identical); the proof verifies; a wrong claimed challenge digest is rejected. This is the
unit the FRI in-circuit transcript chains — the O(1)-verify keystone.
(Run: python3 tests/test_fs_step.py — a slow alghash2 proof.)
"""
import os, sys, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import alghash2 as a2, field as F, fs_step as FST, backend as B
from execnode.stark.transcript import Transcript

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _reference(state_in, root):
    """What backend t_absorb + t_challenge actually compute for this (state, root)."""
    t = Transcript("fri", backend=B.RECURSION)
    t.state = tuple(int(v) % F.P for v in state_in)
    t.absorb(root)
    alpha = t.challenge()
    return alpha, tuple(t.state)


def t_step_matches_and_verifies():
    random.seed(7)
    t0 = Transcript("fri", backend=B.RECURSION)
    state_in = list(t0.state)
    root = tuple(random.randrange(F.P) for _ in range(a2.DIGEST))
    alpha_ref, cstate_ref = _reference(state_in, root)
    proof, c_dig = FST.prove_step(state_in, root, num_queries=4)
    assert c_dig[0] == alpha_ref, "in-circuit alpha must equal Transcript.challenge"
    assert tuple(c_dig) == cstate_ref, "in-circuit challenge digest must equal the post-challenge state"
    ok, why = FST.verify_step(proof, c_dig, num_queries=4)
    assert ok, f"honest FS-step proof must verify: {why}"
    bad = tuple((d + 1) % F.P for d in c_dig)
    assert not FST.verify_step(proof, bad, num_queries=4)[0], "a wrong claimed challenge digest must be rejected"


if __name__ == "__main__":
    check("in-circuit alpha matches Transcript + verifies + wrong digest rejected", t_step_matches_and_verifies)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
