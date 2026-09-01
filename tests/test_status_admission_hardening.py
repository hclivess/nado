"""STATUS ADMISSION HARDENING (2026-09-01 review). A peer's /status is untrusted input that feeds consensus
arithmetic. Three findings, each pinned here:
  1. `latest_block_height` must be TYPED at admission: a string height passed status_fields_well_typed,
     survived int() in core_loop's settle-proof DEPTH GATE, made every remote block "deep" and (with
     SETTLE_PROOF_DEPTH_GATED) switched the STARK verification off on every node at once.
  2. The depth gate reads the pool's UPPER MEDIAN advertised height, never its max — one admitted,
     plausible-looking claim must not relax verification for the whole fleet.
  3. The type check runs BEFORE the protocol comparison: `protocol: null` / "11" raised TypeError ahead of
     it and aborted the rest of the peer pass (admission, mempool reconcile, save_pool, purge_peers)
     every second, with the sender never banned.
Run: python3 tests/test_status_admission_hardening.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


from ops.peer_ops import status_fields_well_typed, _STATUS_INT_FIELDS

check("latest_block_height is a typed consensus field", "latest_block_height" in _STATUS_INT_FIELDS)
check("a string height is refused at admission",
      not status_fields_well_typed({"protocol": 11, "latest_block_height": "999999999999"}))
check("a bool height is refused at admission",
      not status_fields_well_typed({"protocol": 11, "latest_block_height": True}))
check("an int height is admitted", status_fields_well_typed({"protocol": 11, "latest_block_height": 1234}))
check("an absent height is admitted (a mid-restart peer omits fields)", status_fields_well_typed({"protocol": 11}))

core = open(os.path.join(ROOT, "loops", "core_loop.py")).read()
i = core.index("_best_peer = _hs[len(_hs) // 2]")
seg = core[core.rindex("\n", 0, i - 900):i]
check("the depth gate takes the upper median of the pool's heights, not the max",
      "sorted(int(v.get(\"latest_block_height\") or 0)" in seg
      and "isinstance(v.get(\"latest_block_height\"), int)" in seg
      and "max((int(v.get(\"latest_block_height\")" not in core)

# behavioural mirror of the gate's arithmetic: one liar among honest peers cannot move the median
def upper_median(pool):
    hs = sorted(int(v.get("latest_block_height") or 0) for v in pool.values()
                if isinstance(v, dict) and isinstance(v.get("latest_block_height"), int))
    return hs[len(hs) // 2] if hs else 0

honest = {f"p{i}": {"latest_block_height": 1000 + i} for i in range(4)}
check("one tall claim among four honest peers does not move the median past the honest range",
      upper_median({**honest, "liar": {"latest_block_height": 10 ** 9}}) <= 1003)
check("a lone peer is still its own median (a fresh node can catch up)",
      upper_median({"p": {"latest_block_height": 777}}) == 777)
check("a string height never reaches the arithmetic",
      upper_median({"p": {"latest_block_height": "999"}}) == 0)

pl = open(os.path.join(ROOT, "loops", "peer_loop.py")).read()
t = pl.index("not status_fields_well_typed(value)")
p = pl.index("value['protocol'] < self.memserver.protocol")
check("the type check precedes the protocol comparison", t < p)
check("an absent/non-int protocol is banned, not compared",
      re.search(r"not isinstance\(value\.get\('protocol'\), int\) or value\['protocol'\] <", pl) is not None)

print()
print("ALL STATUS-ADMISSION CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
sys.exit(1 if _fails else 0)
