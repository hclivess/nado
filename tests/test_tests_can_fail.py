"""Every test must be capable of failing.

WHY. This branch has now produced four tests that passed while establishing nothing: one exercising a dead
helper, one reporting a SKIP as a PASS, and two whose every assertion sat inside a loop that could be
empty. A suite is evidence only insofar as each check would go red when the thing it describes breaks —
and "it passes" is the one signal that cannot distinguish a working guard from a vacuous test.

This is a STRUCTURAL audit, not a substitute for tests/mutation_check.py. Mutation testing proves a check
notices a specific break; this proves a check has the machinery to notice anything at all. They catch
different failures: a test can be mutation-covered and still vacuous for inputs nobody mutated, and a test
can be structurally sound yet assert something trivially true.

Three shapes are refused:
  * a test function with no assertion and no raise anywhere it can reach (following one level of local
    helper calls, since most of this suite delegates to _refused/_expect_violation/says);
  * an assertion on a literal, which cannot fail;
  * every assertion inside a loop over a NON-LITERAL iterable, with none outside it — vacuous if that
    collection is ever empty. A loop over a literal tuple or list is fine: it cannot be empty by accident.

Run: python3 tests/test_tests_can_fail.py
"""
import ast
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILS = []


def _literal_names(fn):
    """Names bound to a literal list/tuple inside this function — those cannot be empty by accident."""
    out = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign) and isinstance(n.value, (ast.List, ast.Tuple)) and n.value.elts:
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
    return out


def audit(path):
    tree = ast.parse(open(path, encoding="utf8").read())
    helpers = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    out = []
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("t_")]:
        nodes = list(ast.walk(fn))
        # follow ONE level of local helper calls — most checks here delegate their assertion
        for call in [n for n in nodes if isinstance(n, ast.Call)]:
            name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if name in helpers and name != fn.name:
                nodes += list(ast.walk(helpers[name]))
        asserts = [n for n in nodes if isinstance(n, ast.Assert)]
        raises = [n for n in nodes if isinstance(n, ast.Raise)]
        if not asserts and not raises:
            out.append((fn.name, "no assertion reachable, even through a local helper"))
            continue
        for a in asserts:
            if isinstance(a.test, ast.Constant) and a.test.value:
                out.append((fn.name, "assertion on a literal — cannot fail"))
        own = [n for n in ast.walk(fn) if isinstance(n, ast.Assert)]
        if own:
            outside = [a for a in own if not any(a in ast.walk(L)
                                                 for L in ast.walk(fn)
                                                 if isinstance(L, (ast.For, ast.While)))]
            if not outside:
                # Every assertion is inside a loop. Only the loop that ENCLOSES an assertion matters, and
                # only if its iterable could be empty by accident — a literal tuple or list cannot be, and
                # neither can a nested loop that is not the one holding the assert. Being sloppy here makes
                # the audit cry wolf, and an audit nobody believes is worse than none.
                def encloses(loop, node):
                    return any(node is n for n in ast.walk(loop))
                risky = [L for L in ast.walk(fn) if isinstance(L, ast.For)
                         and any(encloses(L, a) for a in own)
                         and not isinstance(L.iter, (ast.Tuple, ast.List))
                         and not (isinstance(L.iter, ast.Name) and L.iter.id in _literal_names(fn))]
                if risky:
                    out.append((fn.name, "every assertion is inside a loop over a possibly-empty iterable"))
    return out


files = sorted(glob.glob(os.path.join(ROOT, "tests", "test_shielded*.py"))
               + glob.glob(os.path.join(ROOT, "tests", "test_appnote*.py")))
assert files, "no test files found to audit — this check would otherwise pass vacuously itself"
print(f"auditing {len(files)} suites")
for f in files:
    problems = audit(f)
    name = os.path.basename(f)
    if problems:
        for fn, why in problems:
            print(f"FAIL  {name}::{fn} — {why}")
            FAILS.append(f"{name}::{fn}")
    else:
        print(f"PASS  {name}")

print()
print(f"{len(FAILS)} test(s) could pass without proving anything: {FAILS}" if FAILS
      else "every test is capable of failing")
sys.exit(1 if FAILS else 0)
