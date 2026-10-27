"""
zkasm — the NADO zkVM assembly language + assembler (doc/zk-execution-proofs.md). "zkasm" is the human-
writable text form every on-chain contract is authored in; this module assembles it (labels, comments, and
the safety/convenience macros below) into the canonical [[op, d, s, imm], ...] instruction lists zkvm2.py
runs and the execution AIR proves. Text form:

    ; dice: payout if guess == roll
    start:
        ctx r1 caller
        hash r2 <- r0 r1          ; r2 = zkvm2.hash_words([r0, r1])
        lo32 r2                   ; window it for divmod
        movi r3 6
        divmod r2 r3              ; r2 = quotient, r7 = remainder
        eq r7 r4
        jnz r7 @win
        movi r0 0
        ret r0
    win:
        pay r1 r5
        movi r0 1
        ret r0

Macros: hash d <- s1 s2 ... (HINIT, one HABS per element, HOUT) · gte d s (LT;NOTB) · not d (alias NOTB) ·
rem/mod d s (d = d % s — DIVMOD then move r7 remainder into d; the safe form of the card/id/roll pattern) ·
slot d field k (d = field*2^32 + k). CTX accepts caller|value|cursor|time. Jump targets are @label (pass 2).
Assets (doc/assets.md): apay <asset> <to> <amt> · amint <asset> <to> <amt> (issuer-only, checked by the exec
layer) · aburn <asset> <amt> · abal d <asset> (this contract's holding) · actx d asset|self (the asset
escrowed WITH this call, and the contract's own address digest).
Args: the first 8 call args preload r0..r7; `arg rd rs` loads args[rs] (any of up to 1024) by dynamic index —
loop over it for variadic inputs (merkle proofs, batches) instead of packing into bitmasks.
Division: `divmod d s` / `divmodw d s` (the same instruction on the 256-bit word: quotient in d, remainder in r7,
a zero divisor reverts); `rem`/`remw` are the remainder-to-dest forms.

ONE INSTRUCTION SET (G9 slice 3b): the gen-28 field VM's ISA ("v1": a hash round opcode block per absorbed word, a RANGE
pair before every LT, 64-bit immediates) was deleted with zkvm.py; every contract assembles for zkvm2, and the output
is byte-identical to what `assemble(text, "v2")` produced before (tests/test_every_contract_builds_byte_identical_
for_the_256_bit_vm.py pins it). The SOURCE of every contract is the text it always was.
"""
from execnode import zkvm2

_CTX = {"caller": zkvm2.CTX_CALLER, "value": zkvm2.CTX_VALUE, "cursor": zkvm2.CTX_CURSOR, "time": zkvm2.CTX_TIME}
_ACTX = {"asset": zkvm2.ACTX_ASSET, "self": zkvm2.ACTX_SELF}
NUM_REGS = 8


def _reg(tok):
    if not (len(tok) == 2 and tok[0] == "r" and tok[1].isdigit() and int(tok[1]) < NUM_REGS):
        raise zkvm2.ZkVMError(f"bad register {tok!r}")
    return int(tok[1])


def _imm(tok, bits=256):
    try:
        v = int(tok, 0)
    except ValueError:
        raise zkvm2.ZkVMError(f"bad immediate {tok!r}")
    if not (0 <= v < 2**bits):
        raise zkvm2.ZkVMError(f"immediate out of range {tok!r}")
    return v


