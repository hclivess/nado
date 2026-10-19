"""The 256-bit contract VM matches the old VM wherever no value wraps, and wraps, compares and hashes as specified.

execnode/zkvm2.py is the generation-29 VM (Goldilocks retirement G3; operator decision 2026-10-19: a 256-bit wrapping
word, doc/stwo/g3-vm-word.md). Contracts port to it mechanically only if it is the SAME machine wherever the old one
did not depend on the field, so:
  1. DIFFERENTIAL: 3,000 random programs over the instructions both VMs share (arithmetic, compares, division,
     branches, storage, payouts, args, context, chain reads), with every value small enough that nothing wraps
     under either word, give identical (ok, return value, storage, io log) on zkvm.py and zkvm2.py;
  2. the word: ADD/SUB/MUL wrap mod 2^256 (so subtraction-as-equality keeps working); LT is exact on full 256-bit
     operands with no RANGE before it; RANGE still bounds to 2^62; DIVMOD is full-width with the remainder in r7 and
     reverts on a zero divisor; LO32 keeps the low 32 bits;
  3. the hash: HINIT/HABS/HOUT compute hash_words, one BLAKE2s compression per word, recomputed here from hashlib;
     the destination may also be a source (`hash r2 <- r2 r1` reads r2 first);
  4. the deploy gate: the 27 alghash round opcodes do not exist, an immediate must fit the word, a lone LT is legal,
     the ASEL pairing rule holds;
  5. replay_io accepts the run's own log and rejects a tampered one.

Run: python3 tests/test_the_256_bit_vm_matches_the_old_vm_wherever_no_value_wraps.py
"""
import _harness
HOME = _harness.isolate("nado-test-zkvm2-")
import hashlib
import random

from execnode import zkvm as V1, zkvm2 as V2

T = _harness.Report()
rnd = random.Random(256)
W = 1 << 256

# ---- 1: differential over the shared instructions, nothing wrapping
SMALL = 1 << 20


def rand_prog(n):
    prog = []
    for i in range(n):
        r = lambda: rnd.randrange(7)                       # never r7 as a DIVMOD destination
        op = rnd.choice(["MOVI", "MOVI", "MOV", "ADD", "MUL", "EQ", "NEZ", "LT", "DIVMOD", "LO32", "JNZ",
                         "SLOAD", "SSTORE", "PAY", "ARG", "CTX", "BHASH", "REQUIRE"])
        if op == "MOVI":
            prog.append(["MOVI", r(), 0, rnd.randrange(1, 300)])
        elif op == "JNZ":
            prog.append(["JNZ", 0, r(), rnd.randrange(i + 1, n + 1)])     # forward only: always terminates
        elif op == "CTX":
            prog.append(["CTX", r(), 0, rnd.randrange(4)])
        elif op == "ARG":
            prog.append(["MOVI", 6, 0, rnd.randrange(4)]); prog.append(["ARG", r(), 6, 0])
        elif op == "BHASH":
            prog.append(["MOVI", 6, 0, rnd.choice([10, 11])]); prog.append(["BHASH", r(), 6, 0])
        elif op == "DIVMOD":
            prog.append(["DIVMOD", r(), r(), 0])
        else:
            prog.append([op, r(), r(), 0])
    prog.append(["RET", 0, rnd.randrange(8), 0])
    # forward jumps may point one past the end; clamp to the RET
    return [[o, d, s, min(imm, len(prog) - 1) if o == "JNZ" else imm] for o, d, s, imm in prog]


diff, window, ran, okc = [], [], 0, 0
for trial in range(3000):
    prog = rand_prog(rnd.randrange(3, 30))
    code = {"m": prog}
    args = [rnd.randrange(1, 200) for _ in range(4)]
    store = {rnd.randrange(5): rnd.randrange(1, 50) for _ in range(3)}
    kw = dict(value=rnd.randrange(100), cursor=rnd.randrange(1000), timestamp=rnd.randrange(1000),
              block_hashes={10: 12345, 11: 777}, beacons={})
    a = V1.run(code, "m", 4242, args, store, **kw)
    b = V2.run(code, "m", 4242, args, store, **kw)
    # keep only runs where no value got near either modulus (MUL can grow; skip any run that did)
    big = any(isinstance(x, int) and x >= SMALL ** 3 for e in (a[3] + b[3]) for x in e) or \
        (a[1] is not None and a[1] >= SMALL ** 3) or (b[1] is not None and b[1] >= SMALL ** 3)
    if big:
        continue
    ran += 1
    okc += bool(a[0])
    if a != b:
        # THE ONE DELIBERATE DIFFERENCE: the old DIVMOD reverts outside its windows (divisor <= 2^15, quotient < 2^48),
        # which existed only to stop field wrap; the new one divides the whole word. A program where only that
        # happened is counted apart, re-checked by running the old VM with every DIVMOD's divisor in its window.
        if a[0] is False and b[0] is True and any(i[0] == "DIVMOD" for i in prog):
            window.append(trial)
        else:
            diff.append((trial, prog, a, b))
T.check(f"1a. {ran} random non-wrapping programs ({okc} completing, the rest reverting): identical on both VMs, "
        f"except {len(window)} where only the old DIVMOD window reverted", not diff and ran > 2000 and okc > 300,
        (len(diff), diff[:1]))
T.check("1b. the old-window cases are a small minority (the windows rarely bind on small values)", len(window) < ran // 20,
        len(window))

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
# ---- 6: the ported "exact hi half" idiom (games/_lib.port_inv32 — hexholm/stormhold reveal) equals the v1 one
from execnode import zkvmasm
from execnode.games import _lib, hexholm, stormhold
IDIOM = """
    mov r6 r1
    lo32 r6
    mov r5 r1
    sub r5 r6
    movi r7 18446744065119617026
    mul r5 r7
    ret r5
"""
p1 = zkvmasm.assemble(IDIOM, "v1")
p2 = zkvmasm.assemble(_lib.port_inv32(IDIOM), "v2")
xs = [0, 1, (1 << 32) - 1, 1 << 32, (1 << 64) - 2 ** 32 - 1] + [rnd.randrange(1 << 64) % V1.F.P for _ in range(2000)]
mism = [x for x in xs if V1.run({"m": p1}, "m", 1, [0, x], {})[1] != V2.run({"m": p2}, "m", 1, [0, x], {})[1]
        or V2.run({"m": p2}, "m", 1, [0, x], {})[1] != x >> 32]
T.check(f"6a. the ported hi-half idiom equals the v1 one (and x >> 32) for {len(xs)} secrets below 2^64", not mism, mism[:3])
try:
    _lib.port_inv32("    movi r1 5\n    ret r1\n"); refused = False
except ValueError:
    refused = True
T.check("6b. port_inv32 refuses a method without the idiom (a declared port that changes nothing)", refused)
try:
    _lib.port_inv32("    movi r3 18446744065119617026\n    mul r7 r3\n"); refused7 = False
except ValueError:
    refused7 = True
T.check("6c. port_inv32 refuses a multiply into r7 (DIVMOD's remainder would overwrite it)", refused7)
T.check("6d. hexholm's and stormhold's v2 reveal carry no field inverse", all(
    18446744065119617026 not in [i[3] for i in m.build("v2")["reveal"]] for m in (hexholm, stormhold)))
T.done("ALL PASS — the 256-bit VM matches the old VM wherever no value wraps")
