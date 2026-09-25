"""Rolling back a block restores every enrolment it touched exactly (ops/account_ops.apply_tpm_enrol_tx revert,
ops/kv_ops.tpm_enrol_revert_put).

Two challengers answering in the same block is the ordinary case. The rollback journal was one slot per
(height, enrolment) and the second message overwrote the first's, so a rollback left the first blob in place, and
re-applying the very same block then raised "this challenger already challenged this enrolment": a node that took an
ordinary one-block reorg could not re-take its own block (review 2026-09-25, reproduced). Pins: after apply + revert
the record is byte-identical to before the block and the block re-applies; and nothing else touches a row in the block
that created it, so the created-row journal is only ever popped by the tpm_enrol that made it.

Run: python3 tests/test_tpm_enrol_rollback_inverse.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-enrol-revert-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.join(os.environ["HOME"], "nado", "index"), exist_ok=True)

from ops import kv_ops, tpm_enrol as te
from ops.account_ops import apply_tpm_enrol_tx

kv_ops.init_env()
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


A, B, C = "a" * 46, "b" * 46, "c" * 46
H = 101


def challenge(sender, eid):
    return {"recipient": "tpm_challenge", "sender": sender, "data": {"id": eid, "blob": "aa", "enc": "bb"}}


def block(eid, txs, revert=False):
    with kv_ops.write_txn():
        for tx in (reversed(txs) if revert else txs):     # rollback_one_block reverts last-to-first
            apply_tpm_enrol_tx(tx, H, revert=revert)


# 1. two challengers in one block, on an enrolment that already existed
eid = "0123456789abcdef0123456789abcdef"
before = te.new_record("e" * 64, b"\x30\x00", "000b" + "11" * 32, b"\x00\x01", "o" * 46, 100, [A, B, C])
with kv_ops.write_txn():
    kv_ops.tpm_enrol_set(eid, before)
txs = [challenge(A, eid), challenge(B, eid)]
block(eid, txs)
check("both challenges apply in one block", len(kv_ops.tpm_enrol_get(eid)["blobs"]) == 2)
block(eid, txs, revert=True)
check("rollback restores the record exactly as it stood before the block", kv_ops.tpm_enrol_get(eid) == before,
      kv_ops.tpm_enrol_get(eid))
try:
    block(eid, txs)
    check("the same block re-applies after the rollback", len(kv_ops.tpm_enrol_get(eid)["blobs"]) == 2)
except AssertionError as e:
    check("the same block re-applies after the rollback", False, e)

# 2. nothing else can touch a row in the block that CREATED it: a challenge must land later than the enrolment, so a
#    created row's journal (None) is only ever popped by its own tpm_enrol, which drops the row and releases the chip.
eid2 = "fedcba9876543210fedcba9876543210"
with kv_ops.write_txn():
    kv_ops.tpm_enrol_set(eid2, te.new_record("f" * 64, b"\x30\x00", "000b" + "22" * 32, b"\x00\x02", "o" * 46, H,
                                              [A, B, C]))
try:
    with kv_ops.write_txn():
        apply_tpm_enrol_tx(challenge(A, eid2), H)
    check("a challenge in the enrolment's own block is refused", False)
except AssertionError:
    check("a challenge in the enrolment's own block is refused", True)

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
