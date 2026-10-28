"""The 256-bit contract VM wraps, compares and hashes as specified.

execnode/zkvm2.py is the generation-29 VM (Goldilocks retirement G3; operator decision 2026-10-19: a 256-bit wrapping
word, doc/stwo/g3-vm-word.md), and since G9 slice 3b the only one:
  1. (the DIFFERENTIAL against the field VM, execnode/zkvm.py — 3,000 random non-wrapping programs identical on both —
     retired with that VM in G9 slice 3b; it was the port's proof, and the port is done)
  2. the word: ADD/SUB/MUL wrap mod 2^256 (so subtraction-as-equality keeps working); LT is exact on full 256-bit
     operands with no RANGE before it; RANGE still bounds to 2^62; DIVMOD is full-width with the remainder in r7 and
     reverts on a zero divisor; LO32 keeps the low 32 bits;
  3. the hash: HINIT/HABS/HOUT compute hash_words, one BLAKE2s compression per word, recomputed here from hashlib;
     the destination may also be a source (`hash r2 <- r2 r1` reads r2 first);
  4. the deploy gate: the 27 alghash round opcodes do not exist, an immediate must fit the word, a lone LT is legal,
     the ASEL pairing rule holds;
  5. replay_io accepts the run's own log and rejects a tampered one;
  6. the "exact hi half" split the hexholm/stormhold/scrapline reveal use (sub lo32, divmod by 2^32) computes x >> 32,
     and no contract source still carries the field VM's inverse of 2^32.

Run: python3 tests/test_the_256_bit_vm_wraps_compares_and_hashes_as_specified.py
"""
import _harness
HOME = _harness.isolate("nado-test-zkvm2-")
import hashlib
import random

from execnode import zkvm2 as V2

T = _harness.Report()
rnd = random.Random(256)
W = 1 << 256

# ---- 2: the word
def one(prog, args=(), **kw):
    """run `prog` then RET r0; the first 8 args preload r0..r7"""
    return V2.run({"m": prog + [["RET", 0, 0, 0]]}, "m", 1, list(args), {}, **kw)


T.check("2a. SUB wraps mod 2^256 (0 - 1)", one([["MOVI", 0, 0, 0], ["MOVI", 1, 0, 1], ["SUB", 0, 1, 0]])[1] == W - 1)
T.check("2b. ADD wraps mod 2^256", one([["ADD", 0, 1, 0]], [W - 1, 5])[1] == 4)
T.check("2c. MUL wraps mod 2^256", one([["MUL", 0, 0, 0]], [1 << 200])[1] == 0)
digest_a, digest_b = (1 << 255) + 12345, (1 << 255) + 99
eq_by_sub = one([["SUB", 0, 1, 0], ["NEZ", 0, 0, 0]], [digest_a, digest_b])[1]
T.check("2d. subtraction-as-equality on two 256-bit digests still answers 'different'", eq_by_sub == 1)
T.check("2e. LT is exact on full 256-bit operands with no RANGE before it",
        one([["LT", 0, 1, 0]], [W - 2, W - 1])[1] == 1
        and one([["LT", 0, 1, 0]], [W - 1, W - 2])[1] == 0)
T.check("2f. RANGE still bounds to 2^62", one([["RANGE", 0, 0, 0]], [1 << 62])[0] is False
        and one([["RANGE", 0, 0, 0]], [(1 << 62) - 1])[0] is True)
dm = V2.run({"m": [["DIVMOD", 0, 1, 0], ["MOV", 2, 7, 0], ["RET", 0, 0, 0]]}, "m", 1, [(1 << 250) + 7, 1 << 100], {},
            witness=True)
T.check("2g. DIVMOD is full-width, remainder in r7", dm[1] == (1 << 150) and dm[4][-1]["regs"][7] == 7)
T.check("2h. a zero divisor reverts", one([["MOVI", 0, 0, 5], ["MOVI", 1, 0, 0], ["DIVMOD", 0, 1, 0]])[0] is False)
T.check("2i. LO32 keeps the low 32 bits of a 256-bit word",
        one([["LO32", 0, 0, 0]], [(1 << 255) | 0xDEADBEEF])[1] == 0xDEADBEEF)

# ---- 3: the hash
def ref(words):
    h = bytes(32)
    for w in words:
        h = hashlib.blake2s(h + w.to_bytes(32, "big"), digest_size=32, person=b"NADOvmH1").digest()
    return int.from_bytes(h, "big")


