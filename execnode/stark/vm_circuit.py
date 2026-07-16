"""
zkVM execution AIR (doc/zk-execution-proofs.md) — prove "running PUBLIC program `code[method]` with PUBLIC
(caller, value, cursor, time, args) produced exactly this PUBLIC I/O log" WITHOUT the verifier executing
anything. One zkVM step = one trace row. The verifier then replays the tiny I/O log against its state
(zkvm.replay_io) — that pair (proof + log replay) is what replaces re-execution.

Layout (one row):
  R0..R7 · PC · IOC (I/O entries emitted so far) · IMM · H0,H1 (sponge) · WI,WJ (per-op inverse/bit witness)
  f_op one-hot (35) · d one-hot (8) · s one-hot (8) · BL0..12 byte limbs · SL0..3 seven-bit limbs
  M_FETCH / M_BYTE / M_7BIT / M_ARG (lookup multiplicities)                                — 87 main columns
  HF,GF (fetch) · HIO,GIO (I/O) · HB0..6,GB (byte, limbs paired) · HS0..1,GS · HA,GA (args) · Z — 18 aux

Five LogUp buses share the single accumulator Z (sound: tuples are domain-tagged, and all columns commit
BEFORE β,γ are drawn — the two-phase protocol in stark.prove):
  fetch  (pc, op, d, s, imm) of every non-NOP row ∈ the program table (periodic, from public code)
  io     (ioc, kind, a, b) of every I/O row  =multiset=  the public log (periodic; ioc pins the ORDER)
  args   (call, index, value) of every ARG row ∈ the public args table (periodic, from the call statement) —
         this is what removes the 8-arg register cap: a call carries up to zkvm.MAX_ARGS args, the first 8
         preload r0..r7, and ARG proves any indexed load against the table (a wrong pair can't verify)
  byte / 7bit   every limb ∈ [0,256) / [0,128)   (range tables as periodic columns)
Public context (caller/value/cursor/time) is baked into the CONSTRAINTS; the first 8 args pin row 0's
registers; the program, log, and args table live in periodic columns — nothing statement-shaped is read
from the proof.
"""
from execnode.stark import field as F, alghash, stark, logup
from execnode import zkvm

# ---- column layout -------------------------------------------------------------------------------
NR = zkvm.NUM_REGS
NOPS = len(zkvm.OPS)
R0 = 0
PC = 8; IOC = 9; IMM = 10; H0 = 11; H1 = 12; WI = 13; WJ = 14
F0 = 15                       # opcode one-hot base: F0 + op_id
D0 = F0 + NOPS                # dest one-hot
S0 = D0 + NR                  # src one-hot
BL = S0 + NR                  # 13 byte limbs
SL = BL + zkvm.NUM_BYTE_LIMBS  # 4 seven-bit limbs
MF = SL + zkvm.NUM_7BIT_LIMBS  # fetch multiplicity
MB = MF + 1; MS = MB + 1      # byte / 7bit multiplicities
MA = MS + 1                   # args-table multiplicity (how many times each (call,idx,val) row is loaded)
W_MAIN = MA + 1
HF = W_MAIN; GF = HF + 1; HIO = GF + 1; GIO = HIO + 1
HB = GIO + 1                  # 7 paired byte helpers
GB = HB + 7
HS = GB + 1                   # 2 paired 7bit helpers
GS = HS + 2
HA = GS + 1; GA = HA + 1      # args bus helpers (execution side / table side)
Z = GA + 1
W_TOTAL = Z + 1
NUM_AUX = W_TOTAL - W_MAIN

# OPTIONAL io-fingerprint column (bind_io=True) — an ordered RLC of the trace's io, APPENDED after Z so the
# default geometry is untouched. It lets a settlement bind the state transition to THIS epoch's exact io by
# matching one field element (the fingerprint) instead of re-checking the whole io log (doc/zk-recursion.md §5c,
# piece 2). FIO[0]=0; FIO[i+1]=FIO[i]+io_active(row_i)·combine([TAG_IO, ioc, kind, a, b], γ_fp) — the io tuple
# already carries IOC (the global order counter), so a plain sum is order-binding. FIO[T-1] is the fingerprint.
FIO = W_TOTAL                              # index when bind_io; effective width is then W_TOTAL+1, aux NUM_AUX+1

# ---- periodic (public) column layout ---------------------------------------------------------------
# The verifier rebuilds ALL of these from the public EPOCH statement (the ordered call list + each call's
# program) — nothing statement-shaped is read from the proof. An EPOCH is N calls concatenated into one
# trace so L1 verifies ONE proof for the whole batch (doc/zk-execution-proofs.md — aggregation). A single
# call is just N=1. Per-call CONTEXT (caller/value/cursor/time/prog) and the call ARGS are periodic columns
# constant within a call's row block; P_START/P_END mark the block boundaries where registers/pc/sponge reset.
PP_PROG, PP_PC, PP_OP, PP_D, PP_S, PP_IMM = range(6)     # fetch table row: (prog_id, local pc, op, d, s, imm)
PL_CTR, PL_KIND, PL_A, PL_B, PL_ACT = range(6, 11)       # io log table row (ctr pins global order)
PB, PS = 11, 12                                          # byte / 7-bit range tables
PC_CALLER, PC_VALUE, PC_CURSOR, PC_TIME, PC_PROG = range(13, 18)   # context of the call owning this row
P_START, P_END = 18, 19                                  # 1 on a call's first row / last-row-before-next-call
PA = 20                                                  # FIRST 8 args of the owning call: PA+0 .. PA+7
PC_CALL = PA + NR                                        # index of the call owning this row (tags the args bus
                                                         # per call — two calls sharing a program have distinct
                                                         # args, so the bus must bind (call, idx, val))
PT_CALL, PT_IDX, PT_VAL = PC_CALL + 1, PC_CALL + 2, PC_CALL + 3   # args table row: (call, index, value)
NUM_PERIODIC = PT_VAL + 1

# The epoch-DATA periodic columns — the ones whose SIZE scales with the epoch (fetch/io/args tables + per-row
# context/args). These are what make a public verify O(epoch): each is a dense length-T column the verifier
# poly_evals per query. COMMIT them (stark commit_periodic) so the verify opens them O(log N) instead, and bind
# their roots to the epoch's commitments (io_commitment / calls_commitment) — the O(1)-verify path. The range
# tables (PB, PS) and the sparse boundary selectors (P_START, P_END) stay public (fixed / structured, cheap).
COMMIT_PERIODIC = [i for i in range(NUM_PERIODIC) if i not in (PB, PS, P_START, P_END)]

TAG_FETCH = 1 << 32           # bus domain tags (outside every raw table's value range)
TAG_IO = 1 << 33
TAG_ARG = 1 << 34
MAX_DEGREE = 8                # sponge x^7 under a selector; register-update mux also lands at 8
MIN_T = 512                   # byte table (256 rows) + headroom must sit within rows 0..T-2
MAX_T = 131072                # the FULL stark.MAX_TRACE_ROWS (2^17) — zkvm.GAS_LIMIT = MAX_T - 2, so any call
                              # the VM can execute fits one proof. Small calls pad to next_pow2 of their
                              # ACTUAL length; this ceiling costs nothing until a contract uses it.

_O = zkvm.OP
_IO_OPS = ("SLOAD", "SSTORE", "PAY", "BHASH", "BEACON", "RET")
_IO_KIND = {"SLOAD": zkvm.IO_SLOAD, "SSTORE": zkvm.IO_SSTORE, "PAY": zkvm.IO_PAY,
            "BHASH": zkvm.IO_BHASH, "BEACON": zkvm.IO_BEACON, "RET": zkvm.IO_RET}
