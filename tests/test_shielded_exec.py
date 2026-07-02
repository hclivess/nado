"""
Shielded pool — execution-node integration (execnode/state.py, doc/privacy.md): the full
shield -> private transfer -> unshield round trip through ExecState (with ML-DSA spend authorisation), the
compact state_root commitment, a provable unshield exit against that root, double-spend rejection, and
save/load persistence.

Run: python3 tests/test_shielded_exec.py
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_shex_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.shielded import note_commitment, note_nullifier, owner_id, transfer_sighash, merkle_path
from hashing import verify_merkle_proof, unshield_leaf
from Curve25519 import generate_keydict, sign, unhex

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

ALICE, BOB = generate_keydict(), generate_keydict()
def out_open(v, kd, rho): return {"value": v, "owner": owner_id(kd["public_key"]), "rho": rho}
def cm(v, kd, rho): return note_commitment(v, owner_id(kd["public_key"]), rho)

PATH = os.path.join(os.environ["HOME"], "exec_shield.json")
st = ExecState(path=PATH)

def transfer_blob(in_specs, out_notes, public_value=0, fee=0, withdraw_addr=None):
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
    res = st.apply_shield(100, [cm(100, ALICE, "r0")], [out_open(100, ALICE, "r0")])
    assert "shield 100" in res, res
    assert st.shielded.size() == 1

def t2_shield_underfunded_rejected():
    n = st.shielded.size()
    res = st.apply_shield(100, [cm(50, ALICE, "re")], [out_open(50, ALICE, "re")])
    assert "skip" in res and "conserved" in res, res
    assert st.shielded.size() == n

def t3_private_transfer():
    res = st.apply_blob(transfer_blob([(100, ALICE, "r0", 0)], [(60, BOB, "rb"), (40, ALICE, "rc")]),
                        sender="relay", txid="t3")
    assert "shielded_transfer ok" in res, res
    assert st.shielded.size() == 3 and st.shielded.has_nullifier(note_nullifier(ALICE["public_key"], "r0"))

def t4_unshield_provable_exit():
    res = st.apply_blob(transfer_blob([(40, ALICE, "rc", 2)], [], public_value=-40, withdraw_addr="ndoAlice"),
                        sender="relay", txid="t4")
    assert "unshield 40" in res, res
    p = st.unshield_withdrawal_proof("1")
    assert p and p["amount"] == 40 and p["addr"] == "ndoAlice", p
    assert verify_merkle_proof(unshield_leaf(p["addr"], p["amount"], p["nonce"]), p["proof"], st.state_root()), \
        "unshield exit must be provable against state_root"

def t5_double_spend_rejected():
    res = st.apply_blob(transfer_blob([(40, ALICE, "rc", 2)], [], public_value=-40, withdraw_addr="ndoAlice"),
                        sender="relay", txid="t5")
    assert "double-spend" in res, res

def t6_persistence_round_trip():
    st.save()
    st2 = ExecState(path=PATH)
    assert st2.shielded.root() == st.shielded.root() and st2.shielded.size() == st.shielded.size()
    assert st2.state_root() == st.state_root(), "state_root persisted byte-identically"
    assert len(st2.unshield_withdrawals) == 1 and st2.uw_nonce == 1

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
