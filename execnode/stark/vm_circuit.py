"""
zkVM execution AIR (doc/zk-execution-proofs.md) — prove "running PUBLIC program `code[method]` with PUBLIC
(caller, value, cursor, time, args) produced exactly this PUBLIC I/O log" WITHOUT the verifier executing
anything. One zkVM step = one trace row. The verifier then replays the tiny I/O log against its state
(zkvm.replay_io) — that pair (proof + log replay) is what replaces re-execution.

Layout (one row):
  R0..R7 · PC · IOC (I/O entries emitted so far) · IMM · H0,H1 (sponge) · WI,WJ (per-op inverse/bit witness)
  f_op one-hot (34) · d one-hot (8) · s one-hot (8) · BL0..12 byte limbs · SL0..3 seven-bit limbs
  M_FETCH / M_BYTE / M_7BIT (lookup multiplicities)                                        — 85 main columns
  HF,GF (fetch bus) · HIO,GIO (I/O bus) · HB0..6,GB (byte bus, limbs paired) · HS0..1,GS · Z — 16 aux columns

Four LogUp buses share the single accumulator Z (sound: tuples are domain-tagged, and all columns commit
BEFORE β,γ are drawn — the two-phase protocol in stark.prove):
  fetch  (pc, op, d, s, imm) of every non-NOP row ∈ the program table (periodic, from public code)
  io     (ioc, kind, a, b) of every I/O row  =multiset=  the public log (periodic; ioc pins the ORDER)
  byte / 7bit   every limb ∈ [0,256) / [0,128)   (range tables as periodic columns)
Public context (caller/value/cursor/time) is baked into the CONSTRAINTS; args pin row 0's registers; the
program and log live in periodic columns — nothing statement-shaped is read from the proof.
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
W_MAIN = MS + 1
HF = W_MAIN; GF = HF + 1; HIO = GF + 1; GIO = HIO + 1
HB = GIO + 1                  # 7 paired byte helpers
GB = HB + 7
HS = GB + 1                   # 2 paired 7bit helpers
GS = HS + 2
Z = GS + 1
W_TOTAL = Z + 1
NUM_AUX = W_TOTAL - W_MAIN

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
PA = 20                                                  # args of the owning call: PA+0 .. PA+7
NUM_PERIODIC = PA + NR

TAG_FETCH = 1 << 32           # bus domain tags (outside every raw table's value range)
TAG_IO = 1 << 33
MAX_DEGREE = 8                # sponge x^7 under a selector; register-update mux also lands at 8
MIN_T = 512                   # byte table (256 rows) + headroom must sit within rows 0..T-2
MAX_T = 8192                  # zkvm.GAS_LIMIT + padding — one call is always one proof

_O = zkvm.OP
_IO_OPS = ("SLOAD", "SSTORE", "PAY", "BHASH", "BEACON", "RET")
_IO_KIND = {"SLOAD": zkvm.IO_SLOAD, "SSTORE": zkvm.IO_SSTORE, "PAY": zkvm.IO_PAY,
            "BHASH": zkvm.IO_BHASH, "BEACON": zkvm.IO_BEACON, "RET": zkvm.IO_RET}
_WRITE_OPS = ("MOVI", "MOV", "ADD", "SUB", "MUL", "EQ", "NEZ", "NOTB", "LT", "DIVMOD", "LO32", "CTX", "HOUT")
_LOAD_OPS = ("SLOAD", "BHASH", "BEACON")   # dest register comes from the I/O bus, not the update mux


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
_SPEC_Q = [(BL + k, 1 << (8 * k)) for k in range(4)]
_SPEC_BM1 = [(BL + 4 + k, 1 << (8 * k)) for k in range(3)] + [(SL + 1, 1 << 24)]
_SPEC_REM = [(BL + 7 + k, 1 << (8 * k)) for k in range(3)] + [(SL + 2, 1 << 24)]
_SPEC_BR1 = [(BL + 10 + k, 1 << (8 * k)) for k in range(3)] + [(SL + 3, 1 << 24)]
_SPEC_LO = _SPEC_Q
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


def _fetch_tuple(row, per, gamma):
    """The instruction fetched at this row, tagged by which PROGRAM the owning call runs (per[PC_PROG]) so a
    multi-contract epoch's fetch bus can't confuse two programs' instructions."""
    return logup.combine([TAG_FETCH, per[PC_PROG], row[PC], _op_id(row), _idx(row, D0), _idx(row, S0),
                          row[IMM]], gamma)


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
def transitions():
    """The full constraint list. All per-call context is PERIODIC (public), so ONE constraint set proves an
    EPOCH of N concatenated calls (aggregation) as well as a single call. Every constraint is
    c(cur, nxt, per, chal), chal = (β, γ). P_START(cur) pins a call's first row (registers←args, pc←0,
    sponge←0); P_END(cur) disables the held/step transitions on the last row of a call whose successor is a
    fresh call, so the reset is exactly at the boundary. The io counter is NEVER reset — it serializes the
    whole epoch's I/O in one global order."""
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
            load_i = F.mul(c[D0 + i], F.add(c[F0 + _O["SLOAD"]],
                                            F.add(c[F0 + _O["BHASH"]], c[F0 + _O["BEACON"]])))
            write = F.mul(c[D0 + i], F.sub(_res_expr(c, p), F.mul(_wr_expr(c), c[R0 + i])))
            # write = d_i·(Σf·res - wr·R_i) = d_i·Σf·(res - R_i)
            rem7 = 0
            if i == 7:                                       # DIVMOD deposits the remainder in r7
                rem7 = F.mul(c[F0 + _O["DIVMOD"]], F.sub(_recomp(c, _SPEC_REM), c[R0 + 7]))
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
    def c_lo32(c, n, p, ch):
        v = F.add(F.mul(_recomp(c, _SPEC_HI), 1 << 32), _recomp(c, _SPEC_LO))
        return F.mul(c[F0 + _O["LO32"]], F.sub(_rd_val(c), v))
    def c_lo32_canon(c, n, p, ch):
        hi, lo = _recomp(c, _SPEC_HI), _recomp(c, _SPEC_LO)
        gate = F.sub(1, F.mul(F.sub(hi, (1 << 32) - 1), c[WJ]))
        return F.mul(c[F0 + _O["LO32"]], F.mul(lo, gate))
    cons.extend([c_lt, c_range, c_dm_main, c_dm_b, c_dm_r, c_lo32, c_lo32_canon])

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
    cons.extend([c_hf, c_gf, c_hio, c_gio])
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
        for j in range(7):
            term = F.add(term, c[HB + j])
        term = F.sub(term, c[GB])
        term = F.add(term, F.add(c[HS + 0], c[HS + 1]))
        term = F.sub(term, c[GS])
        return F.sub(n[Z], F.add(c[Z], term))
    cons.append(c_z)
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
            rows.append(row)
            regs, h0, h1, lioc = st["regs"], st["h0"], st["h1"], st["ioc_after"]
        ioc = base + lioc                                 # advance the global counter by this call's io count
        for e in io:
            epoch_io.append((e[0], e[1] % F.P, e[2] % F.P))
        blocks.append((start, len(rows) - start, pid, call))
        per_call.append({"io": io, "ret": ret, "new_slots": new_slots})

    n = len(rows)
    total_prog = sum(len(p) for p in progs)
    T = max(MIN_T, _next_pow2(max(n, total_prog, len(epoch_io), 256) + 2))
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
    for i in range(T):
        rows[i][MF], rows[i][MB], rows[i][MS] = mf[i], mb[i], ms[i]
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
    # range tables
    for i in range(T):
        cols[PB][i] = i if i < 256 else 0
        cols[PS][i] = i if i < 128 else 0
    # per-execution-row context + args + boundary selectors
    for bi, (start, nrows, pid, call) in enumerate(blocks):
        args8 = [(call["args_f"][k] if k < len(call["args_f"]) else 0) % F.P for k in range(NR)]
        ctx = (call["caller_f"] % F.P, call.get("value", 0) % F.P,
               call.get("cursor", 0) % F.P, call.get("timestamp", 0) % F.P)
        for i in range(start, start + nrows):
            cols[PC_CALLER][i], cols[PC_VALUE][i], cols[PC_CURSOR][i], cols[PC_TIME][i] = ctx
            cols[PC_PROG][i] = pid
            for k in range(NR):
                cols[PA + k][i] = args8[k]
        cols[P_START][start] = 1
        # END on this call's last row iff a NEXT call follows (its start row is the reset target)
        if bi + 1 < len(blocks):
            cols[P_END][start + nrows - 1] = 1
    return cols


