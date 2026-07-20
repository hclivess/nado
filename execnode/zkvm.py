"""
zkVM — NADO's PROVABLE execution VM (doc/zk-execution-proofs.md). A field-native register machine designed so
that one execution step = one STARK trace row (execnode/stark/vm_circuit.py): every value is a Goldilocks
field element, the only hash is the in-circuit alghash sponge (exposed as explicit round opcodes so the AIR
needs no round-constant lookups), and every effect on the world — storage reads/writes, payouts, randomness
reads, the return value — is an ORDERED PUBLIC I/O LOG that a verifier replays against its state without
re-executing the contract. This replaces the string/BLAKE2b stack VM (vm.py) as the execution model that
settlement validity proofs are built over; there is deliberately NO compatibility path between the two.

Machine: 8 registers r0..r7 (the FIRST 8 call args preloaded), pc, an alghash sponge (h0,h1), and per-call
flat storage slot(field) -> value(field). One instruction = [op, d, s, imm] (unused operands 0). Gas =
executed steps (= trace rows), capped only by what fits one proof (the 2^17-row AIR ceiling).

Calls take up to MAX_ARGS (1024) arguments: the first 8 preload r0..r7 (compat with the register ABI), and
ARG rd rs loads args[rs] into rd by DYNAMIC index — so contracts loop over arbitrarily many inputs (merkle
proofs, batch operations) without packing hacks. ARG is proven by a dedicated LogUp lookup into the public
args table (vm_circuit.py), exactly like program fetch: a wrong (index, value) pair makes the proof
unverifiable. DESIGN RULE (mainnet): the VM carries as few limits as possible — no replay is enforced on
contracts, the PROOF is the gate — so every remaining bound is either soundness-mandated (the DIVMOD/LT
windows, which stop field wrap-around forgeries) or proof capacity (the trace ceiling), never taste.

Integer semantics over a prime field (the part that must be exact for the AIR to be SOUND — the interpreter
mirrors the constraints bit-for-bit, and reverts wherever the constraints would be unsatisfiable):
  LT/RANGE   63-bit window, byte+7bit limb decomposition; compare is deterministic for operands < 2^62
             (contract discipline: RANGE-check foreign values; all NADO amounts are far below 2^62).
             NOTE: full-field comparisons (e.g. faucet PoW hash < target) rely on the difference fitting
             the 63-bit window; a SOUND full-field compare needs a 2-limb gadget (open design item).
  DIVMOD     a//b with 1 <= b < 2^15 and q < 2^48 (else revert): q,b-1,rem,b-rem-1 all limb-decomposed,
             so q*b + rem = a cannot wrap p — the classic field-division forgery is structurally excluded.
             The 48/15 split serves big-value-by-small-constant math (stake*99/target).
  DIVMODW    the SAME soundness budget cut the other way: 1 <= b < 2^31 and q < 2^32 (q·b < 2^63 < P still).
             This is division by DATA-sized divisors — pro-rata pool splits (parimutuel payout =
             stake*total//pool), price ratios — in ONE op instead of an unrolled long-division loop.
             Remainder lands in r7 like DIVMOD. Fits the same 13-byte/4-sevenbit witness limbs exactly.
  LO32       canonical split x = hi*2^32 + lo, keeps lo. hi = 2^32-1 forces lo = 0 (the x vs x+p double
             decomposition of small values is excluded) — this is the sound "window a hash for DIVMOD" op.
Commit-reveal / randomness: HINIT/HABS/HR0..HR{ROUNDS-1}/HOUT are alghash.hashn laid out one round per row (the
HR block scales with alghash.ROUNDS — 27 rounds, one opcode each); BHASH and
BEACON read finalized chain randomness through the I/O log (public, so the verifier checks them natively).
"""
from execnode.stark import field as F, alghash

GAS_LIMIT = 131070               # executed steps per call = the FULL proof capacity: the AIR ceiling is
                                 # stark.MAX_TRACE_ROWS = 2^17 = 131072 and the trace needs 2 rows of
                                 # padding, so this is the largest call one proof can carry. Small calls
                                 # pad to the next power of two of their ACTUAL length, so raising the
                                 # ceiling costs nothing until a contract actually uses it.
