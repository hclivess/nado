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


def _fetch_tuple(row, gamma):
    return logup.combine([TAG_FETCH, row[PC], _op_id(row), _idx(row, D0), _idx(row, S0), row[IMM]], gamma)


def _io_tuple(row, nxt, gamma):
    return logup.combine([TAG_IO, row[IOC], _io_kind_expr(row), _io_a_expr(row), _io_b_expr(row, nxt)], gamma)


def _res_expr(row, pub):
    """Σ f_op · (result value) over the register-writing ops (loads excluded — bus-supplied)."""
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
        "CTX": _lagrange4(row[IMM], [pub["caller"], pub["value"], pub["cursor"], pub["time"]]),
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
def transitions(pub):
    """The full constraint list. `pub` = {caller, value, cursor, time} (field elements) — baked in, so a
    proof only verifies for THAT call context. Every constraint c(cur, nxt, per, chal) with chal = (β, γ).
    Periodic layout: 0..4 program (pc,op,d,s,imm) · 5..9 log (ctr,kind,a,b,act) · 10 byte table · 11 7bit."""
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

    # -- NOP is absorbing (nothing executes after RET / a padding gap) --
    def c_absorb(c, n, p, ch):
        halt = F.add(c[F0 + _O["NOP"]], c[F0 + _O["RET"]])
        return F.mul(halt, F.sub(n[F0 + _O["NOP"]], 1))
    cons.append(c_absorb)

    # -- register file: held unless written by the mux; loads are bus-supplied --
    for i in range(NR):
        def c_reg(c, n, p, ch, i=i):
            load_i = F.mul(c[D0 + i], F.add(c[F0 + _O["SLOAD"]],
                                            F.add(c[F0 + _O["BHASH"]], c[F0 + _O["BEACON"]])))
            write = F.mul(c[D0 + i], F.sub(_res_expr(c, pub), F.mul(_wr_expr(c), c[R0 + i])))
            # write = d_i·(Σf·res - wr·R_i) = d_i·Σf·(res - R_i)
            rem7 = 0
            if i == 7:                                       # DIVMOD deposits the remainder in r7
                rem7 = F.mul(c[F0 + _O["DIVMOD"]], F.sub(_recomp(c, _SPEC_REM), c[R0 + 7]))
            delta = F.sub(F.sub(F.sub(n[R0 + i], c[R0 + i]), write), rem7)
            return F.mul(F.sub(1, load_i), delta)
        cons.append(c_reg)

    # -- sponge lanes --
    def c_h0(c, n, p, ch):
        d = F.sub(n[H0], c[H0])
        d = F.sub(d, F.mul(c[F0 + _O["HINIT"]], F.neg(c[H0])))
        d = F.sub(d, F.mul(c[F0 + _O["HABS"]], _rs_val(c)))
        for r in range(8):
            r0, _ = _sponge_round(c, r)
            d = F.sub(d, F.mul(c[F0 + _O[f"HR{r}"]], F.sub(r0, c[H0])))
        return d
    def c_h1(c, n, p, ch):
        d = F.sub(n[H1], c[H1])
        d = F.sub(d, F.mul(c[F0 + _O["HINIT"]], F.sub(alghash.IV, c[H1])))
        for r in range(8):
            _, r1 = _sponge_round(c, r)
            d = F.sub(d, F.mul(c[F0 + _O[f"HR{r}"]], F.sub(r1, c[H1])))
        return d
    cons.extend([c_h0, c_h1])

    # -- pc: +1, jumps, and hold on NOP/RET --
    def c_pc(c, n, p, ch):
        d = F.sub(F.sub(n[PC], c[PC]), 1)
        jump = F.sub(c[IMM], F.add(c[PC], 1))
        d = F.sub(d, F.mul(c[F0 + _O["JMP"]], jump))
        nz = F.mul(_rs_val(c), c[WI])
        d = F.sub(d, F.mul(c[F0 + _O["JNZ"]], F.mul(nz, jump)))
        d = F.sub(d, F.mul(F.add(c[F0 + _O["NOP"]], c[F0 + _O["RET"]]), F.neg(1)))
        return d
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
        return F.sub(F.mul(c[HF], F.add(ch[0], _fetch_tuple(c, ch[1]))), active)
    def c_gf(c, n, p, ch):
        t = logup.combine([TAG_FETCH, p[0], p[1], p[2], p[3], p[4]], ch[1])
        return F.sub(F.mul(c[GF], F.add(ch[0], t)), c[MF])
    def c_hio(c, n, p, ch):
        return F.sub(F.mul(c[HIO], F.add(ch[0], _io_tuple(c, n, ch[1]))), _io_active(c))
    def c_gio(c, n, p, ch):
        t = logup.combine([TAG_IO, p[5], p[6], p[7], p[8]], ch[1])
        return F.sub(F.mul(c[GIO], F.add(ch[0], t)), p[9])
    cons.extend([c_hf, c_gf, c_hio, c_gio])
    for j, (ca, cb) in enumerate(_BYTE_PAIRS):
        def c_hb(c, n, p, ch, j=j, ca=ca, cb=cb):
            la, lb = c[ca], (c[cb] if cb is not None else 0)
            lhs = F.mul(c[HB + j], F.mul(F.add(ch[0], la), F.add(ch[0], lb)))
            return F.sub(lhs, F.add(F.add(F.mul(2, ch[0]), la), lb))
        cons.append(c_hb)
    def c_gb(c, n, p, ch):
        return F.sub(F.mul(c[GB], F.add(ch[0], p[10])), c[MB])
    cons.append(c_gb)
    for j, (ca, cb) in enumerate(_7BIT_PAIRS):
        def c_hs(c, n, p, ch, j=j, ca=ca, cb=cb):
            lhs = F.mul(c[HS + j], F.mul(F.add(ch[0], c[ca]), F.add(ch[0], c[cb])))
            return F.sub(lhs, F.add(F.add(F.mul(2, ch[0]), c[ca]), c[cb]))
        cons.append(c_hs)
    def c_gs(c, n, p, ch):
        return F.sub(F.mul(c[GS], F.add(ch[0], p[11])), c[MS])
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


