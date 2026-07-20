"""
Self-update capability diagnosis + installer-based self-heal (ops/self_update.py).

WHY THIS EXISTS: a sweep of the live fleet found 21 of 25 peers answering `running_commit: null` — they
were installed by hand or by an old installer, have no git metadata, and therefore can NEVER self-update.
Nobody knew, because the refusal reasons only surfaced if somebody called /update. Consensus changes ship
strictly with no backward compatibility, so such a node does not merely go stale: it drifts and forks (one
did, ~300 blocks, the same day).

So the node diagnoses its own updatability at boot, advertises it in /status, and repairs itself by running
THE LOCAL scripts/install.sh — the single supported fixer, shipped with the node, never fetched.

The load-bearing property is that a BROKEN node is detected. A test that only confirms a healthy node looks
healthy would have passed on all 21.

Run: python3 tests/test_updatability.py
"""
import os, sys, tempfile, traceback, subprocess
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado_upd_"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import self_update as SU

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


class patched:
    """Temporarily repoint the module's repo dir / service list / helpers."""
    def __init__(self, **kw): self.kw = kw; self.old = {}
    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = getattr(SU, k)
            setattr(SU, k, v)
        return self
    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(SU, k, v)


def gitless_dir():
    """A node directory with the files but NO .git — the exact shape of the 21 stranded peers."""
    d = tempfile.mkdtemp(prefix="nado_gitless_")
    os.makedirs(os.path.join(d, "scripts"), exist_ok=True)
    open(os.path.join(d, "nado.py"), "w").write("# node\n")
    open(os.path.join(d, "scripts", "install.sh"), "w").write("#!/bin/bash\necho installer\n")
    return d


def t_healthy_node_is_capable():
    """This repo is a real checkout with a unit — the baseline must be clean, or every other result is noise."""
    r = SU.updatability(probe_remote=False)
    assert r["checks"]["git_checkout"], f"this repo should be a checkout: {r}"
    assert r["capable"], f"a healthy node must be capable: {r['blocking']}"


def t_gitless_node_is_detected():
    """THE case that mattered: files present, no git metadata. Must be blocking, not a warning."""
    d = gitless_dir()
    with patched(_REPO_DIR=d, _has_restart_capability=lambda: True):
        r = SU.updatability(probe_remote=False)
    assert not r["capable"], "a git-less node MUST be reported incapable"
    assert any("not a git checkout" in b for b in r["blocking"]), f"and say why: {r['blocking']}"


def t_missing_service_is_detected():
    """Repo current but nothing to restart — three live peers are in exactly this state (repo fast-forwarded,
    running_commit stale forever). An update that never takes effect is not an update."""
    with patched(_has_restart_capability=lambda: False):
        r = SU.updatability(probe_remote=False)
    assert not r["capable"], "no systemd unit MUST be reported incapable"
    assert any("systemd" in b for b in r["blocking"]), f"and say why: {r['blocking']}"


def t_wrong_origin_is_detected():
    """A checkout pointed at a fork would silently pull somebody else's code."""
    with patched(_git=lambda *a, **k: "https://github.com/someone/evil" if a[0] == "remote" else "main",
                 _has_restart_capability=lambda: True):
        r = SU.updatability(probe_remote=False)
    assert not r["capable"] and any("official repo" in b for b in r["blocking"]), f"{r['blocking']}"


def t_offline_is_a_WARNING_not_fatal():
    """THE most important negative: a transient network failure must NEVER mark a node incapable. Treating
    it as fatal would let one GitHub outage take down every node on the network simultaneously."""
    def fake_git(*a, **k):
        if a[0] == "ls-remote":
            raise subprocess.CalledProcessError(1, "git")
        return {"rev-parse": "main", "remote": "https://github.com/hclivess/nado.git"}[a[0]]
    with patched(_git=fake_git, _has_restart_capability=lambda: True):
        r = SU.updatability(probe_remote=True)
    assert r["capable"], "an offline node must STILL be capable — it updates when connectivity returns"
    assert r["warnings"] and not r["blocking"], f"offline is a warning, not blocking: {r}"


def t_heal_runs_the_LOCAL_installer():
    """The fixer must be the installer that ships with the node, not a curl. Asserted by pointing the repo
    dir at a fixture and requiring the spawned command to be that fixture's own install.sh."""
    d = gitless_dir()
    spawned = {}
    class FakePopen:
        def __init__(self, args, **kw): spawned["args"] = args; spawned["cwd"] = kw.get("cwd")
    with patched(_REPO_DIR=d, _heal_attempted=[False]):
        real_popen, SU.subprocess.Popen = SU.subprocess.Popen, FakePopen
        real_euid, SU.os.geteuid = SU.os.geteuid, (lambda: 0)
        try:
            res = SU.heal()
        finally:
            SU.subprocess.Popen = real_popen; SU.os.geteuid = real_euid
    assert res["status"] == "healing", f"heal must start: {res}"
    assert spawned["args"][1] == os.path.join(d, "scripts", "install.sh"), \
        f"must run the LOCAL installer, got {spawned['args']}"
    assert "--service" in spawned["args"], "must install the systemd unit — that is half the defect"
    assert not any(str(a).startswith("http") for a in spawned["args"]), "must NEVER fetch from the network"


def t_heal_is_attempted_once():
    """A heal that does not take must not become a restart loop."""
    d = gitless_dir()
    with patched(_REPO_DIR=d, _heal_attempted=[False]):
        real_popen, SU.subprocess.Popen = SU.subprocess.Popen, (lambda *a, **k: None)
        real_euid, SU.os.geteuid = SU.os.geteuid, (lambda: 0)
        try:
            first, second = SU.heal(), SU.heal()
        finally:
            SU.subprocess.Popen = real_popen; SU.os.geteuid = real_euid
    assert first["status"] == "healing" and second["status"] == "already_attempted", f"{first} {second}"


def t_heal_without_root_reports_the_command():
    """Non-root cannot write a systemd unit. It must say exactly what to run rather than failing silently."""
    d = gitless_dir()
    with patched(_REPO_DIR=d, _heal_attempted=[False]):
        real_euid, SU.os.geteuid = SU.os.geteuid, (lambda: 1000)
        try:
            res = SU.heal()
        finally:
            SU.os.geteuid = real_euid
    assert res["status"] == "needs_root" and "install.sh" in res["reason"], res


def t_ensure_updatable_never_raises():
    """Runs at boot. A broken diagnosis must never prevent the node from starting."""
    with patched(_git=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))):
        r = SU.ensure_updatable(logger=None, auto_heal=False)
    assert isinstance(r, dict), "must return a report, never propagate"


for name, fn in [
    ("healthy node reports capable", t_healthy_node_is_capable),
    ("git-less node IS detected (the 21-peer case)", t_gitless_node_is_detected),
    ("missing systemd unit IS detected", t_missing_service_is_detected),
    ("non-official origin IS detected", t_wrong_origin_is_detected),
    ("offline is a WARNING, never fatal", t_offline_is_a_WARNING_not_fatal),
    ("heal runs the LOCAL installer, never a curl", t_heal_runs_the_LOCAL_installer),
    ("heal is attempted at most once", t_heal_is_attempted_once),
    ("heal without root reports the exact command", t_heal_without_root_reports_the_command),
    ("ensure_updatable never raises at boot", t_ensure_updatable_never_raises),
]:
    check(name, fn)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
