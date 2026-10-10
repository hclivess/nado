"""scripts/run_tests.sh splits the suite into a fast and a slow tier by MEASURED time, starts the longest test first,
gives each test 3x its last measured time (never under the floor), learns from a timeout, keeps its measurements
outside the checkout, and reports every skip with its reason.

WHY (2026-10-10). The full suite took 1 h 56 min wall: 444 tests under 60 s took 1,776 CPU-s and 62 tests took 24,699,
and they started in alphabetical order, so the run ended on whichever hour-long test's letter came last. The 900 s
default timed out test_settlement_proof (never on the hand-kept SLOW list) while test_recursive_verify_hetero (876 s)
and test_wide_pool_depth (748 s) passed within minutes of the same cap. And the runner counted SKIP lines but said OK,
so a test that skipped its whole point looked green.

Drives the real runner on throwaway tests with a throwaway times file. Run: python3 tests/test_runner_schedules_longest_first_in_measured_tiers.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): a throwaway HOME, never the live node's
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-runner-tiers-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import glob, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNNER = os.path.join(ROOT, "scripts", "run_tests.sh")
D = os.environ["HOME"]
TIMES = os.path.join(D, "times.tsv")
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


def fake(name, body):
    p = os.path.join(D, name + ".py")
    open(p, "w").write(body)
    return p


def run(args, **env):
    e = dict(os.environ, PY=sys.executable, NADO_TEST_TIMES=TIMES, NADO_TEST_JOBS="1", **env)
    r = subprocess.run(["bash", RUNNER, *args], cwd=ROOT, capture_output=True, text=True, timeout=300, env=e)
    for d in re.findall(r"logs in (/tmp/nado-tests\.\w+)", r.stdout):     # a red run keeps its logs; these are ours
        shutil.rmtree(d, ignore_errors=True)
    return r


def times():
    return {l.split("\t")[0]: l.rstrip("\n").split("\t") for l in open(TIMES)} if os.path.exists(TIMES) else {}


quick = fake("test_zz_quick", 'print("PASS  quick")\n')
long_ = fake("test_aa_long", 'print("PASS  long")\n')
skip = fake("test_mm_skips", 'print("SKIP  no TPM on this box")\nprint("SKIP  no TPM on this box")\nprint("PASS  rest")\n')
hang = fake("test_hh_hang", "import time; time.sleep(60)\n")
pat = " ".join([quick, long_, skip])

# measured: long = 600 s (slow tier), quick = 2 s, skips = 1 s. Re-seeded before every run, because a run records
# what it measured and a measurement always wins (these fakes really take ~0 s)
def seed():
    open(TIMES, "w").write("test_aa_long\t600\tOK\t0\ntest_zz_quick\t2\tOK\t0\ntest_mm_skips\t1\tOK\t0\n")


seed()

r = run([pat])
order = [m.group(1) for m in re.finditer(r"^OK\s.*?(test_\w+)", r.stdout, re.M)]
check("the full run starts the longest-measured test first, whatever its name", order[:1] == ["test_aa_long"], r.stdout)
check("a green run exits 0 and says so", r.returncode == 0 and "0 failed" in r.stdout, r.stdout[-300:])
check("every test that skipped is listed with its reason (and counted once per distinct line)",
      re.search(r"test_mm_skips \(OK\):\n\s+2 SKIP  no TPM on this box", r.stdout) is not None, r.stdout)
check("a declared skip does not fail the run", r.returncode == 0)
check("the run recorded what it measured (the next run schedules by it)",
      times().get("test_aa_long", ["", "600"])[1] != "600" and times()["test_aa_long"][2] == "OK", times())

seed()

r = run(["--fast", pat])
check("--fast runs only tests measured under 60 s and lists the rest as DEFERRED with their time",
      "test_aa_long" not in re.sub(r"DEFERRED.*", "", r.stdout) and re.search(r"DEFERRED ~600s \(measured\) \S*test_aa_long", r.stdout)
      and "test_zz_quick" in r.stdout and r.returncode == 0, r.stdout)
seed()
r = run(["--slow", pat])
ran = re.findall(r"^OK\s.*?(test_\w+)", r.stdout, re.M)
check("--slow runs only the slow tier", ran == ["test_aa_long"], r.stdout)

# a test with no measurement on this machine falls back to the SLOW list in the runner
os.remove(TIMES)
src = open(RUNNER).read()
slow = dict(re.findall(r"^(test_\w+) (\d+)$", src, re.M))
for n in ("test_settlement_proof", "test_recursive_verify_hetero", "test_wide_pool_depth", "test_settle_fold_tree"):
    check(f"{n} (timed out, or ran within minutes of the old 900 s cap) is on the fallback SLOW list", n in slow)
r = run(["--fast", os.path.join(ROOT, "tests", "test_settle_fold_tree.py")])
check("with no measurement, a test on the SLOW list is slow tier (deferred by --fast, nothing run)",
      "DEFERRED" in r.stdout and "slow-list" in r.stdout and "0 ok" in r.stdout, r.stdout)

# timeout = max(floor, 3 x measured); a TIMEOUT is recorded at what it hit so the next run gets 3x that
open(TIMES, "w").write("test_hh_hang\t1\tOK\t0\n")
r = run([hang], NADO_TEST_TIMEOUT="2")
t = times().get("test_hh_hang", [])
check("a test measured at 1 s gets max(floor 2, 3 x 1) = 3 s and is reported TIMEOUT",
      re.search(r"^TIMEOUT\s.*test_hh_hang [34]s", r.stdout, re.M) is not None and r.returncode == 1, r.stdout)
check("the timeout is recorded at the time it hit, so the next run allows 3x that",
      len(t) >= 3 and t[2] == "TIMEOUT" and 3 <= int(t[1]) <= 4, t)

# measurements live outside the checkout by default: a file the runner rewrote at a tracked path would be a dirty
# tree the fleet's fast-forward must fight
m = re.search(r"^TIMES=\$\{NADO_TEST_TIMES:-(.*)\}$", src, re.M)
check("the default times file is under the user's cache dir, not the checkout",
      m is not None and "HOME" in m.group(1) and ".cache" in m.group(1) and not m.group(1).startswith(("tests", ".", "$OUT")),
      m and m.group(1))
check("the default job count is half the CPUs", "NCPU / 2" in src and "NADO_TEST_JOBS:-$((" in src)

hook = open(os.path.join(ROOT, "scripts", "git-hooks", "pre-push")).read()
check("the pre-push hook runs the touched tests' fast tier only (a push never waits on hour-long proofs)",
      "run_tests.sh --fast" in hook and "--slow" not in hook.replace("run_tests.sh --slow` before", ""))
check("the runner, and the hook's touched-test list, take every test kind: .py, .mjs and .js",
      all(f"tests/test_*.{x}" in src for x in ("py", "mjs", "js")) and all(f"'tests/test_*.{x}'" in hook for x in ("py", "mjs", "js")))

print("ALL PASS — tiers by measured time, longest first, 3x timeouts, skips reported" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
