"""
Shielded pool — execution-node integration (execnode/state.py, doc/privacy.md): the full
shield -> private transfer -> unshield round trip through ExecState, the compact state_root commitment,
a provable unshield exit against that root, double-spend rejection, and save/load persistence.

Run: python3 tests/test_shielded_exec.py
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_shex_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.shielded import note_commitment, note_nullifier, owner_id, merkle_path
from hashing import verify_merkle_proof, unshield_leaf

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def opening(v, ss, rho): return {"value": v, "owner": owner_id(ss), "rho": rho}
def cm(v, ss, rho): return note_commitment(v, owner_id(ss), rho)

PATH = os.path.join(os.environ["HOME"], "exec_shield.json")
st = ExecState(path=PATH)

def transfer_blob(in_specs, out_notes, public_value=0, fee=0, withdraw_addr=None):
    ins, nfs = [], []
    for v, ss, rho, pos in in_specs:
        ins.append({"value": v, "spend_secret": ss, "rho": rho, "pos": pos,
                    "path": merkle_path(st.shielded.commitments, pos)})
        nfs.append(note_nullifier(ss, rho))
    public = {"root": st.shielded.root(), "nullifiers": nfs,
              "out_commitments": [cm(*n) for n in out_notes], "public_value": public_value, "fee": fee}
    if withdraw_addr:
        public["withdraw_addr"] = withdraw_addr
    proof = {"inputs": ins, "outputs": [opening(*n) for n in out_notes]}
    return {"op": "shielded_transfer", "public": public, "proof": proof}


def t1_shield_adds_a_note():
    res = st.apply_shield(100, [cm(100, "alice", "r0")], [opening(100, "alice", "r0")])
    assert "shield 100" in res, res
    assert st.shielded.size() == 1

def t2_shield_that_underfunds_is_rejected():
    # notes claim 50 but the escrow deposit is 100 -> value not conserved -> skipped (no note added)
    n_before = st.shielded.size()
    res = st.apply_shield(100, [cm(50, "eve", "re")], [opening(50, "eve", "re")])
    assert "skip" in res and "conserved" in res, res
    assert st.shielded.size() == n_before, "bad shield must add no note"

def t3_private_transfer():
    res = st.apply_blob(transfer_blob([(100, "alice", "r0", 0)], [(60, "bob", "rb"), (40, "alice", "rc")]),
                        sender="relay", txid="t3")
    assert "shielded_transfer ok" in res, res
    assert st.shielded.size() == 3 and st.shielded.has_nullifier(note_nullifier("alice", "r0"))

def t4_unshield_records_a_provable_exit():
    # spend the 40 change note (pos 2) -> withdraw 40 to an L1 address, no change note
    res = st.apply_blob(transfer_blob([(40, "alice", "rc", 2)], [], public_value=-40, withdraw_addr="ndoAlice"),
                        sender="relay", txid="t4")
    assert "unshield 40" in res, res
    p = st.unshield_withdrawal_proof("1")
    assert p and p["amount"] == 40 and p["addr"] == "ndoAlice", p
    # the exit is provable against the exec state_root (what L1's `unshield` verifies)
    assert verify_merkle_proof(unshield_leaf(p["addr"], p["amount"], p["nonce"]), p["proof"], st.state_root()), \
        "unshield exit must be provable against state_root"

def t5_double_spend_rejected():
    res = st.apply_blob(transfer_blob([(40, "alice", "rc", 2)], [], public_value=-40, withdraw_addr="ndoAlice"),
                        sender="relay", txid="t5")
    assert "double-spend" in res, res

def t6_persistence_round_trip():
    st.save()
    st2 = ExecState(path=PATH)
    assert st2.shielded.root() == st.shielded.root(), "pool root persisted"
    assert st2.shielded.size() == st.shielded.size()
    assert st2.state_root() == st.state_root(), "state_root persisted byte-identically"
    assert len(st2.unshield_withdrawals) == 1 and st2.uw_nonce == 1, "unshield exit persisted"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
