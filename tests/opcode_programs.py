"""The program per zkVM opcode, shared by tests/test_every_opcode_is_provable.py (per-call proofs, every opcode) and
tests/test_every_opcode_settles_natively.py (the shipped settlement path). Not a test itself."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from execnode import zkvmasm
from execnode.stark import field as F

P = F.P
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


