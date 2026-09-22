"""THE UPDATER MUST FAST-FORWARD OVER A LOCAL EDIT, NOT REFUSE IT FOREVER.

check_and_update refused ANY dirty tracked file: "working tree has uncommitted changes — refusing to touch
local edits". On an unattended fleet node that refusal is permanent, because nobody is there to commit.

THE psychz WEEK (2026-09-13). psychz sat 15 commits behind for a day answering every update wave with that
line, missed the fix for the fork it was on, and was the last node still producing a dead branch. The edit
was almost certainly the fleet's OWN doing: _build_crates runs cargo in crates whose Cargo.lock is TRACKED
(only native/attest has a .pinned), cargo rewrites the lock, and from then on the node's own update path
refuses the node its updates. "it is crucial for the updates to be automatic."

The rule is now the one _move_aside_untracked_collisions already applies to untracked collisions: an edit
the incoming commit would change is moved aside as `<file>.local-<time>` — never deleted, named in the
reply — HEAD's copy is restored so git sees a clean path, and the fast-forward lands. An edit the commit
does not touch is left exactly where it is, because git fast-forwards over those. And a rebuild that
rewrote a tracked Cargo.lock puts HEAD's copy back, so the fleet's own wave can no longer brick the fleet.

Each check drives a REAL git repository, because "git would allow that" is exactly the kind of claim that
was wrong before.

Run: python3 tests/test_self_update_dirty_conflict.py
"""
import os, subprocess, sys, tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-su-home-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)   # leave no /tmp home behind (9,600 leaked by 2026-09-22)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import self_update as SU  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  -- " + str(detail)[:160]) if (detail and not cond) else ""))
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


def scratch():
    """origin with a.txt, b.txt and a tracked native/x/Cargo.lock; a clone `work` one commit behind."""
    d = tempfile.mkdtemp(prefix="nado-su-dirty-")
    origin, work = os.path.join(d, "origin"), os.path.join(d, "work")
    os.makedirs(origin)
    git(origin, "init", "-q", "-b", "main")
    write(origin, "a.txt", "a v1\n"); write(origin, "b.txt", "b v1\n")
    write(origin, "native/x/Cargo.lock", "lock v1\n"); write(origin, "native/x/Cargo.toml", "[package]\n")
    git(origin, "add", "."); git(origin, "commit", "-qm", "v1")
    subprocess.run(["git", "clone", "-q", origin, work], check=True, capture_output=True)
    write(origin, "a.txt", "a v2\n"); write(origin, "c.txt", "c v2\n")           # the update changes a, adds c
    git(origin, "add", "."); git(origin, "commit", "-qm", "v2")
    git(work, "fetch", "-q", "origin")
    return origin, work


def ff(work):
    return subprocess.run(["git", "merge", "--ff-only", "--quiet", "origin/main"], cwd=work,
                          capture_output=True, text=True)


# ---------------------------------------------------------------- a conflicting edit
origin, work = scratch()
write(work, "a.txt", "a LOCAL EDIT\n")            # the update changes a.txt -> conflict
write(work, "b.txt", "b LOCAL EDIT\n")            # the update does not touch b.txt -> not a conflict
r = ff(work)
check("git really refuses the fast-forward over a conflicting local edit", r.returncode != 0, r.stderr)

SU._REPO_DIR, saved = work, SU._REPO_DIR
try:
    moved = SU._move_aside_dirty_conflicts("origin/main")
    check("only the CONFLICTING edit is moved aside", moved == ["a.txt"], moved)
    kept = [n for n in os.listdir(work) if n.startswith("a.txt.local-")]
    check("...as <file>.local-<time> beside itself, never deleted", len(kept) == 1, os.listdir(work))
    check("...and the copy holds the local edit",
          kept and open(os.path.join(work, kept[0])).read() == "a LOCAL EDIT\n")
    check("...while the path itself is back to HEAD's copy", open(os.path.join(work, "a.txt")).read() == "a v1\n")
    check("the NON-conflicting edit is left exactly where it was",
          open(os.path.join(work, "b.txt")).read() == "b LOCAL EDIT\n")
    r = ff(work)
    check("the fast-forward lands afterwards, over the untouched edit to b.txt",
          r.returncode == 0 and git(work, "rev-parse", "HEAD") == git(origin, "rev-parse", "HEAD"), r.stderr)
    check("...and delivers the new a.txt", open(os.path.join(work, "a.txt")).read() == "a v2\n")
    check("...and b.txt still carries the local edit", open(os.path.join(work, "b.txt")).read() == "b LOCAL EDIT\n")
finally:
    SU._REPO_DIR = saved

# ---------------------------------------------------------------- a STAGED conflicting edit
origin, work = scratch()
write(work, "a.txt", "a STAGED EDIT\n"); git(work, "add", "a.txt")
SU._REPO_DIR = work
try:
    moved = SU._move_aside_dirty_conflicts("origin/main")
    check("a staged edit is moved aside too", moved == ["a.txt"], moved)
    check("...and the index is reset to HEAD as well (checkout HEAD --, not checkout --)",
          git(work, "diff", "--cached", "--name-only") == "")
    check("...so the fast-forward lands", ff(work).returncode == 0)
finally:
    SU._REPO_DIR = saved

# ---------------------------------------------------------------- nothing to do
origin, work = scratch()
SU._REPO_DIR = work
try:
    check("a clean tree moves nothing", SU._move_aside_dirty_conflicts("origin/main") == [])
    write(work, "b.txt", "b LOCAL EDIT\n")
    check("an edit the update does not touch moves nothing", SU._move_aside_dirty_conflicts("origin/main") == [])
finally:
    SU._REPO_DIR = saved

# ---------------------------------------------------------------- the rebuild that dirtied psychz
origin, work = scratch()
SU._REPO_DIR = work
try:
    crate = os.path.join(work, "native", "x")
    write(work, "native/x/Cargo.lock", "lock REWRITTEN BY CARGO\n")
    check("a tracked Cargo.lock cargo rewrote is restored to HEAD's copy",
          SU._restore_tracked_lock(crate) is True and open(os.path.join(crate, "Cargo.lock")).read() == "lock v1\n")
    check("...leaving the tree clean, so the next update is not refused", git(work, "diff", "--name-only") == "")
    check("an unchanged tracked lock is left alone", SU._restore_tracked_lock(crate) is False)
    os.makedirs(os.path.join(work, "native", "y"))
    write(work, "native/y/Cargo.lock", "untracked lock\n")
    check("an UNTRACKED lock is not git's business here (the untracked-collision helper owns it)",
          SU._restore_tracked_lock(os.path.join(work, "native", "y")) is False
          and os.path.exists(os.path.join(work, "native", "y", "Cargo.lock")))
finally:
    SU._REPO_DIR = saved

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nALL PASS")
sys.exit(1 if fails else 0)
