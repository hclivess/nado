"""A SPLIT REFRESHES THE FORK VERDICT NOW, NOT AT THE NEXT TTL (core_loop._remeasure_on_competing_tip).

2026-09-15: 76 episodes in a day on the relay of a same-height split followed by ~a minute of solo blocks, because
the majority verdict is cached for FORK_STATE_TTL_S and a split right after a measurement stays invisible until the
next one. Pins: a peer advertising a heavier tip whose hash at OUR height differs from ours drops the cached verdict
(once per local tip); the same hash (plain lag) keeps it; a verdict already saying REORG is left alone; nothing is
probed twice for one tip; our own ip is never the peer asked.
Run: python3 tests/test_competing_tip_remeasure.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_ctr_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import loops.core_loop as CL
from loops.core_loop import CoreClient
from ops import fork_resolution as FR

fails = []
def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond: fails.append(label)

class _Quiet:
    def __getattr__(self, _): return lambda *a, **k: None

class Stub:
    def __init__(self, tip_hash, theirs):
        self.memserver = type("M", (), {})(); self.memserver.latest_block = {"block_number": 100, "block_hash": tip_hash}
        self.memserver.ip = "9.9.9.9"; self.memserver.port = 9173; self.memserver.address = "me"
        self.consensus = type("C", (), {})(); self.consensus.heaviest_block_hash = "h" * 64
        self.consensus.status_pool = {"1.1.1.1": {"latest_block_hash": "h" * 64}, "9.9.9.9": {"latest_block_hash": "h" * 64}}
        self.logger = _Quiet(); self.probes = []; self.theirs = theirs
        self._remeasure_on_competing_tip = CoreClient._remeasure_on_competing_tip.__get__(self)
    def _memo_probe(self, peer, h, tip):
        self.probes.append((peer, h)); return (self.theirs, "pk", "sig")

CL.own_ips = lambda: set()
CL.get_config = lambda: {"ip": "9.9.9.9"}

s = Stub("a" * 64, theirs="b" * 64)
s._fork_state_cache = (0, {"state": FR.SYNCED, "ancestor": 100})
check(s._remeasure_on_competing_tip() and s._fork_state_cache is None, "a different hash at our height drops the cached verdict")
check(s.probes == [("1.1.1.1", 100)], f"exactly one probe, of the advertising peer, at our height, never ourselves ({s.probes})")
s._fork_state_cache = (0, {"state": FR.SYNCED})
check(not s._remeasure_on_competing_tip() and s._fork_state_cache is not None and len(s.probes) == 1, "the same local tip is never re-checked (no flap, no second probe)")
s.memserver.latest_block = {"block_number": 101, "block_hash": "c" * 64}
check(s._remeasure_on_competing_tip() and len(s.probes) == 2, "a NEW local tip is checked once more")

lag = Stub("a" * 64, theirs="a" * 64)
lag._fork_state_cache = (0, {"state": FR.SYNCED})
check(not lag._remeasure_on_competing_tip() and lag._fork_state_cache is not None, "the same hash at our height is plain lag — the verdict stays")

minority = Stub("a" * 64, theirs="b" * 64)
minority._fork_state_cache = (0, {"state": FR.REORG, "ancestor": 99})
check(not minority._remeasure_on_competing_tip() and minority._fork_state_cache is not None and not minority.probes,
      "a verdict already saying REORG is left for the reorg leg — nothing probed")

nopeer = Stub("a" * 64, theirs="b" * 64); nopeer.consensus.status_pool = {}
nopeer._fork_state_cache = (0, {"state": FR.SYNCED})
check(not nopeer._remeasure_on_competing_tip() and nopeer._fork_state_cache is not None, "no peer advertising the heaviest tip -> nothing changes")

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "loops", "core_loop.py")).read()
check("self._remeasure_on_competing_tip()" in src.split("def emergency_mode")[1].split("while self.memserver.emergency_mode")[0],
      "wired at the emergency entry, before the throttled log and the loop")
print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
