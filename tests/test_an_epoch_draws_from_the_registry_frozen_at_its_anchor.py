"""An epoch's producer draw and duty committee read the bonded registry frozen at the epoch's anchor block
(protocol.REGISTRY_SNAPSHOT_HEIGHT, ops/block_ops.bonded_registry_for_epoch, kv_ops.regsnap_*).

  * below the gate bonded_registry_for_epoch(E) is the live registry (old rule);
  * from the gate it is regsnap:E — a bond after the anchor moves the live registry but not E's draw input, and the
    duty committee for E follows the snapshot;
  * a missing snapshot past the gate fails loud (never substitutes the live registry);
  * the stored bytes are canonical (insertion order does not matter) and put/del round-trips to canonical-absent;
  * the row enters the L1 state root, inside the root window by its epoch;
  * incorporate_block writes regsnap:(h/L + 1) at the first block of an epoch from the gate and rollback_one_block
    deletes exactly that row (source pins: both sides test the same height expression).

Run: python3 tests/test_an_epoch_draws_from_the_registry_frozen_at_its_anchor.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-regsnap-")          # never the live database (assign)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

import protocol as P                                                   # noqa: E402
import ops.block_ops as B                                              # noqa: E402
from ops import kv_ops, snapshot_ops                                   # noqa: E402
from ops.account_ops import get_bonded_registry                        # noqa: E402

FAILED = []
L = P.EPOCH_LENGTH
GATE = 500 * L


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


kv_ops.init_env()
P.REGISTRY_SNAPSHOT_HEIGHT = GATE
VALS = [f"val{i:02d}" + "q" * 45 for i in range(6)]
for i, a in enumerate(VALS[:4]):
    kv_ops.account_set(a, "bonded", P.B_MIN * (i + 1))

live0 = get_bonded_registry()
check("the fixture has a bonded registry", set(live0) == set(VALS[:4]), sorted(live0))

E_below = GATE // L                    # anchor (E-1)*L = GATE - L < GATE: old rule
check("below the gate the draw reads the live registry", B.bonded_registry_for_epoch(E_below) == live0)

E = GATE // L + 5                      # anchor (E-1)*L >= GATE
try:
    B.bonded_registry_for_epoch(E)
    check("a missing snapshot past the gate fails loud", False, "returned")
except RuntimeError as e:
    check("a missing snapshot past the gate fails loud", "missing" in str(e), e)

# the anchor block freezes the registry as it stands after that block
kv_ops.regsnap_put(E, get_bonded_registry())
kv_ops.account_set(VALS[4], "bonded", P.B_MIN * 9)          # a bond landing after the anchor
kv_ops.account_set(VALS[0], "bonded", 0)                     # and an unbond
check("a bond after the anchor moves the live registry", VALS[4] in get_bonded_registry())
snap = B.bonded_registry_for_epoch(E)
check("but not the epoch's draw input", set(snap) == set(VALS[:4]) and snap == live0, sorted(snap))

B.epoch_beacon = lambda e: "%064x" % (e * 7919 + 13)
B._duty_committee_cache[0] = None
committee = B.duty_committee_for_epoch(E)
check("the duty committee for the epoch is drawn from the snapshot",
      set(committee) <= set(VALS[:4]) and VALS[4] not in committee and committee, committee)

# canonical bytes
raw1 = bytes(kv_ops._read(lambda t: t.get(f"regsnap:{E}".encode(), db=kv_ops._dbs()["meta"])))
kv_ops.regsnap_put(E, dict(reversed(list(live0.items()))))
raw2 = bytes(kv_ops._read(lambda t: t.get(f"regsnap:{E}".encode(), db=kv_ops._dbs()["meta"])))
check("the stored bytes do not depend on insertion order", raw1 == raw2)

# state root: present while the row exists, gone (and the root back) after the delete
root_with = snapshot_ops.l1_state_root()
kv_ops.regsnap_del(E)
root_without = snapshot_ops.l1_state_root()
check("the snapshot row is part of the L1 state root", root_with != root_without)
kv_ops.regsnap_put(E, live0)
check("re-writing the same row restores the same root", snapshot_ops.l1_state_root() == root_with)
kv_ops.regsnap_del(E)
check("delete is canonical-absent", kv_ops.regsnap_get(E) is None and snapshot_ops.l1_state_root() == root_without)
check("the root window reads the row's epoch from its key",
      snapshot_ops._row_epoch("meta", b"regsnap:1234") == 1234 and b"regsnap:" in snapshot_ops.ROOT_WINDOWED_META_PREFIXES)

# incorporate / rollback wiring
cl = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
rb = open(os.path.join(ROOT, "rollback.py")).read()
check("incorporate_block writes regsnap:(h // L + 1) at an epoch's first block from the gate",
      "if _bn >= REGISTRY_SNAPSHOT_HEIGHT:\n                    kv_ops.regsnap_put(_bn // EPOCH_LENGTH + 1, get_bonded_registry())" in cl
      and cl.index("if _bn % EPOCH_LENGTH == 0:") < cl.index("kv_ops.regsnap_put("))
check("rollback_one_block deletes exactly that row under the same test",
      'if block["block_number"] >= REGISTRY_SNAPSHOT_HEIGHT:\n                kv_ops.regsnap_del(block["block_number"] // _EL + 1)' in rb
      and rb.index('if block["block_number"] % _EL == 0:') < rb.index("kv_ops.regsnap_del("))
check("production and verification draw through bonded_registry_for_epoch",
      cl.count("bonded_registry_for_epoch(") >= 2 and "bonded_registry = bonded_registry_for_epoch(epoch)" in
      open(os.path.join(ROOT, "ops", "block_ops.py")).read())

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
