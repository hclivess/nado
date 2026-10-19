"""
zkVM2 — the generation-29 contract VM: zkvm.py with a 256-bit WRAPPING word and BLAKE2s instead of Goldilocks
(Goldilocks retirement G3; operator decision 2026-10-19, doc/stwo/g3-vm-word.md). The reference interpreter the Stwo
execution AIR (G4) will prove; it coexists with zkvm.py until the reroll, and nothing on a consensus path runs it
before BLAKE_EXEC_HEIGHT.

WHAT CHANGES FROM zkvm.py, opcode by opcode (everything else — registers, the ARG table, storage, PAY, chain reads,
the asset layer, the ordered public I/O log and its replay — is the same machine):
  word          a register holds an integer in [0, 2^256). Immediates and args are reduced mod 2^256.
  ADD/SUB/MUL   wrap mod 2^256 (EVM-like). The measured contracts rely on wrap — subtraction feeding NEZ/EQ as an
                equality test in 22 of 27 — and keep working unchanged.
  EQ/NEZ/NOTB   exact over the word (NOTB still reverts on a non-bit).
  LT            SOUND OVER THE WHOLE WORD: 1 iff rd < rs as integers. No window, no RANGE prerequisite — the deploy
                gate's "RANGE; RANGE; LT" rule and the "full-field compare" open item of zkvm.py retire.
  RANGE         kept as a BOUND: reverts unless rd < 2^62. Contracts use it to bound foreign amounts, and that
                meaning is kept; it is no longer what makes LT sound.
  DIVMOD        q = rd // rs into rd, remainder into r7, over the whole word; a zero divisor reverts. The 48/15 and
                32/31 windows existed only to stop field wrap. DIVMODW is the same instruction (kept so the builders'
                `divmodw` compiles unchanged).
  LO32          rd & (2^32 - 1). No canonicality case: a word has one representation.
  HINIT/HABS/HOUT  the hash accumulator h (machine state, not a register): HINIT h = 0; HABS s h = BLAKE2s-256(h || rs,
                person=PERSON_HASH) with both as 32 bytes big-endian — ONE compression per absorbed word, which is
                what the Stwo Blake component proves; HOUT d copies h. The 27 alghash round opcodes are gone: the
                assembler's `hash d <- s1 s2 ...` macro emits HINIT, one HABS per source, HOUT — so `hash r2 <- r2 r1`
                still reads r2 before writing it.
  BHASH/BEACON/ABAL  the chain value as supplied, reduced mod 2^256 (a 256-bit block hash or beacon now fits whole).

FROZEN AT THE REROLL with the opcode ids below (APPEND-ONLY after it, like zkvm.py's).
"""
import hashlib

WORD = 1 << 256
MASK = WORD - 1
GAS_LIMIT = 131070               # unchanged until the Stwo AIR (G4) measures its own ceiling
MAX_ARGS = 1024
NUM_REGS = 8
PERSON_HASH = b"NADOvmH1"        # the VM hash's BLAKE2s personalization: disjoint from the exec root's and auth's

OPS = ["NOP", "MOVI", "MOV", "ADD", "SUB", "MUL", "EQ", "NEZ", "NOTB", "LT", "RANGE", "DIVMOD", "LO32",
       "JMP", "JNZ", "REQUIRE", "CTX", "HINIT", "HABS", "HOUT",
       "SLOAD", "SSTORE", "PAY", "BHASH", "BEACON", "RET", "ARG", "DIVMODW",
       "ASEL", "AMINT", "ABURN", "ABAL", "ACTX", "ARENOUNCE"]
OP = {name: i for i, name in enumerate(OPS)}

# the I/O vocabulary and the context indices are zkvm.py's, unchanged — one definition
from execnode.zkvm import (IO_SLOAD, IO_SSTORE, IO_PAY, IO_BHASH, IO_BEACON, IO_RET, IO_ASEL, IO_AMINT,  # noqa: E402
                           IO_ABURN, IO_ABAL, IO_ARENOUNCE, IO_ASSET_KINDS, CTX_CALLER, CTX_VALUE, CTX_CURSOR,
                           CTX_TIME, ACTX_ASSET, ACTX_SELF, ZkVMError, ZkVMRevert, method_reads_actx)

