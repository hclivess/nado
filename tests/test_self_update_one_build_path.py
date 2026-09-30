"""The updater has ONE way to build a native crate, and the update path and the rollback both use it correctly.

1. A COMMIT THAT CHANGES ONLY Cargo.lock.pinned MUST REBUILD AGAINST THE NEW PIN. _rebuild_native_if_changed
   matched `.pinned` as a reason to rebuild and then ran a bare `cargo build` — without copying the pinned lock
   in. The crate built against the node's OLD untracked Cargo.lock, reported "built", and nothing corrected it
   later (native_guard.is_stale compares against Cargo.lock, not .pinned): the node ran the old dependency set
   indefinitely, the cross-node divergence the pin exists to prevent. The bare call also skipped restoring a
   tracked Cargo.lock cargo rewrote — a dirty tracked file refuses every later update. The update path now goes
   through _build_crates, which does both.

2. A FAILED FAST-FORWARD PUTS BACK THE COPY THIS UPDATE MOVED, not the oldest `<file>.local-*` beside it. The
   rollback took sorted(listdir)'s first match, so with an older copy already there (they are never deleted) it
   restored a previous edit over the current one and left the current one aside.

3. A MOVED-ASIDE FILE IS NAMED UNDER update_warnings (CLAUDE.md, "Deploying"). The move restores HEAD's copy, so
   the dirty-files check never saw it, and the list rode only in the /update reply that periodic and peer-hinted
   checks discard: /status never named it.

4. A RENAME COUNTS BOTH PATHS. git's default rename detection makes `diff --name-only` print only the NEW path:
   moving a code file into doc/ read as documentation-only (no restart), and an upstream rename A -> B did not
   move a local edit to A aside, so the merge refused and the node answered `blocked`.

Real git repositories and a stand-in `cargo` on PATH that records which Cargo.lock it was handed.
"""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-test-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
import os
import stat
import subprocess
import sys
import tempfile

import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ops import self_update as SU  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  -- " + str(detail)[:200]) if (detail and not cond) else ""))
    if not cond:
        fails.append(name)


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


def write(root, rel, text):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


def fake_cargo(bindir, record):
    """A `cargo` that records the Cargo.lock it builds against, "rewrites" the lock the way a newer cargo does,
    and leaves a fresh .so — everything the updater observes of a real build."""
    os.makedirs(bindir, exist_ok=True)
    p = os.path.join(bindir, "cargo")
    with open(p, "w") as f:
        f.write(f"""#!/bin/sh
cat Cargo.lock >> {record} 2>/dev/null || echo MISSING >> {record}
echo "# rewritten by cargo" >> Cargo.lock
mkdir -p target/release && : > target/release/libnado_fake.so
""")
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def pinned_case(bindir, record):
    d = tempfile.mkdtemp(prefix="nado-su-pin-")
    write(d, "native/p/Cargo.toml", "[package]\n"); write(d, "native/p/src/lib.rs", "// rust\n")
    write(d, "native/p/Cargo.lock.pinned", "lock v1\n"); write(d, "native/p/.gitignore", "Cargo.lock\ntarget/\n")
    git(d, "init", "-q", "-b", "main"); git(d, "add", "."); git(d, "commit", "-qm", "v1")
    old = git(d, "rev-parse", "HEAD")
    write(d, "native/p/Cargo.lock", "lock v1\n")                          # the node's untracked lock from its last build
    write(d, "native/p/target/release/libnado_fake.so", "")
    write(d, "native/p/Cargo.lock.pinned", "lock v2\n")                   # the update bumps ONLY the pin
    git(d, "add", "."); git(d, "commit", "-qm", "v2")
    new = git(d, "rev-parse", "HEAD")
    SU._REPO_DIR, SU._CRATES = d, ("native/p",)
    open(record, "w").close()
    report = SU._rebuild_native_if_changed(old, new)
    check("a pin-only change is rebuilt", report == {"native/p": "built"}, report)
    seen = open(record).read()
    check("...against the NEW pinned lock, not the node's old Cargo.lock", seen.startswith("lock v2"), seen)


def tracked_lock_case(bindir, record):
    d = tempfile.mkdtemp(prefix="nado-su-lock-")
    write(d, "native/q/Cargo.toml", "[package]\n"); write(d, "native/q/src/lib.rs", "// v1\n")
    write(d, "native/q/Cargo.lock", "tracked lock\n"); write(d, "native/q/.gitignore", "target/\n")
    git(d, "init", "-q", "-b", "main"); git(d, "add", "."); git(d, "commit", "-qm", "v1")
    old = git(d, "rev-parse", "HEAD")
    write(d, "native/q/src/lib.rs", "// v2\n"); git(d, "add", "."); git(d, "commit", "-qm", "v2")
    new = git(d, "rev-parse", "HEAD")
    SU._REPO_DIR, SU._CRATES = d, ("native/q",)
    report = SU._rebuild_native_if_changed(old, new)
    check("a source change is rebuilt", report == {"native/q": "built"}, report)
    check("...and the tracked Cargo.lock cargo rewrote is restored, so the next update is not refused",
          git(d, "status", "--porcelain", "--untracked-files=no") == "", git(d, "status", "--porcelain"))