MAX_ARGS = 1024                  # statement-size guard, not a semantic limit: args are part of the public
                                 # call statement (they ride in the blob + proof statement), so this only
                                 # bounds DoS-sized statements. The first 8 preload r0..r7; ARG reaches all.
NUM_REGS = 8

# opcode ids — FROZEN once contracts deploy against them (they are baked into program tables inside proofs).
# New ops are APPENDED so existing bytecode/proof statements never shift. The HR round opcodes MUST stay a
# CONTIGUOUS run HR0..HR{ROUNDS-1} (the interpreter/AIR select a round by op-HR0), and their count == the
# alghash round count — so they are generated from alghash.ROUNDS rather than spelled out. Changing ROUNDS
# shifts the ids of the ops AFTER the block, which is a hard reset only (bytecode is re-assembled from zkasm).
OPS = (["NOP", "MOVI", "MOV", "ADD", "SUB", "MUL", "EQ", "NEZ", "NOTB", "LT", "RANGE", "DIVMOD", "LO32",
        "JMP", "JNZ", "REQUIRE", "CTX", "HINIT", "HABS", "HOUT"]
       + [f"HR{r}" for r in range(alghash.ROUNDS)]
       + ["SLOAD", "SSTORE", "PAY", "BHASH", "BEACON", "RET", "ARG", "DIVMODW"]
       + ["ASEL", "AMINT", "ABURN", "ABAL", "ACTX"])
OP = {name: i for i, name in enumerate(OPS)}
HR0 = OP["HR0"]

# I/O log kinds — the public effect vocabulary a verifier replays
IO_SLOAD, IO_SSTORE, IO_PAY, IO_BHASH, IO_BEACON, IO_RET = 1, 2, 3, 4, 5, 6
# ASSET I/O (doc/assets.md): the same replay discipline as PAY — the VM EMITS the intent, the exec layer
# checks authority/solvency against the committed asset ledger. The AIR proves only that the program emitted
# exactly these entries in this order; what they MEAN is public, deterministic replay in execnode/state.py.
IO_ASEL, IO_AMINT, IO_ABURN, IO_ABAL = 7, 8, 9, 10
IO_ASSET_KINDS = (IO_ASEL, IO_AMINT, IO_ABURN, IO_ABAL)

# CTX indices (imm operand of the CTX opcode)
CTX_CALLER, CTX_VALUE, CTX_CURSOR, CTX_TIME = 0, 1, 2, 3
# ACTX indices (imm operand of the ACTX opcode) — the asset-layer half of the call context, kept in its OWN
# opcode rather than widening CTX so the CTX mux stays a degree-3 Lagrange over 4 points in the AIR.
# 2 and 3 are reserved and read as 0 (the mux must be total on 0..3 for the constraint to be sound).
ACTX_ASSET, ACTX_SELF = 0, 1

# limb geometry shared with the AIR: 13 byte limbs (B0..B12) + 4 seven-bit limbs (S0..S3)
NUM_BYTE_LIMBS, NUM_7BIT_LIMBS = 13, 4


class ZkVMError(Exception):
    pass


class ZkVMRevert(ZkVMError):
    """The call is a no-op AND unprovable — the interpreter reverts exactly where the AIR constraints would
    have no satisfying witness, so 'provable' and 'executes successfully' are the same set of calls."""