__all__ = ["run", "replay_io", "validate_code", "hash_words", "OPS", "OP", "WORD", "GAS_LIMIT", "MAX_ARGS",
           "IO_SLOAD", "IO_SSTORE", "IO_PAY", "IO_BHASH", "IO_BEACON", "IO_RET", "IO_ASEL", "IO_AMINT", "IO_ABURN",
           "IO_ABAL", "IO_ARENOUNCE", "IO_ASSET_KINDS", "CTX_CALLER", "CTX_VALUE", "CTX_CURSOR", "CTX_TIME",
           "ACTX_ASSET", "ACTX_SELF", "ZkVMError", "ZkVMRevert", "method_reads_actx"]


def _absorb(h, x):
    return int.from_bytes(hashlib.blake2s(h.to_bytes(32, "big") + (x & MASK).to_bytes(32, "big"), digest_size=32,
                                          person=PERSON_HASH).digest(), "big")


def hash_words(words):
    """What `hash d <- s1 ... sk` computes: HINIT, HABS each word in order, HOUT — the reference the game clients and
    the settlement circuit mirror (the gen-29 algHashn)."""
    h = 0
    for w in words:
        h = _absorb(h, int(w))
    return h


def validate_code(code):
    """zkvm.validate_code's structural rules for the new ISA: known ops, registers in range, immediates in the word,
    jump targets inside the method, DIVMOD never into r7, CTX/ACTX indices, and the ASEL pairing rule (an asset move
    needs its selection on the instruction right before it). The RANGE-before-LT rule is gone: LT is sound alone."""
    if not isinstance(code, dict) or not code:
        raise ZkVMError("contract code must be a non-empty {method: [instructions]} object")
    for method, prog in code.items():
        if not isinstance(method, str) or not isinstance(prog, list) or not prog:
            raise ZkVMError(f"bad method {method!r}")
        if len(prog) > GAS_LIMIT:
            raise ZkVMError(f"method {method} longer than GAS_LIMIT")
        no_jump = set()
        for i, ins in enumerate(prog):
            if (not isinstance(ins, list) or len(ins) != 4 or ins[0] not in OP
                    or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in ins[1:])):
                raise ZkVMError(f"invalid instruction {ins!r} in {method}")
            op, d, s, imm = ins
            if d >= NUM_REGS or s >= NUM_REGS:
                raise ZkVMError(f"register out of range in {ins!r}")
            if imm >= WORD:
                raise ZkVMError(f"immediate outside the 256-bit word in {ins!r}")
            if op in ("JMP", "JNZ") and imm >= len(prog):
                raise ZkVMError(f"jump target out of range in {ins!r}")
            if op in ("DIVMOD", "DIVMODW") and d == 7:
                raise ZkVMError(f"{op} dest must not be r7 (r7 receives the remainder)")
            if op in ("CTX", "ACTX") and imm > 3:
                raise ZkVMError(f"{op} index must be 0..3")
            if op == "ASEL":
                if i + 1 >= len(prog) or prog[i + 1][0] not in ("PAY", "AMINT"):
                    raise ZkVMError(f"ASEL at {i} in {method} must be immediately followed by PAY or AMINT")
                no_jump.add(i + 1)
            if op == "AMINT" and not (i >= 1 and prog[i - 1][0] == "ASEL"):
                raise ZkVMError(f"AMINT at {i} in {method} is not preceded by ASEL (no asset selected)")
        for ins in prog:
            if ins[0] in ("JMP", "JNZ") and ins[3] in no_jump:
                raise ZkVMError(f"jump onto an asset spend at index {ins[3]} in {method} would skip its ASEL")
    return True