_WRITE_OPS = ("MOVI", "MOV", "ADD", "SUB", "MUL", "EQ", "NEZ", "NOTB", "LT", "DIVMOD", "DIVMODW", "LO32",
              "CTX", "HOUT")
_LOAD_OPS = ("SLOAD", "BHASH", "BEACON", "ARG")   # dest register is bus-supplied, not from the update mux
                                                  # (SLOAD/BHASH/BEACON via the io bus, ARG via the args bus)


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


# ---- row expression helpers (used identically by prover composition and verifier spot-checks) ----
def _rd_val(row):
    """Old value of the dest register: Σ d_i · R_i."""
    acc = 0
    for i in range(NR):
        acc = F.add(acc, F.mul(row[D0 + i], row[R0 + i]))
    return acc


def _rs_val(row):
    """Value of the src register: Σ s_i · R_i."""
    acc = 0
    for i in range(NR):
        acc = F.add(acc, F.mul(row[S0 + i], row[R0 + i]))
    return acc


def _idx(row, base):
    """One-hot group → its index as a field value (Σ i·bit_i)."""
    acc = 0
    for i in range(NR):
        acc = F.add(acc, F.mul(i, row[base + i]))
    return acc


def _op_id(row):
    acc = 0
    for k in range(NOPS):
        acc = F.add(acc, F.mul(k, row[F0 + k]))
    return acc


def _recomp(row, spec):
    """Recompose limbs: spec = [(col, weight), ...]."""
    acc = 0
    for col, w in spec:
        acc = F.add(acc, F.mul(row[col], w))
    return acc


_SPEC63 = [(BL + k, 1 << (8 * k)) for k in range(7)] + [(SL + 0, 1 << 56)]
# DIVMOD (widened): q is 48-bit (6 byte limbs); b-1 / rem / b-rem-1 are 15-bit (byte + 7-bit) so a small
# divisor keeps q·b < 2^63 < P — field division cannot wrap. LO32 keeps its own independent lo/hi window.
_SPEC_Q = [(BL + k, 1 << (8 * k)) for k in range(6)]
_SPEC_BM1 = [(BL + 6, 1), (SL + 1, 1 << 8)]
_SPEC_REM = [(BL + 7, 1), (SL + 2, 1 << 8)]
_SPEC_BR1 = [(BL + 8, 1), (SL + 3, 1 << 8)]
# DIVMODW — the same q·b < 2^63 soundness budget cut for DATA-sized divisors: q is 32-bit (4 byte limbs),
# b-1 / rem / b-rem-1 are 31-bit (3 bytes + 7-bit each). Uses exactly the 13 byte + 4 seven-bit limbs.
_SPEC_QW = [(BL + k, 1 << (8 * k)) for k in range(4)]
_SPEC_BM1W = [(BL + 4, 1), (BL + 5, 1 << 8), (BL + 6, 1 << 16), (SL + 1, 1 << 24)]
_SPEC_REMW = [(BL + 7, 1), (BL + 8, 1 << 8), (BL + 9, 1 << 16), (SL + 2, 1 << 24)]
_SPEC_BR1W = [(BL + 10, 1), (BL + 11, 1 << 8), (BL + 12, 1 << 16), (SL + 3, 1 << 24)]
_SPEC_LO = [(BL + k, 1 << (8 * k)) for k in range(4)]
_SPEC_HI = [(BL + 4 + k, 1 << (8 * k)) for k in range(4)]
_BYTE_PAIRS = [(BL + 2 * k, BL + 2 * k + 1) for k in range(6)] + [(BL + 12, None)]   # None = literal 0
_7BIT_PAIRS = [(SL + 0, SL + 1), (SL + 2, SL + 3)]


def _sponge_round(row, r):
    """(r0, r1) of alghash round r from the committed sponge state — the constants are baked in."""
    t0 = F.pw(F.add(row[H0], alghash.RC[r][0]), alghash.ALPHA)
    t1 = F.pw(F.add(row[H1], alghash.RC[r][1]), alghash.ALPHA)
    return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))


_LAG_INV = [F.inv(d % F.P) for d in (-6, 2, -2, 6)]          # Π_{j≠k}(k-j) for k = 0..3

def _lagrange4(imm, vals):
    """Σ vals[k] · L_k(imm) over interpolation points {0,1,2,3} — the CTX mux (degree 3). CTX imm is
    deploy-validated to 0..3 (zkvm.validate_code), so the mux is total on real programs."""
    acc = 0
    for k in range(4):
        num = 1
        for j in range(4):
            if j != k:
                num = F.mul(num, F.sub(imm, j))
        acc = F.add(acc, F.mul(vals[k], F.mul(num, _LAG_INV[k])))
    return acc


def _io_kind_expr(row):
    acc = 0
    for name in _IO_OPS:
        acc = F.add(acc, F.mul(_IO_KIND[name], row[F0 + _O[name]]))
    return acc


def _io_a_expr(row):
    """First I/O tuple payload per op: slot / slot / to / height / epoch / retval."""
    rdv, rsv = _rd_val(row), _rs_val(row)
    acc = F.mul(row[F0 + _O["SLOAD"]], rsv)
    acc = F.add(acc, F.mul(row[F0 + _O["SSTORE"]], rdv))
    acc = F.add(acc, F.mul(row[F0 + _O["PAY"]], rdv))
    for name in ("BHASH", "BEACON", "RET"):
        acc = F.add(acc, F.mul(row[F0 + _O[name]], rsv))
    return acc


def _io_b_expr(row, nxt):
    """Second payload: the LOADED value is the dest register on the NEXT row (that is how a proven load
    gets its value: the bus forces it to equal the log's)."""
    nxt_rd = 0
    for i in range(NR):
        nxt_rd = F.add(nxt_rd, F.mul(row[D0 + i], nxt[R0 + i]))
    loads = F.add(row[F0 + _O["SLOAD"]], F.add(row[F0 + _O["BHASH"]], row[F0 + _O["BEACON"]]))
    acc = F.mul(loads, nxt_rd)
    acc = F.add(acc, F.mul(row[F0 + _O["SSTORE"]], _rs_val(row)))
    acc = F.add(acc, F.mul(row[F0 + _O["PAY"]], _rs_val(row)))
    return acc                                              # RET: b = 0


def _io_active(row):
    acc = 0
    for name in _IO_OPS:
        acc = F.add(acc, row[F0 + _O[name]])
    return acc


def _io_leaf_expr(cur, nxt, gamma_fp):
    """The fingerprint leaf for one row = the io bus tuple (TAG_IO, ioc, kind, a, b) under the fingerprint
    challenge γ_fp. Same (kind, a, b) the io bus reads, so the fingerprint covers the SAME io the exec proves."""
    return logup.combine([TAG_IO, cur[IOC], _io_kind_expr(cur), _io_a_expr(cur), _io_b_expr(cur, nxt)], gamma_fp)


def _io_fingerprint(trace, gamma_fp):
    """Native ordered RLC fingerprint of a trace's io — the value FIO[T-1] the aux column accumulates to.
    Σ over rows 0..T-2 of io_active(row)·_io_leaf_expr(row). Deterministic given γ_fp (public)."""
    Fv, T = 0, len(trace)
    for i in range(T - 1):
        cur, nxt = trace[i], trace[i + 1]
        if _io_active(cur):                                  # io_active is 0/1 on a well-formed trace
            Fv = F.add(Fv, _io_leaf_expr(cur, nxt, gamma_fp))
    return Fv


