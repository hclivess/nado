"""A testnet node never runs the installer and never self-updates (ops/self_update.heal / check_and_update).

WHY (2026-09-28, the gen-28 rehearsal). A loopback node started as root from a worktree on branch reroll-gen28 judged
itself un-updatable (not on main) and self-healed: it launched `scripts/install.sh --service --exec` detached, on the
machine that runs the live node. The installer saw the live nado.service (User=nado), switched to its
move-into-/srv/nado-home/nado mode, and stopped only at its own "already exists — refusing" check. Nothing changed —
measured: units, services and the live checkout untouched — but only by the installer's last guard.

Pins: under NADO_TESTNET, heal() returns "disabled" without spawning anything, even as root and even when forced; the
loopback harnesses write auto_heal/auto_update false into every child's config, so a child neither heals nor fetches and
fast-forwards the tree it runs from. (The update check keys on the config, not on NADO_TESTNET: the test suite runs
every test under NADO_TESTNET and tests/test_self_update_stale_native.py exercises the updater itself.)

Run: python3 tests/test_testnet_never_runs_the_installer.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-noheal-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import subprocess
from ops import self_update as SU

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


spawned = []
real_popen, real_run = subprocess.Popen, subprocess.run
subprocess.Popen = lambda *a, **k: spawned.append(("Popen", a, k))            # nothing may be started
subprocess.run = lambda *a, **k: spawned.append(("run", a, k))
real_euid = os.geteuid
os.geteuid = lambda: 0                                                        # as root, the case that bit
try:
    os.environ["NADO_TESTNET"] = "1"
    SU._heal_attempted[0] = False
    r = SU.heal(force=True)
    check("a testnet node never runs the installer, even as root and forced", r.get("status") == "disabled" and not spawned,
          (r, spawned))
    del os.environ["NADO_TESTNET"]
    SU._heal_attempted[0] = False
    r = SU.heal(force=True)
    check("...while a production node still self-heals (the guard is the testnet flag, nothing else)",
          r.get("status") in ("healing", "unavailable") and (r.get("status") == "unavailable" or spawned), (r, spawned))
finally:
    subprocess.Popen, subprocess.run, os.geteuid = real_popen, real_run, real_euid
    os.environ.pop("NADO_TESTNET", None)

for h in ("run_testnet.py", "test_fork_resolution.py"):
    src = open(os.path.join(ROOT, "scripts", "testnet", h)).read()
    check(f"{h} writes auto_heal and auto_update false into every child's config",
          '"auto_heal": False' in src and '"auto_update": False' in src)

print("ALL PASS — a testnet node never touches the machine it runs on" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
