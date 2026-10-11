"""Rollback journals are kept down to HARD finality, the floor rollback actually stops at.

Rollback crosses the depth floor (finalized_height) and refuses only below hard_finality (rollback.py, two-floor
model). The epoch-boundary prune in core_loop used finalized_height, so a legal reorg between the floors popped an
idle-GC revert record that was already gone, restored nothing, and left a different state root (review 2026-10-11).

  * the prune site passes the hard floor to every journal prune, never finalized_height;
  * the idle-GC journal keeps a record between the floors and drops the one below the hard floor;
  * undo_prune empties a store that lies wholly below the floor without raising (its cursor ran off the end);
  * a failing undo-shadow diagnostic never aborts a rollback.

Run: python3 tests/test_rollback_journals_are_kept_down_to_hard_finality.py
"""
import os
import re
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-journal-floor-")    # never the live database (assign)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from ops import kv_ops                                                 # noqa: E402
from ops.gc_ops import prune_local_revert_records                     # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


# --- the prune site --------------------------------------------------------------------------------------------
src = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
for call in ("prune_local_revert_records", "kv_ops.execsum_revert_prune", "kv_ops.undo_prune"):
    args = re.findall(re.escape(call) + r"\(([^)]*)\)", src)
    check(f"{call} is called with the hard floor", args and all(a.strip() == "new_hard" for a in args), args)

# --- the idle-GC journal between the floors --------------------------------------------------------------------
kv_ops.init_env()
HARD, FINAL = 1000, 1086                                               # the live gap measured 2026-10-11 was 86
rec = {"accounts": [["aa" * 25, {"balance": 5}]], "rows": [], "bond_since": [], "wm_rows": None, "wm_accts": None}
for h in (940, 1040, 1100):
    kv_ops.gc_revert_put(h, rec)
prune_local_revert_records(HARD)
check("a record between the floors survives the prune", kv_ops.gc_revert_pop(1040) is not None)
check("a record above both floors survives", kv_ops.gc_revert_pop(1100) is not None)
check("a record below the hard floor is dropped", kv_ops.gc_revert_pop(940) is None)

# --- undo_prune on a store wholly below the floor -------------------------------------------------------------
def put_undo(h):
    kv_ops._write(lambda t: (t._t if hasattr(t, "_t") else t).put(kv_ops.be8(h), kv_ops._pack([]),
                                                                   db=kv_ops._dbs()["undo"]))
for h in (10, 20, 30):
    put_undo(h)
try:
    n = kv_ops.undo_prune(500)
    err = None
except Exception as e:                                                 # noqa: BLE001
    n, err = None, e
check("undo_prune empties a store wholly below the floor without raising", err is None and n == 3, (n, err))
for h in (10, 600, 700):
    put_undo(h)
n = kv_ops.undo_prune(500)
left = kv_ops._read(lambda t: [kv_ops.un_be8(bytes(k)) for k, _ in (t._t if hasattr(t, "_t") else t)
                               .cursor(db=kv_ops._dbs()["undo"])])
check("undo_prune keeps every record at or above the floor", n == 1 and left == [600, 700], (n, left))

# --- the shadow diagnostic cannot abort a rollback ------------------------------------------------------------
rb = open(os.path.join(ROOT, "rollback.py")).read()
i = rb.index("kv_ops.undo_shadow_verify(")
check("rollback guards the undo-shadow diagnostic", "try:" in rb[max(0, i - 120):i] and "except Exception" in rb[i:i + 200])

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED")
sys.exit(1 if FAILED else 0)
