"""
A plot photo's browser profile is removed however the capture ends (found 2026-11-16 on the live host: 21 land-shot-*
profiles, 1.4 GB, left in /tmp over a week — a restart of the world server cancelled World.shoot inside its wait, and the
lines that killed the browser's group and removed the profile came after the wait, so they never ran). The kill and the
removal are in `finally` now, and World.sweep_shot_profiles removes before every capture any profile older than a capture can run
(a kill -9 or a power cut, which no `finally` sees). Here a stand-in capture that never finishes is started through the
real World.shoot and cancelled as a stop cancels it: its profile is gone; and the sweep removes the old profiles and
keeps a fresh one (a capture in progress).
Run: python3 tests/test_a_plot_photos_browser_profile_is_removed_however_the_capture_ends.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-shotprof-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import asyncio, importlib.util, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import _harness
_report = _harness.Report()
check = _report.check
spec = importlib.util.spec_from_file_location("land_server", os.path.join(ROOT, "scripts", "land_server.py"))
S = importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
tmp = tempfile.mkdtemp(prefix="shot-tmp-", dir=os.environ["HOME"])
S.SHOT_TMP = tmp
# a stand-in capture: a node script that never ends (the real one is a browser taking a photograph)
fake = tempfile.mkdtemp(prefix="repo-", dir=os.environ["HOME"])
os.makedirs(os.path.join(fake, "scripts"))
open(os.path.join(fake, "scripts", "land_shot.mjs"), "w").write("setInterval(() => {}, 1000);\n")
S.REPO = fake
world = S.World.__new__(S.World)
world.plots, world.shots = {}, tempfile.mkdtemp(prefix="shots-", dir=os.environ["HOME"])


async def main():
    task = asyncio.ensure_future(world.shoot(7, "http://127.0.0.1:1"))
    for _ in range(50):
        await asyncio.sleep(0.1)
        if any(n.startswith("land-shot-") for n in os.listdir(tmp)):
            break
    made = [n for n in os.listdir(tmp) if n.startswith("land-shot-")]
    check("the capture made its browser profile", len(made) == 1, made)
    task.cancel()                                                    # what a stop does to the photographer
    try:
        await task
    except asyncio.CancelledError:
        pass
    left = [n for n in os.listdir(tmp) if n.startswith("land-shot-")]
    check("cancelled mid-capture (a restart), its profile is removed", not left, left)

asyncio.run(main())
# the sweep at start: a profile older than any capture can run goes; a fresh one (a capture in progress) stays
old, fresh = os.path.join(tmp, "land-shot-old"), os.path.join(tmp, "land-shot-fresh")
os.makedirs(os.path.join(old, "Default")); os.makedirs(fresh)
past = time.time() - (2 * S.SHOT_TIMEOUT + 120)
os.utime(old, (past, past))
other = os.path.join(tmp, "not-ours"); os.makedirs(other); os.utime(other, (past, past))
n = S.World.sweep_shot_profiles()
check("at start, a profile older than any capture is swept", n == 1 and not os.path.exists(old), n)
check("…a fresh one (a capture running) is kept, and nothing that is not a capture profile is touched", os.path.exists(fresh) and os.path.exists(other))
src = open(os.path.join(ROOT, "scripts", "land_server.py")).read()
loop = src[src.index("async def _photographer():"):][:1200]
check("the photographer sweeps before every capture (a stop mid-capture can outlive its finally)",
      "await asyncio.to_thread(World.sweep_shot_profiles)" in loop and loop.index("sweep_shot_profiles") > loop.index("while True:"))
_report.done()