# ---- witness → trace ------------------------------------------------------------------------------
def build_trace(code, method, caller, args, storage, value=0, cursor=0, timestamp=0, beacons=None,
                block_hashes=None):
    """Run the interpreter and lay its witness out as the main trace. Returns
    (trace, T, io_log, ret, new_storage) or raises ZkVMRevert-shaped ValueError if the call reverts
    (a reverted call is a no-op — there is nothing to prove)."""
    r = zkvm.run(code, method, caller, list(args), storage, value=value, cursor=cursor, timestamp=timestamp,
                beacons=beacons, block_hashes=block_hashes, witness=True)
    ok, ret, new_storage, io, steps = r
    if not ok:
        raise ValueError("call reverted — nothing to prove")
    prog = code[method]
    n = len(steps)
    T = max(MIN_T, _next_pow2(n + 2))
    if T > MAX_T:
        raise ValueError("trace too long")
    args8 = [(args[i] if i < len(args) else 0) % F.P for i in range(NR)]

    rows = []
    regs, h0, h1, ioc = args8, 0, 0, 0
    for st in steps:                                      # row i carries the PRE-state + instruction i
        row = [0] * W_MAIN
        row[R0:R0 + NR] = regs
        row[PC], row[IOC], row[IMM] = st["pc"], ioc, st["imm"] % F.P
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
        regs, h0, h1, ioc = st["regs"], st["h0"], st["h1"], st["ioc_after"]
    ret_pc = steps[-1]["pc"]                              # RET holds pc; NOP padding keeps holding it
    while len(rows) < T:                                  # NOP padding: state held, one-hots valid
        row = [0] * W_MAIN
        row[R0:R0 + NR] = regs
        row[PC], row[IOC] = ret_pc, ioc
        row[H0], row[H1] = h0, h1
        row[F0 + _O["NOP"]] = 1
        row[D0] = 1
        row[S0] = 1
        rows.append(row)

    # lookup multiplicities (mass over rows 0..T-2 only — row T-1's bus terms never enter Z)
    mf = [0] * T
    for st in steps:
        mf[st["pc"]] += 1
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
    return rows, T, io, ret, new_storage


