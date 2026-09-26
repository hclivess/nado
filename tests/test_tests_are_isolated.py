"""NO TEST TOUCHES THE LIVE NODE unless it is declared a live test (CLAUDE.md rule 4; complements
tests/test_tests_never_touch_live_exec_state.py, which covers the exec node's CWD-relative files).

This checkout IS the live node. Found 2026-09-26: 60 tests imported node code that reaches kv_ops (ops, memserver,
genesis, nado, loops) without assigning a throwaway HOME first — under scripts/run_tests.sh every test gets its own HOME,
but run directly from a shell (the way single tests are run) they opened /root/nado, the live database; one set
NADO_HOME=/root/nado, a variable nothing reads, believing it isolated itself. Seven put /root/nado on sys.path, so run
from a worktree they tested the LIVE code instead of the change. And test_otc_swap_e2e posts real transactions with the
operator's keys while matching the runner's test_*.py glob.
Pins, for every tests/*.py: (1) it ASSIGNS HOME before its first import of ops / memserver / genesis / nado / loops (or
re-runs itself in a child whose environment names HOME); (2) it never puts the live checkout on sys.path or opens a
file under it; (3) a URL to the live node's ports in CODE (not prose) appears only in a file listed in LIVE, and
scripts/run_tests.sh skips every LIVE file.

Run: python3 tests/test_tests_are_isolated.py
"""
import ast
import os
import re
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
LIVE = {"test_otc_swap_e2e.py"}          # posts real transactions to 127.0.0.1:9173 with the operator's keys — run by hand
DANGER = re.compile(r"^\s*(from\s+(ops|memserver|genesis|nado|loops)\b|import\s+(ops|memserver|genesis|nado|loops)\b)", re.M)
ASSIGN_HOME = re.compile(r'^\s*_?os\.environ\["HOME"\]\s*=', re.M)
LIVE_URL = re.compile(r"^https?://(127\.0\.0\.1|localhost|\[::1\]):9[12]73")   # a REQUEST, not a peer key or Host header


def _code_strings(src):
    """String constants in CODE — module, class and function docstrings excluded."""
    tree = ast.parse(src)
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                docs.add(id(first.value))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def offenders():
    bad = []
    for name in sorted(os.listdir(TESTS)):
        if not name.endswith(".py") or name == os.path.basename(__file__):
            continue
        src = open(os.path.join(TESTS, name), encoding="utf-8", errors="replace").read()
        m = DANGER.search(src)
        if m and name not in LIVE and not ASSIGN_HOME.search(src[:m.start()]) and "dict(os.environ," not in src[:m.start()]:
            bad.append(f"{name}: imports node code (line {src[:m.start()].count(chr(10)) + 1}) before assigning a throwaway HOME")
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        if re.search(r'sys\.path\.insert\(0,\s*["\']/(root/nado|srv/nado-home/nado)', code) or \
                re.search(r'open\(\s*["\']/(root/nado|srv/nado-home/nado)/', code):
            bad.append(f"{name}: reads code or files from the live checkout instead of its own tree")
        if name not in LIVE and any(LIVE_URL.match(s) for s in _code_strings(src)):
            bad.append(f"{name}: talks to the live node's ports in code but is not listed in LIVE")
    runner = open(os.path.join(ROOT, "scripts", "run_tests.sh")).read()
    for n in sorted(LIVE):
        if n.rsplit(".", 1)[0] not in runner:
            bad.append(f"scripts/run_tests.sh does not skip the live test {n}")
    return bad


def self_check():
    """The detectors must fire on what they exist to catch, or a green run means nothing."""
    assert DANGER.search("from ops import kv_ops") and DANGER.search("import memserver") and not DANGER.search("from execnode.stark import stark")
    assert ASSIGN_HOME.search('os.environ["HOME"] = x') and not ASSIGN_HOME.search('os.environ.setdefault("HOME", x)')
    assert LIVE_URL.match("http://127.0.0.1:9173/status") and LIVE_URL.match("http://localhost:9273") \
        and not LIVE_URL.match("http://127.0.0.2:19173") and not LIVE_URL.match("127.0.0.1:9173")
    assert _code_strings('"""doc http://127.0.0.1:9173"""\nX = 1') == []


if __name__ == "__main__":
    self_check()
    bad = offenders()
    for b in bad:
        print("FAIL  " + b)
    print("ALL PASS — no test can touch the live node unless it is declared live" if not bad else f"{len(bad)} FAILURES")
    sys.exit(1 if bad else 0)