def validate_code(code):
    """Reject malformed zkVM bytecode at deploy: {method: [[op,d,s,imm],...]}, ops known, operands in range,
    jump targets inside the method. Deterministic across nodes (pure structural checks)."""
    if not isinstance(code, dict) or not code:
        raise ZkVMError("contract code must be a non-empty {method: [instructions]} object")
    for method, prog in code.items():
        if not isinstance(method, str) or not isinstance(prog, list) or not prog:
            raise ZkVMError(f"bad method {method!r}")
        if len(prog) > GAS_LIMIT:
            raise ZkVMError(f"method {method} longer than GAS_LIMIT")
        for ins in prog:
            if (not isinstance(ins, list) or len(ins) != 4 or ins[0] not in OP
                    or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in ins[1:])):
                raise ZkVMError(f"invalid instruction {ins!r} in {method}")
            op, d, s, imm = ins
            if d >= NUM_REGS or s >= NUM_REGS:
                raise ZkVMError(f"register out of range in {ins!r}")
            if imm >= F.P:
                raise ZkVMError(f"immediate out of field in {ins!r}")
            if op in ("JMP", "JNZ") and imm >= len(prog):
                raise ZkVMError(f"jump target out of range in {ins!r}")
            if op in ("DIVMOD", "DIVMODW") and d == 7:
                raise ZkVMError(f"{op} dest must not be r7 (r7 receives the remainder)")
            if op == "CTX" and imm > 3:
                raise ZkVMError("CTX index must be 0..3 (caller/value/cursor/time)")
            if op == "ACTX" and imm > 3:
                raise ZkVMError("ACTX index must be 0..3 (asset/self; 2-3 reserved, read 0)")
        # SOUND-COMPARISON ENFORCEMENT (consensus, not just assembler discipline): a windowed prime-field
        # compare is only unforgeable when both operands are proven < 2^62. Every LT MUST be the tail of an
        # atomic `RANGE d ; RANGE s ; LT d s` block (what the `lt`/`gte` macros emit), and no jump may land on
        # the LT or its second RANGE (which would skip a range-check). Without this, hand-crafted bytecode with
        # a naked LT could forge the comparison bit for operands >= ~2^63 (the AIR only decomposes the
        # difference in a 63-bit window). Enforced at the deploy gate, so ALL bytecode is covered.
        no_jump = set()                                   # indices a jump must NOT target (would skip a RANGE)
        for i, ins in enumerate(prog):
            if ins[0] == "LT":
                d, s = ins[1], ins[2]
                if not (i >= 2 and prog[i - 2][0] == "RANGE" and prog[i - 2][1] == d
                        and prog[i - 1][0] == "RANGE" and prog[i - 1][1] == s):
                    raise ZkVMError(f"LT at {i} in {method} is not preceded by RANGE on both operands "
                                    f"(unsound unbounded comparison)")
                no_jump.add(i)          # the LT itself
                no_jump.add(i - 1)      # its second RANGE (jumping here skips the first RANGE)
        # ASSET-SELECTION ENFORCEMENT (same shape, same reason as the compare block above): an asset move
        # needs THREE values — asset, recipient, amount — and an instruction carries only two registers. So
        # `ASEL rs` publishes the asset and the very next instruction spends it. That pairing is only
        # meaningful if it is ATOMIC: a jump landing on the PAY/AMINT would move the asset the PREVIOUS
        # ASEL selected (or, with no prior ASEL, would silently move native NADO instead of the token —
        # a fund-substitution bug the replayer cannot detect, because both logs are individually well-formed).
        # Enforced at the deploy gate so no hand-crafted bytecode can construct the unpaired form.
        for i, ins in enumerate(prog):
            if ins[0] == "ASEL":
                if i + 1 >= len(prog) or prog[i + 1][0] not in ("PAY", "AMINT"):
                    raise ZkVMError(f"ASEL at {i} in {method} must be immediately followed by PAY or AMINT")
                no_jump.add(i + 1)      # jumping onto the spend would use a stale/absent selection
            if ins[0] == "AMINT" and not (i >= 1 and prog[i - 1][0] == "ASEL"):
                raise ZkVMError(f"AMINT at {i} in {method} is not preceded by ASEL (no asset selected)")
        for ins in prog:
            if ins[0] in ("JMP", "JNZ") and ins[3] in no_jump:
                raise ZkVMError(f"jump into a compare macro at index {ins[3]} in {method} would skip a RANGE")
    return True


def _bytes_of(v, n):
    """n little-endian byte limbs of v (v must fit)."""
    return [(v >> (8 * k)) & 255 for k in range(n)]


def _decomp63(v):
    """63-bit window decomposition: 7 byte limbs + 1 seven-bit limb, or None if v >= 2^63. Used by LT/RANGE."""
    if v < 0 or v >= 1 << 63:
        return None
    return _bytes_of(v, 7), (v >> 56) & 127


