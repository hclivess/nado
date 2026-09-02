"""DEAD-FORK PURGE: the on-disk circuit breaker and the narrowed purge scope (ops/data_ops.py, 2026-09-02).

THE INCIDENT. A peer-loop crash left memserver.peers empty; every production gate read "solo node, mint
normally", the node forked from block 7, the (correct) dead-fork verdict purged it, the resync re-forked —
FOURTEEN purges in twelve hours on the public bootstrap node, each wiping peers.dat and the exec DA store
too. Pinned here: purge_storm() refuses a third purge in 24 h from a log that survives purges (private/),
and a dead-fork purge keeps the peer table and the DA store while still dropping the chain.
Run: python3 tests/test_purge_breaker.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_purge_")
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


from ops import data_ops as D
from ops.data_ops import get_home

home = get_home()
os.makedirs(f"{home}/private", exist_ok=True)
NOW = 1_800_000_000
check("no history -> no storm", D.purge_storm(NOW) is False)
D.record_purge(NOW - 3600); D.record_purge(NOW - 1800)
check("two purges inside 24 h -> the third is a storm", D.purge_storm(NOW) is True)
check("...and the log lives under private/, which every purge keeps",
      os.path.isfile(f"{home}/private/{D.PURGE_LOG}") and len(json.load(open(f"{home}/private/{D.PURGE_LOG}"))) == 2)
check("purges older than the window do not count", D.purge_storm(NOW + 86400 + 10) is False)
check("the pure form takes an explicit history", D.purge_storm(NOW, history=[NOW - 10]) is False
      and D.purge_storm(NOW, history=[NOW - 10, NOW - 20]) is True)

# ---- purge scope
for d in ("blocks", "index", "snapshots", "peers", "exec_da"):
    os.makedirs(f"{home}/{d}", exist_ok=True); open(f"{home}/{d}/x", "w").write("x")
for f in ("peers.dat", "exec_state.json", "exec_state.json~ckpt~default~0.json", "version"):
    open(f"{home}/{f}", "w").write("x")
D.purge_chain_data(dead_fork=True)
gone = [d for d in ("blocks", "index", "snapshots") if os.path.exists(f"{home}/{d}")]
gone_f = [f for f in ("exec_state.json", "exec_state.json~ckpt~default~0.json", "version") if os.path.exists(f"{home}/{f}")]
check("a dead-fork purge drops the chain (blocks/index/snapshots, exec state + rungs, version)", not gone and not gone_f, (gone, gone_f))
check("...but KEEPS the learned peer table", os.path.isfile(f"{home}/peers.dat") and os.path.isdir(f"{home}/peers"))
check("...and KEEPS the exec DA store (content-addressed, possibly the fleet's only copy)", os.path.isdir(f"{home}/exec_da"))
D.purge_chain_data()
check("the reroll purge still wipes everything", not any(os.path.exists(f"{home}/{p}") for p in ("peers", "exec_da", "peers.dat")))
check("private/ survives both", os.path.isfile(f"{home}/private/{D.PURGE_LOG}"))

src = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
i = src.index("purge_chain_data(logger=self.logger, dead_fork=True)")
seg = src[src.rindex("def _maybe_escape_dead_fork", 0, i):i]
check("the escape consults the breaker BEFORE purging and records the purge", "if purge_storm(_now_p):" in seg and "record_purge(_now_p)" in seg)
check("the breaker turns production off", "purge_breaker" in src[src.index("def normal_mode"):src.index("def _finalized_block_ref")])
check("zero peers + an answering seed never mints (isolation guard)", "_isolated = (not peers) and self._seeds_answering()" in src)

print()
print("ALL PURGE-BREAKER CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
sys.exit(1 if _fails else 0)
