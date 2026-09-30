"""CI moves a test, it never drops one (tests/ci_exclude.txt, scripts/run_tests.sh NADO_TEST_EXCLUDE,
.github/workflows/ci.yml).

WHY (2026-09-30, the CI the operator asked for). Every push runs the suite on GitHub without the Rust kernels, so the
tests that need them or prove for hours are excluded there — and an exclusion list is where coverage goes to die
quietly. These pins keep it honest: every line names a test that exists and says why; the runner prints each exclusion
with its reason instead of hiding it; and the workflow's native job runs exactly the excluded tests.

Run: python3 tests/test_ci_exclude_is_honest.py
"""
import os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


rows = [l.split(None, 1) for l in open(os.path.join(ROOT, "tests", "ci_exclude.txt")) if l.strip() and not l.startswith("#")]
missing = [r[0] for r in rows if not os.path.exists(os.path.join(ROOT, "tests", r[0] + ".py"))]
check("every excluded test exists (a renamed test must not leave a dead line that hides nothing)", not missing, missing)
check("every exclusion gives its reason", all(len(r) == 2 and len(r[1].strip()) > 10 for r in rows),
      [r[0] for r in rows if len(r) < 2])
check("no test is excluded twice", len({r[0] for r in rows}) == len(rows))

wf = open(os.path.join(ROOT, ".github", "workflows", "ci.yml")).read()
check("the per-push suite uses the exclusion list", "NADO_TEST_EXCLUDE=tests/ci_exclude.txt" in wf)
check("the native job runs exactly the excluded tests", "grep -v '^#' tests/ci_exclude.txt" in wf and "cargo build --release" in wf)

# the runner prints an exclusion with its reason and does not run the test
d = tempfile.mkdtemp(prefix="nado-test-ciex-")
ex = os.path.join(d, "ex.txt")
open(ex, "w").write("test_ci_exclude_is_honest  a reason long enough to be read\n")
r = subprocess.run(["bash", os.path.join(ROOT, "scripts", "run_tests.sh"), "tests/test_ci_exclude_is_honest.py"],
                   cwd=ROOT, capture_output=True, text=True, timeout=120,
                   env=dict(os.environ, NADO_TEST_EXCLUDE=ex, PY=sys.executable))
check("the runner lists an excluded test as EXCLUDED with its reason, and runs nothing for it",
      "EXCLUDED" in r.stdout and "a reason long enough to be read" in r.stdout and "0 ok" in r.stdout, r.stdout[-400:])
import shutil; shutil.rmtree(d, ignore_errors=True)
print("ALL PASS — CI moves a test, it never drops one" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
