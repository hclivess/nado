"""A tpm_enrol is judged by the endorsement roots the kernel verified it against, from EK_ENROL_ROOTS_AT_HEIGHT
(ops/transaction_ops.validate_transaction, protocol.EK_ENROL_ROOTS_AT_HEIGHT).

The kernel verified the chain against ek_roots_at(height), Intel's V2 root included, and the next line re-checked the
root against the BASE set only: an Intel chip passed the kernel and was refused anyway, while the wallet's pre-flight
told its owner the chip was fine. Pins: a V2-root verdict is refused below the gate (replay unchanged) and gets past the
root check from it; a base-root verdict is accepted on both sides; an unpinned root is refused on both.

No real Intel endorsement chain can be minted for a test, so only the kernel's verdict is stubbed — the transaction
around it is real and signed, and the test reads which assertion validation stops at.
Run: python3 tests/test_ek_enrol_roots_at.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-ek-roots-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.join(os.environ["HOME"], "nado", "index"), exist_ok=True)

from ops import kv_ops
kv_ops.init_env(); kv_ops.totals_seed()
import protocol as P
from signatures import generate_keydict, sign, unhex
from ops import transaction_ops as T, attest_native

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


GATE = int(P.EK_ENROL_ROOTS_AT_HEIGHT)
ROOT_MSG = "does not chain to a pinned silicon-vendor root"
V2 = sorted(P.DEVICE_ATTEST_EK_ROOTS_V2)[0]
BASE = sorted(P.DEVICE_ATTEST_EK_ROOTS)[0]
K = generate_keydict()


def enrol_tx(h):
    tx = {"sender": K["address"], "recipient": "tpm_enrol", "amount": 0, "fee": 0, "timestamp": 1,
          "data": {"ek": ["30" * 40], "pub": "00" * 40}, "nonce": f"n{h}", "public_key": K["public_key"],
          "max_block": h, "chain_id": P.CHAIN_ID}
    tx["txid"] = T.create_txid(tx)
    tx["signature"] = sign(private_key=K["private_key"], message=unhex(tx["txid"]))
    return tx


T._anchor_time = lambda tx, h: 1_790_000_000   # the anchor block's time; this temp chain holds no blocks


def stop_reason(root, h):
    attest_native.verify_ek = lambda chain, now, roots=None, height=None: {
        "ok": True, "root_sha256": root, "identity": "ab" * 32, "ek_identity": "ab" * 32}
    try:
        T.validate_transaction(enrol_tx(h), logging.getLogger("t"), block_height=h)
        return "accepted"
    except Exception as e:                       # later checks fail on the stub's fake key: only WHICH one matters
        return f"{type(e).__name__}: {e}"


if GATE <= 1:
    print("SKIP  EK_ENROL_ROOTS_AT_HEIGHT is 1 on this generation: there is no 'below the gate' to pin")
else:
    below, at = stop_reason(V2, GATE - 1), stop_reason(V2, GATE)
    check("a V2-root chip is refused by the root check below the gate (replay unchanged)", ROOT_MSG in below, below)
    check("and gets past the root check from the gate", ROOT_MSG not in at, at)
    print("      (from the gate it stops at the next step instead:", at[:110] + ")")
    check("a base-root chip passes the root check below the gate", ROOT_MSG not in stop_reason(BASE, GATE - 1))
    check("and from it", ROOT_MSG not in stop_reason(BASE, GATE))
    check("an unpinned root is refused from the gate", ROOT_MSG in stop_reason("00" * 32, GATE))

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
