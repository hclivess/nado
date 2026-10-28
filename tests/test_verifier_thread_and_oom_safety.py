"""A node's out-of-memory is never turned into a rejection (ops/transaction_ops.py settle branch; zk audit 2026-09-26
SETTLE-2). A MemoryError while verifying a settle proof escaped as an exception and the block was rejected (and its peer
benched) on a low-memory node while others accepted it; every NODE_LOCAL_ERRORS (MemoryError, a missing native kernel)
now defers instead. Pins: MemoryError is node-local; no L1 verifier narrows the tuple to NativeMissing.
(F3, joinsplit3's S-box memo under threads, was pinned here until the wide pool and joinsplit3 were deleted, G9 slice 5.)

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_verifier_thread_and_oom_safety.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-race-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(os.environ["HOME"])
from execnode.native_guard import NODE_LOCAL_ERRORS

import _harness
_report = _harness.Report()
check = _report.check


# (F3, joinsplit3's S-box memo under threads, went with the wide pool in G9 slice 5: the module is deleted)
check("an out-of-memory is node-local, never a verdict", MemoryError in NODE_LOCAL_ERRORS)
src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
# (the two settle-verify halves that caught NODE_LOCAL_ERRORS were the Goldilocks settle verifier, deleted in G9)
check("no L1 verifier narrows a node-local failure to NativeMissing", "import NativeMissing as _NM" not in src)
print("ALL PASS" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