def make_aux_builder(periodic):
    """The prover's phase-2 witness: the 16 challenge-dependent helper/accumulator columns, built against the
    already-computed public periodic columns."""
    per_cols = periodic

    def build(trace, chal):
        beta, gamma = chal
        T = len(trace)
        cols = [[0] * T for _ in range(NUM_AUX)]
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
            put(HF, i, hf); put(GF, i, gf); put(HIO, i, hio); put(GIO, i, gio)
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
            for jx in range(7):
                term = F.add(term, cols[HB - W_MAIN + jx][i])
            term = F.sub(term, cols[GB - W_MAIN][i])
            term = F.add(term, F.add(cols[HS - W_MAIN][i], cols[HS - W_MAIN + 1][i]))
            term = F.sub(term, cols[GS - W_MAIN][i])
            z = F.add(z, term)
        return cols
    return build


def _boundaries(T):
    """Only the GLOBAL boundaries — per-call resets are enforced by the P_START pins inside the constraints.
    Row 0 is the first call's start (pc/ioc/sponge zero); Z telescopes to 0 at both ends (the LogUp buses
    balance over the whole epoch)."""
    return [(0, PC, 0), (0, IOC, 0), (0, H0, 0), (0, H1, 0), (0, Z, 0), (T - 1, Z, 0)]


