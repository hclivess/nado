"""EVERY zkVM instruction a contract can execute is provable, with exactly the interpreter's effects
(execnode/zkvm.py OPS, the interpreter; execnode/stark/vm_circuit.py, the AIR).

NOP was accepted by the deploy gate and run by the interpreter while the AIR treated it as a halt, so a call executing
it could never be proven (zk audit 2026-09-26, ZKVM-2) — an instruction that exists but cannot be settled by proof. The
operator's rule since: no instruction may be a dummy. For EVERY opcode in zkvm.OPS this runs a program that executes it
(both branches where it branches, edge values where it wraps) and requires, under the rules in force from
block 1: the interpreter completes, the proof verifies, and the proven io log equals the interpreter's. The
last check fails the day an opcode is added without a program here.

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_every_opcode_is_provable.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-opcodes-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import stark, vm_circuit as VC, field as F
from execnode import zkvm, zkvmasm
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

NQ = int(os.environ.get("NQ", "32"))
P = F.P
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


from opcode_programs import CASES, SELF   # the programs live in tests/opcode_programs.py (shared)


def call_of(code, extra):
    c = {"code": code, "method": "go", "caller_f": 1234, "args_f": [], "value": 0, "cursor": 1, "timestamp": 6,
         "asset": 0, "selfd": SELF, "slots": {}}
    c.update(extra)
    return c


covered = set()
with stark.with_rules(stark.RULES_STRICT):
    for name, code, extra in CASES:
        zkvm.validate_code(code)
        for prog in code.values():
            covered |= {ins[0] for ins in prog}
        c = call_of(code, extra)
        r = zkvm.run(code, "go", c["caller_f"], list(c["args_f"]), dict(c["slots"]), value=c["value"],
                     cursor=c["cursor"], timestamp=c["timestamp"], beacons=c.get("beacons"),
                     block_hashes=c.get("block_hashes"), asset=c["asset"], selfd=SELF, abal=c.get("abal"))
        if not r[0]:
            check(f"{name}: the interpreter completes", False, r)
            continue
        io_i = list(r[3])
        pub = {k: v for k, v in c.items() if k != "slots"}
        try:
            proof, io_p, _ = VC.prove_epoch_calls([c], num_queries=NQ)
            ok, why = VC.verify_epoch_calls(proof, [pub], io_p, num_queries=NQ)
        except Exception as e:
            ok, why, io_p = False, f"{type(e).__name__}: {str(e)[:120]}", None
        check(f"{name}: proves, verifies, and the proven io equals the interpreter's",
              ok is True and list(io_p) == io_i, (why, io_p, io_i))

missing = sorted(set(zkvm.OPS) - covered, key=zkvm.OPS.index)
check(f"every one of the {len(zkvm.OPS)} opcodes is executed by a program above", not missing, missing)
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
