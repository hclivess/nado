"""Verification gives the same verdict under threads and never turns this node's out-of-memory into a rejection
(execnode/stark/joinsplit3.py _sboxes; ops/transaction_ops.py settle branch; zk audit 2026-09-26 F3, SETTLE-2).

F3: joinsplit3's S-box memo kept the key and the values in two slots, so under threads a constraint could pair one
row's key with another row's S-boxes and refuse a valid proof (8 wrong evaluations in 19,200 under 4 threads,
reproduced) — a verdict that differs node to node the day verification leaves the event loop. It now swaps one
(key, values) tuple. SETTLE-2: a MemoryError while verifying a settle proof escaped as an exception and the block was
rejected (and its peer benched) on a low-memory node while others accepted it; both halves now turn every
NODE_LOCAL_ERRORS (MemoryError, a missing native kernel) into ProofUnavailable, which defers instead. Pins: 0 wrong
evaluations under 4 threads on satisfying rows; MemoryError is node-local; both settle-verify halves catch the whole
NODE_LOCAL_ERRORS tuple.

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_verifier_thread_and_oom_safety.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-race-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import sys, threading, random
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(os.environ["HOME"])
from execnode.stark import joinsplit3 as J3, field as F, alghash2 as A2
from execnode.stark.native_guard import NODE_LOCAL_ERRORS

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


sys.setswitchinterval(1e-6)                          # hand the GIL over constantly, so a race shows
cons = J3._transitions()[:J3.W_ST]                   # the twelve round constraints, which share _sboxes
rng = random.Random(1)
honest = []
for _ in range(40):
    cur = [rng.randrange(F.P) for _ in range(J3.NCOLS_TOTAL)]
    p = [0] * J3.NPER
    for i in range(J3.W_ST):
        p[J3.RC0 + i] = rng.randrange(F.P)
    p[J3.ACT_R] = 1
    t = [F.pw(F.add(cur[j], p[J3.RC0 + j]), A2.ALPHA) for j in range(J3.W_ST)]
    nxt = list(cur)
    for i in range(J3.W_ST):
        nxt[i] = sum(F.mul(A2._MDS[i][j], t[j]) for j in range(J3.W_ST)) % F.P
    honest.append((cur, nxt, p))
check("the reference rows satisfy every round constraint", all(c(*r) == 0 for r in honest for c in cons))
bad = [0]


def worker(k):
    for it in range(400):
        cur, nxt, p = honest[(k * 7 + it) % len(honest)]
        for c in cons:
            if c(cur, nxt, p) != 0:
                bad[0] += 1


ths = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
[t.start() for t in ths]; [t.join() for t in ths]
check("under 4 threads no satisfying row is evaluated as violated", bad[0] == 0, f"{bad[0]} of {4 * 400 * 12}")

check("an out-of-memory is node-local, never a verdict", MemoryError in NODE_LOCAL_ERRORS)
src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
check("both settle-verify halves catch the whole NODE_LOCAL_ERRORS tuple (KV and records)",
      src.count("from execnode.stark.native_guard import NODE_LOCAL_ERRORS as _NM") == 2
      and "import NativeMissing as _NM" not in src)
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
