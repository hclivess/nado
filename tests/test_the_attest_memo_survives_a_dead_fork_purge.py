"""The attestation memo survives a dead-fork purge (ops/kv_ops.attest_memo_*, ops/data_ops.purge_chain_data).

attest_memo is THIS node's record of which checkpoint it already signed per epoch: the interlock that stops it signing a
second, different attestation for the same epoch, a valid equivocation proof against itself. wipe_non_carried_dbs keeps
it on a re-anchor for exactly that reason. But the memo lived only in the LMDB env under index/, and the dead-fork
escape (purge_chain_data(dead_fork=True)) deletes index/ wholesale. A node that purged and resynced inside the same
epoch had lost the interlock (2026-10-27 incident survey; cometbft/cometbft#6031 is the same class).

Pins, on the real functions in a throwaway home: a memo written before the purge is still read after it, with the
process's env cache dropped as on the restart that follows a purge; the sidecar lives under private/, which no purge
touches; a sidecar from another CHAIN_ID is ignored (a reroll restarts epochs at 0); prune trims the sidecar too; and
the sidecar is written before the LMDB copy.

Run: python3 tests/test_the_attest_memo_survives_a_dead_fork_purge.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-attest-memo-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import inspect
import json
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import kv_ops
from ops.data_ops import get_home, purge_chain_data
import protocol as P

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def make_folders():
    """The two directories a node home needs for this: the state env's and private/ (genesis.make_folders makes more)."""
    for d in (os.path.join(get_home(), "index", "state"), os.path.join(get_home(), "private")):
        os.makedirs(d, exist_ok=True)


def restart():
    """What the process exit after a purge does to this module: no cached env survives."""
    with kv_ops._envs_lock:
        for env in list(kv_ops._envs.values()):
            try:
                env.close()
            except Exception:
                pass
        kv_ops._envs.clear()


make_folders()
home = get_home()
kv_ops.attest_memo_put(41, "aa" * 32)
kv_ops.attest_memo_put(42, "bb" * 32)
check("setup: the memo reads back before any purge", kv_ops.attest_memo_get(42) == "bb" * 32, kv_ops.attest_memo_get(42))
side = os.path.join(home, "private", "attest_memo.json")
check("the memo is mirrored into private/attest_memo.json", os.path.exists(side)
      and json.load(open(side)).get("chain_id") == P.CHAIN_ID, side)

restart()
purge_chain_data(dead_fork=True)
check("setup: the dead-fork purge deleted index/ (where the LMDB memo lived)", not os.path.exists(os.path.join(home, "index")))
make_folders()
check("after a dead-fork purge and restart the memo is still read (no second, different attestation)",
      kv_ops.attest_memo_get(42) == "bb" * 32 and kv_ops.attest_memo_get(41) == "aa" * 32,
      (kv_ops.attest_memo_get(41), kv_ops.attest_memo_get(42)))
check("...and an epoch never attested still reads as none", kv_ops.attest_memo_get(43) is None)

kv_ops.attest_memo_prune(42)
check("prune trims the sidecar as well as the LMDB copy", kv_ops.attest_memo_get(41) is None
      and kv_ops.attest_memo_get(42) == "bb" * 32, json.load(open(side)))

json.dump({"chain_id": "some-other-chain", "memos": {"7": "cc" * 32}}, open(side, "w"))
restart()
purge_chain_data(dead_fork=True)
make_folders()
check("a sidecar written under another CHAIN_ID is ignored (a reroll restarts epochs at 0)", kv_ops.attest_memo_get(7) is None)

src = inspect.getsource(kv_ops.attest_memo_put)
check("the sidecar is written BEFORE the LMDB copy (the copy a purge cannot take comes first)",
      src.index("_attest_memo_store") < src.index("txn.put"), src)

print("\nALL PASS — the attestation memo survives a dead-fork purge" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
