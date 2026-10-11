"""An OPTIONAL native crate is built on update but never blocks one (ops/self_update._OPTIONAL_CRATES).

native/stwo_js (the Stwo shielded-pool verifier) must reach fleet nodes before STWO_POOL_HEIGHT is set, but until then
nothing needs it: a node whose build fails must update and run normally (at the gate it stalls a Stwo spend instead —
tests/test_a_node_without_the_stwo_verifier_stalls_instead_of_skipping.py). Pins, against a scratch repository with a
fake cargo: a changed optional crate is built; a failed build is REPORTED, never purged and never required; no cargo is
reported, not fatal; and /status native.ok ignores an optional crate's state.

Run: python3 tests/test_an_optional_crate_never_blocks_an_update.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-optional-crate-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import stat, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import self_update as SU

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def write(root, rel, text):
    p = os.path.join(root, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(text)


def cargo(bindir, ok):
    os.makedirs(bindir, exist_ok=True)
    p = os.path.join(bindir, "cargo")
    body = "mkdir -p target/release && : > target/release/libnado_o.so\n" if ok else "exit 101\n"
    open(p, "w").write("#!/bin/sh\n" + body)
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def repo():
    d = tempfile.mkdtemp(prefix="nado-su-opt-", dir=os.environ["HOME"])
    write(d, "native/o/Cargo.toml", "[package]\n"); write(d, "native/o/src/lib.rs", "// v1\n")
    write(d, "native/o/.gitignore", "Cargo.lock\ntarget/\n")
    git(d, "init", "-q", "-b", "main"); git(d, "add", "."); git(d, "commit", "-qm", "v1")
    old = git(d, "rev-parse", "HEAD")
    write(d, "native/o/src/lib.rs", "// v2\n"); git(d, "add", "."); git(d, "commit", "-qm", "v2")
    return d, old, git(d, "rev-parse", "HEAD")


saved_path = os.environ["PATH"]
try:
    d, old, new = repo()
    SU._REPO_DIR, SU._CRATES, SU._OPTIONAL_CRATES = d, (), ("native/o",)
    good = os.path.join(d, "goodbin"); cargo(good, True)
    os.environ["PATH"] = good + os.pathsep + saved_path
    check("a changed optional crate is built on update", SU._rebuild_native_if_changed(old, new) == {"native/o": "built"})

    d, old, new = repo()
    SU._REPO_DIR = d
    write(d, "native/o/target/release/libnado_o.so", "previous build")
    bad = os.path.join(d, "badbin"); cargo(bad, False)
    os.environ["PATH"] = bad + os.pathsep + saved_path
    rep = SU._rebuild_native_if_changed(old, new)
    check("a failed optional build is reported, not fatal", rep == {"native/o": "optional-build-failed"}, rep)
    check("...and its previous library is NOT purged (it is optional; the loader judges staleness itself)",
          os.path.exists(os.path.join(d, "native/o/target/release/libnado_o.so")))

    d, old, new = repo()
    SU._REPO_DIR = d
    os.environ["PATH"] = "/nonexistent"
    rep = SU._rebuild_native_if_changed(old, new)
    check("no cargo is reported, not fatal", rep.get("native/o") in ("optional-no-cargo", None), rep)

    SU._NATIVE_REPORT[:] = [0, None]
    os.environ["PATH"] = saved_path
    nr = SU.native_report(max_age=0)
    check("/status native.ok ignores an optional crate's state (missing here)",
          nr["ok"] is True and nr["crates"].get("native/o", {}).get("optional") is True
          and nr["crates"]["native/o"]["state"] == "missing", nr)
finally:
    os.environ["PATH"] = saved_path
check("the live list names native/stwo_js as optional and never as required",
      "native/stwo_js" in open(os.path.join(ROOT, "ops", "self_update.py")).read().split("_OPTIONAL_CRATES = ")[1].split("\n")[0]
      and "native/stwo_js" not in open(os.path.join(ROOT, "ops", "self_update.py")).read().split("_CRATES = (")[1].split(")")[0])
print("ALL PASS — an optional crate never blocks an update" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