def run(code, method, caller, args, storage, value=0, cursor=0, timestamp=0, beacons=None, block_hashes=None,
        asset=0, selfd=0, abal=None, witness=False, meter=None):
    """zkvm.run with the 256-bit word: same signature, same returns, same revert contract — (False, None, storage, [])
    on any revert, a no-op the AIR could not prove either. `witness=True` returns per-step (pc, op, d, s, imm, regs, h,
    io count) for the Stwo trace builder; there are no Goldilocks limb columns."""
    if method not in code:
        return (False, None, storage, []) + (([],) if witness else ())
    prog = code[method]
    if len(args) > MAX_ARGS:
        return (False, None, storage, []) + (([],) if witness else ())
    wargs = [int(a) & MASK for a in args]
    regs = [(wargs[i] if i < len(wargs) else 0) for i in range(NUM_REGS)]
    ctxv = [int(caller) & MASK, int(value) & MASK, int(cursor) & MASK, int(timestamp) & MASK]
    selfd = int(selfd) & MASK
    actxv = [int(asset) & MASK, selfd, 0, 0]
    asel = 0
    apend = {}

    def _aspend(a, amt):
        have = int((abal or {}).get(a, 0)) + apend.get(a, 0)
        if amt > have:
            raise ZkVMRevert("asset move exceeds the contract's holding")
        apend[a] = apend.get(a, 0) - amt

    st = dict(storage)
    io, steps = [], []
    pc, h, gas, ret = 0, 0, 0, None
    try:
        while True:
            if gas >= GAS_LIMIT:
                raise ZkVMRevert("gas limit exceeded")
            gas += 1
            op_name, d, s, imm = prog[pc]
            rd, rs = regs[d], regs[s]
            io_entry, nxt_pc, res, wr = None, pc + 1, None, False
            if op_name == "NOP":
                pass
            elif op_name == "MOVI":
                res, wr = imm & MASK, True
            elif op_name == "MOV":
                res, wr = rs, True
            elif op_name == "ADD":
                res, wr = (rd + rs) & MASK, True
            elif op_name == "SUB":
                res, wr = (rd - rs) & MASK, True
            elif op_name == "MUL":
                res, wr = (rd * rs) & MASK, True
            elif op_name == "EQ":
                res, wr = (1 if rd == rs else 0), True
            elif op_name == "NEZ":
                res, wr = (1 if rd else 0), True
            elif op_name == "NOTB":
                if rd not in (0, 1):
                    raise ZkVMRevert("NOTB on a non-bit")
                res, wr = 1 - rd, True
            elif op_name == "LT":
                res, wr = (1 if rd < rs else 0), True
            elif op_name == "RANGE":
                if rd >= 1 << 62:
                    raise ZkVMRevert("RANGE failed (value >= 2^62)")
            elif op_name in ("DIVMOD", "DIVMODW"):
                if rs == 0:
                    raise ZkVMRevert("division by zero")
                regs[7] = rd % rs
                res, wr = rd // rs, True
            elif op_name == "LO32":
                res, wr = rd & 0xFFFFFFFF, True
            elif op_name == "JMP":
                nxt_pc = imm
            elif op_name == "JNZ":
                nxt_pc = imm if rs else pc + 1
            elif op_name == "REQUIRE":
                if not rs:
                    raise ZkVMRevert("REQUIRE failed")
            elif op_name == "CTX":
                res, wr = ctxv[imm], True
            elif op_name == "HINIT":
                h = 0
            elif op_name == "HABS":
                h = _absorb(h, rs)
            elif op_name == "HOUT":
                res, wr = h, True
            elif op_name == "SLOAD":
                val = st.get(rs, 0)
                io_entry = (IO_SLOAD, rs, val)
                res, wr = val, True
            elif op_name == "SSTORE":
                if rs == 0:
                    st.pop(rd, None)                      # zero = absence, as in zkvm.py
                else:
                    st[rd] = rs
                io_entry = (IO_SSTORE, rd, rs)
            elif op_name == "PAY":
                if asel:
                    if not (selfd and rd == selfd):
                        _aspend(asel, rs)
                    asel = 0
                io_entry = (IO_PAY, rd, rs)
            elif op_name == "BHASH":
                hv = (block_hashes or {}).get(rs)
                if hv is None:
                    raise ZkVMRevert("block hash for height not available")
                hv = int(hv) & MASK
                io_entry = (IO_BHASH, rs, hv)
                res, wr = hv, True
            elif op_name == "BEACON":
                bv = (beacons or {}).get(rs)
                if bv is None:
                    raise ZkVMRevert("beacon for epoch not available")
                bv = int(bv) & MASK
                io_entry = (IO_BEACON, rs, bv)
                res, wr = bv, True
            elif op_name == "ARG":
                if rs >= len(wargs):
                    raise ZkVMRevert("ARG index out of range")
                res, wr = wargs[rs], True
            elif op_name == "ASEL":
                if rs == 0:
                    raise ZkVMRevert("ASEL of asset 0 (native NADO needs no selection)")
                asel = rs
                io_entry = (IO_ASEL, rs, 0)
            elif op_name == "AMINT":
                if selfd and rd == selfd:
                    apend[asel] = apend.get(asel, 0) + rs
                asel = 0
                io_entry = (IO_AMINT, rd, rs)
            elif op_name == "ABURN":
                _aspend(rd, rs)
                io_entry = (IO_ABURN, rd, rs)
            elif op_name == "ABAL":
                bv = (int((abal or {}).get(rs, 0)) + apend.get(rs, 0)) & MASK
                io_entry = (IO_ABAL, rs, bv)
                res, wr = bv, True
            elif op_name == "ACTX":
                res, wr = actxv[imm], True
            elif op_name == "ARENOUNCE":
                io_entry = (IO_ARENOUNCE, rd, 0)
            elif op_name == "RET":
                ret = rs
                io_entry = (IO_RET, rs, 0)
            if wr:
                regs[d] = res
            if io_entry is not None:
                io.append(io_entry)
            if witness:
                steps.append({"pc": pc, "op": OP[op_name], "d": d, "s": s, "imm": imm, "regs": list(regs), "h": h,
                              "ioc_after": len(io)})
            if op_name == "RET":
                break
            pc = nxt_pc
        if meter is not None:
            meter["gas"] = gas
        return (True, ret, st, io) + ((steps,) if witness else ())
    except (ZkVMRevert, IndexError, KeyError):
        if meter is not None:
            meter["gas"] = gas
        return (False, None, storage, []) + (([],) if witness else ())