def _aux_spec(periodic):
    return {"num_challenges": 2, "num_aux": NUM_AUX, "build": make_aux_builder(periodic)}


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


def prove_epoch_calls(calls, num_queries=stark.NUM_QUERIES):
    """Prove an ORDERED batch of zkVM calls as ONE proof (aggregation). Each call is
    {code, method, caller, args, value?, cursor?, timestamp?, beacons?, block_hashes?, slots?}; `slots` is
    that call's PRE-storage (the caller chains them). Returns (proof, epoch_io, per_call). L1 verifies this
    single proof for the whole epoch instead of N proofs."""
    calls = [_norm_call(c) for c in calls]
    trace, T, blocks, progs, epoch_io, per_call = build_epoch_trace(calls)
    periodic = build_periodic(blocks, progs, epoch_io, T)
    proof = stark.prove(trace, transitions(), _boundaries(T), periodic=periodic, max_degree=MAX_DEGREE,
                        num_queries=num_queries, aux_spec=_aux_spec(periodic))
    proof["progs"] = [[list(ins) for ins in p] for p in progs]
    proof["blocks"] = [{"start": s, "n": n, "pid": pid} for (s, n, pid, _c) in blocks]
    return proof, epoch_io, per_call


def verify_epoch_calls(proof, calls, epoch_io, num_queries=stark.NUM_QUERIES):
    """Verify a proven epoch WITHOUT executing any call. `calls` is the public statement (code/method/caller/
    args/context per call, in order); `epoch_io` the claimed global I/O log. Returns (ok, reason). The
    periodic tables (programs, log order, per-call context) are rebuilt locally — nothing is trusted from the
    proof except commitments/openings. On ok, apply the epoch by replaying epoch_io per call."""
    try:
        T, W = proof["T"], proof["W"]
        if not isinstance(T, int) or not (MIN_T <= T <= MAX_T) or W != W_TOTAL:
            return False, "bad trace geometry"
        calls = [_norm_call(c) for c in calls]
        for c in calls:
            zkvm.validate_code(c["code"])
            if c["method"] not in c["code"]:
                return False, "unknown method"
        # rebuild the (blocks, progs) schedule from the public calls + the proof's declared block lengths,
        # then re-derive every periodic column and check the declared lengths against the claimed io log.
        decl = proof.get("blocks")
        if not isinstance(decl, list) or len(decl) != len(calls):
            return False, "block schedule missing/mismatched"
        prog_ids, progs, blocks = {}, [], []
        for c, b in zip(calls, decl):
            prog = c["code"][c["method"]]
            key = _prog_key(prog)
            if key not in prog_ids:
                prog_ids[key] = len(progs); progs.append(prog)
            if not (isinstance(b.get("start"), int) and isinstance(b.get("n"), int) and b["n"] >= 1):
                return False, "bad block"
            blocks.append((b["start"], b["n"], prog_ids[key], c))
        # blocks must tile [0, total) contiguously in order (no gaps/overlaps — that is what makes the
        # concatenation a faithful sequential execution)
        pos = 0
        for (s, n, _pid, _c) in blocks:
            if s != pos:
                return False, "non-contiguous block schedule"
            pos += n
        if pos > T - 2:
            return False, "epoch does not fit the trace"
        for e in epoch_io:
            if not (isinstance(e, (list, tuple)) and len(e) == 3
                    and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < F.P for x in e)):
                return False, "malformed io log entry"
        if len(epoch_io) > T - 2:
            return False, "io log does not fit the trace"
        norm_io = [(e[0], e[1] % F.P, e[2] % F.P) for e in epoch_io]
        periodic = build_periodic(blocks, progs, norm_io, T)
        return stark.verify(proof, transitions(), _boundaries(T), periodic=periodic, max_degree=MAX_DEGREE,
                            num_queries=num_queries, aux_spec=_aux_spec(periodic))
    except Exception as e:
        return False, f"malformed statement/proof: {e}"


# ---- single-call convenience (the N=1 epoch) — the endpoints' interface ------------------------------
def prove_call(code, method, caller, args, storage, value=0, cursor=0, timestamp=0, beacons=None,
               block_hashes=None, num_queries=stark.NUM_QUERIES):
    """Execute + prove ONE zkVM call (the N=1 epoch). Returns (proof, io_log, ret, new_storage). `caller`/
    `args` are already field-form (the runtime digests them at the boundary)."""
    call = {"code": code, "method": method, "caller_f": caller % F.P,
            "args_f": [a % F.P for a in args], "caller": caller, "args": list(args),
            "value": value, "cursor": cursor, "timestamp": timestamp, "beacons": beacons,
            "block_hashes": block_hashes, "slots": storage}
    proof, epoch_io, per_call = prove_epoch_calls([call], num_queries=num_queries)
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
