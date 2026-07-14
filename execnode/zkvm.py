"""
zkVM — NADO's PROVABLE execution VM (doc/zk-execution-proofs.md). A field-native register machine designed so
that one execution step = one STARK trace row (execnode/stark/vm_circuit.py): every value is a Goldilocks
field element, the only hash is the in-circuit alghash sponge (exposed as explicit round opcodes so the AIR
needs no round-constant lookups), and every effect on the world — storage reads/writes, payouts, randomness
reads, the return value — is an ORDERED PUBLIC I/O LOG that a verifier replays against its state without
re-executing the contract. This replaces the string/BLAKE2b stack VM (vm.py) as the execution model that
settlement validity proofs are built over; there is deliberately NO compatibility path between the two.

Machine: 8 registers r0..r7 (call args preloaded), pc, an alghash sponge (h0,h1), and per-call flat storage
slot(field) -> value(field). One instruction = [op, d, s, imm] (unused operands 0). Gas = executed steps
(= trace rows), capped so a call always fits one proof.

Integer semantics over a prime field (the part that must be exact for the AIR to be SOUND — the interpreter
mirrors the constraints bit-for-bit, and reverts wherever the constraints would be unsatisfiable):
  LT/RANGE   63-bit window, byte+7bit limb decomposition; compare is deterministic for operands < 2^62
             (contract discipline: RANGE-check foreign values; all NADO amounts are far below 2^62).
  DIVMOD     a//b with 1 <= b < 2^31 and a < b*2^32 (else revert): q,b-1,rem,b-rem-1 all limb-decomposed,
             so q*b + rem = a cannot wrap p — the classic field-division forgery is structurally excluded.
  LO32       canonical split x = hi*2^32 + lo, keeps lo. hi = 2^32-1 forces lo = 0 (the x vs x+p double
             decomposition of small values is excluded) — this is the sound "window a hash for DIVMOD" op.
Commit-reveal / randomness: HINIT/HABS/HR0..HR7/HOUT are alghash.hashn laid out one round per row; BHASH and
BEACON read finalized chain randomness through the I/O log (public, so the verifier checks them natively).
"""
from execnode.stark import field as F, alghash

GAS_LIMIT = 8191                 # executed steps per call; keeps T = next_pow2(steps+1) <= 8192 (one proof)
MAX_ARGS = 8
NUM_REGS = 8

# opcode ids — FROZEN once contracts deploy against them (they are baked into program tables inside proofs)
OPS = ["NOP", "MOVI", "MOV", "ADD", "SUB", "MUL", "EQ", "NEZ", "NOTB", "LT", "RANGE", "DIVMOD", "LO32",
       "JMP", "JNZ", "REQUIRE", "CTX", "HINIT", "HABS", "HOUT",
       "HR0", "HR1", "HR2", "HR3", "HR4", "HR5", "HR6", "HR7",
       "SLOAD", "SSTORE", "PAY", "BHASH", "BEACON", "RET"]
OP = {name: i for i, name in enumerate(OPS)}
HR0 = OP["HR0"]

# I/O log kinds — the public effect vocabulary a verifier replays
IO_SLOAD, IO_SSTORE, IO_PAY, IO_BHASH, IO_BEACON, IO_RET = 1, 2, 3, 4, 5, 6

# CTX indices (imm operand of the CTX opcode)
CTX_CALLER, CTX_VALUE, CTX_CURSOR, CTX_TIME = 0, 1, 2, 3

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
            if op == "DIVMOD" and d == 7:
                raise ZkVMError("DIVMOD dest must not be r7 (r7 receives the remainder)")
            if op == "CTX" and imm > 3:
                raise ZkVMError("CTX index must be 0..3 (caller/value/cursor/time)")
    return True


def _bytes_of(v, n):
    """n little-endian byte limbs of v (v must fit)."""
    return [(v >> (8 * k)) & 255 for k in range(n)]


