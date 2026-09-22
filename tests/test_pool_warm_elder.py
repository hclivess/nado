"""A restarted node warms its pool only from an ELDER (ops.peer_ops.pool_warm_ready).

2026-09-22, the 07:41 update wave: seven of nine nodes recorded the same split at h191043 — five tpm_ready
announcements the rest of the mesh held, missing from their own block. Each had restarted, warmed its pool
from the first peer to answer (which had also just restarted: two empty pools agreeing), and built. The
warm-up gate existed since 2026-08 and accepted ANY peer's pool hash; that is the vacuous case this pins.

Run: python3 tests/test_pool_warm_elder.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_warm_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.peer_ops import pool_warm_ready
from protocol import POOL_WARM_ELDER_S

fails = []
def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond: fails.append(label)

E = POOL_WARM_ELDER_S
young = {"1.1.1.1": {"reported_uptime": 12}, "2.2.2.2": {"reported_uptime": E - 1}}
elder = {"3.3.3.3": {"reported_uptime": E}}
hashes_all = {"1.1.1.1": "h", "2.2.2.2": "h", "3.3.3.3": "h"}

check(not pool_warm_ready(young, hashes_all), "two just-restarted peers agreeing on a pool do NOT warm us (the h191043 case)")
check(not pool_warm_ready({}, {}), "no peers at all: not warmed here (the 60 s cap in core_loop handles liveness)")
check(pool_warm_ready({**young, **elder}, hashes_all), "one elder that advertised a pool hash warms us")
check(not pool_warm_ready(elder, {}), "an elder we have not yet merged with or matched (no hash from it) does not")
check(not pool_warm_ready(elder, {"9.9.9.9": "h"}), "a hash from someone else does not stand in for the elder's")
check(pool_warm_ready({"3.3.3.3": {"reported_uptime": E}}, {"3.3.3.3": "h"}), "the boundary counts: uptime == POOL_WARM_ELDER_S is an elder")
check(not pool_warm_ready({"3.3.3.3": {"reported_uptime": "junk"}, "4.4.4.4": {}}, {"3.3.3.3": "h", "4.4.4.4": "h"}),
      "a status with a broken or missing uptime is skipped, not trusted")
check(pool_warm_ready({"3.3.3.3": {"reported_uptime": 5}}, {"3.3.3.3": "h"}, elder_s=5), "elder_s is honoured when passed explicitly")
check(E >= 60, f"the elder threshold ({E} s) exceeds the 60 s liveness cap, so a wave cannot warm from itself")

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