def _fetch_tuple(row, per, gamma):
    """The instruction fetched at this row, tagged by which PROGRAM the owning call runs (per[PC_PROG]) so a
    multi-contract epoch's fetch bus can't confuse two programs' instructions."""
    return logup.combine([TAG_FETCH, per[PC_PROG], row[PC], _op_id(row), _idx(row, D0), _idx(row, S0),
                          row[IMM]], gamma)


def _arg_tuple(row, nxt, per, gamma):
    """The (call, index, value) an ARG row loads: index = the source register, value = the dest register ON
    THE NEXT ROW (bus-supplied load, same trick as _io_b_expr). Tagged by the OWNING CALL (per[PC_CALL]) so an
    epoch's args bus can't confuse two calls' argument vectors. The tuple must exist in the public args table
    or the bus can't balance — that is the whole soundness argument for indexed args."""
    nxt_rd = 0
    for i in range(NR):
        nxt_rd = F.add(nxt_rd, F.mul(row[D0 + i], nxt[R0 + i]))
    return logup.combine([TAG_ARG, per[PC_CALL], _rs_val(row), nxt_rd], gamma)


def _io_tuple(row, nxt, gamma):
    return logup.combine([TAG_IO, row[IOC], _io_kind_expr(row), _io_a_expr(row), _io_b_expr(row, nxt)], gamma)


def _res_expr(row, per):
    """Σ f_op · (result value) over the register-writing ops (loads excluded — bus-supplied). CTX reads the
    owning call's context from the PERIODIC columns (per-call, so an epoch of calls with different
    callers/values all verify under one proof)."""
    rdv, rsv = _rd_val(row), _rs_val(row)
    diff = F.sub(rdv, rsv)
    terms = {
        "MOVI": row[IMM],
        "MOV": rsv,
        "ADD": F.add(rdv, rsv),
        "SUB": F.sub(rdv, rsv),
        "MUL": F.mul(rdv, rsv),
        "EQ": F.sub(1, F.mul(diff, row[WI])),
        "NEZ": F.mul(rdv, row[WI]),
        "NOTB": F.sub(1, rdv),
        "LT": row[WI],
        "DIVMOD": _recomp(row, _SPEC_Q),
        "DIVMODW": _recomp(row, _SPEC_QW),
        "LO32": _recomp(row, _SPEC_LO),
        "CTX": _lagrange4(row[IMM], [per[PC_CALLER], per[PC_VALUE], per[PC_CURSOR], per[PC_TIME]]),
        "HOUT": row[H0],
    }
    acc = 0
    for name, val in terms.items():
        acc = F.add(acc, F.mul(row[F0 + _O[name]], val))
    return acc


def _wr_expr(row):
    acc = 0
    for name in _WRITE_OPS:
        acc = F.add(acc, row[F0 + _O[name]])
    return acc


