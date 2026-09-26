"""EVERY zkVM instruction a contract can execute is provable, with exactly the interpreter's effects
(execnode/zkvm.py OPS, the interpreter; execnode/stark/vm_circuit.py, the AIR).

NOP was accepted by the deploy gate and run by the interpreter while the AIR treated it as a halt, so a call executing
it could never be proven (zk audit 2026-09-26, ZKVM-2) — an instruction that exists but cannot be settled by proof. The
operator's rule since: no instruction may be a dummy. For EVERY opcode in zkvm.OPS this runs a program that executes it
(both branches where it branches, edge values where it wraps) and requires, under the rules in force from
ZK_HARDEN_HEIGHT: the interpreter completes, the proof verifies, and the proven io log equals the interpreter's. The
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

NQ = int(os.environ.get("NQ", "32"))
P = F.P
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


A = zkvmasm.assemble
SELF = 4242
CASES = [  # (name, code {method: prog}, extra call fields)
    ("NOP (a real step)", {"go": [["NOP", 0, 0, 0], ["MOVI", 1, 0, 7], ["NOP", 0, 0, 0], ["RET", 0, 1, 0]]}, {}),
    ("MOVI / MOV", {"go": A("movi r2 9\n mov r1 r2\n ret r1")}, {}),
    ("ADD wraps mod p", {"go": A(f"movi r1 5\n movi r2 {P - 1}\n add r1 r2\n ret r1")}, {}),
    ("SUB wraps below 0", {"go": A("movi r1 3\n movi r2 5\n sub r1 r2\n ret r1")}, {}),
    ("MUL", {"go": A(f"movi r1 {2**40}\n movi r2 {2**40}\n mul r1 r2\n ret r1")}, {}),
    ("EQ equal", {"go": A("movi r1 6\n movi r2 6\n eq r1 r2\n ret r1")}, {}),
    ("EQ unequal", {"go": A("movi r1 6\n movi r2 7\n eq r1 r2\n ret r1")}, {}),
    ("NEZ zero and nonzero", {"go": A("movi r1 0\n nez r1\n movi r2 5\n nez r2\n add r1 r2\n ret r1")}, {}),
    ("NOTB", {"go": A("movi r1 0\n notb r1\n ret r1")}, {}),
    ("LT true (with its RANGEs)", {"go": A("movi r1 3\n movi r2 9\n lt r1 r2\n ret r1")}, {}),
    ("LT false", {"go": A(f"movi r1 {2**61}\n movi r2 9\n lt r1 r2\n ret r1")}, {}),
    ("RANGE", {"go": A(f"movi r1 {2**61 + 5}\n range r1\n ret r1")}, {}),
    ("DIVMOD (quotient + r7 remainder)", {"go": A("movi r1 1000003\n movi r2 97\n divmod r1 r2\n add r1 r7\n ret r1")}, {}),
    ("DIVMODW", {"go": A(f"movi r1 {2**40 + 12345}\n movi r2 {2**31}\n divmodw r1 r2\n add r1 r7\n ret r1")}, {}),
    ("LO32", {"go": A(f"movi r1 {2**40 + 5}\n lo32 r1\n ret r1")}, {}),
    ("JMP", {"go": [["MOVI", 1, 0, 1], ["JMP", 0, 0, 3], ["MOVI", 1, 0, 99], ["RET", 0, 1, 0]]}, {}),
    ("JNZ taken and not taken", {"go": [["MOVI", 2, 0, 0], ["JNZ", 0, 2, 4], ["MOVI", 2, 0, 1], ["JNZ", 0, 2, 5],
                                        ["MOVI", 1, 0, 99], ["RET", 0, 2, 0]]}, {}),
    ("REQUIRE", {"go": A("movi r1 1\n require r1\n ret r1")}, {}),
    ("CTX caller/value/cursor/time", {"go": A("ctx r1 caller\n ctx r2 value\n add r1 r2\n ctx r2 cursor\n add r1 r2\n "
                                              "ctx r2 time\n add r1 r2\n ret r1")}, {"value": 11}),
    ("HINIT / HABS / HR0..HR26 / HOUT (hash)", {"go": A("movi r1 5\n movi r2 6\n hash r3 <- r1 r2\n ret r3")}, {}),
    ("SLOAD (set and unset) / SSTORE (write and clear)",
     {"go": A("movi r1 3\n sload r2 r1\n movi r4 8\n sload r5 r4\n movi r6 4\n sstore r6 r2\n movi r0 0\n sstore r1 r0\n ret r2")},
     {"slots": {3: 77}}),
    ("PAY", {"go": A("movi r1 55\n movi r2 10\n pay r1 r2\n ret r2")}, {"value": 10}),
    ("BHASH", {"go": A("movi r1 5\n bhash r2 r1\n ret r2")}, {"block_hashes": {5: 123456789}}),
    ("BEACON", {"go": A("movi r1 3\n beacon r2 r1\n ret r2")}, {"beacons": {3: 987654321}}),
    ("ARG", {"go": A("movi r2 1\n arg r1 r2\n movi r2 0\n arg r3 r2\n add r1 r3\n ret r1")}, {"args_f": [11, 22]}),
    ("ASEL + PAY (asset pay)", {"go": A("movi r1 77\n movi r2 55\n movi r3 4\n apay r1 r2 r3\n ret r3")},
     {"abal": {77: 100}}),
    ("ASEL + AMINT", {"go": A("movi r1 77\n movi r2 55\n movi r3 4\n amint r1 r2 r3\n ret r3")}, {}),
    ("ABURN", {"go": A("movi r1 77\n movi r2 4\n aburn r1 r2\n ret r2")}, {"abal": {77: 100}}),
    ("ABAL", {"go": A("movi r1 77\n abal r2 r1\n ret r2")}, {"abal": {77: 100}}),
    ("ACTX asset/self", {"go": A("actx r1 asset\n actx r2 self\n add r1 r2\n ret r1")}, {"asset": 9}),
    ("ARENOUNCE", {"go": A("movi r1 77\n arenounce r1\n movi r2 1\n ret r2")}, {}),
]


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