def replay_io(io_log, storage, with_assets=False):
    """zkvm.replay_io over the 256-bit word: identical rules (one RET, last; reads match the state in order; ASEL spent
    by the very next entry; asset entries only with with_assets), entries bounded by 2^256 instead of P."""
    st = dict(storage)
    payouts, chain_reads, effects = [], [], []
    ret, ret_seen = None, False
    bad = (False, None, storage, [], []) + (([],) if with_assets else ())
    sel = 0
    for entry in io_log:
        if ret_seen:
            return bad
        if not (isinstance(entry, (list, tuple)) and len(entry) == 3
                and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < WORD for x in entry)):
            return bad
        kind, a, b = entry
        if kind in IO_ASSET_KINDS and not with_assets:
            return bad
        if sel and kind not in (IO_PAY, IO_AMINT):
            return bad
        if kind == IO_SLOAD:
            if st.get(a, 0) != b:
                return bad
        elif kind == IO_SSTORE:
            if b == 0:
                st.pop(a, None)
            else:
                st[a] = b
        elif kind == IO_PAY:
            if sel:
                effects.append(("pay", sel, a, b))
                sel = 0
            else:
                payouts.append((a, b))
        elif kind == IO_AMINT:
            if not sel:
                return bad
            effects.append(("mint", sel, a, b))
            sel = 0
        elif kind in (IO_BHASH, IO_BEACON):
            chain_reads.append((kind, a, b))
        elif kind == IO_RET:
            ret, ret_seen = a, True
        elif kind == IO_ASEL:
            if a == 0 or b != 0:
                return bad
            sel = a
        elif kind == IO_ABURN:
            if a == 0:
                return bad
            effects.append(("burn", a, 0, b))
        elif kind == IO_ABAL:
            if a == 0:
                return bad
            effects.append(("bal", a, 0, b))
        elif kind == IO_ARENOUNCE:
            if a == 0 or b != 0:
                return bad
            effects.append(("renounce", a, 0, 0))
        else:
            return bad
    if not ret_seen or sel:
        return bad
    return (True, ret, st, payouts, chain_reads) + ((effects,) if with_assets else ())
