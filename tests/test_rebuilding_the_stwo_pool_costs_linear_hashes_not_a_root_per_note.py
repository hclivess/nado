"""Loading the Stwo pool from a snapshot costs O(1) tree hashes per note, not a full root per note
(execnode/shielded_stwo.py StwoShieldedPool.__init__/from_dict, reached by ExecState._restore and ExecState.clone).

REVIEW 2026-10-11 (integration, reproduced; FIXED: StwoShieldedPool.__init__ walks the frontier once). StwoShieldedPool rebuilds its tree by calling append() for
every stored commitment, and append() computes root() — DEPTH (48) BLAKE2s node hashes — to remember an anchor, so a
pool of n notes costs ~49 n node hashes to load. Measured here: ~850 us per note in CPython, 17 s for 20,000 notes.
That load runs on every ExecState._restore, and clone() is a _restore: the exec node clones its states for the
provisional view on EVERY poll (execnode.py _refresh_provisional), and on rewinds and boot. 20,000 notes cost an
attacker ~20,000 x (1 + MIN_TX_FEE) raw ~ 0.002 NADO. The per-block cost then scales with the pool's age — the
"per-block cost must not scale with chain age" class. The wide pool fixed exactly this (shielded_wide._rebuilt:
"REBUILT THROUGH THE FRONTIER, ONCE ... O(n) + ANCHOR_WINDOW*depth"); the Stwo pool did not inherit it.

Pins: from_dict of n notes, and ExecState.clone of a state holding them, hash at most 2n + 2*ANCHOR_WINDOW*DEPTH tree
nodes — and the rebuilt anchor window is the live one (so a fix cannot change which roots a spend may name).

Run: python3 tests/test_rebuilding_the_stwo_pool_costs_linear_hashes_not_a_root_per_note.py
"""
import os, sys, tempfile, hashlib
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-rebuild-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
H = os.environ["HOME"]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode import shielded_stwo as SP
from execnode.state import ExecState

import _harness
_report = _harness.Report()
check = _report.check


N = 1000
cms = [hashlib.blake2s(b"note%d" % i).hexdigest() for i in range(N)]
live = SP.StwoShieldedPool()
for i, c in enumerate(cms):
    live.append(c, 5000 + i // 3)              # block marks too: 3 notes per block

count = [0]
_orig = SP.node


def _counting(a, b):
    count[0] += 1
    return _orig(a, b)


SP.node = _counting
BOUND = 2 * N + 2 * (SP.ANCHOR_WINDOW + len(live.marks)) * SP.DEPTH
count[0] = 0
p = SP.StwoShieldedPool.from_dict(live.to_dict())
n_load = count[0]
SP.node = _orig
check("the rebuilt pool is the live pool: root, and the anchor window a spend may name",
      p.root() == live.root() and p.anchors == live.anchors and p.marks == live.marks
      and all(p.knows_root(live._mark_roots[c], 5400) for _, c in live.marks))
SP.node = _counting
check(f"loading {N} notes hashes at most {BOUND} tree nodes (linear), not a 48-hash root per note",
      n_load <= BOUND, f"{n_load} node hashes ({n_load / N:.1f} per note)")

st = ExecState(os.path.join(tempfile.mkdtemp(dir=H), "s.json"))
st.stwo_pool = p
st._touch()
count[0] = 0
c = st.clone()
n_clone = count[0]
SP.node = _orig
check(f"ExecState.clone (every provisional poll) of a {N}-note pool is linear too",
      n_clone <= BOUND, f"{n_clone} node hashes ({n_clone / N:.1f} per note)")
p.append(hashlib.blake2s(b"x").hexdigest(), 6000)
check("a duplicate check is a set lookup, not a list scan", p.has_commitment(cms[0]) and not p.has_commitment("00" * 32))
print("ALL PASS — the Stwo pool loads in linear time" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
