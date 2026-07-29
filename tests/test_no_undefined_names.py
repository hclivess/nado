"""NO PRODUCTION MODULE MAY REFERENCE A NAME IT NEVER BOUND.

WHY THIS IS A TEST AND NOT A STYLE CHECK. The alphanet-14 prefix removal replaced a dozen
`x.startswith(ADDRESS_PREFIX)` sniffs with `is_address(x)` — and in three places forgot to import it. Each
one is a NameError that fires only when that branch is reached:

  * nado.py:792          — every incoming-transfer alias lookup in account_mempool
  * forum/server.py:59   — address normalisation
  * execnode/settlement_proofs.py:392,399 — `_bk` in verify_settlement_o1, the O(1) FOLDED settlement
                           verifier, i.e. THE code path SETTLE_PROOF_RECURSIVE switches on for this release

The third is the one that makes this file necessary. tests/test_settlement_o1.py already exists and covers
that function, but its full-recursion branch is opt-in behind NADO_HEAVY=1 (~15 GB, minutes), so a normal
suite run executes the fast segment path and never reaches the NameError. No amount of ordinary testing was
going to find it: the defect lives specifically in the code that is too expensive to run by default.

A static check has no such blind spot. It costs about a second and reads every branch whether or not anything
can afford to execute it — which is exactly the property the heavy-gated paths need.

Scope is deliberately narrow: ONLY pyflakes' "undefined name" class, which is a real bug in every instance
and never a matter of taste. Unused imports, shadowing and line length are not checked and are not this
file's business.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


try:
    import pyflakes  # noqa: F401
except ImportError:
    print("FAIL  pyflakes is not installed — `pip install pyflakes` (it is in requirements.txt)")
    print()
    print("This check is not optional: it is the only thing that reads NADO_HEAVY-gated code paths on an")
    print("ordinary run, and it has already caught a NameError in the O(1) settlement verifier.")
    sys.exit(1)

listed = subprocess.run(["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True)
files = [f for f in listed.stdout.split() if not f.startswith("tests/")]
check(len(files) > 50, f"found the production sources to scan ({len(files)} files)")

proc = subprocess.run([sys.executable, "-m", "pyflakes"] + files,
                      cwd=ROOT, capture_output=True, text=True)
undefined = [ln for ln in (proc.stdout + proc.stderr).splitlines() if "undefined name" in ln]

check(not undefined,
      f"no production module references an unbound name ({len(undefined)} found)")
for ln in undefined:
    print("     " + ln)

# The three sites that motivated this file, pinned by import rather than by grep — a grep for the call would
# pass just as happily against a file that still cannot resolve it.
import importlib

for mod, name in (("ops.address_ops", "is_address"),):
    sys.path.insert(0, ROOT)
    m = importlib.import_module(mod)
    check(hasattr(m, name), f"{mod}.{name} exists to be imported in the first place")

for path, name in (("nado.py", "is_address"),
                   ("forum/server.py", "is_address"),
                   ("execnode/settlement_proofs.py", "_bk")):
    src = open(os.path.join(ROOT, path)).read()
    uses = name + "(" in src or name + "." in src
    imported = (f"import {name}" in src or f", {name}" in src
                or f"{name} =" in src or f"as {name}" in src)
    check((not uses) or imported,
          f"{path} imports {name!r} that it uses (the exact omission this file exists for)")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL UNDEFINED-NAME CHECKS PASSED")
