"""A second node on the same host restarts ONLY its own unit after an update (ops/self_update NADO_INSTANCE,
2026-10-29).

The updater's restart targets were fixed names — units nado / nado-exec / forum, flag /run/nado/restart-request, bridge
nado-restart.path — i.e. the relay's. A second node beside it (same service account) would have written the relay's
flag on every update: the relay bounced, the second node kept old code. Pins:
  1. unset (every ordinary node): the relay's names, unchanged;
  2. NADO_INSTANCE=nado2: only unit nado2, flag /run/nado2/restart-request, bridge nado2-restart.path;
  3. _schedule_restart with the instance probes and restarts nado2 only (systemctl is faked; nothing runs);
  4. an instance value that is not a plain nado<name> (or is "nado" itself) is ignored — never a path or unit
     injected from the environment.

Run: python3 tests/test_a_second_node_on_one_host_restarts_only_its_own_unit.py
"""
import os, sys, tempfile
_T = tempfile.mkdtemp(prefix="nado-test-instance-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import importlib
import _harness
_report = _harness.Report()
check = _report.check


def load(instance):
    if instance is None:
        os.environ.pop("NADO_INSTANCE", None)
    else:
        os.environ["NADO_INSTANCE"] = instance
    import ops.self_update as su
    return importlib.reload(su)


su = load(None)
check("1. unset: the relay's units, flag and bridge",
      su._SERVICES == ("nado", "nado-exec", "forum") and su._RESTART_FLAG == "/run/nado/restart-request"
      and su._RESTART_BRIDGE == "/etc/systemd/system/nado-restart.path")

su = load("nado2")
check("2. NADO_INSTANCE=nado2: only its own unit, flag and bridge",
      su._SERVICES == ("nado2",) and su._RESTART_FLAG == "/run/nado2/restart-request"
      and su._RESTART_BRIDGE == "/etc/systemd/system/nado2-restart.path")

calls = []


class _Ok:
    returncode = 0


def fake_run(cmd, **kw):
    calls.append(list(cmd))
    return _Ok()


real_run, real_popen, real_euid = su.subprocess.run, su.subprocess.Popen, su.os.geteuid
su.subprocess.run = fake_run
su.subprocess.Popen = lambda *a, **k: calls.append(["popen", *a])
su.os.geteuid = lambda: 0                      # the direct systemctl path: the restart command itself is visible
try:
    got = su._schedule_restart()
finally:
    su.subprocess.run, su.subprocess.Popen, su.os.geteuid = real_run, real_popen, real_euid
named = [c for c in calls if "systemctl" in c]
check("3. _schedule_restart probes and restarts nado2 and nothing else",
      got == ["nado2"] and all(("nado2.service" in c) or (c[-2:] == ["restart", "nado2"]) for c in named)
      and not any(u in c for c in calls for u in ("nado.service", "nado-exec", "forum")), calls)

bad = ["../etc", "nado", "nado-exec", "nado2;rm", "evil", "nado" + "x" * 20]
ok = True
for v in bad:
    s = load(v)
    ok = ok and s._SERVICES == ("nado", "nado-exec", "forum") and s._RESTART_FLAG == "/run/nado/restart-request"
check("4. anything but a plain nado<name> is ignored", ok)
load(None)
_report.done()
