"""NO TEST MAY OPEN THE LIVE EXEC NODE'S FILES (2026-09-24).

CLAUDE.md rule 4 made every test assign a throwaway HOME before importing the node, because `import nado` opens a
write transaction on the live LMDB. The exec node has a SECOND path that HOME does not cover: execnode/execnode.py
resolves `STATE_PATH = os.environ.get("NADO_EXEC_STATE", "exec_state.json")` — relative to the WORKING DIRECTORY —
and at import time it reads the state, restores the settle stash, warms the fold cache and re-stamps the `.gen`
marker there. Run from /srv/nado-home/nado, which is the live checkout, a test importing it touched the live exec
node's files. Found 2026-09-24 when a new settle test printed "settle stash: restored 6 pre-state(s)" with the live
cursors and the live `.gen` mtime moved mid-run; eight tests carried the hazard, one of them with no HOME at all.

Static, so it costs nothing and catches the next test before it runs: every test that imports execnode.execnode must
ASSIGN HOME, NADO_EXEC_STATE and NADO_EXEC_DA (the DA dir is CWD-relative too, and a generation mismatch
rmtree()s it at import) before that import, or re-run itself in a child whose environment names all three. `setdefault` does not count — a shell or a service
environment may already carry the variable, which is exactly the setdefault(HOME) trap rule 4 records.

Run: python3 tests/test_tests_never_touch_live_exec_state.py
"""
import os
import re
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
IMPORT = re.compile(r"^\s*(from\s+execnode\s+import\s+[^\n]*\bexecnode\b|from\s+execnode\.execnode\s+import|import\s+execnode\.execnode)", re.M)
ASSIGN_HOME = re.compile(r'^\s*os\.environ\["HOME"\]\s*=', re.M)
ASSIGN_EXEC = re.compile(r'^\s*os\.environ\["NADO_EXEC_STATE"\]\s*=', re.M)
ASSIGN_DA = re.compile(r'^\s*os\.environ\["NADO_EXEC_DA"\]\s*=', re.M)
# The other safe shape: the test re-runs ITSELF in a child whose environment names all three (test_exec_rewind_e2e).
def _child_env_names_all_three(head):
    i = head.find("dict(os.environ,")
    win = head[i:i + 600] if i >= 0 else ""
    return all(re.search(rf"\b{k}=", win) for k in ("HOME", "NADO_EXEC_STATE", "NADO_EXEC_DA"))


def offenders():
    bad = []
    for name in sorted(os.listdir(TESTS)):
        if not name.endswith(".py") or name == os.path.basename(__file__):
            continue
        src = open(os.path.join(TESTS, name), encoding="utf-8", errors="replace").read()
        m = IMPORT.search(src)
        if not m:
            continue
        head = src[:m.start()]
        if _child_env_names_all_three(head):
            continue
        missing = [what for what, rx in (("HOME", ASSIGN_HOME), ("NADO_EXEC_STATE", ASSIGN_EXEC),
                                         ("NADO_EXEC_DA", ASSIGN_DA)) if not rx.search(head)]
        if missing:
            bad.append(f"{name}: imports execnode.execnode (line {src[:m.start()].count(chr(10)) + 1}) without first "
                       f"assigning {', '.join(missing)}")
    return bad


def self_check():
    """The detector must see every import form in use, or a green run means nothing."""
    for form in ("from execnode import execnode as X", "from execnode.execnode import _apply_block",
                 "import execnode.execnode", "    from execnode.execnode import _apply_block"):
        assert IMPORT.search(form), f"detector misses {form!r}"
    assert not IMPORT.search("from execnode import state"), "detector must not flag other execnode modules"


if __name__ == "__main__":
    self_check()
    bad = offenders()
    for b in bad:
        print("FAIL  " + b)
    print("ALL PASS — no test can open the live exec node's files" if not bad else f"{len(bad)} FAILURES")
    sys.exit(1 if bad else 0)
