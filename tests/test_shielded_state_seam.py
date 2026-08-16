"""
The Phase-2 seam: a real STARK, verified against the public statement alone.

This is the check that the feature is no longer scaffolding. Everything here runs with
CONSENSUS_ALLOW_TRANSPARENT at its shipped value (False) — the transparent witness path is off, so a
transition applies ONLY because a proof verified.

ONE prove, reused by every check, because a prove is ~30 s and every assertion below is about what the
VERIFIER does with it.

Run: python3 tests/test_shielded_state_seam.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode import shielded_state as S

FAILS = []


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


CID = "d0be764f3da9c9cc6bb609280a887929"
OTHER = "230860957a7c1db403434ffb4a3969b3"
NSK, NSK2 = 0xA11CE, 0xB0B
CM = S.note_commitment(CID, S.KIND_VALUE, [1000], S.owner_of(NSK), 7)


def fresh():
    """A pool holding exactly the note the proof spends."""
    return S.ShieldedStatePool({CID: [CM]})


print("proving once (~30 s)…", flush=True)
_t0 = time.time()
_pool = fresh()
PUBLIC, PROOF = S.prove_transition(_pool, CID, S.KIND_VALUE, NSK, [1000], 7, _pool.position(CID, CM),
                                   [700], S.owner_of(NSK2), 11, public_delta=-300, withdraw_addr="dest")
print(f"  proved in {time.time() - _t0:.1f}s\n", flush=True)


# ---- the shipped configuration ----------------------------------------------------------------------
def t_the_transparent_path_is_off():
    assert S.CONSENSUS_ALLOW_TRANSPARENT is False, \
        "the transparent witness path is enabled — a chain would publish spend keys"


def t_the_proof_carries_no_witness():
    """The whole point. A Phase-1 blob carried nsk and note openings; this carries neither."""
    assert "witness" not in PROOF, "a witness rode along with the proof"
    assert set(PROOF) == {"stark"}, f"the proof blob carries more than the proof: {sorted(PROOF)}"
    assert set(PUBLIC) <= {"cid", "kind", "root", "nullifiers", "out_commitments", "public_delta",
                           "withdraw_addr"}, f"the public statement leaks a field: {sorted(PUBLIC)}"


def t_a_proved_transition_applies():
    pool = fresh()
    r = S.apply_transition(PUBLIC, PROOF, pool)
    assert r is None, f"a valid proof was rejected: {r}"
    assert len(pool.nullifiers) == 1, "the spent note was not nullified"
    assert len(pool.trees[CID]) == 2, "the output note was not appended"


def t_replay_is_rejected():
    pool = fresh()
    assert S.apply_transition(PUBLIC, PROOF, pool) is None
    assert S.apply_transition(PUBLIC, PROOF, pool) == "note already spent", "the proof was replayable"


# ---- what the verifier must refuse -------------------------------------------------------------------
def _refused(what, **over):
    pub = dict(PUBLIC)
    pub.update(over)
    pool = fresh()
    r = S.apply_transition(pub, PROOF, pool)
    assert r is not None, f"the verifier accepted {what}"
    assert not pool.nullifiers and len(pool.trees[CID]) == 1, f"{what} mutated the pool before rejecting"


def t_a_redirected_exit_is_refused():
    """H-4: withdraw_addr is in the Fiat-Shamir transcript, so a copied proof cannot be re-addressed."""
    _refused("a redirected withdrawal", withdraw_addr="attacker")


def t_a_tampered_delta_is_refused():
    _refused("a different public delta", public_delta=-299)


def t_a_substituted_nullifier_is_refused():
    _refused("a substituted nullifier", nullifiers=[PUBLIC["nullifiers"][0] + 1])


def t_a_substituted_commitment_is_refused():
    _refused("a substituted output commitment", out_commitments=[PUBLIC["out_commitments"][0] + 1])


def t_a_foreign_contract_is_refused():
    _refused("the proof presented as another contract", cid=OTHER)


def t_an_unknown_anchor_is_refused():
    _refused("a root the contract never held", root=12345)


# ---- the guard that matters most, because nothing else would catch it -------------------------------
def t_a_kind_with_no_circuit_cannot_use_the_proof_path():
    """A kind whose predicate is only in PREDICATES has NO in-circuit rule. If the proof path accepted it,
    the transition would be 'valid' because nobody checked it — the AIR enforces conservation for
    KIND_VALUE and knows nothing about any other kind. This registers a predicate-only kind to prove the
    guard, rather than trusting that the two tables happen to match today."""
    fake = 4242
    S.PREDICATES[fake] = lambda i, o, d: None          # a predicate exists…
    try:
        assert fake not in S.STARK_KINDS, "the fixture kind is already circuit-backed"
        pub = dict(PUBLIC, kind=fake)
        r = S.apply_transition(pub, PROOF, fresh())
        assert r is not None and "no proving circuit" in r, \
            f"a kind with no in-circuit predicate took the proof path: {r}"
    finally:
        del S.PREDICATES[fake]


def t_stark_kinds_is_a_subset_of_predicates():
    assert S.STARK_KINDS <= set(S.PREDICATES), \
        "a circuit exists for a kind the state machine has no predicate for"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ALL SEAM CHECKS PASSED")
sys.exit(1 if FAILS else 0)