def _decomp62(v):
    """62-bit window: 6 byte limbs + 2 seven-bit limbs (48 + 7 + 7 bits), or None if v >= 2^62. RANGE's SOUND
    bound: with P ~ 2^64, a comparison is unforgeable only when both operands are < 2^62 (then the wrong bit's
    field-wrapped difference is >= P - 2^62 > 2^63 and cannot fit LT's window). RANGE-checking both operands to
    < 2^62 before an LT is exactly what makes LT sound — the `lt`/`gte` macros do it automatically."""
    if v < 0 or v >= 1 << 62:
        return None
    hi = v >> 48                                          # bits 48..61 (14 bits) -> two 7-bit limbs
    return _bytes_of(v, 6), hi & 127, (hi >> 7) & 127


def _decomp31(v):
    """31-bit window: 3 byte limbs + 1 seven-bit limb, or None if v >= 2^31."""
    if v < 0 or v >= 1 << 31:
        return None
    return _bytes_of(v, 3), (v >> 24) & 127


def _decomp15(v):
    """15-bit window: 1 byte limb + 1 seven-bit limb, or None if v >= 2^15 (the DIVMOD divisor/remainder
    window). Small divisors keep q·b < 2^63 < P so field-division can't wrap (the classic forgery)."""
    if v < 0 or v >= 1 << 15:
        return None
    return v & 255, (v >> 8) & 127