def build_periodic(prog, io_log, T):
    """The 12 public periodic columns: program table (pc,op,d,s,imm), I/O log (ctr,kind,a,b,act), byte and
    7-bit range tables. The VERIFIER rebuilds these from the public statement — none come from the proof."""
    L = len(io_log)
    p_pc = [i if i < len(prog) else 0 for i in range(T)]
    p_op = [_O[prog[i][0]] if i < len(prog) else 0 for i in range(T)]
    p_d = [prog[i][1] if i < len(prog) else 0 for i in range(T)]
    p_s = [prog[i][2] if i < len(prog) else 0 for i in range(T)]
    p_imm = [prog[i][3] % F.P if i < len(prog) else 0 for i in range(T)]
    l_ctr = [i if i < L else 0 for i in range(T)]
    l_kind = [io_log[i][0] if i < L else 0 for i in range(T)]
    l_a = [io_log[i][1] % F.P if i < L else 0 for i in range(T)]
    l_b = [io_log[i][2] % F.P if i < L else 0 for i in range(T)]
    l_act = [1 if i < L else 0 for i in range(T)]
    b_tbl = [i if i < 256 else 0 for i in range(T)]
    s_tbl = [i if i < 128 else 0 for i in range(T)]
    return [p_pc, p_op, p_d, p_s, p_imm, l_ctr, l_kind, l_a, l_b, l_act, b_tbl, s_tbl]


def make_aux_builder(prog, io_log, T):
    """The prover's phase-2 witness: all 16 challenge-dependent helper/accumulator columns."""
    per = build_periodic(prog, io_log, T)

    def build(trace, chal):
        beta, gamma = chal
        cols = [[0] * T for _ in range(NUM_AUX)]
        def put(idx, row, val):
            cols[idx - W_MAIN][row] = val
        for i in range(T):
            cur = trace[i]
            nxt = trace[i + 1] if i + 1 < T else trace[i]
            hf = F.mul(F.sub(1, cur[F0 + _O["NOP"]]), F.inv(F.add(beta, _fetch_tuple(cur, gamma))))
            gf_t = logup.combine([TAG_FETCH, per[0][i], per[1][i], per[2][i], per[3][i], per[4][i]], gamma)
            gf = F.mul(cur[MF], F.inv(F.add(beta, gf_t)))
            hio = F.mul(_io_active(cur), F.inv(F.add(beta, _io_tuple(cur, nxt, gamma))))
            gio_t = logup.combine([TAG_IO, per[5][i], per[6][i], per[7][i], per[8][i]], gamma)
            gio = F.mul(per[9][i], F.inv(F.add(beta, gio_t)))
            put(HF, i, hf); put(GF, i, gf); put(HIO, i, hio); put(GIO, i, gio)
            for j, (ca, cb) in enumerate(_BYTE_PAIRS):
                la, lb = cur[ca], (cur[cb] if cb is not None else 0)
                put(HB + j, i, F.add(F.inv(F.add(beta, la)), F.inv(F.add(beta, lb))))
            put(GB, i, F.mul(cur[MB], F.inv(F.add(beta, per[10][i]))))
            for j, (ca, cb) in enumerate(_7BIT_PAIRS):
                put(HS + j, i, F.add(F.inv(F.add(beta, cur[ca])), F.inv(F.add(beta, cur[cb]))))
            put(GS, i, F.mul(cur[MS], F.inv(F.add(beta, per[11][i]))))
        z = 0
        for i in range(T):
            put(Z, i, z)
            term = F.sub(cols[HF - W_MAIN][i], cols[GF - W_MAIN][i])
            term = F.add(term, F.sub(cols[HIO - W_MAIN][i], cols[GIO - W_MAIN][i]))
            for j in range(7):
                term = F.add(term, cols[HB - W_MAIN + j][i])
            term = F.sub(term, cols[GB - W_MAIN][i])
            term = F.add(term, F.add(cols[HS - W_MAIN][i], cols[HS - W_MAIN + 1][i]))
            term = F.sub(term, cols[GS - W_MAIN][i])
            z = F.add(z, term)
        return cols
    return build


