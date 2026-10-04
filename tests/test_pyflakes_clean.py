"""THE PRODUCTION TREE IS PYFLAKES-CLEAN: ZERO MESSAGES, OF EVERY CLASS.

WHY ZERO AND NOT "ONLY THE REAL BUGS". tests/test_no_undefined_names.py pins the one class that is a bug in every
instance (a NameError on a branch nothing executes). The other classes were left alone as matters of taste, and
they accumulated: on 2026-09-30 the operator asked for pyflakes and the tree carried 119 findings (76 unused
imports, 27 f-strings without placeholders, 13 unused locals, 2 redefinitions, 1 unused global — 107 of them on
main, the rest in the live e2e scripts and tools/replay_chain.py). They were not all taste. One was a real bug that only an "unused local" report could have shown:

  * scripts/nado_cli.py `register` fetched the anchor, asked the node for its required T and ran the WHOLE
    sequential PoSW proof — minutes of CPU — and only then raised "retired at gen 25". The unused `proof` was the
    whole symptom: the user waited out a proof nothing would ever submit.

A tree with a hundred accepted findings hides the next one of those in the noise; a tree with none makes it the
only line in the output. So the rule is zero, and a finding is fixed where it is found, not allow-listed here:
  - an unused import goes, after checking nothing imports the name THROUGH this module (tests included —
    tests/test_games_e2e.py read dice.TP/dice.TC, which dice only re-imported from execnode.games._lib);
  - an import kept for a side effect or an availability probe says so in code (importlib.util.find_spec, or a
    use), never silently — pyflakes does not honour `# noqa`, and a `noqa` that pyflakes ignores documents nothing;
  - an unused value whose COMPUTATION refuses bad input keeps the computation as a bare expression with a comment
    (execnode/state.py's joinsplit3 root parse, execnode/stark/fri_verify.py's blowup read, loops/core_loop.py's
    block_number int() in verify_block) — deleting a refusal is a behaviour change, not a cleanup.

Scope: every tracked *.py outside tests/ (the same set test_no_undefined_names.py reads). A file that does not parse
is a finding too — pyflakes checks nothing else in it.

Run: python3 tests/test_pyflakes_clean.py
"""
import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


if importlib.util.find_spec("pyflakes") is None:     # availability probe: the checks below run it as a subprocess
    print("FAIL  pyflakes is not installed — `pip install pyflakes` (it is in requirements.txt)")
    sys.exit(1)


def pyflakes(paths, cwd):
    """Every line pyflakes prints (stdout and stderr: syntax errors go to stderr) for `paths`."""
    proc = subprocess.run([sys.executable, "-m", "pyflakes"] + paths, cwd=cwd, capture_output=True, text=True)
    return [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()], proc.returncode


listed = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True)
files = [f for f in listed.stdout.split() if not f.startswith("tests/")]
check(len(files) > 50, f"found the production sources to scan ({len(files)} files)")
if listed.returncode != 0:          # e.g. git's "dubious ownership" refusal under a stripped environment: say so
    print("     git ls-files: " + listed.stderr.strip().replace("\n", "\n     "))

# NEVER RUN pyflakes WITH NO PATHS: it then reads source from stdin and waits there forever.
findings, rc = pyflakes(files, ROOT) if files else (["(no production sources were listed, nothing was checked)"], 1)
check(not findings and rc == 0,
      f"the production tree is pyflakes-clean ({len(findings)} finding(s), exit {rc})")
for ln in findings:
    print("     " + ln)

# SELF-CHECK: a clean result is only evidence if the same invocation reports each class this file exists for.
# One planted instance per class; every one must be reported, or the check above is green by accident.
PLANTED = {
    "imported but unused": "import os\n",
    "f-string is missing placeholders": "x = f'plain'\n",
    "assigned to but never used": "def f():\n    y = 1\n",
    "redefinition of unused": "import os\nimport os\nos\n",
    "is unused: name is never assigned in scope": "def g():\n    global Z\n    return Z\nZ = 1\n",
    "undefined name": "undefined_thing()\n",
}
with tempfile.TemporaryDirectory() as d:
    for want, src in PLANTED.items():
        p = os.path.join(d, "planted.py")
        with open(p, "w") as fh:
            fh.write(src)
        seen, _ = pyflakes([p], d)
        check(any(want in ln for ln in seen), f"the check reports a planted {want!r}")
    with open(os.path.join(d, "bad.py"), "w") as fh:
        fh.write("from x import (a,\nfrom y import z\n b)\n")
    seen, prc = pyflakes([os.path.join(d, "bad.py")], d)
    check(bool(seen) and prc != 0, "the check reports a file that does not parse")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    if findings:
        print()
        print("Fix each finding where it is (see this file's docstring for the rules), do not allow-list it here:")
        for ln in findings:
            print("  " + ln)
    sys.exit(1)
print("ALL PYFLAKES CHECKS PASSED")
