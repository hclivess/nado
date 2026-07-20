"""
Every live e2e script must at least still be able to LOAD.

Run: python3 tests/test_e2e_scripts.py

These scripts talk to a running node, so they cannot be run in a unit suite — which is exactly why they rot
undisturbed. `_cf_e2e.py` and `_cf_stakes_e2e.py` had been dead since two separate migrations: they imported
`Curve25519` (gone when signing moved to post-quantum ML-DSA) and `execnode.contract_lib.COIN_FLIP` (gone
when the zkVM became the only runtime). Both failed in ONE SECOND, and nothing noticed, because nobody runs
a script that takes twenty minutes unless they are already suspicious.

The cost of that is not the script — it is the false confidence. Coinflip looked like it had end-to-end
coverage. It had none, and had not for months.

This test does not run them. It resolves every module they import, which is enough to catch a script whose
world has moved on underneath it.
"""
import ast
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

fails = []


def imports_of(path):
    tree = ast.parse(open(path).read())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods.add(n.module)
    # dynamic imports hide behind __import__("pkg.mod", fromlist=[...]) — the coinflip scripts used exactly
    # that to reach a module that no longer exists, so a plain AST import scan would have missed it
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "__import__"
                and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str)):
            mods.add(n.args[0].value)
    return sorted(mods)


def main():
    scripts = sorted(f for f in os.listdir(ROOT) if f.startswith("_") and f.endswith("_e2e.py"))
    assert scripts, "found no _*_e2e.py scripts — has the naming convention changed?"
    print(f"checking {len(scripts)} live e2e scripts\n")
    for f in scripts:
        bad = []
        for m in imports_of(os.path.join(ROOT, f)):
            try:
                if importlib.util.find_spec(m) is None:
                    bad.append(m)
            except (ImportError, ModuleNotFoundError, ValueError):
                bad.append(m)
        if bad:
            fails.append(f)
            print(f"  FAIL  {f:26s} cannot load: {', '.join(bad)}")
        else:
            print(f"  PASS  {f:26s} imports resolve")
    return 1 if fails else 0


if __name__ == "__main__":
    rc = main()
    if fails:
        print(f"\n{len(fails)} e2e script(s) are dead code — they fail before reaching the chain, so the "
              f"games they claim to cover have NO end-to-end coverage at all.")
    else:
        print("\nALL PASS")
    sys.exit(rc)
