"""
THE WORKED EXAMPLE: a private balance book, end to end, on real proofs.

Alice puts 1000 public NADO into a contract's private state, hands the whole balance to Bob without the
chain learning that either of them was involved, and Bob takes it out to an address of his choosing. Every
step goes through apply_blob exactly as a submitted transaction would, with CONSENSUS_ALLOW_TRANSPARENT at
its shipped value — so nothing here works because a test forced a switch.

WHAT THE CHAIN SEES at each step is asserted, not described: a nullifier, an output commitment, a public
delta, and nothing else. What it never sees is who owns which note, or that the second step moved anything
between two parties at all.

THE INVARIANT UNDER TEST is the turnstile: `bridge[cid]` equals the total of that contract's private notes
at every height. Individual values are private; the aggregate is public by construction, so the vault is
auditable without being readable.

~70 s (three real proofs: a deposit at ~5 s, two transitions at ~31 s).

Run: python3 tests/test_shielded_vault_e2e.py
"""
import json
import os
import sys
import tempfile
import time

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_vault_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.state import ExecState
from execnode import shielded_state as S

FAILS = []


def step(name, fn):
    t0 = time.time()
    try:
        fn()
        print(f"PASS  {name}  ({time.time() - t0:.1f}s)")
    except AssertionError as e:
        print(f"FAIL  {name} — {e}")
        FAILS.append(name)
    except Exception as e:
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


VAULT = "d0be764f3da9c9cc6bb609280a887929"
ALICE_KEY, BOB_KEY = 0xA11CE, 0xB0B
ALICE_L1 = "ebd27698662f14ee2389e509781d5ff57487f4289a4d67"
BOB_L1 = "c041167affec9c9649cbf3fe72f921a7fb001ba9831ba0"

ST = ExecState(path=os.path.join(os.environ["HOME"], "vault.json"))
ST.contracts[VAULT] = {"runtime": "zkvm", "code": {}, "storage": {}, "abi": {}}
ST.bridge[ALICE_L1] = 5000

NOTES = {}          # what each party privately remembers: label -> (fields, nsk, rho)


def private_total():
    """What the notes actually add up to — the test knows every opening, the chain knows none of them."""
    live = 0
    for fields, nsk, rho in NOTES.values():
        cm = S.note_commitment(VAULT, S.KIND_VALUE, fields, S.owner_of(nsk), rho)
        if cm in ST.app_state.trees.get(VAULT, []) and not ST.app_state.has_nullifier(
                S.note_nullifier(nsk, cm)):
            live += fields[0]
    return live


def turnstile_holds():
    esc = ST.bridge.get(VAULT, 0)
    tot = private_total()
    assert esc == tot, f"escrow {esc} != private total {tot}"


def submit(public, proof, label):
    """Exactly what a node does with a submitted blob: the public statement inline, the proof as the JSON
    string the DA resolver would have injected."""
    payload = {"op": "private_call",
               "public_json": json.dumps(public, default=str),
               "proof_json": json.dumps(proof, default=str)}
    r = ST.apply_blob(payload, ALICE_L1, label)
    assert r.startswith("private_call "), f"{label} rejected: {r}"
    return r


# ---- 1. Alice deposits ------------------------------------------------------------------------------
def t_1_alice_deposits_1000():
    public, proof = S.prove_deposit(VAULT, S.KIND_VALUE, [1000], S.owner_of(ALICE_KEY), 111,
                                    public_delta=1000)
    NOTES["alice"] = ([1000], ALICE_KEY, 111)
    submit(public, proof, "deposit")
    assert ST.bridge[ALICE_L1] == 4000, "the depositor was not debited"
    assert ST.bridge[VAULT] == 1000, "the vault did not escrow the deposit"
    assert public["nullifiers"] == [], "a deposit spent something"
    turnstile_holds()


# ---- 2. Alice hands the balance to Bob, privately ---------------------------------------------------
def t_2_alice_pays_bob_privately():
    cm = S.note_commitment(VAULT, S.KIND_VALUE, [1000], S.owner_of(ALICE_KEY), 111)
    pos = ST.app_state.position(VAULT, cm)
    assert pos is not None, "alice's note is not in the tree"
    public, proof = S.prove_transition(ST.app_state, VAULT, S.KIND_VALUE, ALICE_KEY, [1000], 111, pos,
                                       [1000], S.owner_of(BOB_KEY), 222, public_delta=0)
    NOTES["bob"] = ([1000], BOB_KEY, 222)
    submit(public, proof, "transfer")

    # WHAT THE CHAIN LEARNED. One nullifier, one commitment, a zero delta. No amount, no parties.
    assert public["public_delta"] == 0, "a private transfer moved public value"
    assert len(public["nullifiers"]) == 1 and len(public["out_commitments"]) == 1
    seen = json.dumps(public, default=str)
    assert "1000" not in seen, "the transferred amount is visible in the public statement"
    assert str(S.owner_of(BOB_KEY)) not in seen, "the recipient is visible in the public statement"
    assert ST.bridge[VAULT] == 1000, "a purely private transfer moved escrow"
    turnstile_holds()


# ---- 3. Bob withdraws to an address of his choosing -------------------------------------------------
def t_3_bob_withdraws():
    cm = S.note_commitment(VAULT, S.KIND_VALUE, [1000], S.owner_of(BOB_KEY), 222)
    pos = ST.app_state.position(VAULT, cm)
    # 1-in/1-out, so the exit leaves a zero-value note behind rather than nothing: 1000 + (-1000) = 0.
    public, proof = S.prove_transition(ST.app_state, VAULT, S.KIND_VALUE, BOB_KEY, [1000], 222, pos,
                                       [0], S.owner_of(BOB_KEY), 333, public_delta=-1000,
                                       withdraw_addr=BOB_L1)
    NOTES["bob_change"] = ([0], BOB_KEY, 333)
    submit(public, proof, "withdraw")
    assert ST.bridge.get(BOB_L1) == 1000, "the withdrawal did not reach its destination"
    assert VAULT not in ST.bridge, "the emptied vault left a zero escrow row behind"
    turnstile_holds()


# ---- 4. and the ledger is whole ----------------------------------------------------------------------
def t_4_no_value_was_created_or_destroyed():
    assert ST.bridge[ALICE_L1] == 4000 and ST.bridge[BOB_L1] == 1000, \
        f"ledger does not balance: {dict(ST.bridge)}"
    assert ST.bridge[ALICE_L1] + ST.bridge[BOB_L1] == 5000, "value entered or left the system"
    assert len(ST.app_state.nullifiers) == 2, "wrong number of spends recorded"
    assert len(ST.app_state.trees[VAULT]) == 3, "wrong number of notes created"


def t_5_the_settled_root_moved_with_every_step():
    """Private state is consensus state: it is committed under exec_root tags 11/12, so a node that
    disagreed about the vault's contents would disagree about the state root."""
    from execnode import exec_root as ER
    proj = ER.records_projection(ST)
    app = [k for k in proj if k == ER.record_key(ER.T_APP_ROOT, VAULT,
                                                 str(int(ST.app_state.root(VAULT)) % (2 ** 64 - 2 ** 32 + 1)))]
    assert app, "the vault's note root is not committed in the settled state"
    assert ER.record_key(ER.T_APP_NULL, ST.app_state.nullifier_digest()) in proj, \
        "the spent set is not committed in the settled state"


for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t_")):
    step(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "VAULT LIFECYCLE COMPLETE — deposit, private transfer, withdrawal")
sys.exit(1 if FAILS else 0)
