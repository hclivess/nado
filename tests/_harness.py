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


# ---- GATES ACROSS A REROLL (gen-29 rehearsal, 2026-10-25) ----------------------------------------------------------
# A test that pins a gate's DORMANT behaviour used to read the shipped constant ("2^62 on generation 28"), so the day the
# generation moved every such check failed although nothing was wrong: the old rule is still needed — the previous
# generation's history replays through it until its cleanup — it is just no longer the shipped value. Two helpers say
# what such a test means: the gate's value AT a generation (its protocol.py expression, as test_gate_reroll_transfer
# reads it), and the old rule run explicitly under that value.
def gate_at(name, generation):
    """protocol.py's `name = <expr>` evaluated with CHAIN_GENERATION = `generation` (the GATE LEDGER form)."""
    import re
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "protocol.py")).read()
    m = re.search(r"^" + name + r" = ([^#\n]+)", src, re.M)
    if not m:
        raise KeyError(f"{name} is not a gate in protocol.py")
    return eval(m.group(1).strip(), {"CHAIN_GENERATION": int(generation)})   # noqa: S307 - our own constant expression


class pinned:
    """`with pinned(SIG_SCHEMES_HEIGHT=1 << 62): ...` — protocol gates set to these values inside the block, restored after
    (the module attribute: code that reads `protocol.X` at call time sees it)."""

    def __init__(self, **gates):
        self.gates = gates
        self.saved = {}

    def __enter__(self):
        import protocol
        for k, v in self.gates.items():
            self.saved[k] = getattr(protocol, k)
            setattr(protocol, k, v)
        return self

    def __exit__(self, *exc):
        import protocol
        for k, v in self.saved.items():
            setattr(protocol, k, v)
        return False


def exit_module(cursor=0):
    """The exit verifier L1 uses for a settled root AT `cursor` — execnode/exec_root_b2 at every cursor (BLAKE_EXEC_HEIGHT,
    gen 28's gate, inlined in G9). A test that proves an exit with exec_root.py directly tests generation 28's verifier
    only; the gen-29 rehearsal found six such tests unable to verify a gen-29 exit because they named the old module,
    not because the exit was wrong."""
    from execnode import exec_root_b2 as R2
    return R2
