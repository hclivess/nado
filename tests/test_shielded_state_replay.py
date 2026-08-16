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
OTHER_CID = "230860957a7c1db403434ffb4a3969b3"
REAL_ADDR = "ebd27698662f14ee2389e509781d5ff57487f4289a4d67"
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


# ---- mod-P aliasing of the public delta ---------------------------------------------------------------
# The circuit pins CONS = -public_delta as a FIELD element, so every delta congruent mod P satisfies the
# same boundary: a proof for -1000 is equally a proof for -1000 - P. Without a bound, the proof attests to
# `delta mod P`, not to the delta the ledger then moves.
#
# HONEST SEVERITY: this was not exploitable in practice. Total supply (~2.3e12 raw) is nine orders of
# magnitude below P (~1.8e19), so the op's solvency checks would always have refused an aliased amount.
# It is fixed because "an unreachable amount stops it" is a property of today's supply and check ordering,
# not of the proof — and the proof is what is supposed to be doing the work.
def t_the_delta_is_bound_to_an_integer_not_a_residue():
    from execnode.stark import field as Fld
    cm = S.note_commitment(CID, S.KIND_VALUE, [1000], S.owner_of(ALICE), 222)
    pool = S.ShieldedStatePool({CID: [cm]})
    public, proof = S.prove_transition(pool, CID, S.KIND_VALUE, ALICE, [1000], 222,
                                       pool.position(CID, cm), [0], S.owner_of(ALICE), 333,
                                       public_delta=-1000, withdraw_addr="dest")
    fresh = lambda: S.ShieldedStatePool({CID: [cm]})
    assert S.verify_transition(public, proof, fresh()) is None, "the honest withdrawal was rejected"
    for alias in (-1000 - Fld.P, -1000 + Fld.P):
        pub = dict(public, public_delta=alias)
        r = S.verify_transition(pub, proof, fresh())
        assert r is not None and "out of range" in r, \
            f"a delta aliased mod P was accepted ({alias}): {r}"


def t_the_bound_matches_the_in_circuit_range():
    """|delta| < VALUE_MAX, the same bound the note values are held to in-circuit. Together they make the
    mod-P conservation equation coincide with the integer one — the C-3 argument, applied to the one
    public value the range gadget does not cover."""
    assert S.VALUE_MAX == 1 << 62, "VALUE_MAX moved away from the circuit's range bound"
    p = S.ShieldedStatePool()
    r = S.verify_transition({"cid": CID, "kind": S.KIND_VALUE, "nullifiers": [], "public_delta": S.VALUE_MAX,
                             "out_commitments": [1]}, {"stark": {}}, p)
    assert r is not None and "out of range" in r, f"a delta at the bound was accepted: {r}"


# ---- the withdrawal destination ----------------------------------------------------------------------
# Unlike the pool's unshield — which records an exit for L1 to release, and lets L1 check the address —
# a private withdrawal credits an exec-layer balance DIRECTLY. Whatever string lands there IS the account.
def _withdraw_to(dest):
    cm = S.note_commitment(CID, S.KIND_VALUE, [1000], S.owner_of(ALICE), 222)
    pool = S.ShieldedStatePool({CID: [cm]})
    public, proof = S.prove_transition(pool, CID, S.KIND_VALUE, ALICE, [1000], 222,
                                       pool.position(CID, cm), [0], S.owner_of(ALICE), 333,
                                       public_delta=-1000, withdraw_addr=dest)
    st = _state()
    st.contracts[OTHER_CID] = {"runtime": "zkvm", "code": {}, "storage": {}, "abi": {}}
    st.bridge[CID] = 1000
    st.app_state = S.ShieldedStatePool({CID: [cm]})
    return st, st.apply_blob({"op": "private_call", "public": public, "proof": proof}, "alice", "w")


def t_a_withdrawal_to_a_real_address_works():
    st, r = _withdraw_to(REAL_ADDR)
    assert r.startswith("private_call "), f"an honest withdrawal was rejected: {r}"
    assert st.bridge[REAL_ADDR] == 1000, "the destination was not credited"


def t_a_withdrawal_cannot_target_a_contract():
    """The turnstile-breaking shape: crediting a contract's escrow while it holds NO notes makes
    bridge[cid] != that contract's private total, and the coins are unspendable, because spending contract
    escrow requires a note under that cid."""
    st, r = _withdraw_to(OTHER_CID)
    assert "not a spendable account" in r, f"a withdrawal credited a contract's escrow: {r}"
    assert OTHER_CID not in st.bridge, "the rejected withdrawal still moved value"
    assert st.bridge[CID] == 1000, "the rejected withdrawal drained the source contract"


def t_a_withdrawal_cannot_burn_to_a_non_address():
    """A typo or truncation would otherwise create a balance under a key no bridge_withdraw can move."""
    st, r = _withdraw_to("not-an-address")
    assert "not a spendable account" in r, f"value was burned to a non-address: {r}"


def t_a_withdrawal_cannot_target_a_reserved_name():
    st, r = _withdraw_to("bond")
    assert "not a spendable account" in r, f"a reserved protocol name was accepted as a destination: {r}"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ALL REPLAY CHECKS PASSED")
sys.exit(1 if FAILS else 0)
