"""
IN-CIRCUIT slot_key derivation (execnode/stark/slot_key_air.py) — proves key = slot_key(cid, slot) via the
alghash sponge, so an O(1) settlement never recomputes the position hash per io entry.

Checks: the AIR digest equals the native alghash.hashn AND slot_key's truncation; the proof verifies for the
public (cid, slot); a wrong slot, wrong cid, or wrong digest is rejected (the inputs are pinned).

Run: python3 tests/test_slot_key_air.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import slot_key_air as SK, alghash as A, exec_state_bind as ESB, field as F, backend as B

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

CID, SLOT, DEPTH, NQ = "e" * 64, 5, 24, 8
bk = B.ALGHASH2


def t_digest_matches_native():
    _tr, _T, _els, digest = SK.build_trace(CID, SLOT)
    assert digest == A.hashn(SK.elements(CID, SLOT)), "AIR digest must equal native hashn"
    assert ESB.slot_key(CID, SLOT, DEPTH) == (digest & ((1 << DEPTH) - 1)), "slot_key must be the truncated digest"


def t_derivation_verifies():
    proof, digest = SK.prove(CID, SLOT, num_queries=NQ, backend=bk)
    ok, why = SK.verify(proof, CID, SLOT, digest, num_queries=NQ, backend=bk)
    assert ok, f"honest slot_key derivation must verify: {why}"


def t_wrong_inputs_rejected():
    proof, digest = SK.prove(CID, SLOT, num_queries=NQ, backend=bk)
    ok1, _ = SK.verify(proof, CID, SLOT + 1, digest, num_queries=NQ, backend=bk)
    assert not ok1, "a wrong slot must be rejected"
    ok2, _ = SK.verify(proof, "f" * 64, SLOT, digest, num_queries=NQ, backend=bk)
    assert not ok2, "a wrong cid must be rejected"
    ok3, _ = SK.verify(proof, CID, SLOT, (int(digest) + 1) % F.P, num_queries=NQ, backend=bk)
    assert not ok3, "a wrong digest must be rejected"


def t_recursion_committed():
    """Provable under RECURSION too (foldable into the settlement bundle)."""
    proof, digest = SK.prove(CID, SLOT, num_queries=NQ, backend=B.RECURSION)
    ok, why = SK.verify(proof, CID, SLOT, digest, num_queries=NQ, backend=B.RECURSION)
    assert ok, f"RECURSION-committed derivation must verify: {why}"


if __name__ == "__main__":
    check("AIR digest == native hashn == slot_key truncation", t_digest_matches_native)
    check("derivation verifies for public (cid, slot)", t_derivation_verifies)
    check("wrong slot / cid / digest rejected", t_wrong_inputs_rejected)
    check("provable + verifiable under RECURSION (foldable)", t_recursion_committed)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
