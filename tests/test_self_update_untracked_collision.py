"""The updater must fast-forward over an UNTRACKED file that the target commit tracks.

2026-09-07 fleet stall: commit 070023a9 shipped native/attest without a Cargo.lock, every node's cargo build wrote
an untracked one, the next commit tracked that path, and `git merge --ff-only` refused on every peer forever
("untracked working tree files would be overwritten by merge"). ops/self_update._move_aside_untracked_collisions
renames such files to <path>.local-<ts> before the merge; this test rebuilds that exact situation in a scratch
repository and proves (a) git really refuses, (b) the helper moves ONLY the colliding file, (c) the fast-forward
then lands, (d) nothing was deleted. It also pins the two conventions that keep the class away: no crate tracks
Cargo.lock at the path cargo writes (Cargo.lock.pinned instead), and _build_crates copies the pinned lock in.
"""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="nado-su-home-"))

fails = 0


def check(name, cond, detail=""):
    global fails
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        fails += 1


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


def t_scratch_repo():
    from ops import self_update as SU
    d = tempfile.mkdtemp(prefix="nado-su-ff-")
    origin, work = os.path.join(d, "origin"), os.path.join(d, "work")
    os.makedirs(os.path.join(origin, "native", "x"))
    git(origin, "init", "-q", "-b", "main")
    open(os.path.join(origin, "native", "x", "Cargo.toml"), "w").write("[package]\n")
    git(origin, "add", "."); git(origin, "commit", "-qm", "crate without a lock")
    subprocess.run(["git", "clone", "-q", origin, work], check=True, capture_output=True)
    # the node "built" the crate: cargo wrote an untracked lock; and an unrelated scratch file exists
    open(os.path.join(work, "native", "x", "Cargo.lock"), "w").write("built locally\n")
    open(os.path.join(work, "notes.txt"), "w").write("operator scratch\n")
    # the next official commit tracks the lock path
    open(os.path.join(origin, "native", "x", "Cargo.lock"), "w").write("tracked\n")
    git(origin, "add", "."); git(origin, "commit", "-qm", "track the lock")
    git(work, "fetch", "-q", "origin")
    r = subprocess.run(["git", "merge", "--ff-only", "--quiet", "origin/main"], cwd=work, capture_output=True, text=True)
    check("git refuses the fast-forward over the untracked lock (the 2026-09-07 stall)",
          r.returncode != 0 and "untracked working tree files" in r.stderr, r.stderr[:200])
    SU._REPO_DIR, saved = work, SU._REPO_DIR
    try:
        moved = SU._move_aside_untracked_collisions("origin/main")
    finally:
        SU._REPO_DIR = saved
    check("only the colliding file is moved aside", moved == ["native/x/Cargo.lock"], moved)
    kept = [f for f in os.listdir(os.path.join(work, "native", "x")) if f.startswith("Cargo.lock.local-")]
    check("the local file is renamed beside itself, not deleted",
          len(kept) == 1 and open(os.path.join(work, "native", "x", kept[0])).read() == "built locally\n", kept)
    check("unrelated untracked files are untouched", os.path.exists(os.path.join(work, "notes.txt")))
    r = subprocess.run(["git", "merge", "--ff-only", "--quiet", "origin/main"], cwd=work, capture_output=True, text=True)
    check("the fast-forward lands afterwards", r.returncode == 0 and git(work, "rev-parse", "HEAD") == git(origin, "rev-parse", "HEAD"), r.stderr[:200])
    check("the tracked lock is what git checked out", open(os.path.join(work, "native", "x", "Cargo.lock")).read() == "tracked\n")


def t_conventions():
    from ops import self_update as SU
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    attest_lock = [p for p in tracked if p == "native/attest/Cargo.lock"]
    check("native/attest tracks Cargo.lock.pinned, never Cargo.lock (cargo writes that path on every node)",
          not attest_lock and "native/attest/Cargo.lock.pinned" in tracked)
    check("native/attest ignores the cargo-written lock", "Cargo.lock" in open(os.path.join(ROOT, "native/attest/.gitignore")).read().split())
    src = open(SU.__file__).read()
    check("the ff path moves collisions aside before merging",
          src.index("_move_aside_untracked_collisions(remote)") < src.index('"merge", "--ff-only"'))
    check("_build_crates copies Cargo.lock.pinned in before cargo build",
          "Cargo.lock.pinned" in src.split("def _build_crates")[1].split("\ndef ")[0])


if __name__ == "__main__":
    t_scratch_repo()
    t_conventions()
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