ws = [5, 1 << 255, 0, 77]
T.check("3a. hash_words is one BLAKE2s compression per word, recomputed from hashlib", V2.hash_words(ws) == ref(ws))
hp = one([["HINIT", 0, 0, 0], ["HABS", 0, 2, 0], ["HABS", 0, 1, 0], ["HOUT", 2, 0, 0], ["MOV", 0, 2, 0]], [0, 22, 11])
T.check("3b. `hash r2 <- r2 r1`: the destination is read before it is written", hp[1] == ref([11, 22]))
T.check("3c. a different order is a different hash", V2.hash_words([22, 11]) != V2.hash_words([11, 22]))

# ---- 4: the deploy gate
gate = {}
for name, code in (("an alghash round opcode", {"m": [["HR0", 0, 0, 0], ["RET", 0, 0, 0]]}),
                   ("an immediate outside the word", {"m": [["MOVI", 0, 0, W], ["RET", 0, 0, 0]]}),
                   ("an unpaired ASEL", {"m": [["ASEL", 0, 1, 0], ["RET", 0, 0, 0]]}),
                   ("DIVMOD into r7", {"m": [["DIVMOD", 7, 1, 0], ["RET", 0, 0, 0]]})):
    try:
        V2.validate_code(code); gate[name] = "accepted"
    except V2.ZkVMError:
        gate[name] = "refused"
T.check("4a. the deploy gate refuses round opcodes, oversized immediates, unpaired ASEL, DIVMOD into r7",
        set(gate.values()) == {"refused"}, gate)
T.check("4b. a lone LT (no RANGE before it) is legal", V2.validate_code({"m": [["LT", 0, 1, 0], ["RET", 0, 0, 0]]}))
T.check("4c. a 2^256-1 immediate is legal", V2.validate_code({"m": [["MOVI", 0, 0, W - 1], ["RET", 0, 0, 0]]}))

# ---- 5: replay
r = V2.run({"m": [["MOVI", 1, 0, 9], ["MOVI", 2, 0, 1 << 255], ["SSTORE", 1, 2, 0], ["SLOAD", 3, 1, 0], ["PAY", 2, 1, 0],
                  ["RET", 0, 3, 0]]}, "m", 1, [], {})
ok = V2.replay_io(r[3], {})
T.check("5a. replay_io accepts the run's own log: the same storage, payout and return", ok[0] and ok[1] == 1 << 255
        and ok[2] == {9: 1 << 255} and ok[3] == [(1 << 255, 9)])
bad = list(r[3]); bad[1] = (V2.IO_SLOAD, 9, 5)
T.check("5b. replay_io rejects a log whose read does not match the state", V2.replay_io(bad, {})[0] is False)
# ---- 6: the "exact hi half" split (hexholm/stormhold/scrapline reveal). The sources were once written in the field VM's
# `x - lo32(x)` times-the-inverse-of-2^32 idiom and rewritten at build time (games/_lib.port_inv32, deleted with
# Goldilocks); they now say `movi rA 2^32 ; divmod rB rA` themselves. The byte-identical build test pins that the
# bytecode did not move; this pins what the instruction pair computes, and that no inverse constant is left anywhere.
from execnode import zkvmasm
from execnode.games import _lib, hexholm, stormhold, scrapline
IDIOM = """
    mov r6 r1
    lo32 r6
    mov r5 r1
    sub r5 r6
    movi r3 4294967296
    divmod r5 r3
    ret r5
"""
p2 = zkvmasm.assemble(IDIOM)
xs = [0, 1, (1 << 32) - 1, 1 << 32, (1 << 64) - 2 ** 32 - 1] + [rnd.randrange(1 << 64) for _ in range(2000)]
mism = [x for x in xs if V2.run({"m": p2}, "m", 1, [0, x], {})[1] != x >> 32]
T.check(f"6a. the hi-half split (sub lo32, divmod by 2^32) is x >> 32 for {len(xs)} secrets below 2^64", not mism, mism[:3])
INV32_GOLDILOCKS = 18446744065119617026
T.check("6b. hexholm's, stormhold's and scrapline's reveal carry no field inverse and do divide by 2^32", all(
    INV32_GOLDILOCKS not in [i[3] for i in m.build()["reveal"]]
    and any(i[0] == "DIVMOD" for i in m.build()["reveal"]) for m in (hexholm, stormhold, scrapline)))
import glob
import os
_left = [f for f in glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "execnode", "**", "*.py"),
                              recursive=True) if str(INV32_GOLDILOCKS) in open(f).read()]
T.check("6c. no contract source still writes the Goldilocks inverse of 2^32 (and _lib no longer ports it)",
        not _left and not hasattr(_lib, "port_inv32") and not hasattr(_lib, "INV32_FIELD"), _left)
T.done("ALL PASS — the 256-bit VM wraps, compares and hashes as specified")
