"""
Shielded contracts — execution-node integration (execnode/state.py `op: private_call`).

Three properties are load-bearing here and each has its own check:

  * OFF BY DEFAULT. Phase 1's witness carries nsk in the clear. The op must refuse it, so merging this
    branch cannot leak a spend key even if a blob carrying one lands.
  * IT CANNOT POISON SETTLEMENT. `calls_commit.block_calls` collects only op == "call", and a call the
    chain skips or reverts makes the whole settle span unprovable (ROADMAP, 2026-08-06). A private call is
    rejected whenever its proof does not verify, which any user can cause at will — so if it were routed
    through the zkVM call path, one bad proof per span would switch the chain off validity proofs. The
    check below builds a real block carrying a private_call blob and asserts block_calls ignores it.
  * A NODE WITH NO PRIVATE STATE IS UNCHANGED, on disk as well as in the root.

Run: python3 tests/test_shielded_state_exec.py
"""
import os
import sys
import tempfile
import traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_appstate_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.state import ExecState
from execnode import shielded_state as S
from execnode.stark import calls_commit

FAILS = []


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except Exception as e:
        FAILS.append(name)
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


CID = "d0be764f3da9c9cc6bb609280a887929"
NSK, NSK2 = 0xC0FFEE1234, 0xBEEF5678
SENDER = "ebd27698662f14ee2389e509781d5ff57487f4289a4d67"
# A REAL checksummed address: a withdrawal destination has to be a spendable account, because it
# credits an exec balance directly rather than recording an exit for L1 to validate.
DEST = "c041167affec9c9649cbf3fe72f921a7fb001ba9831ba0"


def _state():
    """A fresh ExecState with one contract present — the op only needs the cid to exist, so this skips a
    real zkVM deploy and keeps the check on the private-state path."""
    st = ExecState(path=os.path.join(os.environ["HOME"], f"exec_{len(FAILS)}_{os.urandom(4).hex()}.json"))
    st.contracts[CID] = {"runtime": "zkvm", "code": {}, "storage": {}, "abi": {}}
    return st


def _seed(st, fields, nsk, rho):
    cm = S.note_commitment(CID, S.KIND_VALUE, fields, S.owner_of(nsk), rho)
    st.app_state.append(CID, cm)
    return cm


def _blob(st, in_notes, out_notes, public_delta=0, cid=CID):
    """The private_call payload a wallet would submit."""
    ins, nfs = [], []
    for fields, nsk, rho in in_notes:
        cm = S.note_commitment(cid, S.KIND_VALUE, fields, S.owner_of(nsk), rho)
        pos = st.app_state.position(cid, cm)
        sibs, dirs = S.tree_path(st.app_state.trees.get(cid, []), pos if pos is not None else 0)
        ins.append({"nsk": nsk, "fields": fields, "rho": rho, "siblings": sibs, "dirs": dirs})
        nfs.append(S.note_nullifier(nsk, cm))
    outs, cms = [], []
    for fields, owner, rho in out_notes:
        outs.append({"fields": fields, "owner": owner, "rho": rho})
        cms.append(S.note_commitment(cid, S.KIND_VALUE, fields, owner, rho))
    return {"op": "private_call",
            "public": {"cid": cid, "kind": S.KIND_VALUE, "root": st.app_state.root(cid),
                       "nullifiers": nfs, "out_commitments": cms, "public_delta": public_delta},
            "proof": {"witness": {"inputs": ins, "outputs": outs}}}


class _Transparent:
    def __enter__(self):
        self.prev = S.CONSENSUS_ALLOW_TRANSPARENT
        S.CONSENSUS_ALLOW_TRANSPARENT = True

    def __exit__(self, *a):
        S.CONSENSUS_ALLOW_TRANSPARENT = self.prev


# ---- the safety default ------------------------------------------------------------------------------
def t_op_refuses_a_transparent_witness_by_default():
    st = _state()
    _seed(st, [100], NSK, 1)
    r = st.apply_blob(_blob(st, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 2)]), SENDER, "tx1")
    assert "transparent witness refused" in r, f"the op accepted a witness in the clear: {r}"
    assert not st.app_state.nullifiers, "a refused transition still spent a note"


def t_op_exists_and_is_reachable():
    st = _state()
    r = st.apply_blob({"op": "private_call"}, SENDER, "tx0")
    assert r == "skip: bad private_call", f"the op is not wired: {r}"


# ---- settlement cannot be poisoned -------------------------------------------------------------------
def t_a_private_call_never_enters_the_settlement_call_list():
    block = {"block_number": 100, "block_transactions": [
        {"recipient": "blob", "sender": SENDER, "txid": "a" * 64,
         "data": {"op": "private_call", "public": {"cid": CID}, "proof": {}}},
        {"recipient": "blob", "sender": SENDER, "txid": "b" * 64,
         "data": {"op": "call", "contract": CID, "method": "m", "args": [], "value": 0}},
    ]}
    calls = calls_commit.block_calls(block)
    assert len(calls) == 1, f"a private_call entered the provable calls list ({len(calls)} calls)"


