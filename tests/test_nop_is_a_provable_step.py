"""NOP is a real, provable instruction from block 1 (execnode/stark/vm_circuit.py _nop_steps; zk audit 2026-09-26
ZKVM-2; gen 27's ZK_HARDEN_HEIGHT, 1 from gen 28 and deleted).

The interpreter has always stepped over NOP (pc + 1), while the AIR treated every NOP as a halt, so a contract that
executed one ran on the exec layer and could never be proven — every settle span containing it fell back to the
quorum. Pins: under the hardened rules a program executing NOPs (in a row, before a jump target, before RET) proves
and verifies with exactly the interpreter's io; a program without NOP proves too; and the fetch table's padding can no
longer pose as a fetched instruction (program ids start at 1 in the table and on every execution row).

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_nop_is_a_provable_step.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-nopstep-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import stark, vm_circuit as VC
from execnode import zkvm, zkvmasm

NQ = int(os.environ.get("NQ", "48"))
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


NOPPY = {"go": [["NOP", 0, 0, 0], ["MOVI", 1, 0, 7], ["NOP", 0, 0, 0], ["NOP", 0, 0, 0], ["MOVI", 3, 0, 5],
                ["JMP", 0, 0, 7], ["MOVI", 1, 0, 99], ["NOP", 0, 0, 0], ["SSTORE", 3, 1, 0], ["NOP", 0, 0, 0],
                ["RET", 0, 1, 0]]}
PLAIN = {"go": zkvmasm.assemble("movi r1 7\n movi r3 5\n sstore r3 r1\n ret r1")}
zkvm.validate_code(NOPPY); zkvm.validate_code(PLAIN)


def call(code):
    return {"code": code, "method": "go", "caller_f": 1, "args_f": [], "value": 0, "cursor": 1, "timestamp": 6,
            "asset": 0, "selfd": 2, "slots": {}}


def prove_verify(code, rules):
    c = call(code)
    pub = {k: v for k, v in c.items() if k != "slots"}
    with stark.with_rules(rules):
        try:
            proof, io, _ = VC.prove_epoch_calls([c], num_queries=NQ)
        except Exception as e:
            return None, f"prover: {type(e).__name__}: {str(e)[:80]}"
        return io, VC.verify_epoch_calls(proof, [pub], io, num_queries=NQ)


ok, ret, _st, io_i = zkvm.run(NOPPY, "go", 1, [], {})
check("the interpreter runs the NOP program (and skips the jumped-over write)", ok and ret == 7 and io_i[0] == (zkvm.IO_SSTORE, 5, 7), (ok, ret, io_i))

io, v = prove_verify(NOPPY, stark.RULES_STRICT)
check("hardened rules: a program executing NOPs proves and verifies", isinstance(v, tuple) and v[0] is True, v)
check("... with exactly the interpreter's io", io is not None and list(io) == list(io_i), (io, io_i))

io, v = prove_verify(PLAIN, stark.RULES_STRICT)
check("hardened rules: a program without NOP proves and verifies", isinstance(v, tuple) and v[0] is True, v)

with stark.with_rules(stark.RULES_STRICT):
    trace, T, blocks, progs, epoch_io, _per = VC.build_epoch_trace([call(PLAIN)])
    cols = VC.build_periodic(blocks, progs, epoch_io, T)
    nprog = sum(len(p) for p in progs)
    check("hardened rules: every real fetch-table row has a program id >= 1, padding stays 0",
          all(cols[VC.PP_PROG][j] >= 1 for j in range(nprog)) and all(cols[VC.PP_PROG][j] == 0 for j in range(nprog, T)))
    inb = [i for (st, nr, _p, _c) in blocks for i in range(st, st + nr)]
    check("... and every execution row's program id >= 1", all(cols[VC.PC_PROG][i] >= 1 for i in inb))

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