# ---- the transition constraints -------------------------------------------------------------------
def transitions(bind_io=False, gamma_fp=0):
    """The full constraint list. All per-call context is PERIODIC (public), so ONE constraint set proves an
    EPOCH of N concatenated calls (aggregation) as well as a single call. Every constraint is
    c(cur, nxt, per, chal), chal = (β, γ). P_START(cur) pins a call's first row (registers←args, pc←0,
    sponge←0); P_END(cur) disables the held/step transitions on the last row of a call whose successor is a
    fresh call, so the reset is exactly at the boundary. The io counter is NEVER reset — it serializes the
    whole epoch's I/O in one global order.

    `bind_io=True` appends the FIO fingerprint accumulator constraint (γ_fp is the public fingerprint challenge)
    — an opt-in extra column, default OFF so the live proof is byte-identical."""
    cons = []

    # -- selector well-formedness: every one-hot group is bits summing to 1 --
    for k in range(NOPS):
        cons.append((lambda k: lambda c, n, p, ch: F.mul(c[F0 + k], F.sub(c[F0 + k], 1)))(k))
    for i in range(NR):
        cons.append((lambda i: lambda c, n, p, ch: F.mul(c[D0 + i], F.sub(c[D0 + i], 1)))(i))
        cons.append((lambda i: lambda c, n, p, ch: F.mul(c[S0 + i], F.sub(c[S0 + i], 1)))(i))
    def c_sums(c, n, p, ch):
        s = F.neg(3)
        for k in range(NOPS):
            s = F.add(s, c[F0 + k])
        for i in range(NR):
            s = F.add(s, F.add(c[D0 + i], c[S0 + i]))
        return s                                             # Σf + Σd + Σs = 3 (each group sums to 1; the
    cons.append(c_sums)                                      # bit constraints make a 2/0 split impossible
    def c_group_f(c, n, p, ch):                              # only if groups are individually pinned:)
        s = F.neg(1)
        for k in range(NOPS):
            s = F.add(s, c[F0 + k])
        return s
    cons.append(c_group_f)
    def c_group_d(c, n, p, ch):
        s = F.neg(1)
        for i in range(NR):
            s = F.add(s, c[D0 + i])
        return s
    cons.append(c_group_d)

    # -- NOP is absorbing (nothing executes after RET / a padding gap) — but NOT across a call boundary,
    #    where the next row is the successor call's (pinned) START row instead of a NOP --
    def c_absorb(c, n, p, ch):
        halt = F.add(c[F0 + _O["NOP"]], c[F0 + _O["RET"]])
        return F.mul(F.sub(1, p[P_END]), F.mul(halt, F.sub(n[F0 + _O["NOP"]], 1)))
    cons.append(c_absorb)

    # -- call-start pins: on the first row of each call, registers = the call's periodic args, pc = 0,
    #    sponge = (0, 0). This is what "resets" the machine per call so an epoch is a clean concatenation. --
    for i in range(NR):
        cons.append((lambda i: lambda c, n, p, ch: F.mul(p[P_START], F.sub(c[R0 + i], p[PA + i])))(i))
    cons.append(lambda c, n, p, ch: F.mul(p[P_START], c[PC]))
    cons.append(lambda c, n, p, ch: F.mul(p[P_START], c[H0]))
    cons.append(lambda c, n, p, ch: F.mul(p[P_START], c[H1]))

    # -- register file: held unless written by the mux; loads are bus-supplied. The step transition is
    #    disabled on a boundary row (P_END), where the successor's START pin sets the registers instead. --
    for i in range(NR):
        def c_reg(c, n, p, ch, i=i):
            load_i = F.mul(c[D0 + i], F.add(F.add(c[F0 + _O["SLOAD"]], c[F0 + _O["ARG"]]),
                                            F.add(c[F0 + _O["BHASH"]], c[F0 + _O["BEACON"]])))
            write = F.mul(c[D0 + i], F.sub(_res_expr(c, p), F.mul(_wr_expr(c), c[R0 + i])))
            # write = d_i·(Σf·res - wr·R_i) = d_i·Σf·(res - R_i)
            rem7 = 0
            if i == 7:                                       # DIVMOD/DIVMODW deposit the remainder in r7
                rem7 = F.add(F.mul(c[F0 + _O["DIVMOD"]], F.sub(_recomp(c, _SPEC_REM), c[R0 + 7])),
                             F.mul(c[F0 + _O["DIVMODW"]], F.sub(_recomp(c, _SPEC_REMW), c[R0 + 7])))
            delta = F.sub(F.sub(F.sub(n[R0 + i], c[R0 + i]), write), rem7)
            return F.mul(F.sub(1, p[P_END]), F.mul(F.sub(1, load_i), delta))
        cons.append(c_reg)

    # -- sponge lanes (step transition disabled on a boundary row; the START pin resets to (0,0)) --
    def c_h0(c, n, p, ch):
        d = F.sub(n[H0], c[H0])
        d = F.sub(d, F.mul(c[F0 + _O["HINIT"]], F.neg(c[H0])))
        d = F.sub(d, F.mul(c[F0 + _O["HABS"]], _rs_val(c)))
        for r in range(8):
            r0, _ = _sponge_round(c, r)
            d = F.sub(d, F.mul(c[F0 + _O[f"HR{r}"]], F.sub(r0, c[H0])))
        return F.mul(F.sub(1, p[P_END]), d)
    def c_h1(c, n, p, ch):
        d = F.sub(n[H1], c[H1])
        d = F.sub(d, F.mul(c[F0 + _O["HINIT"]], F.sub(alghash.IV, c[H1])))
        for r in range(8):
            _, r1 = _sponge_round(c, r)
            d = F.sub(d, F.mul(c[F0 + _O[f"HR{r}"]], F.sub(r1, c[H1])))
        return F.mul(F.sub(1, p[P_END]), d)
    cons.extend([c_h0, c_h1])

    # -- pc: +1, jumps, and hold on NOP/RET (step disabled on a boundary; START pins pc = 0) --
    def c_pc(c, n, p, ch):
        d = F.sub(F.sub(n[PC], c[PC]), 1)
        jump = F.sub(c[IMM], F.add(c[PC], 1))
        d = F.sub(d, F.mul(c[F0 + _O["JMP"]], jump))
        nz = F.mul(_rs_val(c), c[WI])
        d = F.sub(d, F.mul(c[F0 + _O["JNZ"]], F.mul(nz, jump)))
        d = F.sub(d, F.mul(F.add(c[F0 + _O["NOP"]], c[F0 + _O["RET"]]), F.neg(1)))
        return F.mul(F.sub(1, p[P_END]), d)
    cons.append(c_pc)

    # -- io counter --
    def c_ioc(c, n, p, ch):
        return F.sub(F.sub(n[IOC], c[IOC]), _io_active(c))
    cons.append(c_ioc)

    # -- inverse-witness soundness (EQ/NEZ/JNZ/REQUIRE) + bit ops --
    def c_eq(c, n, p, ch):
        diff = F.sub(_rd_val(c), _rs_val(c))
        return F.mul(c[F0 + _O["EQ"]], F.mul(diff, F.sub(1, F.mul(diff, c[WI]))))
    def c_nez(c, n, p, ch):
        v = _rd_val(c)
        return F.mul(c[F0 + _O["NEZ"]], F.mul(v, F.sub(1, F.mul(v, c[WI]))))
    def c_jnz(c, n, p, ch):
        v = _rs_val(c)
        return F.mul(c[F0 + _O["JNZ"]], F.mul(v, F.sub(1, F.mul(v, c[WI]))))
    def c_req(c, n, p, ch):
        return F.mul(c[F0 + _O["REQUIRE"]], F.sub(F.mul(_rs_val(c), c[WI]), 1))
    def c_ltbit(c, n, p, ch):
        return F.mul(c[F0 + _O["LT"]], F.mul(c[WI], F.sub(c[WI], 1)))
    def c_notb(c, n, p, ch):
        v = _rd_val(c)
        return F.mul(c[F0 + _O["NOTB"]], F.mul(v, F.sub(v, 1)))
    cons.extend([c_eq, c_nez, c_jnz, c_req, c_ltbit, c_notb])

    # -- limb ties: the semantic value each windowed op decomposed --
    def c_lt(c, n, p, ch):
        rdv, rsv, b = _rd_val(c), _rs_val(c), c[WI]
        D = F.add(F.mul(b, F.sub(F.sub(rsv, rdv), 1)), F.mul(F.sub(1, b), F.sub(rdv, rsv)))
        return F.mul(c[F0 + _O["LT"]], F.sub(D, _recomp(c, _SPEC63)))
    def c_range(c, n, p, ch):
        return F.mul(c[F0 + _O["RANGE"]], F.sub(_rd_val(c), _recomp(c, _SPEC63)))
    def c_dm_main(c, n, p, ch):
        q, b, rem = _recomp(c, _SPEC_Q), _rs_val(c), _recomp(c, _SPEC_REM)
        return F.mul(c[F0 + _O["DIVMOD"]], F.sub(F.add(F.mul(q, b), rem), _rd_val(c)))
    def c_dm_b(c, n, p, ch):
        return F.mul(c[F0 + _O["DIVMOD"]], F.sub(F.sub(_rs_val(c), 1), _recomp(c, _SPEC_BM1)))
    def c_dm_r(c, n, p, ch):
        return F.mul(c[F0 + _O["DIVMOD"]],
                     F.sub(F.sub(F.sub(_rs_val(c), _recomp(c, _SPEC_REM)), 1), _recomp(c, _SPEC_BR1)))
    def c_dmw_main(c, n, p, ch):
        q, b, rem = _recomp(c, _SPEC_QW), _rs_val(c), _recomp(c, _SPEC_REMW)
        return F.mul(c[F0 + _O["DIVMODW"]], F.sub(F.add(F.mul(q, b), rem), _rd_val(c)))
    def c_dmw_b(c, n, p, ch):
        return F.mul(c[F0 + _O["DIVMODW"]], F.sub(F.sub(_rs_val(c), 1), _recomp(c, _SPEC_BM1W)))
    def c_dmw_r(c, n, p, ch):
        return F.mul(c[F0 + _O["DIVMODW"]],
                     F.sub(F.sub(F.sub(_rs_val(c), _recomp(c, _SPEC_REMW)), 1), _recomp(c, _SPEC_BR1W)))
    def c_lo32(c, n, p, ch):
        v = F.add(F.mul(_recomp(c, _SPEC_HI), 1 << 32), _recomp(c, _SPEC_LO))
        return F.mul(c[F0 + _O["LO32"]], F.sub(_rd_val(c), v))
    def c_lo32_canon(c, n, p, ch):
        hi, lo = _recomp(c, _SPEC_HI), _recomp(c, _SPEC_LO)
        gate = F.sub(1, F.mul(F.sub(hi, (1 << 32) - 1), c[WJ]))
        return F.mul(c[F0 + _O["LO32"]], F.mul(lo, gate))
    cons.extend([c_lt, c_range, c_dm_main, c_dm_b, c_dm_r, c_dmw_main, c_dmw_b, c_dmw_r,
                 c_lo32, c_lo32_canon])

    # -- the four LogUp buses (one shared accumulator) --
    def c_hf(c, n, p, ch):
        active = F.sub(1, c[F0 + _O["NOP"]])
        return F.sub(F.mul(c[HF], F.add(ch[0], _fetch_tuple(c, p, ch[1]))), active)
    def c_gf(c, n, p, ch):
        t = logup.combine([TAG_FETCH, p[PP_PROG], p[PP_PC], p[PP_OP], p[PP_D], p[PP_S], p[PP_IMM]], ch[1])
        return F.sub(F.mul(c[GF], F.add(ch[0], t)), c[MF])
    def c_hio(c, n, p, ch):
        return F.sub(F.mul(c[HIO], F.add(ch[0], _io_tuple(c, n, ch[1]))), _io_active(c))
    def c_gio(c, n, p, ch):
        t = logup.combine([TAG_IO, p[PL_CTR], p[PL_KIND], p[PL_A], p[PL_B]], ch[1])
        return F.sub(F.mul(c[GIO], F.add(ch[0], t)), p[PL_ACT])
    def c_ha(c, n, p, ch):
        return F.sub(F.mul(c[HA], F.add(ch[0], _arg_tuple(c, n, p, ch[1]))), c[F0 + _O["ARG"]])
    def c_ga(c, n, p, ch):
        t = logup.combine([TAG_ARG, p[PT_CALL], p[PT_IDX], p[PT_VAL]], ch[1])
        return F.sub(F.mul(c[GA], F.add(ch[0], t)), c[MA])
    cons.extend([c_hf, c_gf, c_hio, c_gio, c_ha, c_ga])
    for j, (ca, cb) in enumerate(_BYTE_PAIRS):
        def c_hb(c, n, p, ch, j=j, ca=ca, cb=cb):
            la, lb = c[ca], (c[cb] if cb is not None else 0)
            lhs = F.mul(c[HB + j], F.mul(F.add(ch[0], la), F.add(ch[0], lb)))
            return F.sub(lhs, F.add(F.add(F.mul(2, ch[0]), la), lb))
        cons.append(c_hb)
    def c_gb(c, n, p, ch):
        return F.sub(F.mul(c[GB], F.add(ch[0], p[PB])), c[MB])
    cons.append(c_gb)
    for j, (ca, cb) in enumerate(_7BIT_PAIRS):
        def c_hs(c, n, p, ch, j=j, ca=ca, cb=cb):
            lhs = F.mul(c[HS + j], F.mul(F.add(ch[0], c[ca]), F.add(ch[0], c[cb])))
            return F.sub(lhs, F.add(F.add(F.mul(2, ch[0]), c[ca]), c[cb]))
        cons.append(c_hs)
    def c_gs(c, n, p, ch):
        return F.sub(F.mul(c[GS], F.add(ch[0], p[PS])), c[MS])
    cons.append(c_gs)
    def c_z(c, n, p, ch):
        term = F.sub(c[HF], c[GF])
        term = F.add(term, F.sub(c[HIO], c[GIO]))
        term = F.add(term, F.sub(c[HA], c[GA]))
        for j in range(7):
            term = F.add(term, c[HB + j])
        term = F.sub(term, c[GB])
        term = F.add(term, F.add(c[HS + 0], c[HS + 1]))
        term = F.sub(term, c[GS])
        return F.sub(n[Z], F.add(c[Z], term))
    cons.append(c_z)

    if bind_io:                                              # opt-in io fingerprint accumulator (piece 2)
        def c_fio(c, n, p, ch):
            return F.sub(n[FIO], F.add(c[FIO], F.mul(_io_active(c), _io_leaf_expr(c, n, gamma_fp))))
        cons.append(c_fio)
    return cons


