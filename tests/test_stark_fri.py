"""
FRI low-degree proof — the STARK engine (execnode/stark/fri.py, doc/privacy.md). The properties that make it
a sound proof system: it ACCEPTS a genuinely low-degree polynomial, REJECTS a high-degree one, and REJECTS
any tampering with the committed evaluations or the transcript.

Run: python3 tests/test_stark_fri.py
"""
import os, sys, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, fri
from execnode.stark.transcript import Transcript

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

random.seed(7)
OFF = F.GENERATOR

def coset_evals(coeffs, N, offset):
    """Evaluate a coefficient polynomial (len<=N) on the size-N coset {offset·ω^i}."""
    c = list(coeffs) + [0] * (N - len(coeffs))
    g = [F.mul(c[j], F.pw(offset, j)) for j in range(N)]
    return F.evaluate(g)


def t1_accepts_low_degree():
    N, blowup = 64, 4                              # claimed degree < 16
    coeffs = [random.randrange(F.P) for _ in range(16)]
    evals = coset_evals(coeffs, N, OFF)
    proof = fri.prove(evals, OFF, blowup, num_queries=24)
    ok, why = fri.verify(proof)
    assert ok, f"low-degree poly must verify: {why}"

def t2_rejects_high_degree():
    N, blowup = 64, 4                              # claim degree < 16, but feed degree ~40
    coeffs = [random.randrange(F.P) for _ in range(40)]
    evals = coset_evals(coeffs, N, OFF)
    proof = fri.prove(evals, OFF, blowup, num_queries=24)
    ok, why = fri.verify(proof)
    assert not ok, "a degree-40 polynomial must NOT pass a 'degree < 16' claim"

def t3_rejects_random_function():
    N, blowup = 128, 4
    evals = [random.randrange(F.P) for _ in range(N)]   # not a low-degree polynomial at all
    proof = fri.prove(evals, OFF, blowup, num_queries=30)
    ok, why = fri.verify(proof)
    assert not ok, "a random function must be rejected"

def t4_rejects_tampering():
    N, blowup = 64, 4
    coeffs = [random.randrange(F.P) for _ in range(16)]
    proof = fri.prove(coset_evals(coeffs, N, OFF), OFF, blowup, num_queries=24)
    assert fri.verify(proof)[0], "sanity: untampered proof verifies"
    # flip one opened value in one query -> Merkle opening (or fold) must fail
    proof["queries"][0]["steps"][0]["lo"] = F.add(proof["queries"][0]["steps"][0]["lo"], 1)
    ok, why = fri.verify(proof)
    assert not ok, "tampered query value must be rejected"

def t5_rejects_wrong_transcript_label():
    N, blowup = 64, 4
    coeffs = [random.randrange(F.P) for _ in range(16)]
    proof = fri.prove(coset_evals(coeffs, N, OFF), OFF, blowup, num_queries=24, transcript=Transcript("A"))
    ok, _ = fri.verify(proof, transcript=Transcript("B"))    # different Fiat-Shamir context
    assert not ok, "a proof must not verify under a different transcript"
    assert fri.verify(proof, transcript=Transcript("A"))[0], "…but verifies under the matching transcript"

def t6_grinding_required():
    # C-1: the proof-of-work nonce must be present and meet GRIND_BITS, else the proof is rejected.
    N, blowup = 64, 4
    coeffs = [random.randrange(F.P) for _ in range(16)]
    proof = fri.prove(coset_evals(coeffs, N, OFF), OFF, blowup, num_queries=24)
    assert fri.verify(proof)[0], "sanity: a properly-ground proof verifies"
    assert proof["pow"] >= 0 and isinstance(proof["pow"], int), "proof carries a PoW nonce"
    # a missing nonce is rejected
    no_pow = dict(proof); no_pow["pow"] = None
    assert not fri.verify(no_pow)[0], "a proof with no PoW nonce must be rejected"
    # a tampered nonce almost surely fails the PoW threshold (and even if it flukes it, diverges the queries)
    bad = dict(proof); bad["pow"] = proof["pow"] + 1
    ok, why = fri.verify(bad)
    assert not ok, "a proof whose PoW nonce doesn't meet GRIND_BITS must be rejected"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