# ---- the turnstile: value crossing between the public ledger and private state ----------------------
# bridge[cid] must equal the total of that contract's private notes at every height. Individual note
# values are private; the aggregate is public by construction, which is what makes the whole thing
# auditable without seeing into it.
def t_a_deposit_debits_the_sender_and_escrows_in_the_contract():
    with _Transparent():
        st = _state()
        st.bridge[SENDER] = 500
        b = _blob(st, [], [([30], S.owner_of(NSK), 1)], public_delta=30)
        r = st.apply_blob(b, SENDER, "dep1")
        assert r.startswith("private_call "), f"a funded deposit was rejected: {r}"
        assert st.bridge[SENDER] == 470, f"sender was not debited: {st.bridge[SENDER]}"
        assert st.bridge[CID] == 30, f"contract did not escrow the deposit: {st.bridge.get(CID)}"
        assert len(st.app_state.trees[CID]) == 1, "the deposited note was not created"


def t_a_withdrawal_releases_escrow_to_the_named_destination():
    with _Transparent():
        st = _state()
        st.bridge[SENDER] = 500
        assert st.apply_blob(_blob(st, [], [([30], S.owner_of(NSK), 1)], public_delta=30),
                             SENDER, "dep2").startswith("private_call ")
        b = _blob(st, [([30], NSK, 1)], [], public_delta=-30)
        b["public"]["withdraw_addr"] = DEST
        r = st.apply_blob(b, SENDER, "wd1")
        assert r.startswith("private_call "), f"a withdrawal was rejected: {r}"
        assert st.bridge.get(CID) is None, f"escrow row was not deleted at zero: {st.bridge.get(CID)}"
        assert st.bridge[DEST] == 30, "the destination was not credited"


def t_escrow_tracks_the_private_total():
    """The turnstile invariant, over a deposit, an internal split and a partial withdrawal."""
    with _Transparent():
        st = _state()
        st.bridge[SENDER] = 500
        assert st.apply_blob(_blob(st, [], [([100], S.owner_of(NSK), 1)], public_delta=100),
                             SENDER, "d").startswith("private_call ")
        assert st.bridge[CID] == 100, "escrow wrong after deposit"
        # split 100 into 70 + 30, entirely inside private state — escrow must not move
        assert st.apply_blob(_blob(st, [([100], NSK, 1)],
                                   [([70], S.owner_of(NSK2), 2), ([30], S.owner_of(NSK), 3)]),
                             SENDER, "s").startswith("private_call ")
        assert st.bridge[CID] == 100, f"a private split moved public escrow: {st.bridge[CID]}"
        # withdraw the 30
        b = _blob(st, [([30], NSK, 3)], [], public_delta=-30)
        b["public"]["withdraw_addr"] = DEST
        assert st.apply_blob(b, SENDER, "w").startswith("private_call ")
        assert st.bridge[CID] == 70, f"escrow does not track the private total: {st.bridge[CID]}"


def t_an_unfunded_deposit_moves_nothing():
    with _Transparent():
        st = _state()
        st.bridge[SENDER] = 5
        b = _blob(st, [], [([30], S.owner_of(NSK), 1)], public_delta=30)
        r = st.apply_blob(b, SENDER, "dep3")
        assert "insufficient bridge balance" in r, f"an unfunded deposit was accepted: {r}"
        assert st.bridge[SENDER] == 5, "a rejected deposit moved the sender's balance"
        assert not st.app_state.trees.get(CID), "a rejected deposit created a note"


def t_a_withdrawal_beyond_escrow_is_refused():
    with _Transparent():
        st = _state()
        st.bridge[SENDER] = 500
        assert st.apply_blob(_blob(st, [], [([10], S.owner_of(NSK), 1)], public_delta=10),
                             SENDER, "d2").startswith("private_call ")
        b = _blob(st, [([10], NSK, 1)], [], public_delta=-999)
        b["public"]["withdraw_addr"] = DEST
        r = st.apply_blob(b, SENDER, "w2")
        assert "escrow cannot cover" in r, f"a withdrawal drained more than the contract held: {r}"
        assert st.bridge[CID] == 10, "a refused withdrawal moved escrow"
        assert not st.app_state.nullifiers, "a refused withdrawal spent the note"


def t_a_withdrawal_must_name_a_destination():
    with _Transparent():
        st = _state()
        st.bridge[SENDER] = 500
        assert st.apply_blob(_blob(st, [], [([10], S.owner_of(NSK), 1)], public_delta=10),
                             SENDER, "d3").startswith("private_call ")
        r = st.apply_blob(_blob(st, [([10], NSK, 1)], [], public_delta=-10), SENDER, "w3")
        assert r == "skip private_call: withdrawal names no destination", \
            f"an unaddressed withdrawal was accepted: {r}"


