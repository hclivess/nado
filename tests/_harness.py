"""THE SHARED TEST PLUMBING (consolidation stage 1, 2026-10-18): isolation and the PASS/FAIL report, written once.

Before this, 564 test files each re-declared their own `check()` (51 variants) and their own throwaway-HOME setup — the
setup is the one thing a test must never get wrong (CLAUDE.md rule 4: `import nado` opens a WRITE transaction against
whatever HOME names), and 28 copies of it once used setdefault and wrote into the live node's home.

    import _harness                                   # tests/ is on sys.path when a test runs as a script
    HOME = _harness.isolate("nado-test-<topic>-")     # BEFORE any import of ops / memserver / genesis / nado / loops
    T = _harness.Report()
    T.check("refuses a reveal in the commitment's own block", ok, detail)
    T.run("a fresh node boots", fn)                   # fn raises on failure; the traceback is printed
    T.done("ALL PASS — <the property>")               # prints the summary and exits 1 on any failure

INVARIANT: this module imports nothing from the node (tests/test_tests_are_isolated.py treats `_harness.isolate(` as the
HOME assignment, which is only true while importing this module cannot reach kv_ops)."""
import atexit
import os
import shutil
import sys
import tempfile
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def isolate(prefix="nado-test-", exec_state=True):
    """A throwaway HOME (ASSIGNED, never setdefault — a shell always has HOME), removed at exit; with exec_state the
    exec node's CWD-relative state and DA paths too (tests/test_tests_never_touch_live_exec_state.py); and this tree on
    sys.path, so a test run from a worktree tests the worktree. Returns the HOME path."""
    home = tempfile.mkdtemp(prefix=prefix)
    os.environ["HOME"] = home
    if exec_state:
        os.environ["NADO_EXEC_STATE"] = os.path.join(home, "exec_state.json")
        os.environ["NADO_EXEC_DA"] = os.path.join(home, "exec_da")
    atexit.register(shutil.rmtree, home, ignore_errors=True)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    return home


class Report:
    """PASS/FAIL lines and the exit code. `fails` counts failed checks."""

    def __init__(self):
        self.fails = 0

    def check(self, name, ok, detail=""):
        """One property: PASS when `ok`, else FAIL with `detail` (any object; shown on failure only)."""
        print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
        self.fails += 0 if ok else 1
        return bool(ok)

    def run(self, name, fn):
        """One property as a function that raises on failure (assert); its traceback is printed."""
        try:
            fn()
            print(f"PASS  {name}")
            return True
        except Exception as e:
            self.fails += 1
            print(f"FAIL  {name}: {e}")
            traceback.print_exc()
            return False

    def done(self, ok_line="ALL PASS"):
        """Print `ok_line`, or the failure count, and exit with the matching status."""
        print(ok_line if not self.fails else f"{self.fails} FAILURES")
        sys.exit(1 if self.fails else 0)
