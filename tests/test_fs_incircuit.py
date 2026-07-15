"""
In-circuit alghash2.hashn sponge (execnode/stark/fs_incircuit.py) — the atomic gadget the in-circuit Fiat-Shamir
transcript chains (O(1)-verify keystone). Proves a witness preimage's hashn equals a public digest, for a
multi-chunk input. Guards: the in-circuit digest equals alghash2.hashn (arithmetization is bit-identical); the
proof verifies; a wrong claimed digest is rejected.
(Run: python3 tests/test_fs_incircuit.py — a couple slow alghash2 proofs.)
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import alghash2 as a2, field as F, fs_incircuit as FS

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def t_single_chunk():
    els = [11, 22, 33, 44, 55, 66]                      # els=[6,...] -> 1 chunk
    proof, digest = FS.prove_hashn(els, num_queries=4)
    assert tuple(digest) == a2.hashn(els), "in-circuit digest must equal alghash2.hashn"
    ok, why = FS.verify_hashn(proof, digest, num_queries=4)
    assert ok, f"honest hashn proof must verify: {why}"


def t_multi_chunk():
    els = list(range(100, 113))                        # els=[13,...] -> 2 chunks
    proof, digest = FS.prove_hashn(els, num_queries=4)
    assert tuple(digest) == a2.hashn(els), "multi-chunk in-circuit digest must equal alghash2.hashn"
    ok, why = FS.verify_hashn(proof, digest, num_queries=4)
    assert ok, f"honest multi-chunk hashn proof must verify: {why}"
    bad = tuple((d + 1) % F.P for d in digest)
    assert not FS.verify_hashn(proof, bad, num_queries=4)[0], "a wrong claimed digest must be rejected"


if __name__ == "__main__":
    check("single-chunk hashn: bit-identical + verifies", t_single_chunk)
    check("multi-chunk hashn: bit-identical + verifies + wrong digest rejected", t_multi_chunk)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
