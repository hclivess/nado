"""
Replay and duplication — the fund-lock class, found by attacking the finished system.

THE BUG THIS FILE EXISTS FOR. A deposit is 0-in/1-out: it has no nullifier, because there is nothing to
spend. That makes its proof and public statement INFINITELY REPLAYABLE — nothing about them is consumed.
Each replay appended the same commitment to the tree again, and since nf = H(nsk, cm) depends only on the
note, every copy shared ONE nullifier. Spend either and the rest become permanently unspendable while
their value still sits in the contract's escrow: coins locked forever, and the turnstile invariant
(escrow == private total) broken with them.

That is the same shape as the fund locks this repo has paid for before, and it was not caught by any of
the 86 checks that existed when the feature was "finished" — every one of them exercised the system
working, not an adversary reusing a valid artefact.

THE FIX is one rule: a commitment is UNIQUE, exactly as a nullifier is. Checked before either verifier
runs, so it covers deposits and transitions alike rather than only the path that exposed it. An honest
depositor pays nothing for it — fresh rho gives a fresh commitment.

Run: python3 tests/test_shielded_state_replay.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_replay_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.state import ExecState
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
ALICE = 0xA11CE

print("proving one deposit (~6 s)…", flush=True)
DEP_PUBLIC, DEP_PROOF = S.prove_deposit(CID, S.KIND_VALUE, [1000], S.owner_of(ALICE), 111,
                                        public_delta=1000)
DEP_CM = DEP_PUBLIC["out_commitments"][0]


def _state():
    st = ExecState(path=os.path.join(os.environ["HOME"], f"s{os.urandom(4).hex()}.json"))
    st.contracts[CID] = {"runtime": "zkvm", "code": {}, "storage": {}, "abi": {}}
    st.bridge["alice"] = 5000
    st.bridge["attacker"] = 5000
    return st


def _deposit(st, sender="alice", label="d"):
    return st.apply_blob({"op": "private_call", "public": DEP_PUBLIC, "proof": DEP_PROOF}, sender, label)


# ---- the bug itself ----------------------------------------------------------------------------------
def t_a_deposit_cannot_be_replayed():
    st = _state()
    assert _deposit(st).startswith("private_call "), "the honest deposit was rejected"
    r = _deposit(st, "alice", "d2")
    assert r == "skip private_call: output commitment already exists (a replayed or reused note)", \
        f"a deposit was replayable: {r}"


def t_a_third_party_cannot_replay_someones_deposit():
    """The griefing shape: the attacker pays for the replay out of their OWN balance, so it costs them
    money — and the damage lands on the depositor, whose second note would be unspendable."""
    st = _state()
    assert _deposit(st).startswith("private_call ")
    before = st.bridge["attacker"]
    r = _deposit(st, "attacker", "grief")
    assert r.startswith("skip"), f"a third party replayed the deposit: {r}"
    assert st.bridge["attacker"] == before, "the rejected replay still debited the attacker"


def t_a_replay_mutates_nothing():
    st = _state()
    _deposit(st)
    esc, notes, alice = st.bridge[CID], list(st.app_state.trees[CID]), st.bridge["alice"]
    _deposit(st, "alice", "d3")
    assert st.bridge[CID] == esc, "a rejected replay moved escrow"
    assert st.app_state.trees[CID] == notes, "a rejected replay appended a note"
    assert st.bridge["alice"] == alice, "a rejected replay debited the sender"


def t_the_turnstile_survives_a_replay_attempt():
    """The invariant the bug broke: escrow must equal the claimable private total. A duplicated note is
    NOT claimable twice — it shares one nullifier — so escrow that counted it twice was unbacked."""
    st = _state()
    _deposit(st)
    _deposit(st, "attacker", "d4")
    claimable = 1000                      # exactly one spendable note exists
    assert st.bridge[CID] == claimable, \
        f"escrow {st.bridge[CID]} exceeds the claimable private total {claimable}"


# ---- the rule, at the state-machine level ------------------------------------------------------------
def t_a_commitment_is_unique_per_contract():
    p = S.ShieldedStatePool()
    cm = S.note_commitment(CID, S.KIND_VALUE, [5], S.owner_of(ALICE), 1)
    assert not p.has_commitment(CID, cm), "an empty pool claims to hold a commitment"
    p.append(CID, cm)
    assert p.has_commitment(CID, cm), "an appended commitment is not found"
    assert not p.has_commitment("other_cid", cm), "commitments are not scoped per contract"


def t_the_membership_index_survives_a_snapshot():
    """_cmset is derived state and is never persisted, so a reloaded pool must rebuild it — otherwise the
    guard silently stops working after a restart, which is the worst possible failure for it."""
    p = S.ShieldedStatePool()
    cm = S.note_commitment(CID, S.KIND_VALUE, [5], S.owner_of(ALICE), 1)
    p.append(CID, cm)
    q = S.ShieldedStatePool.from_dict(p.to_dict())
    assert q.has_commitment(CID, cm), "the duplicate guard does not survive a reload"


def t_a_duplicate_within_one_transition_is_refused():
    p = S.ShieldedStatePool()
    cm = S.note_commitment(CID, S.KIND_VALUE, [5], S.owner_of(ALICE), 1)
    r = S.verify_transition({"cid": CID, "kind": S.KIND_VALUE, "nullifiers": [],
                             "out_commitments": [cm, cm], "public_delta": 1}, {"stark": {}}, p)
    assert r == "duplicate output commitment within one transition", \
        f"one transition created the same note twice: {r}"


def t_a_transition_cannot_recreate_an_existing_note():
    """The rule is not deposit-specific: a prover reusing rho on the OUTPUT side hits it too."""
    p = S.ShieldedStatePool()
    cm = S.note_commitment(CID, S.KIND_VALUE, [5], S.owner_of(ALICE), 1)
    p.append(CID, cm)
    r = S.verify_transition({"cid": CID, "kind": S.KIND_VALUE, "root": p.root(CID), "nullifiers": [7],
                             "out_commitments": [cm], "public_delta": 0}, {"stark": {}}, p)
    assert r == "output commitment already exists (a replayed or reused note)", \
        f"a transition recreated an existing note: {r}"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ALL REPLAY CHECKS PASSED")
sys.exit(1 if FAILS else 0)
