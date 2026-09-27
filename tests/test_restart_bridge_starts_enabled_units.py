"""The restart bridge never leaves an enabled unit down after an update (scripts/install.sh, nado-restart.service).

MEASURED 2026-09-27 23:39: after the update wave to 7709680c, 185.100.232.5 reported "nado-exec.service inactive" (dead,
result success) and stayed so. nado-exec has Requires=nado.service, so restarting nado stops it; that node got two restart
requests close together (the wave kick answered "busy" and queued a re-check), and the bridge's only action on nado-exec
was `systemctl try-restart`, which restarts RUNNING units — a stopped one stays stopped, forever.

Pins, by running the bridge's own ExecStart (extracted from install.sh, rendered the way the heredoc and systemd render it)
against a fake systemctl that records calls, with the live flag file and the root reconciler rewritten to throwaway
paths so nothing on this host is touched:
  1. an ENABLED unit that is not active is started;
  2. a DISABLED unit that is not active is left alone (an operator turns a unit off by disabling it);
  3. running units still get the try-restart they always got.

Run: python3 tests/test_restart_bridge_starts_enabled_units.py
"""
import os, re, subprocess, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-bridge-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


src = open(os.path.join(ROOT, "scripts", "install.sh")).read()
block = src[src.index("cat > /etc/systemd/system/nado-restart.service <<BRIDGEEOF"):]
block = block[:block.index("\nBRIDGEEOF")]
m = re.search(r"^ExecStart=/bin/sh -c '(.*)'$", block, re.M)
check("the bridge's ExecStart is found in install.sh", m is not None)
cmd = m.group(1) if m else ""
# render: the unquoted heredoc turns \$ into $, then systemd turns $$ into $
cmd = cmd.replace("\\$", "$").replace("$$", "$")
H = os.environ["HOME"]
cmd = cmd.replace("/run/nado/restart-request", os.path.join(H, "restart-request"))
cmd = cmd.replace("/usr/local/sbin/nado-reconcile-units", os.path.join(H, "no-such-reconciler"))
check("the live flag file and the root reconciler are rewritten away from this host",
      "/run/nado" not in cmd and "/usr/local/sbin" not in cmd, cmd)

fake = os.path.join(H, "bin"); os.makedirs(fake)
log = os.path.join(H, "calls.log")
# states: nado running+enabled, nado-exec enabled but inactive, forum disabled and inactive
open(os.path.join(fake, "systemctl"), "w").write(f"""#!/bin/sh
echo "$*" >> {log}
case "$*" in
  "is-enabled --quiet nado.service"|"is-enabled --quiet nado-exec.service") exit 0;;
  "is-enabled --quiet forum.service") exit 1;;
  "is-active --quiet nado.service") exit 0;;
  "is-active --quiet nado-exec.service"|"is-active --quiet forum.service") exit 3;;
esac
exit 0
""")
open(os.path.join(fake, "sleep"), "w").write("#!/bin/sh\nexit 0\n")
for f in ("systemctl", "sleep"):
    os.chmod(os.path.join(fake, f), 0o755)
if m:
    subprocess.run(["/bin/sh", "-c", cmd], env={"PATH": fake + ":/usr/bin:/bin"}, timeout=30)
calls = open(log).read().splitlines() if os.path.exists(log) else []
check("an ENABLED unit left stopped is started", "start nado-exec.service" in calls, calls)
check("a DISABLED stopped unit is left alone", "start forum.service" not in calls, calls)
check("a running unit is not started twice", "start nado.service" not in calls, calls)
check("running units still get their try-restart", "try-restart nado.service" in calls, calls)

print("ALL PASS — no enabled unit is left down" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
