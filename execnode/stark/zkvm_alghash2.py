"""
alghash2 INSIDE the zkVM (doc/zk-recursion.md §4, Option A — the in-VM STARK verifier). The recursion fold
proves "I ran the inner-proof verifier and it accepted" by running that verifier as an ordinary zkVM program
and `prove_call`-ing it — so the fold's soundness rests on the ALREADY-AUDITED execution AIR, not a new
bespoke verifier circuit. The verifier's dominant work is hashing (Merkle paths + transcript), and the inner
proofs commit with `alghash2` (the wide sponge, width-12). This module emits the zkasm that computes the
alghash2 permutation and sponge IN THE VM, bit-identical to execnode/stark/alghash2.py (guarded by
tests/test_zkvm_alghash2.py) — the atomic hashing primitive the in-VM verifier is built from.

The 12-lane state does NOT fit the VM's 8 registers, so it lives in SCRATCH STORAGE (field SC): slots 0..11
hold the sponge state s, slots 12..23 the per-round sbox outputs t. Everything is straight-line field
arithmetic (add / mul; x^7 as 4 muls; the MDS mix as 12x12 constant multiply-accumulate) — no VM change.
"""
from execnode.stark import alghash2 as a2, field as F

SC = 100                      # scratch storage field for the sponge state (avoid a game's field range)
_W, _R, _RATE, _CAP = a2.WIDTH, a2.ROUNDS, a2.RATE, a2.CAPACITY


def _slot(i):
    return (SC << 32) + i


def permute_asm(scratch="r1"):
    """Emit the asm for ONE width-12 permutation operating in place on state slots 0..11 (using slots 12..23
    as t-scratch). Uses r1..r5 + r4 for addresses. Bit-identical to alghash2.permute."""
    L = []
    for r in range(_R):
        # sbox: t_i = (s_i + RC[r][i])^7   (x^7 = x2=x*x; x4=x2*x2; x6=x4*x2; x7=x6*x)
        for i in range(_W):
            L += [f"movi r4 {_slot(i)}", "sload r1 r4", f"movi r2 {a2.RC[r][i]}", "add r1 r2",
                  "mov r2 r1", "mul r2 r1",   # r2 = x^2
                  "mov r3 r2", "mul r3 r2",   # r3 = x^4
                  "mul r3 r2",                # r3 = x^6
                  "mul r3 r1",                # r3 = x^7
                  f"movi r4 {_slot(12 + i)}", "sstore r4 r3"]
        # MDS mix: s_i = Σ_j MDS[i][j]·t_j
        for i in range(_W):
            L.append("movi r5 0")
            for j in range(_W):
                L += [f"movi r4 {_slot(12 + j)}", "sload r2 r4", f"movi r3 {a2._MDS[i][j]}", "mul r2 r3",
                      "add r5 r2"]
            L += [f"movi r4 {_slot(i)}", "sstore r4 r5"]
    return L


def hashn_asm(num_elements):
    """Emit the asm to alghash2-hash `num_elements` field elements passed as call args (arg 0..N-1), leaving
    the CAPACITY-lane digest in state slots 0..3. Mirrors alghash2.hashn: els = [len] + elements; state =
    [0]*RATE + IV; absorb RATE lanes at a time (add into the rate, permute); squeeze the first CAPACITY lanes."""
    L = []
    # init state: slots 0..RATE-1 = 0, slots RATE..W-1 = IV
    for i in range(_RATE):
        L += [f"movi r4 {_slot(i)}", "movi r1 0", "sstore r4 r1"]
    for k in range(_CAP):
        L += [f"movi r4 {_slot(_RATE + k)}", f"movi r1 {a2.IV[k]}", "sstore r4 r1"]
    # els[0] = num_elements (length prefix), els[1..] = args[0..num_elements-1]
    els_len = num_elements + 1
    for off in range(0, els_len, _RATE):
        for pos in range(min(_RATE, els_len - off)):
            idx = off + pos
            # load the element value into r1
            if idx == 0:
                L.append(f"movi r1 {num_elements}")           # the length prefix
            else:
                ai = idx - 1
                if ai == 0:
                    L.append("mov r1 r0")                      # arg 0 preloads r0
                else:
                    L += [f"movi r1 {ai}", "arg r1 r1"]
            # state[pos] += r1
            L += [f"movi r4 {_slot(pos)}", "sload r2 r4", "add r2 r1", "sstore r4 r2"]
        L += permute_asm()
    return L


def build_hashn_contract(num_elements):
    """A one-method zkVM contract `h` that hashes `num_elements` args and returns 0 (the digest is in scratch
    slots 0..3 — read them from the post-storage). For tests + as the hashing subroutine the verifier inlines."""
    from execnode import zkvmasm
    src = "\n".join(hashn_asm(num_elements) + ["ret r0"])
    return zkvmasm.assemble_contract({"h": src})


def digest_slots():
    """The scratch slot addresses holding the CAPACITY-lane digest after a hashn run."""
    return [_slot(i) for i in range(_CAP)]