def t_the_destination_is_wired_into_the_proof_transcript():
    """H-4: with withdraw_addr outside the proven message, a front-runner could copy a blob, swap only the
    address and redirect the exit.

    THIS CHECKS THE WIRING, and says so, because the previous version of this test did not. It hashed two
    statements through a `transition_sighash` helper and asserted the digests differed — which proves that
    a hash function is a hash function, and nothing about whether the system binds anything. That helper
    turned out to be DEAD CODE: nothing in either verifier called it, because authorisation here is
    knowledge of nsk proven in-circuit rather than a signature over a sighash, so the pool's sighash shape
    was never needed. A passing test pointing at unreachable code is worse than no test.

    The real binding is `aux` in the Fiat-Shamir transcript, and the BEHAVIOURAL proof of it lives in
    tests/test_shielded_state_seam.py::a_redirected_exit_is_refused, which takes a real proof, swaps the
    destination and requires the verifier to refuse. This asserts the wiring that test depends on."""
    import inspect
    src = inspect.getsource(S.verify_transition)
    assert 'aux = str(public.get("withdraw_addr") or "")' in src, \
        "the destination is no longer bound into the transcript"
    assert src.count("aux=aux") == 2, \
        "aux is not passed to BOTH the deposit and the transition verifier"
    assert not hasattr(S, "transition_sighash"), \
        "transition_sighash is back — if something needs it, this test should test THAT thing"


def t_unknown_contract_is_refused():
    with _Transparent():
        st = _state()
        b = _blob(st, [], [([5], S.owner_of(NSK), 1)], cid="f" * 32)
        r = st.apply_blob(b, SENDER, "tx3")
        assert r == "skip private_call: no such contract", f"notes were created under no contract: {r}"


# ---- the happy path, and that it moves the settled root ----------------------------------------------
def t_a_verified_transition_applies_and_moves_the_root():
    with _Transparent():
        st = _state()
        _seed(st, [100], NSK, 1)
        before = st.state_root()
        b = _blob(st, [([100], NSK, 1)], [([60], S.owner_of(NSK2), 2), ([40], S.owner_of(NSK), 3)])
        r = st.apply_blob(b, SENDER, "tx4")
        assert r.startswith("private_call "), f"a valid transition was rejected: {r}"
        assert len(st.app_state.nullifiers) == 1, "the spent note was not nullified"
        assert len(st.app_state.trees[CID]) == 3, "outputs were not appended"
        assert st.state_root() != before, "private state changed but the settled root did not"


def t_double_spend_through_the_op():
    with _Transparent():
        st = _state()
        _seed(st, [100], NSK, 1)
        assert st.apply_blob(_blob(st, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 2)]),
                             SENDER, "tx5").startswith("private_call ")
        r = st.apply_blob(_blob(st, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 7)]), SENDER, "tx6")
        assert r == "skip private_call: note already spent", f"double spend through the op: {r}"


# ---- persistence -------------------------------------------------------------------------------------
def t_an_untouched_node_writes_no_app_state_key():
    """On-disk twin of 'empty is absent': a node holding no private state must write what it always did."""
    st = _state()
    assert "app_state" not in st._snapshot(), "an empty pool was serialized into the snapshot"


def t_private_state_survives_save_and_load():
    with _Transparent():
        path = os.path.join(os.environ["HOME"], "exec_persist.json")
        st = ExecState(path=path)
        st.contracts[CID] = {"runtime": "zkvm", "code": {}, "storage": {}, "abi": {}}
        _seed(st, [100], NSK, 1)
        assert st.apply_blob(_blob(st, [([100], NSK, 1)], [([100], S.owner_of(NSK2), 2)]),
                             SENDER, "tx7").startswith("private_call ")
        assert "app_state" in st._snapshot(), "a populated pool was not serialized"
        st.save()
        back = ExecState(path=path)
        assert back.app_state.root(CID) == st.app_state.root(CID), "note root did not survive a reload"
        assert back.app_state.nullifiers == st.app_state.nullifiers, "spent set did not survive a reload"
        assert back.state_root() == st.state_root(), "settled root did not survive a reload"


def t_clone_carries_private_state():
    """The provisional tail runs on ExecState.clone(). If a clone dropped app_state it would apply private
    calls against an EMPTY pool — accepting double-spends speculatively and diverging from the finalized
    state, which is a fork the state root would only reveal after the fact."""
    st = _state()
    cm = _seed(st, [1000], NSK, 1)
    st.app_state.spend(12345)
    c = st.clone()
    assert hasattr(c, "app_state"), "the clone has no private state at all"
    assert len(c.app_state.trees.get(CID, [])) == 1, "the clone lost the note tree"
    assert c.app_state.has_nullifier(12345), "the clone lost the spent set — it would accept a double spend"
    assert c.app_state.has_commitment(CID, cm), "the clone lost the duplicate guard"
    c.app_state.append(CID, 999)
    assert len(st.app_state.trees[CID]) == 1, "the clone shares state with the finalized pool"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "ALL PRIVATE-CALL INTEGRATION CHECKS PASSED")
sys.exit(1 if FAILS else 0)
