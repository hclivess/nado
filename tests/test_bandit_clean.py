import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-bandit-")   # CLAUDE.md rule 4 (this test imports no node code)
"""THE PRODUCTION TREE IS BANDIT-CLEAN AT MEDIUM AND ABOVE (2026-09-30, operator: add bandit).

Bandit is the Python security linter. Its first run over the production tree (every tracked .py outside tests/) found
a remote node kill that no unit test could: urllib and aiohttp follow redirects, so a peer answering
`302 -> http://127.0.0.1:9173/terminate` made the node GET its own loopback-authorized endpoint (B310 triage; fixed in
ops/outbound_guard.py, pinned by tests/test_outbound_never_follows_redirect_to_loopback.py). This keeps the tree there.

THE GATE: zero unsuppressed findings of MEDIUM or HIGH severity. LOW findings are PRINTED per test id, not failed:
they are B101 (assert — the consensus spine rejects via assert, and protocol.py refuses to start under -O, so asserts
are always live), B110/B112 (try/except/pass on best-effort paths), B404/B603/B607 (subprocess with a fixed argv list,
no shell), B311 (random for game ids, jitter and a local-cache spot check). Annotating ~770 such lines, most of them in
consensus files that are replay-proven, would bury the real signal; the per-id counts are printed so a jump is visible.

THE SUPPRESSION RULE: a finding that does not apply is suppressed on its own line as `# nosec BXXX # <reason>` — never a
bare `# nosec`, never a nosec without a reason, never a test id skipped tree-wide in pyproject.toml. (The second `#`
is needed: bandit reads every word after `nosec` as a test id until the next `#`.) This test enforces all three.

Runs bandit only if it is importable (the node's venv deliberately does not carry it); prints SKIP otherwise, or set
BANDIT=/path/to/bandit to use one from a throwaway venv. CI runs, from the checkout root:
    pip install "bandit==1.9.4"
    bandit -c pyproject.toml -r . --severity-level medium -q
Run: python3 tests/test_bandit_clean.py
"""
import collections
import io
import json
import re
import subprocess
import sys
import tokenize

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def _bandit_cmd():
    exe = os.environ.get("BANDIT")
    if exe:
        return [exe]
    try:
        import bandit  # noqa: F401
    except ImportError:
        return None
    return [sys.executable, "-m", "bandit"]


def _production_files():
    """Every tracked .py outside tests/ — the same set `bandit -r .` sees on a clean checkout with pyproject.toml's
    excludes, but immune to untracked scratch files in a working tree."""
    try:
        out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "*.py"], capture_output=True, timeout=60,
                             check=True).stdout.decode()
    except Exception as e:
        print(f"SKIP  git ls-files unavailable ({type(e).__name__}); cannot list the production tree")
        return None
    return sorted(f for f in out.split("\0") if f and not f.startswith("tests/") and os.path.isfile(os.path.join(ROOT, f)))


NOSEC = re.compile(r"#\s*nosec\b(?P<rest>.*)$")
PROPER = re.compile(r"^:?\s*(?P<ids>B\d{3}(?:\s*,\s*B\d{3})*)\s*#\s*(?P<why>\S.{9,})$")


def t1_every_nosec_names_an_id_and_a_reason(files):
    bad = []
    for rel in files:
        try:
            src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
            toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        except Exception:
            continue                                     # an unparseable file is reported by bandit itself
        for tok in toks:
            if tok.type != tokenize.COMMENT:
                continue
            m = NOSEC.search(tok.string)
            if m and not PROPER.match(m.group("rest").strip()):
                bad.append(f"{rel}:{tok.start[0]}: {tok.string.strip()[:100]}")
    check("every `# nosec` in production code names its test id(s) AND a reason (`# nosec BXXX # why`)",
          not bad, "\n      " + "\n      ".join(bad))


def t2_no_test_id_is_skipped_tree_wide():
    try:
        import tomllib
    except ImportError:
        print("SKIP  tomllib unavailable (Python < 3.11): pyproject.toml skip check not run")
        return
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        conf = tomllib.load(fh).get("tool", {}).get("bandit", {})
    check("pyproject.toml [tool.bandit] skips no test id tree-wide (suppress per line instead)",
          not conf.get("skips") and not conf.get("tests"), conf)
    excl = conf.get("exclude_dirs") or []
    check("pyproject.toml excludes only tests/venv/native/node_modules (nothing production)",
          set(excl) <= {"./tests/", "./nado_venv/", "./native/", "/node_modules/"}, excl)


def t3_zero_medium_or_high(cmd, files):
    argv = cmd + ["-c", os.path.join(ROOT, "pyproject.toml"), "-f", "json", "-q"] + files
    p = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=1800)
    try:
        report = json.loads(p.stdout)
    except ValueError:
        check("bandit produced a JSON report", False, (p.stderr or p.stdout)[-2000:])
        return
    errors = report.get("errors") or []
    check("bandit parsed every production file (a skipped file hides its findings)", not errors, errors[:10])
    results = report.get("results") or []
    serious = [r for r in results if r.get("issue_severity") in ("MEDIUM", "HIGH")]
    low = collections.Counter(r["test_id"] + " " + r["test_name"] for r in results if r.get("issue_severity") == "LOW")
    print(f"INFO  bandit scanned {len(files)} files; suppressed per line: "
          f"{report.get('metrics', {}).get('_totals', {}).get('skipped_tests', '?')}")
    for k, v in sorted(low.items()):
        print(f"INFO  LOW (reported, not failed) {v:5d}  {k}")
    detail = "\n      ".join(f"{r['test_id']} {r['issue_severity']} {r['filename']}:{r['line_number']}  "
                             f"{r['issue_text']}" for r in serious)
    check("zero unsuppressed MEDIUM/HIGH bandit findings in the production tree", not serious, "\n      " + detail)


if __name__ == "__main__":
    cmd = _bandit_cmd()
    files = _production_files()
    if files is not None:
        t1_every_nosec_names_an_id_and_a_reason(files)
    t2_no_test_id_is_skipped_tree_wide()
    if cmd is None:
        print("SKIP  bandit is not importable here (the node venv does not carry it): "
              "pip install bandit in a throwaway venv and set BANDIT=<venv>/bin/bandit, or let CI run it")
    elif files is not None:
        t3_zero_medium_or_high(cmd, files)
    print("ALL PASS" if not _fails else f"FAILED: {len(_fails)}: {_fails}")
    sys.exit(1 if _fails else 0)