def assemble(text):
    """Assemble one method body. Returns the instruction list ready for zkvm2.validate_code."""
    # pass 1: expand macros into (op, d, s, imm-or-("@", label)) tuples, record label positions
    out, labels = [], {}
    for raw in text.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line.endswith(":"):
            labels[line[:-1].strip()] = len(out)
            continue
        toks = line.replace(",", " ").split()
        op = toks[0].upper()
        if op == "HASH":                                       # hash d <- s1 s2 ...
            if len(toks) < 4 or toks[2] != "<-":
                raise zkvm2.ZkVMError(f"hash syntax: hash d <- s1 s2 ... ({line!r})")
            d = _reg(toks[1])
            out.append(["HINIT", 0, 0, 0])
            for stok in toks[3:]:
                out.append(["HABS", 0, _reg(stok), 0])           # one HABS is the whole BLAKE2s compression
            out.append(["HOUT", d, 0, 0])
        elif op == "SLOT":                                     # slot rd <field> rk  ->  rd = field*2^32 + rk
            # Composite integer storage addressing (doc/zk-execution-proofs.md game model): a game's map
            # entry lives at slot = field_id * 2^32 + key. field_id*2^32 is a COMPILE-TIME constant (one MOVI)
            # so a slot address costs just MOVI+ADD, and the frontend computes the identical slot from
            # (field, key) with no hashing. Keys (game/table/seat ids) are frontend ints < 2^32 -> enumerable.
            d = _reg(toks[1]); field = _imm(toks[2], 256); k = _reg(toks[3])
            out.append(["MOVI", d, 0, field << 32])
            out.append(["ADD", d, k, 0])
        elif op == "LT":                                       # lt d s  ->  LT d s (exact over the whole word)
            # (the field VM needed a RANGE pair before every LT to make its windowed compare sound; zkvm2's LT is
            # sound alone, so the macro emits none — the gen-29 contracts were assembled exactly so)
            d, s = _reg(toks[1]), _reg(toks[2])
            out.append(["LT", d, s, 0])
        elif op == "GTE":                                      # gte d s  ->  LT d s ; notb d
            d, s = _reg(toks[1]), _reg(toks[2])
            out.append(["LT", d, s, 0])
            out.append(["NOTB", d, 0, 0])
        elif op in ("REM", "MOD", "REMW"):                     # rem[w] d s  ->  d = d % s  (remainder to dest)
            # DIVMOD/DIVMODW put the quotient in `d` and the remainder in r7; the remainder is what game logic
            # almost always wants (card%52, id%n, roll%6). Writing that as two ops (divmod d s ; mov d r7) is
            # the single most repeated footgun in these contracts — forget the `mov` and you silently use the
            # QUOTIENT. `rem`/`remw` make it atomic and impossible to get wrong. Guards: d must differ from s
            # and never be r7 (the op writes both quotient->d and remainder->r7, so d==r7 is ambiguous).
            d, s = _reg(toks[1]), _reg(toks[2])
            if d == s or d == 7:
                raise zkvm2.ZkVMError(f"rem/mod dest must differ from divisor and not be r7 ({line!r})")
            out.append(["DIVMODW" if op == "REMW" else "DIVMOD", d, s, 0])
            out.append(["MOV", d, 7, 0])
        elif op == "NOT":
            out.append(["NOTB", _reg(toks[1]), 0, 0])
        elif op == "CTX":
            if toks[2] not in _CTX:
                raise zkvm2.ZkVMError(f"ctx wants caller|value|cursor|time ({line!r})")
            out.append(["CTX", _reg(toks[1]), 0, _CTX[toks[2]]])
        elif op == "ACTX":
            if len(toks) < 3 or toks[2] not in _ACTX:
                raise zkvm2.ZkVMError(f"actx wants asset|self ({line!r})")
            out.append(["ACTX", _reg(toks[1]), 0, _ACTX[toks[2]]])
        elif op in ("APAY", "AMINT"):                          # apay/amint <asset> <to> <amount>
            # An asset move needs three registers and an instruction holds two, so it assembles to the atomic
            # pair `ASEL asset ; PAY|AMINT to amount` that zkvm2.validate_code enforces. Only the MACRO is
            # exposed — there is deliberately no way to write a bare `asel` in zkasm, so an author cannot
            # separate the selection from the spend (the fund-substitution footgun the deploy gate rejects).
            if len(toks) != 4:
                raise zkvm2.ZkVMError(f"{op.lower()} syntax: {op.lower()} <asset> <to> <amount> ({line!r})")
            out.append(["ASEL", 0, _reg(toks[1]), 0])
            out.append(["PAY" if op == "APAY" else "AMINT", _reg(toks[2]), _reg(toks[3]), 0])
        elif op == "ABURN":                                    # aburn <asset> <amount> — burns from SELF
            out.append(["ABURN", _reg(toks[1]), _reg(toks[2]), 0])
        elif op == "ABAL":                                     # abal rd <asset> — SELF's balance of an asset
            out.append(["ABAL", _reg(toks[1]), _reg(toks[2]), 0])
        elif op == "ARENOUNCE":                                # arenounce <asset> — SELF seals its own mint
            out.append(["ARENOUNCE", _reg(toks[1]), 0, 0])
        elif op in ("JMP", "JNZ"):
            tgt = toks[-1]
            if not tgt.startswith("@"):
                raise zkvm2.ZkVMError(f"jump target must be @label ({line!r})")
            s = _reg(toks[1]) if op == "JNZ" else 0
            out.append([op, 0, s, ("@", tgt[1:])])
        elif op == "MOVI":
            out.append(["MOVI", _reg(toks[1]), 0, _imm(toks[2], 256)])
        elif op in ("MOV", "ADD", "SUB", "MUL", "EQ", "DIVMOD", "DIVMODW", "SLOAD", "SSTORE", "PAY",
                    "ARG"):
            out.append([op, _reg(toks[1]), _reg(toks[2]), 0])
        elif op in ("NEZ", "NOTB", "RANGE", "LO32", "HOUT"):
            out.append([op, _reg(toks[1]), 0, 0])
        elif op in ("REQUIRE", "HABS", "RET"):
            out.append([op, 0, _reg(toks[1]), 0])
        elif op in ("BHASH", "BEACON"):
            out.append([op, _reg(toks[1]), _reg(toks[2]), 0])
        elif op in ("NOP", "HINIT"):
            out.append([op, 0, 0, 0])
        else:
            raise zkvm2.ZkVMError(f"unknown op {op!r}")
    # pass 2: resolve labels
    for ins in out:
        if isinstance(ins[3], tuple):
            name = ins[3][1]
            if name not in labels:
                raise zkvm2.ZkVMError(f"unknown label @{name}")
            ins[3] = labels[name]
    return out


def assemble_contract(methods):
    """{method: asm text} -> validated zkvm2 code object."""
    code = {m: assemble(t) for m, t in methods.items()}
    zkvm2.validate_code(code)
    return code