# ---- an epoch = an ordered list of calls, concatenated into ONE trace --------------------------------
# Each call is a dict {code, method, caller, args, value, cursor, timestamp, beacons, block_hashes}. A single
# proven call is the N=1 epoch; settlement proves a whole batch as one proof (doc/zk-execution-proofs.md).

def _prog_key(prog):
    """A hashable identity for a method's bytecode — same bytecode ⇒ same prog_id in the fetch table."""
    return tuple(tuple(ins) for ins in prog)


def build_epoch_trace(calls):
    """Run every call and concatenate their witnesses into one trace. Returns
    (trace, T, blocks, progs, epoch_io, per_call) where `blocks` = [(start_row, n_rows, prog_id, call)] and
    `progs` = the distinct program list (prog_id = index). Raises ValueError if any call reverts (a reverted
    call is a no-op — nothing to prove) or the batch exceeds one trace."""
    prog_ids = {}
    progs = []
    blocks = []
    rows = []
    epoch_io = []
    per_call = []
    ioc = 0
    arg_base = []                                         # args-table row offset of each call (concatenated)
    args_total = 0
    arg_uses = []                                         # (call_index, arg_index) per executed ARG
    for call in calls:
        code, method = call["code"], call["method"]
        zkvm.validate_code(code)
        cf, fargs = call["caller_f"], call["args_f"]
        r = zkvm.run(code, method, cf, list(fargs), call["slots"], value=call.get("value", 0),
                     cursor=call.get("cursor", 0), timestamp=call.get("timestamp", 0),
                     beacons=call.get("beacons"), block_hashes=call.get("block_hashes"), witness=True)
        ok, ret, new_slots, io, steps = r
        if not ok:
            raise ValueError("a call reverted — nothing to prove")
        prog = code[method]
        key = _prog_key(prog)
        if key not in prog_ids:
            prog_ids[key] = len(progs); progs.append(prog)
        pid = prog_ids[key]
        ci = len(blocks)                                  # this call's index (tags its args-table rows)
        arg_base.append(args_total)
        args_total += len(fargs)
        args8 = [(fargs[i] if i < len(fargs) else 0) % F.P for i in range(NR)]
        start = len(rows)
        regs, h0, h1 = args8, 0, 0
        base = ioc                                        # GLOBAL io offset: the witness ioc restarts at 0
        lioc = 0                                          # per call, so add `base` to keep IOC monotone epoch-wide
        for st in steps:                                  # row carries the PRE-state + this instruction
            row = [0] * W_MAIN
            row[R0:R0 + NR] = regs
            row[PC], row[IOC], row[IMM] = st["pc"], base + lioc, st["imm"] % F.P
            row[H0], row[H1] = h0, h1
            row[WI], row[WJ] = st["wi"], st["wj"]
            row[F0 + st["op"]] = 1
            row[D0 + st["d"]] = 1
            row[S0 + st["s"]] = 1
            for k, v in enumerate(st["bl"]):
                row[BL + k] = v
            for k, v in enumerate(st["sl"]):
                row[SL + k] = v
            if st["op"] == _O["ARG"]:                     # index = the source register's PRE-state value
                arg_uses.append((ci, regs[st["s"]]))
            rows.append(row)
            regs, h0, h1, lioc = st["regs"], st["h0"], st["h1"], st["ioc_after"]
        ioc = base + lioc                                 # advance the global counter by this call's io count
        for e in io:
            epoch_io.append((e[0], e[1] % F.P, e[2] % F.P))
        blocks.append((start, len(rows) - start, pid, call))
        per_call.append({"io": io, "ret": ret, "new_slots": new_slots})

    n = len(rows)
    total_prog = sum(len(p) for p in progs)
    T = max(MIN_T, _next_pow2(max(n, total_prog, len(epoch_io), args_total, 256) + 2))
    if T > MAX_T:
        raise ValueError("epoch too long for one trace")

    ret_pc = rows[-1][PC] if rows else 0
    last_regs = [rows[-1][R0 + i] for i in range(NR)] if rows else [0] * NR
    lh0, lh1 = (rows[-1][H0], rows[-1][H1]) if rows else (0, 0)
    while len(rows) < T:                                  # NOP padding after the last call
        row = [0] * W_MAIN
        row[R0:R0 + NR] = last_regs
        row[PC], row[IOC] = ret_pc, ioc
        row[H0], row[H1] = lh0, lh1
        row[F0 + _O["NOP"]] = 1
        row[D0] = 1
        row[S0] = 1
        rows.append(row)

    # lookup multiplicities (mass over rows 0..T-2 only). Fetch multiplicity is per FETCH-TABLE row j, which
    # holds instruction (prog offset + local pc); count executed rows by their (prog_id, pc) via the layout.
    prog_base = {}
    off = 0
    for pid, p in enumerate(progs):
        prog_base[pid] = off; off += len(p)
    mf = [0] * T
    for (start, nrows, pid, _call) in blocks:
        for i in range(start, start + nrows):
            mf[prog_base[pid] + rows[i][PC]] += 1
    mb = [0] * T
    ms = [0] * T
    for i in range(T - 1):
        r = rows[i]
        for k in range(zkvm.NUM_BYTE_LIMBS):
            mb[r[BL + k]] += 1
        mb[0] += 1                                        # the (BL12, literal-0) pair partner, every row
        for k in range(zkvm.NUM_7BIT_LIMBS):
            ms[r[SL + k]] += 1
    ma = [0] * T                                          # args-table multiplicities (per ARG execution)
    for ci, idx in arg_uses:
        ma[arg_base[ci] + idx] += 1
    for i in range(T):
        rows[i][MF], rows[i][MB], rows[i][MS], rows[i][MA] = mf[i], mb[i], ms[i], ma[i]
    return rows, T, blocks, progs, epoch_io, per_call


