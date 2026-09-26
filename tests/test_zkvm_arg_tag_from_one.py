"""The first call's first argument cannot be forged to 0 through the ARG bus's padding row, from ZK_HARDEN_HEIGHT
(execnode/stark/vm_circuit.py build_periodic: calls tagged from 1 on PT_CALL and PC_CALL; zk audit 2026-09-26 ZKVM-1).

The args table fills rows past args_total with (call 0, index 0, value 0) and its multiplicity MA is a free witness, so
while call 0 was tagged 0 that padding row was a valid args entry: a forged proof read call 0's args[0] as 0 and proved a
false storage write (reproduced at the protocol's 320 queries). Pins: under the hardened rules the forged proof is
refused (or cannot even be built) while an honest proof verifies; under the pre-gate rules the old behaviour is
unchanged (history replays as it was).

Run: NADO_ALLOW_PYTHON_KERNELS=1 python3 tests/test_zkvm_arg_tag_from_one.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-argtag-")
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


CODE = {"go": zkvmasm.assemble("movi r2 0\n arg r1 r2\n movi r3 5\n sstore r3 r1\n ret r1")}
CALL = {"code": CODE, "method": "go", "caller_f": 1234, "args_f": [42, 7], "value": 0, "cursor": 1,
        "timestamp": 6, "asset": 0, "selfd": 9, "slots": {}}
PUB = {k: v for k, v in CALL.items() if k != "slots"}
real = VC.build_epoch_trace


def forged(calls):
    trace, T, blocks, progs, io, per = real(calls)
    for i in range(2, T):                      # r1 after the ARG := 0, the padding row's value
        trace[i][VC.R0 + 1] = 0
    trace[0][VC.MA] = 0                        # move the multiplicity from (call 0, 0, 42) to the padding row
    trace[2][VC.MA] += 1
    return trace, T, blocks, progs, [(zkvm.IO_SSTORE, 5, 0), (zkvm.IO_RET, 0, 0)], per


def attempt(rules, forge):
    with stark.with_rules(rules):
        VC.build_epoch_trace = forged if forge else real
        try:
            proof, io, _ = VC.prove_epoch_calls([CALL], num_queries=NQ)
        except Exception as e:
            return f"prover refused: {type(e).__name__}"
        finally:
            VC.build_epoch_trace = real
        return VC.verify_epoch_calls(proof, [PUB], io, num_queries=NQ), io


STRICT, PRE = stark.RULES_STRICT, stark.RULES_PRE_HARDEN
check("the gate is in the rules: STRICT hardens, the pre-gate rules do not", STRICT.zk_harden and not PRE.zk_harden)
r = attempt(STRICT, forge=False)
check("an honest proof verifies under the hardened rules", isinstance(r, tuple) and r[0][0] is True, r)
r = attempt(STRICT, forge=True)
check("the forged args[0] = 0 proof is refused under the hardened rules",
      isinstance(r, str) or r[0][0] is False, r)
r = attempt(PRE, forge=False)
check("an honest proof still verifies under the pre-gate rules", isinstance(r, tuple) and r[0][0] is True, r)
r = attempt(PRE, forge=True)
check("under the pre-gate rules the old (forgeable) behaviour is unchanged, so history replays",
      isinstance(r, tuple) and r[0][0] is True and r[1][0] == (zkvm.IO_SSTORE, 5, 0), r)

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