def run(code, method, caller, args, storage, value=0, cursor=0, timestamp=0, beacons=None, block_hashes=None,
        asset=0, selfd=0, abal=None, witness=False):
    """Execute code[method] with r0..r7 = the first 8 args (padded); ARG reaches all of them (up to
    MAX_ARGS) by dynamic index. `caller` is a FIELD element (the alghash address
    digest — address strings never enter zkVM; the exec layer digests them at the call boundary). `storage` is
    {slot(int): value(int)} for this contract. Returns (ok, ret, new_storage, io_log[, steps]):
      io_log = ordered [(kind, a, b)] — SLOAD/SSTORE (slot,value), PAY (to_digest, amount),
               BHASH/BEACON (height/epoch, value), RET (value, 0) — always ending in exactly one RET on ok.
      steps (witness=True) = per-row prover witness: regs/pc/sponge after each step + wi/wj inverses + limbs.
    Asset context (doc/assets.md): `asset` is the asset id escrowed with this call (0 = native NADO), `selfd`
    the running contract's own address digest — both read through ACTX. `abal` is {asset_id: balance} of what
    the contract HOLDS, read through ABAL exactly the way `beacons`/`block_hashes` are read through
    BEACON/BHASH: supplied by the exec layer, echoed into the public io log, replayed by the verifier.
    On any revert (REQUIRE fail, window violation, gas, missing chain data) returns (False, None, storage, [])
    — a no-op, and equally unprovable in the AIR."""
    if method not in code:
        return (False, None, storage, []) + (([],) if witness else ())
    prog = code[method]
    fargs = [a % F.P for a in args]                      # the FULL args vector — ARG indexes into it
    regs = [(fargs[i] if i < len(fargs) else 0) for i in range(NUM_REGS)]
    if len(fargs) > MAX_ARGS:
        return (False, None, storage, []) + (([],) if witness else ())
    caller %= F.P
    ctxv = [caller, value % F.P, cursor % F.P, timestamp % F.P]
    actxv = [asset % F.P, selfd % F.P, 0, 0]             # 2-3 reserved: the AIR mux must be total on 0..3
    selfd %= F.P
    asel = 0                # the asset a live ASEL published, spent by the very next instruction
    apend = {}              # asset -> this call's pending delta on SELF's holding (see the ABAL case)

    def _aspend(a, amt):
        """Debit `amt` of asset `a` from the contract's own holding for the rest of this call, reverting if
        that would take it negative. The exec layer re-derives the identical arithmetic when it settles the
        call's effects in order (ExecState.stage_asset_effects); reverting HERE only means the VM refuses to
        produce a log for a call the layer would reject anyway, and keeps every ABAL a sane number."""
        have = int((abal or {}).get(a, 0)) + apend.get(a, 0)
        if amt > have:
            raise ZkVMRevert("asset move exceeds the contract's holding")
        apend[a] = apend.get(a, 0) - amt
    st = dict(storage)
    io = []
    steps = []
    pc = 0
    h0 = h1 = 0
    gas = 0
    ret = None
    try:
        while True:
            if gas >= GAS_LIMIT:
                raise ZkVMRevert("gas limit exceeded")
            gas += 1
            op_name, d, s, imm = prog[pc]
            op = OP[op_name]
            rd, rs = regs[d], regs[s]
            wi = wj = 0
            bl = [0] * NUM_BYTE_LIMBS
            sl = [0] * NUM_7BIT_LIMBS
            io_entry = None
            nxt_pc = pc + 1
            res, wr = None, False

            if op_name == "NOP":
                pass
            elif op_name == "MOVI":
                res, wr = imm, True
            elif op_name == "MOV":
                res, wr = rs, True
            elif op_name == "ADD":
                res, wr = F.add(rd, rs), True
            elif op_name == "SUB":
                res, wr = F.sub(rd, rs), True
            elif op_name == "MUL":
                res, wr = F.mul(rd, rs), True
            elif op_name == "EQ":
                diff = F.sub(rd, rs)
                wi = F.inv(diff) if diff else 0
                res, wr = (0 if diff else 1), True
            elif op_name == "NEZ":
                wi = F.inv(rd) if rd else 0
                res, wr = (1 if rd else 0), True
            elif op_name == "NOTB":
                if rd not in (0, 1):
                    raise ZkVMRevert("NOTB on a non-bit")
                res, wr = 1 - rd, True
            elif op_name == "LT":
                b = 1 if rd < rs else 0
                dv = (rs - rd - 1) if b else (rd - rs)
                dec = _decomp63(dv)
                if dec is None:
                    raise ZkVMRevert("LT operands outside the 63-bit window")
                bl[:7], sl[0] = dec[0], dec[1]
                wi = b                                        # the AIR's b-bit lives in the wi column
                res, wr = b, True
            elif op_name == "RANGE":
                dec = _decomp62(rd)                            # SOUND bound: < 2^62 (makes a following LT unforgeable)
                if dec is None:
                    raise ZkVMRevert("RANGE failed (value >= 2^62)")
                bl[0:6], sl[0], sl[1] = dec[0], dec[1], dec[2]
            elif op_name == "DIVMOD":
                a, b = rd, rs
                if not (1 <= b <= (1 << 15)):                 # small divisor keeps q·b < 2^63 (no field wrap)
                    raise ZkVMRevert("DIVMOD divisor outside [1, 2^15]")
                q, rem = a // b, a % b
                if q >= (1 << 48):                            # 48-bit quotient window (financial operands)
                    raise ZkVMRevert("DIVMOD quotient outside [0, 2^48)")
                bl[0:6] = _bytes_of(q, 6)                     # q: 6 byte limbs
                bl[6], sl[1] = _decomp15(b - 1)               # b-1, rem, b-rem-1: byte + 7-bit each (15 bits)
                bl[7], sl[2] = _decomp15(rem)
                bl[8], sl[3] = _decomp15(b - rem - 1)
                regs[7] = rem                                 # remainder lands in r7 (fixed convention)
                res, wr = q, True
            elif op_name == "DIVMODW":
                a, b = rd, rs
                if not (1 <= b <= (1 << 31)):             # wide divisor: data-sized (pool splits, ratios)
                    raise ZkVMRevert("DIVMODW divisor outside [1, 2^31]")
                q, rem = a // b, a % b
                if q >= (1 << 32):                        # 32-bit quotient keeps q·b < 2^63 (no field wrap)
                    raise ZkVMRevert("DIVMODW quotient outside [0, 2^32)")
                bl[0:4] = _bytes_of(q, 4)                 # q: 4 byte limbs (32 bits)
                bw = _decomp31(b - 1)                     # b-1, rem, b-rem-1: 3 bytes + 7 bits each (31 bits)
                bl[4:7], sl[1] = bw[0], bw[1]
                rw = _decomp31(rem)
                bl[7:10], sl[2] = rw[0], rw[1]
                brw = _decomp31(b - rem - 1)
                bl[10:13], sl[3] = brw[0], brw[1]
                regs[7] = rem                             # remainder lands in r7 (same convention as DIVMOD)
                res, wr = q, True
            elif op_name == "LO32":
                hi, lo = rd >> 32, rd & 0xFFFFFFFF
                if hi == (1 << 32) - 1 and lo != 0:           # canonical: only p-1's decomposition may top out
                    raise ZkVMRevert("LO32 non-canonical")     # (unreachable for in-field values, kept exact)
                bl[0:4] = _bytes_of(lo, 4)
                bl[4:8] = _bytes_of(hi, 4)
                him = F.sub(hi, (1 << 32) - 1)
                wj = F.inv(him) if him else 0
                res, wr = lo, True
            elif op_name == "JMP":
                nxt_pc = imm
            elif op_name == "JNZ":
                wi = F.inv(rs) if rs else 0
                nxt_pc = imm if rs else pc + 1
            elif op_name == "REQUIRE":
                if not rs:
                    raise ZkVMRevert("REQUIRE failed")
                wi = F.inv(rs)
            elif op_name == "CTX":
                if imm > 3:
                    raise ZkVMRevert("bad CTX index")
                res, wr = ctxv[imm], True
            elif op_name == "HINIT":
                h0, h1 = 0, alghash.IV
            elif op_name == "HABS":
                h0 = F.add(h0, rs)
            elif op_name == "HOUT":
                res, wr = h0, True
            elif op >= HR0 and op < HR0 + alghash.ROUNDS:
                r = op - HR0
                t0 = alghash.sbox(F.add(h0, alghash.RC[r][0]))
                t1 = alghash.sbox(F.add(h1, alghash.RC[r][1]))
                h0, h1 = F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))
            elif op_name == "SLOAD":
                val = st.get(rs, 0)
                io_entry = (IO_SLOAD, rs, val)
                res, wr = val, True
            elif op_name == "SSTORE":
                if rs == 0:
                    st.pop(rd, None)                          # zero = absence (canonical minimal state)
                else:
                    st[rd] = rs
                io_entry = (IO_SSTORE, rd, rs)
            elif op_name == "PAY":
                if asel:                                  # the ASEL right before this one made it an ASSET pay
                    if not (selfd and rd == selfd):       # paying ITSELF is a no-op on its own holding
                        _aspend(asel, rs)
                    asel = 0
                io_entry = (IO_PAY, rd, rs)
            elif op_name == "BHASH":
                hv = (block_hashes or {}).get(rs)
                if hv is None:
                    raise ZkVMRevert("block hash for height not available")
                hv %= F.P
                io_entry = (IO_BHASH, rs, hv)
                res, wr = hv, True
            elif op_name == "BEACON":
                bv = (beacons or {}).get(rs)
                if bv is None:
                    raise ZkVMRevert("beacon for epoch not available")
                bv %= F.P
                io_entry = (IO_BEACON, rs, bv)
                res, wr = bv, True
            elif op_name == "ARG":
                # indexed arg load: rd = args[rs]. Reverts out-of-range — exactly where the AIR's args-table
                # lookup would have no satisfying row (the tuple (call, idx, val) must exist in the table).
                if rs >= len(fargs):
                    raise ZkVMRevert("ARG index out of range")
                res, wr = fargs[rs], True
            elif op_name == "ASEL":
                # Publish the asset the NEXT instruction spends. Emits no value and writes no register — its
                # whole effect is the io entry, which the deploy gate has already bound to the instruction
                # that follows it (validate_code). asset 0 would mean "native", which ASEL must never select
                # (a contract writing `asel r; pay` with r=0 would move NADO where it meant to move a token).
                if rs == 0:
                    raise ZkVMRevert("ASEL of asset 0 (native NADO needs no selection)")
                asel = rs
                io_entry = (IO_ASEL, rs, 0)
            elif op_name == "AMINT":
                if selfd and rd == selfd:                 # minting to ITSELF raises its own holding
                    apend[asel] = apend.get(asel, 0) + rs
                asel = 0
                io_entry = (IO_AMINT, rd, rs)             # mint rs of the SELECTED asset to digest rd
            elif op_name == "ABURN":
                _aspend(rd, rs)
                io_entry = (IO_ABURN, rd, rs)             # burn rs of asset rd from the contract's own holding
            elif op_name == "ABAL":
                # The contract's own balance of asset rs — a LOAD off the io bus, identical in shape to
                # SLOAD/BHASH/BEACON: the value is supplied by the exec layer, published in the log, and the
                # verifier replays it against the committed asset ledger. Unknown asset reads 0 (an asset
                # nobody holds and an asset that does not exist are the same balance), so this never reverts.
                #
                # It reads the ledger PLUS this call's own pending moves. It has to: the exec layer settles
                # a call's effects IN ORDER, so `apay(x); abal(x)` must see the reduced holding or the VM and
                # the settlement replay would disagree about the same number and the call would revert on a
                # balance check it thought it had passed.
                bv = (int((abal or {}).get(rs, 0)) + apend.get(rs, 0)) % F.P
                io_entry = (IO_ABAL, rs, bv)
                res, wr = bv, True
            elif op_name == "ACTX":
                res, wr = actxv[imm], True
            elif op_name == "RET":
                ret = rs
                io_entry = (IO_RET, rs, 0)

            if wr:
                regs[d] = res
            if io_entry is not None:
                io.append(io_entry)
            if witness:
                steps.append({"pc": pc, "op": op, "d": d, "s": s, "imm": imm, "regs": list(regs),
                              "h0": h0, "h1": h1, "wi": wi, "wj": wj, "bl": list(bl), "sl": list(sl),
                              "ioc_after": len(io)})
            if op_name == "RET":
                break
            pc = nxt_pc
        return (True, ret, st, io) + ((steps,) if witness else ())
    except (ZkVMRevert, IndexError, KeyError, ZeroDivisionError):
        return (False, None, storage, []) + (([],) if witness else ())


