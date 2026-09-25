"""One slash per offence per block (SLASH_DEDUP_HEIGHT, review 2026-09-25, reproduced).

The in-block uniqueness key for a `slash` read the block-authorship proof's fields; a double-VOTE (attestation) proof
has none, so the key fell back to the txid and two reports of ONE offence both entered a block: the offender's bond
burned twice, or (bond == one penalty) a raise inside incorporate_block that stalls production. From the gate a slash
is keyed by the resolved (offender, dedup height), so the second report of the same offence collides and is dropped.

Run: python3 tests/test_slash_dedup.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-slash-dedup-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.join(os.environ["HOME"], "nado", "index"), exist_ok=True)
from ops import kv_ops
kv_ops.init_env(); kv_ops.totals_seed()
import protocol as P
from signatures import generate_keydict, sign, unhex
from ops import transaction_ops as T
from protocol import CHAIN_ID, B_MIN, EPOCH_LENGTH

fails = []
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails.append(name)

att, rep = generate_keydict(), generate_keydict()
with kv_ops.write_txn():
    kv_ops.account_set_field(att["address"], "bonded", 2 * B_MIN)
    kv_ops.account_set_field(att["address"], "public_key", att["public_key"])
    kv_ops.account_set_field(rep["address"], "balance", 10**10)


def attest(epoch, h):
    tx = {"sender": att["address"], "recipient": "attest", "amount": 0, "timestamp": 1,
          "data": {"target_epoch": epoch, "target_hash": h}, "nonce": "n" + h[:4], "public_key": att["public_key"],
          "max_block": epoch * EPOCH_LENGTH, "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = T.create_txid(tx); tx["signature"] = sign(private_key=att["private_key"], message=unhex(tx["txid"]))
    return tx


def slash(nonce, proof, max_block):
    tx = {"sender": rep["address"], "recipient": "slash", "amount": 0, "timestamp": 1, "data": proof, "nonce": nonce,
          "public_key": rep["public_key"], "max_block": max_block, "chain_id": CHAIN_ID, "fee": 0}
    tx["txid"] = T.create_txid(tx); tx["signature"] = sign(private_key=rep["private_key"], message=unhex(tx["txid"]))
    return tx


proof = {"attest_a": attest(5, "aa" * 32), "attest_b": attest(5, "bb" * 32)}
G = int(P.SLASH_DEDUP_HEIGHT)
old = [T.reserved_uniqueness_keys(slash(n, proof, G - 1)) for n in ("n1", "n2")]
new = [T.reserved_uniqueness_keys(slash(n, proof, G)) for n in ("n1", "n2")]
check("THE FINDING: below the gate two reports of one double-vote get distinct keys (replay unchanged)",
      old[0] != old[1])
check("from the gate they share one key, so the second is dropped from the block", new[0] == new[1])
check("the key names the offender", new[0][0][1] == att["address"])
other = {"attest_a": attest(6, "cc" * 32), "attest_b": attest(6, "dd" * 32)}
check("a DIFFERENT offence still gets its own key", T.reserved_uniqueness_keys(slash("n3", other, G)) != new[0])
check("the ledger pins the gate", "SLASH_DEDUP_HEIGHT = 233300 if CHAIN_GENERATION == 25 else 1" in
      open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocol.py")).read())
print("ALL PASS" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
