"""The node runs its exec node itself while nado-exec.service is down, and hands it back (ops/exec_supervisor.py), and no
two exec nodes ever run over one state file (execnode.acquire_state_lock).

MEASURED 2026-09-27: after two update waves, 185.100.232.5 and 185.238.249.208 had nado-exec "inactive (dead), result
success" (Requires=nado.service stops it on a node restart; the fleet's root bridge only try-restarts running units), and
no root-side fix reaches community machines — the node process is the only thing every machine updates.

Pins, with a fake root-owned unit file, a fake systemctl on PATH and a stand-in exec program:
  1. enabled + inactive -> the node starts the unit's own ExecStart, with its Environment= and WorkingDirectory=;
  2. a second pass does not start a second one;
  3. the service comes back (active) -> the node stops its own, so the service owns it;
  4. disabled -> never started (an operator turns exec off by disabling it);
  5. systemd state unreadable -> nothing (unknown is never "down"); a unit for another account, or one that does not run
     execnode/execnode.py -> nothing;
  6. the state lock: a second holder is refused, and the real execnode.py run as a program exits at once when the lock is
     held — BEFORE the module-level state load that writes the .gen marker and the settle stash.

Run: python3 tests/test_exec_supervisor.py
"""
import os, sys, tempfile, time, subprocess
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-execsup-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
H = os.environ["HOME"]
os.environ["NADO_EXEC_STATE"] = os.path.join(H, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(H, "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import exec_supervisor as S

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


# the stand-in exec program: records its environment and working directory, then sleeps
prog_dir = os.path.join(H, "repo", "execnode"); os.makedirs(prog_dir)
prog = os.path.join(prog_dir, "execnode.py")
marker = os.path.join(H, "child.txt")
open(prog, "w").write(f"import os, time\nopen({marker!r}, 'w').write(os.environ.get('NADO_EXEC_PORT','') + '|' + os.getcwd())\n"
                      "time.sleep(120)\n")
unit = os.path.join(H, "nado-exec.service")
ME = "nado-test"
open(unit, "w").write(f"[Service]\nUser={ME}\nWorkingDirectory={H}/repo\nEnvironment=NADO_EXEC_PORT=19273\n"
                      f"ExecStart={sys.executable} {prog}\n")
state_file = os.path.join(H, "systemd_state")
fake = os.path.join(H, "bin"); os.makedirs(fake)
open(os.path.join(fake, "systemctl"), "w").write(f"#!/bin/sh\ncat {state_file}\n")
os.chmod(os.path.join(fake, "systemctl"), 0o755)
os.environ["PATH"] = fake + ":" + os.environ.get("PATH", "/usr/bin:/bin")


def systemd(active, enabled):
    open(state_file, "w").write("" if active is None else f"ActiveState={active}\nUnitFileState={enabled}\n")


logs = []
run = lambda: S.supervise(log=logs.append, unit_path=unit, current_user=ME)

# 1
systemd("inactive", "enabled")
r = run()
time.sleep(1.5)
check("enabled + inactive: the node starts the exec node itself", r.startswith("started it") and S._alive(), r)
got = open(marker).read() if os.path.exists(marker) else ""
check("...with the unit's own Environment= and WorkingDirectory=", got == f"19273|{H}/repo", got)
pid = S.status()["child_pid"]
# 2
r = run()
check("a second pass keeps the one it runs (no second child)", r.startswith("running it") and S.status()["child_pid"] == pid, r)
# 3
systemd("active", "enabled")
r = run()
check("the service is back: the node stops its own and lets systemd own it", r == "the service runs it" and not S._alive(), r)
# 4
systemd("inactive", "disabled")
r = run()
check("disabled: never started (the operator turned it off)", r == "disabled by the operator" and not S._alive(), r)
# 5
systemd(None, None)
check("systemd state unreadable: nothing (unknown is never read as down)", run() == "systemd state unknown" and not S._alive())
systemd("inactive", "enabled")
check("a unit for another account: nothing", S.supervise(log=logs.append, unit_path=unit, current_user="someone-else")
      .startswith("the unit runs as") and not S._alive())
other = os.path.join(H, "other.service")
open(other, "w").write(f"[Service]\nUser={ME}\nExecStart=/bin/sh -c 'echo hi'\n")
check("a unit that does not run execnode/execnode.py: nothing",
      S.supervise(log=logs.append, unit_path=other, current_user=ME) == "the unit does not run the exec node")
check("not an exec machine: nothing", S.supervise(unit_path=os.path.join(H, "absent.service")) == "not an exec machine")
S._stop_child("test end", logs.append)

# 6 the state lock
sys.path.insert(0, ROOT)
from execnode.execnode import acquire_state_lock      # imported as a module: takes no lock itself
lock_path = os.environ["NADO_EXEC_STATE"]
held = acquire_state_lock(lock_path)
check("the first exec node gets the state lock", held is not None)
probe = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); from execnode.execnode import "
                        "acquire_state_lock as a; print(a(%r) is None)" % (ROOT, lock_path)],
                       capture_output=True, text=True, timeout=120, env=dict(os.environ))
check("a second process is refused the lock", probe.stdout.strip().endswith("True"), probe.stdout[-200:] + probe.stderr[-300:])
# the program run, in a FRESH state directory whose lock this test holds with a raw flock (no execnode import here — an
# import is a module load, which itself writes the .gen marker)
import fcntl
fresh = os.path.join(H, "fresh"); os.makedirs(fresh)
fresh_state = os.path.join(fresh, "exec_state.json")
raw = open(fresh_state + ".lock", "a+"); fcntl.flock(raw.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
run2 = subprocess.run([sys.executable, os.path.join(ROOT, "execnode", "execnode.py")], capture_output=True, text=True,
                      timeout=120, cwd=fresh, env=dict(os.environ, PYTHONPATH=ROOT, NADO_EXEC_STATE=fresh_state,
                                                       NADO_EXEC_DA=os.path.join(fresh, "exec_da")))
check("the real execnode.py exits at once while another holds the lock",
      run2.returncode != 0 and "already holds" in run2.stderr, (run2.returncode, run2.stderr[-300:]))
check("...before the state load: it wrote no state file and no .gen marker",
      sorted(os.listdir(fresh)) == ["exec_state.json.lock"], os.listdir(fresh))
raw.close()
held.close()
probe = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); from execnode.execnode import "
                        "acquire_state_lock as a; print(a(%r) is not None)" % (ROOT, lock_path)],
                       capture_output=True, text=True, timeout=120, env=dict(os.environ))
check("once the holder exits, the next exec node gets it", probe.stdout.strip().endswith("True"), probe.stdout[-200:])

print("ALL PASS — an exec machine never stays without its exec node" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
