"""Rolling back a block restores the exec summary it retention-pruned EXACTLY — every field, not a re-derivation.

incorporate_block puts block h's summary and prunes the one at h-RETENTION, journaling it (execsum_revert_put).
rollback_one_block put the journaled summary back through exec_summary_put(inert, calls), which drops the
records-half fields (rd, rec, dc — the dividend carry). kv_ops.exec_summary_restore writes the journaled document
back byte for byte; this pins it on the real tables.

Run: python3 tests/test_rollback_restores_the_whole_exec_summary.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-execsum-restore-")  # never the live database (assign)
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
H_OLD, H_NEW = 1000, 1000 + 4000
with kv_ops.write_txn():
    kv_ops.exec_summary_put(H_OLD, False, {"default": [11, 22]}, records=[(3, ["a", "b"], -5)], derivable=True,
                            div_carry=77)
full = kv_ops.exec_summary_get(H_OLD)
check("the fixture summary carries the records-half fields", {"rd", "rec", "dc"} <= set(full), full)

# apply-side: journal then prune (as incorporate_block does)
with kv_ops.write_txn():
    kv_ops.execsum_revert_put(H_NEW, H_OLD, kv_ops.exec_summary_get(H_OLD))
    kv_ops.exec_summary_del(H_OLD)
check("the pruned summary is gone", kv_ops.exec_summary_get(H_OLD) is None)

# rollback-side, through the real rollback code path's restore
src = open(os.path.join(ROOT, "rollback.py")).read()
check("rollback_one_block restores through exec_summary_restore", "kv_ops.exec_summary_restore(_ph, _doc)" in src
      and "kv_ops.exec_summary_put(_ph, bool(_doc.get(" not in src)
with kv_ops.write_txn():
    ph, doc = kv_ops.execsum_revert_pop(H_NEW)
    kv_ops.exec_summary_restore(ph, doc)
check("the restored summary equals the pruned one field for field", kv_ops.exec_summary_get(H_OLD) == full,
      (kv_ops.exec_summary_get(H_OLD), full))

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