def build_periodic(blocks, progs, epoch_io, T):
    """The public periodic columns for an epoch. The VERIFIER rebuilds every one of these from the public
    statement (the call list + programs) — none come from the proof. Fetch table = the distinct programs
    concatenated (each row tagged with its prog_id + local pc); io table = the whole epoch's log in one global
    order; context/args/start-end columns describe which call owns each execution row."""
    cols = [[0] * T for _ in range(NUM_PERIODIC)]
    # fetch table: prog_id, local pc, op, d, s, imm  (progs concatenated)
    j = 0
    for pid, prog in enumerate(progs):
        for pc, ins in enumerate(prog):
            if j >= T:
                raise ValueError("programs do not fit the trace")
            cols[PP_PROG][j] = pid; cols[PP_PC][j] = pc; cols[PP_OP][j] = _O[ins[0]]
            cols[PP_D][j] = ins[1]; cols[PP_S][j] = ins[2]; cols[PP_IMM][j] = ins[3] % F.P
            j += 1
    # io log table: global order
    for i, e in enumerate(epoch_io):
        if i >= T:
            raise ValueError("io log does not fit the trace")
        cols[PL_CTR][i] = i; cols[PL_KIND][i] = e[0]; cols[PL_A][i] = e[1] % F.P; cols[PL_B][i] = e[2] % F.P
        cols[PL_ACT][i] = 1
    # args table: every call's FULL argument vector, concatenated in call order (call, index, value). This is
    # what the ARG opcode's bus looks values up in — rebuilt from the public statement, never from the proof.
    j = 0
    for bi, (_start, _nrows, _pid, call) in enumerate(blocks):
        for k, v in enumerate(call["args_f"]):
            if j >= T:
                raise ValueError("args do not fit the trace")
            cols[PT_CALL][j] = bi; cols[PT_IDX][j] = k; cols[PT_VAL][j] = v % F.P
            j += 1
    # per-execution-row context + args (dense, epoch-sized — these live in COMMIT_PERIODIC)
    starts, ends = [], []
    for bi, (start, nrows, pid, call) in enumerate(blocks):
        args8 = [(call["args_f"][k] if k < len(call["args_f"]) else 0) % F.P for k in range(NR)]
        ctx = (call["caller_f"] % F.P, call.get("value", 0) % F.P,
               call.get("cursor", 0) % F.P, call.get("timestamp", 0) % F.P)
        for i in range(start, start + nrows):
            cols[PC_CALLER][i], cols[PC_VALUE][i], cols[PC_CURSOR][i], cols[PC_TIME][i] = ctx
            cols[PC_PROG][i] = pid
            cols[PC_CALL][i] = bi
            for k in range(NR):
                cols[PA + k][i] = args8[k]
        starts.append((start, 1))
        # END on this call's last row iff a NEXT call follows (its start row is the reset target)
        if bi + 1 < len(blocks):
            ends.append((start + nrows - 1, 1))
    # The FIXED range tables and the SPARSE boundary selectors go out in structured {period,base,sparse} form,
    # not dense length-T lists: stark._per_expand rebuilds them to the SAME dense column (proofs byte-identical,
    # test_periodic_structured_identity), but the verifier evaluates them in O(256)/O(#calls) per query instead
    # of an O(T) interpolation — so nothing the settlement verifier rebuilds here is O(T).
    cols[PB] = {"period": 1, "base": [0], "sparse": [(i, i) for i in range(256)]}
    cols[PS] = {"period": 1, "base": [0], "sparse": [(i, i) for i in range(128)]}
    cols[P_START] = {"period": 1, "base": [0], "sparse": starts}
    cols[P_END] = {"period": 1, "base": [0], "sparse": ends}
    return cols


def make_aux_builder(periodic, bind_io=False, gamma_fp=0):
    """The prover's phase-2 witness: the 18 challenge-dependent helper/accumulator columns, built against the
    already-computed public periodic columns. With `bind_io`, ALSO fills the appended FIO fingerprint column."""
    def build(trace, chal):
        beta, gamma = chal
        T = len(trace)
        # dense-expand every periodic column (structured {period,base,sparse} range/selector columns → their
        # length-T form) so the row reader below can index per_cols[c][i] uniformly.
        per_cols = [stark._per_expand(pc, T) for pc in periodic]
        cols = [[0] * T for _ in range(NUM_AUX + (1 if bind_io else 0))]
        def put(idx, row, val):
            cols[idx - W_MAIN][row] = val
        def perrow(i):
            return [per_cols[c][i] for c in range(NUM_PERIODIC)]
        for i in range(T):
            cur = trace[i]
            nxt = trace[i + 1] if i + 1 < T else trace[i]
            p = perrow(i)
            hf = F.mul(F.sub(1, cur[F0 + _O["NOP"]]), F.inv(F.add(beta, _fetch_tuple(cur, p, gamma))))
            gf_t = logup.combine([TAG_FETCH, p[PP_PROG], p[PP_PC], p[PP_OP], p[PP_D], p[PP_S], p[PP_IMM]], gamma)
            gf = F.mul(cur[MF], F.inv(F.add(beta, gf_t)))
            hio = F.mul(_io_active(cur), F.inv(F.add(beta, _io_tuple(cur, nxt, gamma))))
            gio_t = logup.combine([TAG_IO, p[PL_CTR], p[PL_KIND], p[PL_A], p[PL_B]], gamma)
            gio = F.mul(p[PL_ACT], F.inv(F.add(beta, gio_t)))
            ha = F.mul(cur[F0 + _O["ARG"]], F.inv(F.add(beta, _arg_tuple(cur, nxt, p, gamma))))
            ga_t = logup.combine([TAG_ARG, p[PT_CALL], p[PT_IDX], p[PT_VAL]], gamma)
            ga = F.mul(cur[MA], F.inv(F.add(beta, ga_t)))
            put(HF, i, hf); put(GF, i, gf); put(HIO, i, hio); put(GIO, i, gio)
            put(HA, i, ha); put(GA, i, ga)
            for jx, (ca, cb) in enumerate(_BYTE_PAIRS):
                la, lb = cur[ca], (cur[cb] if cb is not None else 0)
                put(HB + jx, i, F.add(F.inv(F.add(beta, la)), F.inv(F.add(beta, lb))))
            put(GB, i, F.mul(cur[MB], F.inv(F.add(beta, p[PB]))))
            for jx, (ca, cb) in enumerate(_7BIT_PAIRS):
                put(HS + jx, i, F.add(F.inv(F.add(beta, cur[ca])), F.inv(F.add(beta, cur[cb]))))
            put(GS, i, F.mul(cur[MS], F.inv(F.add(beta, p[PS]))))
        z = 0
        for i in range(T):
            put(Z, i, z)
            term = F.sub(cols[HF - W_MAIN][i], cols[GF - W_MAIN][i])
            term = F.add(term, F.sub(cols[HIO - W_MAIN][i], cols[GIO - W_MAIN][i]))
            term = F.add(term, F.sub(cols[HA - W_MAIN][i], cols[GA - W_MAIN][i]))
            for jx in range(7):
                term = F.add(term, cols[HB - W_MAIN + jx][i])
            term = F.sub(term, cols[GB - W_MAIN][i])
            term = F.add(term, F.add(cols[HS - W_MAIN][i], cols[HS - W_MAIN + 1][i]))
            term = F.sub(term, cols[GS - W_MAIN][i])
            z = F.add(z, term)
        if bind_io:                                          # FIO[0]=0; FIO[i+1]=FIO[i]+active·leaf
            Fv = 0
            for i in range(T):
                cols[FIO - W_MAIN][i] = Fv
                cur = trace[i]; nxt = trace[i + 1] if i + 1 < T else trace[i]
                if _io_active(cur):
                    Fv = F.add(Fv, _io_leaf_expr(cur, nxt, gamma_fp))
        return cols
    return build


