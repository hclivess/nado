"""The browser's shielded-pool hashes are the pool's: static/shielded.js produces byte-for-byte what
execnode/shielded.py (the consensus reference the exec node enforces) produces — owner ids, note commitments,
nullifiers, transfer sighashes, Merkle roots and paths — over vectors generated from the Python module at run time.

tests/shielded_js_crosscheck.mjs is not named tests/test_*, so the suite runner never ran it; it then sat red on main
with six "failures" that were only stale pinned hashes (the debrand cutover 6531186b renamed DOMAIN_SHIELD in both
sides). This driver puts it in the suite, and the generator makes the vectors impossible to go stale.
Run: python3 tests/test_shielded_js_matches_the_pool.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-shielded-js-")   # never the live database (assign, not setdefault)
import atexit; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if not shutil.which("node"):
    print("SKIP  node not installed")
    sys.exit(0)

gen = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "shielded_js_crosscheck_gen.py")], cwd=ROOT,
                     capture_output=True, timeout=600)
if gen.returncode != 0 or not gen.stdout:
    print("FAIL  the shielded reference vectors generate\n" + gen.stderr.decode(errors="replace")[-800:])
    sys.exit(1)
print("PASS  the shielded reference vectors generate from execnode/shielded.py")

js = subprocess.run(["node", os.path.join(ROOT, "tests", "shielded_js_crosscheck.mjs"), "-"], cwd=ROOT,
                    input=gen.stdout, capture_output=True, timeout=600)
out = js.stdout.decode(errors="replace") + js.stderr.decode(errors="replace")
ok = js.returncode == 0 and "ALL PASSED" in out
print(("PASS  " if ok else "FAIL  ") + "static/shielded.js hashes byte-identically to execnode/shielded.py")
if not ok:
    print(out[-2000:])
print("ALL PASS" if ok else "1 FAILURE")
sys.exit(0 if ok else 1)
