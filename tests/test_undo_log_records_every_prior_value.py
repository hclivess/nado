"""The generic undo log records the prior bytes of every consensus key a block writes (ops/kv_ops UNDO LOG).

  * a block's first write to each key records what it held before (plain value, full dup list, or absent);
  * a later write to the same key in the same block does not overwrite that record (first write wins);
  * node-local DBs (the *_revert journals, the undo DB itself) are never recorded;
  * a revert that restores every key verifies with zero mismatches; one that misses a key is caught;
  * an aborted block leaves no record (the record commits with the block or not at all);
  * pruning drops records below the floor.

Run: python3 tests/test_undo_log_records_every_prior_value.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-undo-log-")         # never the live database (assign)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from ops import kv_ops                                                 # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


kv_ops.init_env()
D = kv_ops._dbs()
A, B, C = "aa" * 25, "bb" * 25, "cc" * 25
kv_ops.account_set(A, "balance", 100)                    # exists before the block
kv_ops.reveal_put(7, "secret-old")                       # a DUPSORT key with one value before the block


def raw(name, key):
    return kv_ops._read(lambda t: kv_ops._undo_prior(t._t if hasattr(t, "_t") else t, name, key))


def records():
    return kv_ops._read(lambda t: [kv_ops.un_be8(bytes(k)) for k, _v in t.cursor(db=D["undo"])])


before = {("accounts", A.encode()): raw("accounts", A.encode()), ("accounts", B.encode()): raw("accounts", B.encode()),
          ("reveals", kv_ops.be8(7)): raw("reveals", kv_ops.be8(7))}

# --- a "block": modify A twice, create B, add a dup value, write a local journal --------------------------------------
H = 500
with kv_ops.write_txn():
    kv_ops.undo_begin(H)
    kv_ops.account_set(A, "balance", 150)
    kv_ops.account_set(A, "balance", 175)                # second write: the record keeps the FIRST prior
    kv_ops.account_set(B, "balance", 5)                  # created
    kv_ops.reveal_put(7, "secret-new")                   # dup list grows
    kv_ops.gc_revert_put(H, {"x": 1})                    # node-local journal: must not be recorded
rec = kv_ops._read(lambda t: kv_ops._unpack(bytes(t.get(kv_ops.be8(H), db=D["undo"]))))
keys = {(n, bytes(k)) for n, k, _p in rec}
check("the block's record exists after commit", H in records())
check("every consensus key the block wrote is recorded", set(before) <= keys, sorted(keys))
check("node-local DBs are never recorded", not any(n in kv_ops._LOCAL_DBS for n, _k in keys), sorted(keys))
_prior = {(n, bytes(k)): p for n, k, p in rec}
check("first write wins: A's record is the value before the block, not after its first write",
      _prior[("accounts", A.encode())] == before[("accounts", A.encode())])
check("a created key records 'absent'", _prior[("accounts", B.encode())] is None)
check("a DUPSORT key records its full prior dup list",
      [bytes(x) for x in _prior[("reveals", kv_ops.be8(7))]] == before[("reveals", kv_ops.be8(7))])

# --- a revert that misses a key is caught ------------------------------------------------------------------------------
with kv_ops.write_txn():
    kv_ops.account_set(A, "balance", 100)                # restores A only
    bad = kv_ops.undo_shadow_verify(H)
check("an incomplete revert is reported key by key", {(n) for n, _k, _w, _g in bad} == {"accounts", "reveals"}
      and len(bad) == 2, bad)
check("the mismatch is counted", kv_ops.UNDO_SHADOW["mismatch"] >= 2)

# --- a complete revert verifies clean ----------------------------------------------------------------------------------
H2 = 501
with kv_ops.write_txn():
    kv_ops.undo_begin(H2)
    kv_ops.account_set(C, "balance", 9)
    kv_ops.reveal_put(8, "s8")
m0 = kv_ops.UNDO_SHADOW["mismatch"]
with kv_ops.write_txn():
    kv_ops.delete_account(C) if hasattr(kv_ops, "delete_account") else kv_ops._write(lambda t: t.delete(C.encode(), db=D["accounts"]))
    kv_ops.reveal_del(8, "s8")
    ok = kv_ops.undo_shadow_verify(H2)
check("a revert that restores every key verifies with zero mismatches", ok == [] and kv_ops.UNDO_SHADOW["mismatch"] == m0, ok)
check("verification pops the record", H2 not in records())

# --- an aborted block leaves no record ---------------------------------------------------------------------------------
H3 = 502
try:
    with kv_ops.write_txn():
        kv_ops.undo_begin(H3)
        kv_ops.account_set(A, "balance", 1)
        raise RuntimeError("block voided")
except RuntimeError:
    pass
check("an aborted block leaves no record and no recorder", H3 not in records() and getattr(kv_ops._local, "undo", None) is None)

# --- pruning ---------------------------------------------------------------------------------------------------------
for h in (600, 601, 700):
    with kv_ops.write_txn():
        kv_ops.undo_begin(h)
        kv_ops.account_set(A, "balance", h)
kv_ops.undo_prune(650)
check("pruning drops records below the floor and keeps the rest", 600 not in records() and 700 in records(), records())

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
