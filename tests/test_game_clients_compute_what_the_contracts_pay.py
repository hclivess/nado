"""The game clients compute what the contracts pay: runs the two node cross-checks the suite runner never picked up
(their names do not match tests/test_*), so a drift between a page and its contract fails the suite.

  * tests/pets_js_crosscheck.mjs over tests/pets_js_crosscheck_gen.py's vectors (genes, stats, training, battles);
  * tests/bankedgame_scoreboard_test.mjs (the shared banked-game scoreboard rule).

Both were broken on main for the same reason (static/nadodapp.js wired a DOM listener at import) and nothing noticed.
Run: python3 tests/test_game_clients_compute_what_the_contracts_pay.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-client-xcheck-")   # never the live database (assign, not setdefault)
import atexit; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


if not shutil.which("node"):
    print("SKIP  node not installed")
    sys.exit(0)

gen = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "pets_js_crosscheck_gen.py")], cwd=ROOT,
                     capture_output=True, timeout=600)
check("the pets reference vectors generate", gen.returncode == 0 and gen.stdout, gen.stderr[-400:])
js = subprocess.run(["node", os.path.join(ROOT, "tests", "pets_js_crosscheck.mjs")], cwd=ROOT, input=gen.stdout,
                    capture_output=True, timeout=600)
out = js.stdout.decode(errors="replace")
check("pets-genes.js matches the contract's reference on every vector", js.returncode == 0 and "PASS" in out,
      (out + js.stderr.decode(errors="replace"))[-600:])

sb = subprocess.run(["node", os.path.join(ROOT, "tests", "bankedgame_scoreboard_test.mjs")], cwd=ROOT,
                    capture_output=True, timeout=600)
o2 = sb.stdout.decode(errors="replace")
check("the banked-game scoreboard rule", sb.returncode == 0 and " 0 failed" in o2,
      (o2 + sb.stderr.decode(errors="replace"))[-600:])

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