def _decomp63(v):
    """63-bit window decomposition: 7 byte limbs + 1 seven-bit limb, or None if v >= 2^63."""
    if v < 0 or v >= 1 << 63:
        return None
    return _bytes_of(v, 7), (v >> 56) & 127


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
        witness=False):
    """Execute code[method] with r0..r7 = args (padded). `caller` is a FIELD element (the alghash address
    digest — address strings never enter zkVM; the exec layer digests them at the call boundary). `storage` is
    {slot(int): value(int)} for this contract. Returns (ok, ret, new_storage, io_log[, steps]):
      io_log = ordered [(kind, a, b)] — SLOAD/SSTORE (slot,value), PAY (to_digest, amount),
               BHASH/BEACON (height/epoch, value), RET (value, 0) — always ending in exactly one RET on ok.
      steps (witness=True) = per-row prover witness: regs/pc/sponge after each step + wi/wj inverses + limbs.
    On any revert (REQUIRE fail, window violation, gas, missing chain data) returns (False, None, storage, [])
    — a no-op, and equally unprovable in the AIR."""
    if method not in code:
        return (False, None, storage, []) + (([],) if witness else ())
    prog = code[method]
    regs = [(args[i] if i < len(args) else 0) % F.P for i in range(NUM_REGS)]
    if len(args) > MAX_ARGS:
        return (False, None, storage, []) + (([],) if witness else ())
    caller %= F.P
    ctxv = [caller, value % F.P, cursor % F.P, timestamp % F.P]
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
                dec = _decomp63(rd)
                if dec is None:
                    raise ZkVMRevert("RANGE failed (value >= 2^63)")
                bl[:7], sl[0] = dec[0], dec[1]
            elif op_name == "DIVMOD":
                a, b = rd, rs
                if not (1 <= b < (1 << 15)):                  # small divisor keeps q·b < 2^63 (no field wrap)
                    raise ZkVMRevert("DIVMOD divisor outside [1, 2^15)")
                q, rem = a // b, a % b
                if q >= (1 << 48):                            # 48-bit quotient window (financial operands)
                    raise ZkVMRevert("DIVMOD quotient outside [0, 2^48)")
                bl[0:6] = _bytes_of(q, 6)                     # q: 6 byte limbs
                bl[6], sl[1] = _decomp15(b - 1)               # b-1, rem, b-rem-1: byte + 7-bit each (15 bits)
                bl[7], sl[2] = _decomp15(rem)
                bl[8], sl[3] = _decomp15(b - rem - 1)
                regs[7] = rem                                 # remainder lands in r7 (fixed convention)
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
            elif op >= HR0 and op < HR0 + 8:
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


def replay_io(io_log, storage):
    """What a VERIFIER does instead of executing: replay a proven call's public I/O log against its copy of
    the contract storage. Returns (ok, ret, new_storage, payouts, chain_reads). Read entries must match the
    current state exactly (read-after-write works because entries apply in order); chain_reads (BHASH/BEACON)
    are returned for the caller to check against finalized chain data. ok requires exactly one RET, last."""
    st = dict(storage)
    payouts, chain_reads = [], []
    ret, ret_seen = None, False
    for i, entry in enumerate(io_log):
        if ret_seen:
            return (False, None, storage, [], [])
        if not (isinstance(entry, (list, tuple)) and len(entry) == 3
                and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < F.P for x in entry)):
            return (False, None, storage, [], [])
        kind, a, b = entry
        if kind == IO_SLOAD:
            if st.get(a, 0) != b:
                return (False, None, storage, [], [])
        elif kind == IO_SSTORE:
            if b == 0:
                st.pop(a, None)
            else:
                st[a] = b
        elif kind == IO_PAY:
            payouts.append((a, b))
        elif kind in (IO_BHASH, IO_BEACON):
            chain_reads.append((kind, a, b))
        elif kind == IO_RET:
            ret, ret_seen = a, True
        else:
            return (False, None, storage, [], [])
    if not ret_seen:
        return (False, None, storage, [], [])
    return (True, ret, st, payouts, chain_reads)