def _boundaries(T, bind_io=False, fp_exec=0):
    """Only the GLOBAL boundaries — per-call resets are enforced by the P_START pins inside the constraints.
    Row 0 is the first call's start (pc/ioc/sponge zero); Z telescopes to 0 at both ends (the LogUp buses
    balance over the whole epoch). With `bind_io`, pin FIO[0]=0 and FIO[T-1]=fp_exec (the io fingerprint,
    the O(1) public output that a settlement matches against the replay's fingerprint)."""
    bnds = [(0, PC, 0), (0, IOC, 0), (0, H0, 0), (0, H1, 0), (0, Z, 0), (T - 1, Z, 0)]
    if bind_io:
        bnds += [(0, FIO, 0), (T - 1, FIO, int(fp_exec) % F.P)]
    return bnds


def _aux_spec(periodic, bind_io=False, gamma_fp=0):
    return {"num_challenges": 2, "num_aux": NUM_AUX + (1 if bind_io else 0),
            "build": make_aux_builder(periodic, bind_io, gamma_fp)}


def _norm_call(call):
    """Fill in the field-form caller/args a call needs (idempotent). `caller`/`args` may be raw (int/str);
    `caller_f`/`args_f` are the digested field forms the trace uses."""
    from execnode import runtimes
    c = dict(call)
    if "caller_f" not in c or "args_f" not in c:
        cf, fargs = runtimes.zkvm_statement(c.get("caller", "epoch"), c.get("args", []), {})
        c["caller_f"], c["args_f"] = cf, fargs
    c.setdefault("slots", {})
    return c


def prove_epoch_calls(calls, num_queries=stark.NUM_QUERIES, backend=None, row_commit=False,
                      commit_periodic=None, bind_io=False, gamma_fp=0):
    """Prove an ORDERED batch of zkVM calls as ONE proof (aggregation). Each call is
    {code, method, caller, args, value?, cursor?, timestamp?, beacons?, block_hashes?, slots?}; `slots` is
    that call's PRE-storage (the caller chains them). Returns (proof, epoch_io, per_call). L1 verifies this
    single proof for the whole epoch instead of N proofs.

    `backend` selects the proof's hash (doc/zk-recursion.md): None/blake2b (default, the fast native-hash
    proof L1 + browsers verify directly) or the alghash2 wide sponge, which makes THIS proof's verification
    field-native — i.e. RECURSION-READY, so a fold circuit can verify it inside another proof. The hybrid
    wrap: prove segment/inner proofs with alghash2, fold them, and let the OUTERMOST proof stay blake2b.

    `bind_io=True` also proves the io FINGERPRINT (an ordered RLC of the epoch's io under the public challenge
    `gamma_fp`) as an appended column pinned to a boundary — `proof["io_fingerprint"]` is that O(1) value a
    settlement matches against the state replay's fingerprint (piece 2). Default OFF ⇒ byte-identical proof."""
    calls = [_norm_call(c) for c in calls]
    trace, T, blocks, progs, epoch_io, per_call = build_epoch_trace(calls)
    periodic = build_periodic(blocks, progs, epoch_io, T)
    fp_exec = _io_fingerprint(trace, gamma_fp) if bind_io else 0
    proof = stark.prove(trace, transitions(bind_io, gamma_fp), _boundaries(T, bind_io, fp_exec),
                        periodic=periodic, max_degree=MAX_DEGREE, num_queries=num_queries,
                        aux_spec=_aux_spec(periodic, bind_io, gamma_fp), backend=backend,
                        row_commit=row_commit, commit_periodic=commit_periodic)
    proof["progs"] = [[list(ins) for ins in p] for p in progs]
    proof["blocks"] = [{"start": s, "n": n, "pid": pid} for (s, n, pid, _c) in blocks]
    if bind_io:
        proof["io_fingerprint"] = fp_exec
    if backend is not None:
        proof["backend"] = getattr(backend, "name", str(backend))
    return proof, epoch_io, per_call


def epoch_statement(proof, calls, epoch_io, bind_io=False):
    """Rebuild the epoch AIR's PUBLIC statement — the periodic tables + boundaries — from the public calls +
    io log + the proof's DECLARED block lengths (cross-checked for contiguity/fit; nothing else is trusted).
    Everything verify_epoch_calls checks before the STARK itself, factored out so the RECURSIVE verifier
    (recursive_verify over row-committed segments) can build the same statement without running stark.verify.
    Returns (ok, reason, periodic, boundaries). `bind_io` widens the expected trace by the FIO column."""
    T, W = proof["T"], proof["W"]
    if not isinstance(T, int) or not (MIN_T <= T <= MAX_T) or W != W_TOTAL + (1 if bind_io else 0):
        return False, "bad trace geometry", None, None
    calls = [_norm_call(c) for c in calls]
    for c in calls:
        zkvm.validate_code(c["code"])
        if c["method"] not in c["code"]:
            return False, "unknown method", None, None
        if len(c["args_f"]) > zkvm.MAX_ARGS:          # provable == executable: the VM would refuse it
            return False, "too many args", None, None
    # rebuild the (blocks, progs) schedule from the public calls + the proof's declared block lengths,
    # then re-derive every periodic column and check the declared lengths against the claimed io log.
    decl = proof.get("blocks")
    if not isinstance(decl, list) or len(decl) != len(calls):
        return False, "block schedule missing/mismatched", None, None
    prog_ids, progs, blocks = {}, [], []
    for c, b in zip(calls, decl):
        prog = c["code"][c["method"]]
        key = _prog_key(prog)
        if key not in prog_ids:
            prog_ids[key] = len(progs); progs.append(prog)
        if not (isinstance(b.get("start"), int) and isinstance(b.get("n"), int) and b["n"] >= 1):
            return False, "bad block", None, None
        blocks.append((b["start"], b["n"], prog_ids[key], c))
    # blocks must tile [0, total) contiguously in order (no gaps/overlaps — that is what makes the
    # concatenation a faithful sequential execution)
    pos = 0
    for (s, n, _pid, _c) in blocks:
        if s != pos:
            return False, "non-contiguous block schedule", None, None
        pos += n
    if pos > T - 2:
        return False, "epoch does not fit the trace", None, None
    for e in epoch_io:
        if not (isinstance(e, (list, tuple)) and len(e) == 3
                and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < F.P for x in e)):
            return False, "malformed io log entry", None, None
    if len(epoch_io) > T - 2:
        return False, "io log does not fit the trace", None, None
    norm_io = [(e[0], e[1] % F.P, e[2] % F.P) for e in epoch_io]
    periodic = build_periodic(blocks, progs, norm_io, T)
    return True, "ok", periodic, _boundaries(T)