def replay_io(io_log, storage, with_assets=False):
    """What a VERIFIER does instead of executing: replay a proven call's public I/O log against its copy of
    the contract storage. Returns (ok, ret, new_storage, payouts, chain_reads). Read entries must match the
    current state exactly (read-after-write works because entries apply in order); chain_reads (BHASH/BEACON)
    are returned for the caller to check against finalized chain data. ok requires exactly one RET, last.

    ASSETS (doc/assets.md). `with_assets=True` returns a SIXTH element, `effects` — the ordered asset
    intents ("pay"/"mint"/"burn", asset, to, amount) and reads ("bal", asset, value) the caller must settle
    and check against the asset ledger. It defaults to FALSE and then REJECTS any log containing an asset
    entry: fail-closed, because a verifier that silently dropped the asset half of a log would confirm a
    state transition it had not actually checked. Opting in is how a caller states it can settle them."""
    st = dict(storage)
    payouts, chain_reads, effects = [], [], []
    ret, ret_seen = None, False
    bad = (False, None, storage, [], []) + (([],) if with_assets else ())
    sel = 0                                          # asset published by an ASEL, live for exactly one entry
    for i, entry in enumerate(io_log):
        if ret_seen:
            return bad
        if not (isinstance(entry, (list, tuple)) and len(entry) == 3
                and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < F.P for x in entry)):
            return bad
        kind, a, b = entry
        if kind in IO_ASSET_KINDS and not with_assets:
            return bad                               # fail-closed: see the with_assets note above
        # Mirror of validate_code's ASEL pairing rule, re-checked HERE because replay_io verifies a LOG, not
        # a program: an unpaired PAY after an ASEL would move native NADO where the contract meant to move a
        # token, and an AMINT with no selection has no asset at all. Both entries are well-formed in
        # isolation, so the pairing is the only thing that makes the log unambiguous.
        if sel and kind not in (IO_PAY, IO_AMINT):
            return bad                               # a selection MUST be spent by the very next entry
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
                return bad                           # a mint with no asset selected
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
        elif kind == IO_ABAL:                        # a read the caller checks against the ledger
            if a == 0:
                return bad
            effects.append(("bal", a, 0, b))
        else:
            return bad
    if not ret_seen or sel:
        return bad
    return (True, ret, st, payouts, chain_reads) + ((effects,) if with_assets else ())
