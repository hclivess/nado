"""
IN-CIRCUIT slot_key derivation (execnode/stark/slot_key_air.py) — proves key = slot_key(cid, slot) via ONE
alghash2 permutation (7 inputs = one chunk), so an O(1) settlement never recomputes the position hash per io
entry, at 128-bit (matching the alghash2 state tree).

Checks: the AIR digest equals native alghash2.hashn AND slot_key's truncation; the proof verifies for the public
(cid, slot); a wrong slot, cid, or digest is rejected (the init is verifier-rebuilt from (cid, slot)).

Run: python3 tests/test_slot_key_air.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import slot_key_air as SK, alghash2 as A2, exec_state_bind as ESB, field as F, backend as B
from execnode.stark.state_io_tie import _key

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

CID, SLOT, DEPTH, NQ = "e" * 64, 5, 24, 8
bk = B.ALGHASH2


def t_digest_matches_native():
    _rows, _T, _init, digest = SK.build_trace(CID, SLOT)
    assert digest == A2.hashn(SK.elements(CID, SLOT)), "AIR digest must equal native alghash2.hashn"
    assert ESB.slot_key(CID, SLOT, DEPTH) == _key(digest, DEPTH), "slot_key must be the packed+truncated digest"


def t_derivation_verifies():
    proof, digest = SK.prove(CID, SLOT, num_queries=NQ, backend=bk)
    ok, why = SK.verify(proof, CID, SLOT, digest, num_queries=NQ, backend=bk)
    assert ok, f"honest slot_key derivation must verify: {why}"


def t_wrong_inputs_rejected():
    proof, digest = SK.prove(CID, SLOT, num_queries=NQ, backend=bk)
    bad_digest = tuple([(int(digest[0]) + 1) % F.P] + list(digest[1:]))
    assert not SK.verify(proof, CID, SLOT + 1, digest, num_queries=NQ, backend=bk)[0], "wrong slot"
    assert not SK.verify(proof, "f" * 64, SLOT, digest, num_queries=NQ, backend=bk)[0], "wrong cid"
    assert not SK.verify(proof, CID, SLOT, bad_digest, num_queries=NQ, backend=bk)[0], "wrong digest"


def t_recursion_committed():
    proof, digest = SK.prove(CID, SLOT, num_queries=NQ, backend=B.RECURSION)
    ok, why = SK.verify(proof, CID, SLOT, digest, num_queries=NQ, backend=B.RECURSION)
    assert ok, f"RECURSION-committed derivation must verify: {why}"


if __name__ == "__main__":
    check("AIR digest == native alghash2.hashn == slot_key truncation", t_digest_matches_native)
    check("derivation verifies for public (cid, slot)", t_derivation_verifies)
    check("wrong slot / cid / digest rejected", t_wrong_inputs_rejected)
    check("provable + verifiable under RECURSION (foldable)", t_recursion_committed)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
