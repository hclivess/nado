"""The pre-push hook refuses a code change that ships without a test (scripts/git-hooks/pre-push; CLAUDE.md rule 11).

Every push to the fleet leaves from this checkout, so the hook is where "every change ships with its test" is enforced
instead of remembered (8 code commits of the 2026-09-26 session had none). Pins, in a throwaway clone: a commit that
changes code and no test is refused before anything runs; the same commit with "[no-test: <reason>]" in its message
passes that check and reaches the core guards; a doc-only commit needs no test.

Run: python3 tests/test_pre_push_hook_requires_tests.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-hook-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "scripts", "git-hooks", "pre-push")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def git(repo, *a):
    return subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, check=True).stdout.strip()


repo = os.path.join(os.environ["HOME"], "r")
os.makedirs(os.path.join(repo, "ops")); os.makedirs(os.path.join(repo, "doc")); os.makedirs(os.path.join(repo, "tests"))
env_git = ["-c", "user.name=t", "-c", "user.email=t@t"]
subprocess.run(["git", "init", "-q", repo], check=True)
open(os.path.join(repo, "ops", "x.py"), "w").write("X = 1\n")
git(repo, "add", "-A"); git(repo, *env_git, "commit", "-qm", "base")
base = git(repo, "rev-parse", "HEAD")
git(repo, "update-ref", "refs/remotes/origin/main", base)


def push_check(msg, path, text):
    open(os.path.join(repo, path), "w").write(text)
    git(repo, "add", "-A"); git(repo, *env_git, "commit", "-qm", msg)
    head = git(repo, "rev-parse", "HEAD")
    r = subprocess.run(["bash", HOOK], input=f"refs/heads/main {head} refs/heads/main {base}\n", cwd=repo,
                       capture_output=True, text=True, env={**os.environ, "PY": sys.executable})
    git(repo, "reset", "-q", "--hard", base)
    return r


r = push_check("change code, no test", "ops/x.py", "X = 2\n")
check("a code change without a test is refused", r.returncode != 0 and "without a test" in r.stdout, r.stdout[-300:])
check("... before any guard runs", "core guards" not in r.stdout)
r = push_check("change code\n\n[no-test: a constant nothing reads yet]", "ops/x.py", "X = 3\n")
check("with [no-test: <reason>] it passes the test check and reaches the core guards",
      "without a test" not in r.stdout and "core guards" in r.stdout, r.stdout[-300:])
r = push_check("docs", "doc/a.md", "words\n")
check("a doc-only change needs no test", "without a test" not in r.stdout and "core guards" in r.stdout, r.stdout[-300:])
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