def _boundaries(args, T):
    args8 = [(args[i] if i < len(args) else 0) % F.P for i in range(NR)]
    bnd = [(0, PC, 0), (0, IOC, 0), (0, H0, 0), (0, H1, 0), (0, Z, 0), (T - 1, Z, 0)]
    bnd += [(0, R0 + i, args8[i]) for i in range(NR)]
    return bnd


def _aux_spec(prog, io_log, T):
    return {"num_challenges": 2, "num_aux": NUM_AUX, "build": make_aux_builder(prog, io_log, T)}


def prove_call(code, method, caller, args, storage, value=0, cursor=0, timestamp=0, beacons=None,
               block_hashes=None, num_queries=stark.NUM_QUERIES):
    """Execute + prove one zkVM call. Returns (proof, io_log, ret, new_storage). The proof attests: running
    PUBLIC code[method] with PUBLIC (caller,value,cursor,time,args) emits exactly PUBLIC io_log. Any node
    then applies the call via zkvm.replay_io(io_log, ...) — no execution."""
    zkvm.validate_code(code)
    trace, T, io, ret, new_storage = build_trace(code, method, caller, args, storage, value=value,
                                                 cursor=cursor, timestamp=timestamp, beacons=beacons,
                                                 block_hashes=block_hashes)
    pub = {"caller": caller % F.P, "value": value % F.P, "cursor": cursor % F.P, "time": timestamp % F.P}
    prog = code[method]
    proof = stark.prove(trace, transitions(pub), _boundaries(args, T), periodic=build_periodic(prog, io, T),
                        max_degree=MAX_DEGREE, num_queries=num_queries, aux_spec=_aux_spec(prog, io, T))
    return proof, io, ret, new_storage


def verify_call(proof, code, method, caller, args, io_log, value=0, cursor=0, timestamp=0,
                num_queries=stark.NUM_QUERIES):
    """Verify a proven call WITHOUT executing it. The statement is entirely caller-supplied: code (public,
    deploy-validated), method, call context, args, and the claimed io_log. Geometry (T, W, program/log fit)
    is pinned before any crypto. Returns (ok, reason). On ok, apply the call with zkvm.replay_io(io_log, st)
    — which also re-checks the log against current storage and hands back payouts + chain reads."""
    try:
        zkvm.validate_code(code)
        if method not in code:
            return False, "unknown method"
        prog = code[method]
        T, W = proof["T"], proof["W"]
        if not isinstance(T, int) or not (MIN_T <= T <= MAX_T) or W != W_TOTAL:
            return False, "bad trace geometry"
        if len(prog) > T - 2 or len(io_log) > T - 2:
            return False, "program or log does not fit the trace"
        for e in io_log:
            if not (isinstance(e, (list, tuple)) and len(e) == 3
                    and all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < F.P for x in e)):
                return False, "malformed io log entry"
        if sum(1 for e in io_log if e[0] == zkvm.IO_RET) != 1 or (io_log and io_log[-1][0] != zkvm.IO_RET):
            return False, "io log must end with exactly one RET"
        if not io_log:
            return False, "empty io log"
        pub = {"caller": caller % F.P, "value": value % F.P, "cursor": cursor % F.P, "time": timestamp % F.P}
        return stark.verify(proof, transitions(pub), _boundaries(args, T),
                            periodic=build_periodic(prog, io_log, T), max_degree=MAX_DEGREE,
                            num_queries=num_queries, aux_spec=_aux_spec(prog, io_log, T))
    except Exception as e:
        return False, f"malformed statement/proof: {e}"