def rollback_case():
    d = tempfile.mkdtemp(prefix="nado-su-rollback-")
    write(d, "x.txt", "current edit\n")
    write(d, "x.txt.local-1700000000", "an OLDER edit from a previous update\n")
    SU._REPO_DIR = d
    moved = SU._move_aside(["x.txt"])
    check("the current edit was moved aside", moved == ["x.txt"] and not os.path.exists(os.path.join(d, "x.txt")))
    SU._restore_moved_aside(moved)
    check("the rollback puts back THIS update's copy",
          open(os.path.join(d, "x.txt")).read() == "current edit\n", open(os.path.join(d, "x.txt")).read())
    check("...and leaves the older copy where it was",
          open(os.path.join(d, "x.txt.local-1700000000")).read().startswith("an OLDER edit"))


def warnings_case():
    d = tempfile.mkdtemp(prefix="nado-su-warn-")
    write(d, "a.txt", "a\n"); git(d, "init", "-q", "-b", "main"); git(d, "add", "."); git(d, "commit", "-qm", "v1")
    SU._REPO_DIR = d
    r = SU.updatability(probe_remote=False)
    check("a clean checkout names nothing as moved aside", r["checks"].get("moved_aside") == [], r["checks"])
    write(d, "a.txt.local-1790000000", "an edit an update moved\n")
    write(d, "notes.local-draft", "not the updater's naming\n")
    r = SU.updatability(probe_remote=False)
    check("an update's moved-aside copy is listed", r["checks"].get("moved_aside") == ["a.txt.local-1790000000"],
          r["checks"].get("moved_aside"))
    check("...and named under update_warnings", any("a.txt.local-1790000000" in w for w in r["warnings"]),
          r["warnings"])
    check("...as a warning, never a block", not any("local-" in b for b in r["blocking"]), r["blocking"])


def rename_case():
    body = "".join(f"line {i}\n" for i in range(200))   # long enough for git to call the move a rename
    d = tempfile.mkdtemp(prefix="nado-su-rename-")
    write(d, "ops/x.py", body); write(d, "ops/a.py", body + "a\n")
    git(d, "init", "-q", "-b", "main"); git(d, "add", "."); git(d, "commit", "-qm", "v1")
    old = git(d, "rev-parse", "HEAD")
    os.makedirs(os.path.join(d, "doc"))
    git(d, "mv", "ops/x.py", "doc/x.py"); git(d, "commit", "-qm", "move code into doc/")
    new = git(d, "rev-parse", "HEAD")
    SU._REPO_DIR = d
    check("git itself reports only the new path by default (the premise)",
          git(d, "diff", "--name-only", old, new) == "doc/x.py")
    check("moving a code file into doc/ still restarts", SU._restart_needed(old, new) is True)
    git(d, "checkout", "-q", old)                         # a node one commit behind, with a local edit
    git(d, "checkout", "-q", "-b", "node")
    git(d, "mv", "ops/a.py", "ops/b.py"); git(d, "commit", "-qm", "upstream rename")   # stand-in for origin
    upstream = git(d, "rev-parse", "HEAD")
    git(d, "checkout", "-q", old)
    write(d, "ops/a.py", body + "a LOCAL EDIT\n")
    moved = SU._move_aside_dirty_conflicts(upstream)
    check("a local edit to a path upstream renames away is moved aside", moved == ["ops/a.py"], moved)
    r = subprocess.run(["git", "merge", "--ff-only", "--quiet", upstream], cwd=d, capture_output=True, text=True)
    check("...so the fast-forward lands", r.returncode == 0, r.stderr)


def main():
    saved = (SU._REPO_DIR, SU._CRATES, os.environ.get("PATH", ""))
    bindir = tempfile.mkdtemp(prefix="nado-su-bin-")
    record = os.path.join(bindir, "seen.txt")
    fake_cargo(bindir, record)
    os.environ["PATH"] = bindir + os.pathsep + saved[2]
    try:
        pinned_case(bindir, record)
        tracked_lock_case(bindir, record)
        rollback_case()
        warnings_case()
        rename_case()
    finally:
        SU._REPO_DIR, SU._CRATES = saved[0], saved[1]
        os.environ["PATH"] = saved[2]


if __name__ == "__main__":
    main()
    print(("\nFAILED: " + "; ".join(fails)) if fails else "\nALL PASS")
    sys.exit(1 if fails else 0)
