"""The update cascade is jittered, and one delayed check runs at a time (ops.self_update).

Every node that heard a peer hint restarted at once; the whole fleet was down and back inside a few
seconds, so no node came back to a mesh with an elder to warm its pool from, and every wave split
(h191043, 2026-09-22). A peer-hint check now waits a uniform 0..UPDATE_WAVE_JITTER_S; the operator's own
/update and the timer wait nothing. A second hint while one check is pending must not start a second pull.

Run: python3 tests/test_update_wave_jitter.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_jitter_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops import self_update as su
from protocol import UPDATE_WAVE_JITTER_S, POOL_WARM_ELDER_S

fails = []
def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond: fails.append(label)

check(su.wave_delay("remote") == 0.0, "the operator's own /update waits nothing")
check(su.wave_delay("timer") == 0.0, "the 15-minute timer waits nothing")
check(su.wave_delay("peer-hint", rng=lambda: 0.0) == 0.0, "a peer hint can draw zero")
check(su.wave_delay("peer-hint", rng=lambda: 1.0) == UPDATE_WAVE_JITTER_S, "a peer hint can draw the full jitter")
check(su.wave_delay("peer-hint", rng=lambda: 0.5) == UPDATE_WAVE_JITTER_S / 2, "the draw is uniform in between")
check(UPDATE_WAVE_JITTER_S > POOL_WARM_ELDER_S + 30,
      f"the jitter ({UPDATE_WAVE_JITTER_S} s) outlasts the elder threshold ({POOL_WARM_ELDER_S} s) plus a boot, "
      f"so the first nodes to restart are elders before the last ones do")

# one pending check at a time: fake the thread, force the hint to look unknown
started = []
class FakeThread:
    def __init__(self, target=None, args=(), daemon=None, name=None): started.append((target, args))
    def start(self): pass
su.threading.Thread = FakeThread
su._git = lambda *a, **k: (_ for _ in ()).throw(Exception("not an ancestor"))
su._hints.clear(); su._wave_pending = False
first = su.peer_hint("feedfacefeed")
second = su.peer_hint("cafebabecafe")
check(first is True and len(started) == 1, "the first unknown hint schedules exactly one delayed check")
check(second is False and len(started) == 1, "a second hint while that check is pending schedules nothing")
target, args = started[0]
check(target is su._delayed_check and 0.0 <= args[0] <= UPDATE_WAVE_JITTER_S, "the scheduled check carries a delay inside the jitter")
su._wave_pending = False
check(su.peer_hint("deadbeefdead") is True and len(started) == 2, "once the pending check has run, the next hint schedules again")

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
