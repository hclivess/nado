"""The carry tools leave no throwaway HOME behind (tools/carry.py _isolate, tools/carry_census.py contract_names).

Both make a temporary HOME so the game builders never import against the live node's database (CLAUDE.md rule 4) — and
neither removed it: nine nado-carry-* directories had piled up in /tmp by 2026-10-26. Pins, by running _isolate in a
child process: the directory exists while the tool runs and is gone after it exits; and the census registers the same
removal (source pin — it needs a real exec state to run).

Run: python3 tests/test_the_carry_tools_leave_no_temp_home_behind.py
"""
import os, sys, tempfile, subprocess
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carrytmp-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


env = {k: v for k, v in os.environ.items() if k not in ("NADO_CARRY_ISOLATED",)}
code = ("import sys, os; sys.path.insert(0, %r); from tools import carry; carry._isolate(); "
        "print(os.environ['HOME']); print(os.path.isdir(os.environ['HOME']))") % ROOT
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300, env=env, cwd=ROOT)
lines = [l for l in r.stdout.splitlines() if l.strip() and not l.startswith("[PQ]")]
home = lines[-2] if len(lines) >= 2 else ""
check("_isolate makes a throwaway HOME that exists while the tool runs", r.returncode == 0 and lines[-1:] == ["True"]
      and "nado-carry-" in home, (r.returncode, r.stdout[-300:], r.stderr[-300:]))
check("...and it is gone once the tool exits", bool(home) and not os.path.exists(home), home)
src = open(os.path.join(ROOT, "tools", "carry_census.py"), encoding="utf-8").read()
i = src.index('tempfile.mkdtemp(prefix="nado-carry-census-")')
check("the census removes its throwaway HOME at exit too", "atexit.register(shutil.rmtree, os.environ[\"HOME\"]" in src[i:i + 400])
print("\nALL PASS — the carry tools leave no temp home behind" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
