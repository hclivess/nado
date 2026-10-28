"""The updater removes the build output G9 left on every node for the Goldilocks crates it deleted
(ops/self_update._remove_retired_build_dirs, 2026-10-28).

G9 slice 6 deleted native/alghash2, starkcompose, starkprove and wasm/goldilocks, but their target/ dirs are git-ignored,
so every fleet node kept the compiled Goldilocks libraries (the relay: ~1.1 MB). Pins, against a temporary git repo:
  1. each retired crate's target/ goes, and the crate dir with it when nothing else is in it;
  2. a hand-made file in a retired crate (an untracked Cargo.toml) stays, and so does its dir;
  3. a retired path that git TRACKS again is a live crate: nothing under it is touched;
  4. a target/ that is a symlink is not followed or removed; a second pass removes nothing;
  5. a live crate's target/ (native/mldsa44) is never touched;
  6. every update check runs it (check_and_update calls it right after the fetch).

Run: python3 tests/test_the_updater_removes_the_deleted_goldilocks_crates_build_output.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-retired-build-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ops import self_update as SU

import _harness
_report = _harness.Report()
check = _report.check

repo = tempfile.mkdtemp(dir=os.environ["HOME"])


def put(rel, data="x"):
    p = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(data)


def git(*a):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=repo, check=True, capture_output=True)


git("init", "-q")
put("README", "r"); put("native/mldsa44/Cargo.toml"); put("native/starkprove/Cargo.toml")   # starkprove tracked again
git("add", "-A"); git("commit", "-qm", "base")
for c in ("native/alghash2", "native/starkcompose", "native/starkprove", "wasm/goldilocks", "native/mldsa44"):
    put(f"{c}/target/release/lib.so")
put("native/starkcompose/Cargo.toml")                                     # hand-made, untracked
outside = tempfile.mkdtemp(dir=os.environ["HOME"])
open(os.path.join(outside, "keep.so"), "w").write("k")
os.makedirs(os.path.join(repo, "native/linked"))

saved = SU._REPO_DIR, SU._RETIRED_BUILD_DIRS
SU._REPO_DIR = repo
SU._RETIRED_BUILD_DIRS = saved[1] + ("native/linked",)
os.symlink(outside, os.path.join(repo, "native/linked/target"))
try:
    removed = SU._remove_retired_build_dirs()
    ex = lambda rel: os.path.exists(os.path.join(repo, rel))  # noqa: E731
    check("1. a retired crate's target/ and its emptied dir go",
          not ex("native/alghash2") and not ex("wasm/goldilocks")
          and {"native/alghash2/target", "native/alghash2", "wasm/goldilocks/target", "wasm/goldilocks"} <= set(removed),
          removed)
    check("2. a hand-made file in a retired crate stays (only target/ goes)",
          ex("native/starkcompose/Cargo.toml") and not ex("native/starkcompose/target"))
    check("3. a retired path git tracks again is untouched",
          ex("native/starkprove/target/release/lib.so") and not any(r.startswith("native/starkprove") for r in removed))
    check("4. a symlinked target/ is neither followed nor removed",
          os.path.islink(os.path.join(repo, "native/linked/target")) and os.path.exists(os.path.join(outside, "keep.so")))
    check("4. a second pass removes nothing", SU._remove_retired_build_dirs() == [])
    check("5. a live crate's build output is never touched", ex("native/mldsa44/target/release/lib.so"))
finally:
    SU._REPO_DIR, SU._RETIRED_BUILD_DIRS = saved

src = open(SU.__file__).read()
body = src[src.index("\ndef check_and_update("):]
body = body[:body.index("\ndef ", 10)]
check("6. every update check removes them, right after the fetch",
      '_latest_remote[0] = remote[:12]\n        _remove_retired_build_dirs()' in body)
check("6. the four paths are exactly the crates G9 deleted",
      SU._RETIRED_BUILD_DIRS == ("native/alghash2", "native/starkcompose", "native/starkprove", "wasm/goldilocks")
      and not set(SU._RETIRED_BUILD_DIRS) & set(SU._CRATES + SU._OPTIONAL_CRATES))
_report.done()
