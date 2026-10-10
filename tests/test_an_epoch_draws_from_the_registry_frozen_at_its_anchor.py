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
check("the producer draw reads bonded_registry_for_epoch (inside derive_header)",
      "bonded_registry = bonded_registry_for_epoch(epoch)" in open(os.path.join(ROOT, "ops", "block_ops.py")).read())

# FORK WEIGHT IS NOT A DRAW INPUT, and the header is derived in ONE place. Construction once weighed a block from the
# frozen draw registry while verify_block used the live one; they differed by 2 shares after a bond landed past the
# anchor and every node refused block 135625 (2026-10-09). block_ops.derive_header is now the only derivation.
import re as _re
_bo = open(os.path.join(ROOT, "ops", "block_ops.py")).read()
_dh = _bo[_bo.index("def derive_header("):_bo.index("def get_block_candidate(")]
check("derive_header weighs from the live registry and draws from the frozen one",
      "block_fork_weight(get_bonded_registry(), block_number)" in _dh and "bonded_registry_for_epoch(epoch)" in _dh)
_outside = (_bo.replace(_dh, "") + cl)
check("nothing outside derive_header draws a producer or weighs a block",
      not _re.search(r"(?<!def )\bselect_producer_two_lane\(", _outside) and not _re.search(r"(?<!def )\bblock_fork_weight\(", _outside),
      _re.findall(r".{0,40}(?:select_producer_two_lane|block_fork_weight)\(.{0,30}", _outside))
check("production, rebuild and verification all call derive_header",
      "derive_header(latest_block, block_number)" in _bo and cl.count("derive_header(") >= 3)

# behaviour: with a bond after the anchor, the draw input and the weight input differ, and derive_header keeps them apart
B.get_open_registry = lambda e: {}
kv_ops.regsnap_put(E, live0)
kv_ops.account_set(VALS[5], "bonded", P.B_MIN * 7)            # lands after the anchor: live registry only
hdr = B.derive_header({"cumulative_weight": 0}, E * L + 3)
from ops.mining_ops import block_fork_weight as _bfw
check("derive_header's weight is the live registry's, not the snapshot's",
      hdr["block_weight"] == _bfw(get_bonded_registry(), E * L + 3) and hdr["block_weight"] != _bfw(live0, E * L + 3),
      (hdr["block_weight"], _bfw(live0, E * L + 3)))
check("derive_header's draw comes from the snapshot (a post-anchor bonder is never the creator)",
      hdr["creator"] in live0 and hdr["eligible_n"] == len(live0), hdr)

# FINALITY READS THE EPOCH'S OWN REGISTRY: a committee member who unbonds after the anchor must not retroactively
# un-justify a checkpoint it attested (the live-registry filter let two nodes refreshing at different moments disagree)
from ops.attestation_ops import checkpoint_justified
kv_ops.regsnap_put(E, live0)
B._duty_committee_cache[0] = None
_com = B.duty_committee_for_epoch(E)
_ck = "ef" * 32
from protocol import FFG_NUM, FFG_DEN
for _v in _com:
    kv_ops.attestation_put(E - 1, _v, "11" * 32)               # every member active in the inactivity window
_total = sum(_com.values())
_U = max(sorted(_com), key=lambda v: _com[v])                # the member who unbonds after the anchor: the most seats
# attesters for epoch E: _U plus the fewest others that clear 2/3 WITH it, so that WITHOUT it they do not
_others = sorted((v for v in _com if v != _U), key=lambda v: _com[v])
_att = [_U]
for _v in _others:
    if sum(_com[a] for a in _att) * FFG_DEN > _total * FFG_NUM:
        break
    _att.append(_v)
_decisive = (sum(_com[a] for a in _att) * FFG_DEN > _total * FFG_NUM
             and sum(_com[a] for a in _att if a != _U) * FFG_DEN <= _total * FFG_NUM)
for _v in _att:
    kv_ops.attestation_put(E, _v, _ck)
kv_ops.account_set(_U, "bonded", 0)                          # unbonded after the anchor (live registry only)
check("a committee member that unbonded after the anchor still counts toward its epoch's justification",
      _decisive and _U not in get_bonded_registry() and checkpoint_justified(E, _ck, get_bonded_registry()),
      (_decisive, _att, dict(_com)))

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
