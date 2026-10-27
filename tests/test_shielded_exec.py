"""
Shielded pool — execution-node integration (execnode/state.py, doc/privacy.md): the full
shield -> private transfer -> unshield round trip through ExecState (with ML-DSA spend authorisation), the
compact state_root commitment, a provable unshield exit against that root, double-spend rejection, and
save/load persistence.

Run: python3 tests/test_shielded_exec.py
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_shex_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)   # leave no /tmp home behind (9,600 leaked by 2026-09-22)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.shielded import note_commitment, note_nullifier, owner_id, transfer_sighash, merkle_path
from hashing import verify_merkle_proof, unshield_leaf
from signatures import generate_keydict, sign, unhex

import _harness
_report = _harness.Report()
check = _report.run

ALICE, BOB = generate_keydict(), generate_keydict()
def out_open(v, kd, rho):
    """Output-note opening {value, owner, rho} for value v owned by keydict kd."""
    return {"value": v, "owner": owner_id(kd["public_key"]), "rho": rho}
def cm(v, kd, rho):
    """Note commitment for value v owned by keydict kd with randomness rho."""
    return note_commitment(v, owner_id(kd["public_key"]), rho)

PATH = os.path.join(os.environ["HOME"], "exec_shield.json")
st = ExecState(path=PATH)

def transfer_blob(in_specs, out_notes, public_value=0, fee=0, withdraw_addr=None):
    """Build a signed shielded_transfer blob spending in_specs [(value, kd, rho, pos)] into out_notes [(value, kd, rho)] against the live pool root."""
    # in_specs: [(value, kd, rho, pos)]; out_notes: [(value, kd, rho)]
    nfs = [note_nullifier(kd["public_key"], rho) for (_, kd, rho, _) in in_specs]
    public = {"root": st.shielded.root(), "nullifiers": nfs,
              "out_commitments": [cm(*n) for n in out_notes], "public_value": public_value, "fee": fee}
    if withdraw_addr:
        public["withdraw_addr"] = withdraw_addr
    sh = transfer_sighash(public)
    ins = [{"value": v, "pubkey": kd["public_key"], "rho": rho, "pos": pos,
            "path": merkle_path(st.shielded.commitments, pos), "sig": sign(kd["private_key"], unhex(sh))}
           for (v, kd, rho, pos) in in_specs]
    return {"op": "shielded_transfer", "public": public, "proof": {"inputs": ins, "outputs": [out_open(*n) for n in out_notes]}}


def t1_shield_adds_a_note():
    """Seed a funded legacy note (what the deleted apply_shield did; no transaction can since G9 slice 5)."""
    ok, why = _harness.seed_legacy_notes(st, 100, [cm(100, ALICE, "r0")], [out_open(100, ALICE, "r0")])
    assert ok, why
    assert st.shielded.size() == 1

def t2_a_transfer_with_no_inputs_appends_zero_value_notes_and_nothing_else():
    """WHY THE LEGACY POOL IS STILL LIVE ON GENERATION 29 (G9 slice 5): a shielded_transfer with no inputs balances when its
    outputs are worth 0, so any sender appends notes and moves shield_root — while a non-zero output cannot balance.
    (On a separate state: the pool `st` carries the notes t3.. spend.)"""
    s2 = ExecState(path=os.path.join(os.environ["HOME"], "exec_shield_zero.json"))
    s2.cursor = 5000                                    # a gen-29 height, past every gate
    root = s2.state_root()
    res = s2.apply_blob(transfer_blob([], [(5, BOB, "rz5")]), sender="anyone", txid="t2a")
    assert "skip" in res and "conserved" in res, res
    assert s2.shielded.size() == 0 and s2.state_root() == root
    res = s2.apply_blob(transfer_blob([], [(0, BOB, "rz0")]), sender="anyone", txid="t2b")
    assert res == "shielded_transfer ok (1 out)", res
    assert s2.shielded.commitments == [cm(0, BOB, "rz0")] and s2.state_root() != root and s2.pool_value == 0

def t3_private_transfer():
    """Prove a private 2-output transfer applies through ExecState, growing the tree and spending the input nullifier."""
    res = st.apply_blob(transfer_blob([(100, ALICE, "r0", 0)], [(60, BOB, "rb"), (40, ALICE, "rc")]),
                        sender="relay", txid="t3")
    assert "shielded_transfer ok" in res, res
    assert st.shielded.size() == 3 and st.shielded.has_nullifier(note_nullifier(ALICE["public_key"], "r0"))

def t4_unshield_provable_exit():
    """Prove an unshield records a withdrawal whose Merkle proof verifies against state_root."""
    res = st.apply_blob(transfer_blob([(40, ALICE, "rc", 2)], [], public_value=-40, withdraw_addr="ndoAlice"),
                        sender="relay", txid="t4")
    assert "unshield 40" in res, res
    w = st.unshield_withdrawals.get("1")
    assert w and w["amount"] == 40 and w["addr"] == "ndoAlice", w
    ER = _harness.exit_module(st.cursor)       # L1's verifier for this root (exit_root_module)
    proof, root = st.record_proof_at(None, ER.T_UNSHIELD_WD, w["addr"], "1", value=w["amount"])
    assert root == st.state_root() and ER.verify_unshield(root, w["addr"], w["amount"], "1", proof), \
        "unshield exit must be provable against state_root"

def t5_double_spend_rejected():
    """Prove replaying the same unshield (same note/nullifier) is rejected as a double-spend."""
    res = st.apply_blob(transfer_blob([(40, ALICE, "rc", 2)], [], public_value=-40, withdraw_addr="ndoAlice"),
                        sender="relay", txid="t5")
    assert "double-spend" in res, res

def t6_persistence_round_trip():
    """Prove save/load round-trips the pool, withdrawals, nonce, and a byte-identical state_root."""
    st.save()
    st2 = ExecState(path=PATH)
    assert st2.shielded.root() == st.shielded.root() and st2.shielded.size() == st.shielded.size()
    assert st2.state_root() == st.state_root(), "state_root persisted byte-identically"
    assert len(st2.unshield_withdrawals) == 1 and st2.uw_nonce == 1

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not _report.fails else str(_report.fails)+' FAILED'}")
sys.exit(1 if _report.fails else 0)
