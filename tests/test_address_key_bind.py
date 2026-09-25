"""An address is bound to the key it already published, from ADDRESS_KEY_BIND_HEIGHT (review 2026-09-25, reproduced).

An address is the first 42 hex of the ML-DSA public key: the first 21 bytes of rho, the public matrix seed. rho is
something a key builder CHOOSES (FIPS 204 verification never checks it came from a seed), so a key built on a victim's
rho prefix derives the victim's address and signs validly. Knowing an address was enough to spend from it, to sign
blocks as it, and to forge double-sign evidence that burns its bond.

From the gate every check that ties a key to an address also requires the key to EQUAL the one the account already
recorded (PUBKEY-ONCE: its first sent transaction). This file builds the forged key exactly as an attacker would and
shows each path refused at the gate and accepted below it (replay unchanged), with honest use unaffected. It also pins
the limitation: an address that never sent has no recorded key and is NOT protected by this rule.

Run: python3 tests/test_address_key_bind.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-addr-bind-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys, secrets, logging, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.makedirs(os.path.join(os.environ["HOME"], "nado", "index"), exist_ok=True)

from ops import kv_ops
kv_ops.init_env(); kv_ops.totals_seed()
import protocol as P
import signatures
from signatures import generate_keydict, unhex
from ops.address_ops import make_address, key_bound
from ops import transaction_ops as T, auth_ops as A
from dilithium_py.ml_dsa import ML_DSA_44 as M

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

GATE = 1   # the rule holds from block 1 (gen 25's ADDRESS_KEY_BIND_HEIGHT, deleted after the betanet-8 reroll); height 0 is below it
log = logging.getLogger("t")


def forge_key_for(address):
    """FIPS 204 KeyGen with a CHOSEN rho whose first 21 bytes are the address body — what an attacker runs."""
    rho = bytes.fromhex(address[:42]) + secrets.token_bytes(11)
    rb = secrets.token_bytes(128)
    rho_prime, K = rb[32:96], rb[96:]
    A_hat = M._expand_matrix_from_seed(rho)
    s1, s2 = M._expand_vector_from_seed(rho_prime)
    t = (A_hat @ s1.to_ntt()).from_ntt() + s2
    t1, t0 = t.power_2_round(M.d)
    pk = M._pack_pk(rho, t1)
    sk = M._pack_sk(rho, K, M._h(pk, 64), s1, s2, t0)
    return pk.hex(), sk


def _sign(sk, msg):
    with signatures._CRYPTO_LOCK:
        return signatures._BACKEND.sign_internal(sk, msg, secrets.token_bytes(32)).hex()


VICTIM = generate_keydict()
NEVER_SENT = generate_keydict()
with kv_ops.write_txn():
    kv_ops.account_set_field(VICTIM["address"], "balance", 5 * 10**12)
    kv_ops.account_set_field(VICTIM["address"], "public_key", VICTIM["public_key"])   # it has sent before
    kv_ops.account_set_field(NEVER_SENT["address"], "balance", 10**12)                # funded, never sent
FORGED_PK, FORGED_SK = forge_key_for(VICTIM["address"])


def _tx(pk, sk, sender):
    tx = {"sender": sender, "recipient": generate_keydict()["address"], "amount": 1000, "timestamp": 1, "data": "",
          "nonce": secrets.token_hex(4), "public_key": pk, "max_block": GATE + 10, "chain_id": P.CHAIN_ID,
          "fee": 1000}
    tx["txid"] = T.create_txid(tx)
    if sk is not None:
        tx["signature"] = _sign(sk, unhex(tx["txid"]))
    return tx


def _raises(fn):
    try:
        fn()
    except AssertionError:
        return True
    return False


def t_the_forged_key_really_derives_the_victims_address():
    assert FORGED_PK != VICTIM["public_key"] and make_address(FORGED_PK) == VICTIM["address"]
    assert signatures.verify(_sign(FORGED_SK, b"x" * 32), FORGED_PK, b"x" * 32), "and it signs validly"


def t_a_forged_spend_is_refused_from_the_gate_and_accepted_below_it():
    tx = _tx(FORGED_PK, FORGED_SK, VICTIM["address"])
    assert T.validate_origin(tx, GATE - 1), "THE FINDING: below the gate the forged key is accepted (replay unchanged)"
    assert _raises(lambda: T.validate_origin(tx, GATE)), "from the gate a forged key must be refused"


def t_the_owner_still_spends_with_or_without_carrying_the_key():
    # the wallet's own signing path (the key dict holds the 32-byte seed; signatures.sign re-derives the key)
    tx = _tx(VICTIM["public_key"], None, VICTIM["address"])
    tx["signature"] = signatures.sign(VICTIM["private_key"], unhex(tx["txid"]))
    assert T.validate_origin(tx, GATE)
    tx2 = {k: v for k, v in tx.items() if k not in ("public_key", "txid", "signature")}
    tx2["txid"] = T.create_txid(tx2)
    tx2["signature"] = signatures.sign(VICTIM["private_key"], unhex(tx2["txid"]))
    assert T.validate_origin(tx2, GATE), "PUBKEY-ONCE: omitting the key still resolves the recorded one"


def t_block_signatures_and_logins_need_the_recorded_key():
    assert not A.key_authorized(FORGED_PK, VICTIM["address"], height=GATE), "forged block signer"
    assert A.key_authorized(VICTIM["public_key"], VICTIM["address"], height=GATE)
    assert A.key_authorized(FORGED_PK, VICTIM["address"], height=GATE - 1), "below the gate: unchanged"


def t_evidence_is_judged_at_the_including_block_not_the_offence_height():
    old_offence = 10
    assert not A.key_valid_at(FORGED_PK, VICTIM["address"], old_offence, judge_height=GATE), \
        "forged evidence naming a pre-gate offence must still be refused when judged at the gate"
    assert A.key_valid_at(VICTIM["public_key"], VICTIM["address"], old_offence, judge_height=GATE)
    assert not A.key_valid_at(FORGED_PK, VICTIM["address"], old_offence), "an off-chain caller gets the rule"
    assert A.key_valid_at(FORGED_PK, VICTIM["address"], old_offence, judge_height=GATE - 1), "replay unchanged"


def t_limitation_an_address_that_never_sent_is_not_protected_by_this_rule():
    """Recorded, not fixed: with no key on chain there is nothing to compare, so whoever sends first wins. Only a
    hash-based address (a reroll) closes it. If this assertion ever flips, update the protocol comment and the doc."""
    pk, sk = forge_key_for(NEVER_SENT["address"])
    assert key_bound(NEVER_SENT["address"], pk, GATE)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
