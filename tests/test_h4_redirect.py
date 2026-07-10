"""
H-4 regression — the transparent shielded_transfer unshield path must bind withdraw_addr into the signed
sighash, so a front-runner cannot copy a victim's unshield blob, swap only the destination address, and
redirect the exit. Before the fix transfer_sighash omitted withdraw_addr, so the swapped blob still verified.

Run: python3 tests/test_h4_redirect.py
"""
import os, sys, tempfile, traceback, copy
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_h4_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.shielded import note_commitment, note_nullifier, owner_id, transfer_sighash, merkle_path
from signatures import generate_keydict, sign, unhex

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

ALICE = generate_keydict()
def out_open(v, kd, rho):
    """Build the output-note opening dict (value, owner, rho) for keydict kd."""
    return {"value": v, "owner": owner_id(kd["public_key"]), "rho": rho}
def cm(v, kd, rho):
    """Compute the note commitment for value v owned by keydict kd with randomness rho."""
    return note_commitment(v, owner_id(kd["public_key"]), rho)

st = ExecState(path=os.path.join(os.environ["HOME"], "exec_shield.json"))

CHANGE_POS = 2   # setup: pos0=100-note (spent), pos1=60-note, pos2=40-note (Alice's change, rho="rc")

def _victim_unshield_blob(withdraw_addr):
    """Alice unshields her 40-coin note to `withdraw_addr`, signed correctly."""
    nf = note_nullifier(ALICE["public_key"], "rc")
    public = {"root": st.shielded.root(), "nullifiers": [nf], "out_commitments": [],
              "public_value": -40, "fee": 0, "withdraw_addr": withdraw_addr}
    sh = transfer_sighash(public)
    ins = [{"value": 40, "pubkey": ALICE["public_key"], "rho": "rc", "pos": CHANGE_POS,
            "path": merkle_path(st.shielded.commitments, CHANGE_POS), "sig": sign(ALICE["private_key"], unhex(sh))}]
    return {"op": "shielded_transfer", "public": public, "proof": {"inputs": ins, "outputs": []}}

def setup():
    """Shield 100 coins to Alice, then split them so pos 2 holds her 40-coin change note."""
    # a note Alice can later unshield (pos 0), plus a private transfer so pos 1 = Alice's 40-coin change
    st.apply_shield(100, [cm(100, ALICE, "r0")], [out_open(100, ALICE, "r0")])
    st.apply_blob({"op": "shielded_transfer", **_split_100()}, sender="relay", txid="setup")

def _split_100():
    """Build a signed private transfer splitting Alice's 100-coin note into 60 + 40 change notes."""
    nf = note_nullifier(ALICE["public_key"], "r0")
    public = {"root": st.shielded.root(), "nullifiers": [nf],
              "out_commitments": [cm(60, ALICE, "rb"), cm(40, ALICE, "rc")], "public_value": 0, "fee": 0}
    sh = transfer_sighash(public)
    ins = [{"value": 100, "pubkey": ALICE["public_key"], "rho": "r0", "pos": 0,
            "path": merkle_path(st.shielded.commitments, 0), "sig": sign(ALICE["private_key"], unhex(sh))}]
    return {"public": public, "proof": {"inputs": ins, "outputs": [out_open(60, ALICE, "rb"), out_open(40, ALICE, "rc")]}}

def t_redirect_rejected():
    """Prove a copied unshield blob with only withdraw_addr swapped fails the signature and spends nothing (H-4)."""
    victim = _victim_unshield_blob("ndoVictimAddress")
    # Attacker copies the victim's blob verbatim and swaps ONLY the destination address.
    attack = copy.deepcopy(victim)
    attack["public"]["withdraw_addr"] = "ndoAttackerAddress"
    res = st.apply_blob(attack, sender="relay", txid="attack")
    assert "skip" in res, f"redirected blob must be REJECTED, got: {res!r}"
    assert "authorisation" in res or "signature" in res, f"expected a signature failure, got: {res!r}"
    # nullifier must NOT have been consumed by the rejected attempt
    assert not st.shielded.has_nullifier(note_nullifier(ALICE["public_key"], "rc")), "rejected tx must not spend the note"

def t_legit_unshield_still_ok():
    """Prove the correctly-signed unshield is still accepted and records the victim's withdrawal proof."""
    victim = _victim_unshield_blob("ndoVictimAddress")
    res = st.apply_blob(victim, sender="relay", txid="legit")
    assert "unshield 40" in res, f"the correctly-signed unshield must be accepted, got: {res!r}"
    p = st.unshield_withdrawal_proof("1")
    assert p and p["addr"] == "ndoVictimAddress" and p["amount"] == 40, p

setup()
check("t_redirect_rejected (H-4: swapped withdraw_addr fails the signature)", t_redirect_rejected)
check("t_legit_unshield_still_ok", t_legit_unshield_still_ok)
print("\n" + ("ALL PASSED" if not fails else f"{fails} FAILED"))
sys.exit(1 if fails else 0)
