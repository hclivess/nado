"""The job reconciler installs every declared operator job as the node's own account, and nothing else
(scripts/reconcile_units.py, deploy/units/manifest.json, doc/jobs.md).

Root runs the reconciler (a root-owned copy), while the manifest and unit files come from the account-owned checkout —
so they are untrusted data. Pins: every repo unit renders and validates; without "operator_jobs" nothing is written;
with it, every operator job is written with the tokens filled and enabled; a unit that would run as root, escalate an
Exec line, carry a non-nado name, or a timer that triggers someone else's service is refused; units install.sh owns
are never written. A temporary directory stands in for /etc/systemd/system and systemctl is recorded, not run.

Run: python3 tests/test_reconcile_units.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-reconcile-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import sys, json, importlib.util, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("reconcile_units", os.path.join(ROOT, "scripts", "reconcile_units.py"))
R = importlib.util.module_from_spec(spec); spec.loader.exec_module(R)

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def machine(operator):
    """A fake /etc/systemd/system with a service-account nado.service, and a repo copy whose config says `operator`."""
    etc = tempfile.mkdtemp(dir=os.environ["HOME"])
    repo = tempfile.mkdtemp(dir=os.environ["HOME"])
    shutil.copytree(os.path.join(ROOT, "deploy"), os.path.join(repo, "deploy"))
    os.makedirs(os.path.join(repo, "private"))
    json.dump({"operator_jobs": operator}, open(os.path.join(repo, "private", "config.json"), "w"))
    open(os.path.join(etc, "nado.service"), "w").write(
        f"[Service]\nUser=nado\nGroup=nado\nWorkingDirectory={repo}\nEnvironment=HOME=/srv/nado-home\n")
    return etc, repo


calls = []


class _Done:
    def __init__(self, out=""): self.stdout, self.stderr, self.returncode = out, "", 0


def fake_run(args, **kw):
    calls.append(args[1:])
    return _Done("disabled" if args[1] == "is-enabled" else "inactive" if args[1] == "is-active" else "")


R.subprocess.run = fake_run
R.RESULT = os.path.join(os.environ["HOME"], "result.json")

# 1. without the operator flag: nothing
etc, repo = machine(False)
R.DEST = etc
calls.clear()
check("a node that is not the operator gets no operator jobs", R.main() == 0 and sorted(os.listdir(etc)) == ["nado.service"])

# 2. the operator: every job written, filled in, enabled
etc, repo = machine(True)
R.DEST = etc
calls.clear()
rc = R.main()
manifest = json.load(open(os.path.join(ROOT, "deploy", "units", "manifest.json")))
want = sorted(f for j in manifest["jobs"] if j.get("source") == "repo" and j["role"] == "operator" for f in j["files"])
got = sorted(f for f in os.listdir(etc) if f != "nado.service")
check("the operator gets every declared operator unit", rc == 0 and got == want, (rc, got, want))
texts = {f: open(os.path.join(etc, f)).read() for f in got}
check("every template token is filled", not any("@" + t + "@" in s for s in texts.values() for t in ("USER", "GROUP", "HOME", "REPO")))
check("every service runs as the node's account", all("User=nado" in s for f, s in texts.items() if f.endswith(".service")))
check("no written unit points at /root", not any("/root" in s.split("#")[0] for s in texts.values()))
enabled = sorted(c[2] for c in calls if c[:2] == ["enable", "--now"])
check("every operator job is enabled", enabled == sorted(j["unit"] for j in manifest["jobs"]
                                                         if j.get("source") == "repo" and j["role"] == "operator"), enabled)
check("units install.sh owns are never written", not {"nado-exec.service", "forum.service", "nado-restart.path"} & set(got))

# 3. what the account could put in the checkout is refused
V = lambda n, t, svc=frozenset(): R.validate(n, t, "nado", "nado", set(svc))
check("a unit running as root is refused", V("nado-x.service", "[Service]\nUser=root\nExecStart=/bin/true\n"))
check("a unit with no User= (= root) is refused", V("nado-x.service", "[Service]\nExecStart=/bin/true\n"))
check("an escalating Exec prefix is refused", V("nado-x.service", "[Service]\nUser=nado\nExecStartPre=+/bin/sh\n"))
check("a double User= is refused", V("nado-x.service", "[Service]\nUser=nado\nUser=root\n"))
check("a system unit name is refused", V("ssh.service", "[Service]\nUser=nado\n"))
check("a timer triggering another service is refused", V("nado-x.timer", "[Timer]\nUnit=ssh.service\n", {"nado-x.service"}))
check("a timer triggering its own validated service is accepted", not V("nado-x.timer", "[Timer]\nUnit=nado-x.service\n", {"nado-x.service"}))
check("a plain account service is accepted", not V("nado-x.service", "[Service]\nUser=nado\nExecStart=/bin/true\n"))

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
