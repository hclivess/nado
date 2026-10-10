"""
Every live e2e script (scripts/live/) and operator script (scripts/operator/) must at least still be able to LOAD.

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

They live in scripts/live/ (drivers that spend real NADO on the live chain) and scripts/operator/ (the faucet
distributor the nado-faucet-rewards unit runs, and its top-up). They used to sit at the repo root as `_*.py`; one
left behind there would silently drop out of this check, so the root is required to hold none.
"""
import ast
import re
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
    live = sorted(os.path.join("scripts", "live", f) for f in os.listdir(os.path.join(ROOT, "scripts", "live"))
                  if f.startswith("_") and f.endswith(".py"))
    operator = sorted(os.path.join("scripts", "operator", f)
                      for f in os.listdir(os.path.join(ROOT, "scripts", "operator")) if f.endswith(".py"))
    assert any(f.endswith("_e2e.py") for f in live), "found no scripts/live/_*_e2e.py — has the layout changed?"
    stray = sorted(f for f in os.listdir(ROOT) if f.startswith("_") and f.endswith(".py"))
    if stray:
        fails.extend(stray)
        print(f"  FAIL  live/operator scripts at the repo root (move them to scripts/live or scripts/operator): {stray}")
    print(f"checking {len(live)} live + {len(operator)} operator scripts\n")
    for f in live + operator:
        bad = []
        for m in imports_of(os.path.join(ROOT, f)):
            try:
                if importlib.util.find_spec(m) is None:
                    bad.append(m)
            except (ImportError, ModuleNotFoundError, ValueError):
                bad.append(m)
        if bad:
            fails.append(f)
            print(f"  FAIL  {f:44s} cannot load: {', '.join(bad)}")
        else:
            print(f"  PASS  {f:44s} imports resolve")
        # A PASTED contract id is the same rot one layer down: it dies at every reroll while the script still loads.
        # After betanet-8, 13 of these scripts targeted contracts that no longer existed. Derive it: target_cids().
        # (the operator distributor is exempt: its GAMES table IS the pasted-cid list redeploy rewires in place)
        pasted = re.findall(r'"[0-9a-f]{32}"', open(os.path.join(ROOT, f)).read()) if f in live else []
        if pasted:
            fails.append(f)
            print(f"  FAIL  {f:44s} pastes a contract id ({pasted[0]}) — use execnode.games.redeploy.target_cids()")
    return 1 if fails else 0


if __name__ == "__main__":
    rc = main()
    if fails:
        print(f"\n{len(fails)} e2e script(s) are dead code — they fail before reaching the chain, so the "
              f"games they claim to cover have NO end-to-end coverage at all.")
    else:
        print("\nALL PASS")
    sys.exit(rc)
