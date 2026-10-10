"""A 2-output join-split proof made by the browser (with the C-3 range gadget) verifies in the node's Python verifier.

A wallet whose proofs the node rejects cannot spend its shielded notes. It lived in tests/joinsplit2_js_crosscheck.sh, which nothing ran — a shell script matches no test glob — until 2026-10-10; this
runs it the way it was meant to be run (VENV = this interpreter) and fails on any non-zero exit. The browser
leg is tests/joinsplit2_js_crosscheck.mjs.

Run: python3 tests/test_joinsplit2_js_proof_verifies_in_python.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): a throwaway HOME and exec files, never the live node's
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-joinsplit2_js_proof_-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import subprocess, sys

TESTS = os.path.dirname(os.path.abspath(__file__))
r = subprocess.run(["bash", os.path.join(TESTS, "joinsplit2_js_crosscheck.sh")], cwd=os.path.dirname(TESTS),
                   env=dict(os.environ, VENV=sys.executable, TMPDIR=os.environ["HOME"]), capture_output=True, text=True)
sys.stdout.write(r.stdout[-6000:]); sys.stdout.write(r.stderr[-3000:])
ok = r.returncode == 0 and "ALL PASSED" in r.stdout
print(("PASS  " if ok else "FAIL  ") + "A 2-output join-split proof made by the browser (with the C-3 range gadget) verifies in the node's Python verifier." + ("" if ok else f"  (exit {r.returncode})"))
print("ALL PASS" if ok else "1 FAILURES")
sys.exit(0 if ok else 1)