def verify_epoch_calls(proof, calls, epoch_io, num_queries=stark.NUM_QUERIES, backend=None, row_commit=False,
                       commit_periodic=None, periodic_roots=None, bind_io=False, gamma_fp=0):
    """Verify a proven epoch WITHOUT executing any call. `calls` is the public statement (code/method/caller/
    args/context per call, in order); `epoch_io` the claimed global I/O log. Returns (ok, reason). The
    periodic tables (programs, log order, per-call context) are rebuilt locally — nothing is trusted from the
    proof except commitments/openings. On ok, apply the epoch by replaying epoch_io per call.

    `bind_io=True` also enforces the io-fingerprint column: the boundary pins FIO[T-1] to the proof's claimed
    `io_fingerprint` (and c_fio + FIO[0]=0 force that to be the real ordered RLC under `gamma_fp`), so the
    fingerprint the settlement matches against is itself proven."""
    try:
        ok, why, periodic, bnds = epoch_statement(proof, calls, epoch_io, bind_io=bind_io)
        if not ok:
            return False, why
        if bind_io:                                       # rebuild the boundaries with the proven fingerprint
            fp = int(proof.get("io_fingerprint", 0)) % F.P
            bnds = _boundaries(proof["T"], bind_io=True, fp_exec=fp)
        if backend is None and proof.get("backend"):     # honour the hash the proof was produced with
            from execnode.stark import backend as _bk
            backend = _bk.get(proof["backend"])
        return stark.verify(proof, transitions(bind_io, gamma_fp), bnds, periodic=periodic, max_degree=MAX_DEGREE,
                            num_queries=num_queries, aux_spec=_aux_spec(periodic, bind_io, gamma_fp),
                            backend=backend, row_commit=row_commit, commit_periodic=commit_periodic,
                            periodic_roots=periodic_roots)
    except Exception as e:
        return False, f"malformed statement/proof: {e}"


def _o1_periodic(blocks_decl, T):
    """The verifier-cheap periodic columns for the O(1) path: ONLY the fixed range tables + the sparse block
    selectors, in structured (T-independent) form. The epoch-DATA columns (COMMIT_PERIODIC) are committed — their
    values come from the proof's openings, so they are placeholders here (stark.verify ignores committed slots).
    `blocks_decl` = proof["blocks"] (the declared call schedule). Cost is O(#calls), never O(#io)/O(#program)."""
    per = [0] * NUM_PERIODIC
    per[PB] = {"period": 1, "base": [0], "sparse": [(i, i) for i in range(256)]}
    per[PS] = {"period": 1, "base": [0], "sparse": [(i, i) for i in range(128)]}
    starts = [(int(b["start"]), 1) for b in blocks_decl]
    ends = [(int(b["start"]) + int(b["n"]) - 1, 1)
            for i, b in enumerate(blocks_decl) if i + 1 < len(blocks_decl)]
    per[P_START] = {"period": 1, "base": [0], "sparse": starts}
    per[P_END] = {"period": 1, "base": [0], "sparse": ends}
    return per


def verify_epoch_o1(proof, per_roots, num_queries=stark.NUM_QUERIES, backend=None):
    """O(1)-SHAPED exec verify: the epoch-data periodic tables (program/io/args/context) are COMMITTED and their
    roots are taken from `per_roots` (the on-chain statement) — the verifier NEVER rebuilds them, so it does no
    O(#io)/O(#program) work. It builds only the fixed range tables + the sparse block selectors (from the proof's
    declared schedule, O(#calls)) and checks the STARK, opening the committed columns O(log N) per query.

    SOUNDNESS: this trusts `per_roots`. The caller MUST bind them to the epoch's commitments (io_commitment /
    calls_commitment / program root) via a folded chain proof — WITHOUT that binding a prover could commit
    arbitrary tables. (Unlike verify_epoch_calls, which rebuilds every table from the public calls + io log and
    is self-contained but O(epoch).) Returns (ok, reason)."""
    try:
        T, W = proof["T"], proof["W"]
        if not isinstance(T, int) or not (MIN_T <= T <= MAX_T) or W != W_TOTAL:
            return False, "bad trace geometry"
        if len(per_roots) != len(COMMIT_PERIODIC):
            return False, "wrong committed-root count"
        decl = proof.get("blocks")
        if not isinstance(decl, list) or not decl:
            return False, "block schedule missing"
        pos = 0                                          # the schedule must tile [0,total) contiguously (as in
        for b in decl:                                   # epoch_statement) — a faithful sequential concatenation
            if not (isinstance(b.get("start"), int) and isinstance(b.get("n"), int) and b["n"] >= 1):
                return False, "bad block"
            if b["start"] != pos:
                return False, "non-contiguous block schedule"
            pos += b["n"]
        if pos > T - 2:
            return False, "epoch does not fit the trace"
        periodic = _o1_periodic(decl, T)
        if backend is None and proof.get("backend"):
            from execnode.stark import backend as _bk
            backend = _bk.get(proof["backend"])
        return stark.verify(proof, transitions(), _boundaries(T), periodic=periodic, max_degree=MAX_DEGREE,
                            num_queries=num_queries, aux_spec=_aux_spec(periodic), backend=backend,
                            commit_periodic=COMMIT_PERIODIC, periodic_roots=list(per_roots))
    except Exception as e:
        return False, f"malformed statement/proof: {e}"


# ---- single-call convenience (the N=1 epoch) — the endpoints' interface ------------------------------
def prove_call(code, method, caller, args, storage, value=0, cursor=0, timestamp=0, beacons=None,
               block_hashes=None, num_queries=stark.NUM_QUERIES, backend=None):
    """Execute + prove ONE zkVM call (the N=1 epoch). Returns (proof, io_log, ret, new_storage). `caller`/
    `args` are already field-form (the runtime digests them at the boundary). `backend` as in
    prove_epoch_calls (alghash2 ⇒ a recursion-ready, field-verifiable proof)."""
    call = {"code": code, "method": method, "caller_f": caller % F.P,
            "args_f": [a % F.P for a in args], "caller": caller, "args": list(args),
            "value": value, "cursor": cursor, "timestamp": timestamp, "beacons": beacons,
            "block_hashes": block_hashes, "slots": storage}
    proof, epoch_io, per_call = prove_epoch_calls([call], num_queries=num_queries, backend=backend)
    pc0 = per_call[0]
    return proof, pc0["io"], pc0["ret"], pc0["new_slots"]


def verify_call(proof, code, method, caller, args, io_log, value=0, cursor=0, timestamp=0,
                num_queries=stark.NUM_QUERIES):
    """Verify one proven call (N=1 epoch) WITHOUT executing it. Returns (ok, reason)."""
    if sum(1 for e in io_log if e[0] == zkvm.IO_RET) != 1 or not io_log or io_log[-1][0] != zkvm.IO_RET:
        return False, "io log must end with exactly one RET"
    call = {"code": code, "method": method, "caller_f": caller % F.P,
            "args_f": [a % F.P for a in args], "caller": caller, "args": list(args),
            "value": value, "cursor": cursor, "timestamp": timestamp}
    return verify_epoch_calls(proof, [call], io_log, num_queries=num_queries)
