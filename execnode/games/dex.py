"""
DEX — a constant-product AMM (x·y=k) for NADO ↔ asset pairs, on the zkVM.

The venue layer from ROADMAP Phase 2: any Phase-1 asset gets a price and a NADO pair, with no listing,
no admin and no rake to us. Swaps pay 30 bps that accrues ENTIRELY to the liquidity providers (the fee
is simply never removed from the reserves), so the contract never mints and never profits — the rule
bet.py and the banked games already follow.

WHY LIQUIDITY IS TWO-STEP. A zkVM call carries exactly ONE asset: `in_asset()` names it, `value()` is
the amount. NADO and a token cannot ride the same call, so seeding a pair cannot be one transaction.
Liquidity is staged into a POSITION the caller owns: fundn/fundt credit its two pending sides, join()
consumes them and mints shares. Pending funds stay the depositor's — refund() returns them at any time,
so a half-finished deposit is never stranded (the escape-hatch fund-lock class, closed by construction).

POSITIONS ARE SLOT-KEYED, NOT HASH-KEYED. Per-(pool, provider) state via m.at(hash(...)) is correct but
costs several registers per access, and a named temp is pinned for the whole method — together they
exhaust the ~7-register file. A position id (the seat pattern farkle/holdem use) keys with plain
slot(field, id) arithmetic instead, and binds an owner, which is also what makes `exit` authenticated.

ARITHMETIC — the part that decides whether the trace is provable at all. Reserves are held in UNITs:
DIVMODW needs a divisor in [1, 2^31) and a quotient < 2^32, and every AMM formula divides by a
reserve-sized number. UNIT = 10^8 gives 0.01 NADO granularity and caps a side at ~21.4M NADO — the same
scaling, for the same reason, as reserve.py and bet.py. Everything that can GROW is bounded < 2^31:
    swap: out = RT·dxf // (RN + dxf)   divisor RN+dxf < 2^31, quotient out <= RT < 2^31 < 2^32   ✓
    join: sh  = pn·SUP // RN           divisor RN < 2^31,     quotient <= SUP < 2^31             ✓
    exit: amt = sh·R   // SUP          divisor SUP < 2^31,    quotient <= R < 2^31               ✓
`x·y` is never formed — k is implicit in those divisions, so nothing approaches the field size.

AMOUNTS ARE STATED, THEN VERIFIED BY MULTIPLICATION (`value == units·UNIT`), never derived with `//`:
`//` is DIVMOD (divisor < 2^15, but UNIT is 10^8) and DIVMODW on an unbounded `value` leaves its budget.

Slot model: slot(field, id) = field·2^32 + id, so EVERY id is required < 2^32 — an id at or above that
aliases onto another field's slots (the cross-entity storage-aliasing lock class).

Pool fields  (keyed by pid): 1 ast · 2 rn(UNITs) · 3 rt(UNITs) · 4 sup(shares) · 9 list; slot 0 = count.
Position flds(keyed by posId): 5 own · 6 pool · 7 sh · 10 pn(UNITs) · 11 pt(UNITs)
Methods: open(pid,asset) · fundn(posId,pid,units)[NADO] · fundt(posId,units)[asset] · join(posId)
         refund(posId) · exit(posId,shares) · swapn(pid,units,minOut)[NADO] · swapt(pid,units,minOut)[asset]
"""
from execnode import zkpy

AST, RN, RT, SUP, LIST = 1, 2, 3, 4, 9
POW, PPOOL, PSH, PPN, PPT = 5, 6, 7, 10, 11

UNIT = 10 ** 8                     # 10^8 raw = 0.01 NADO — see the ARITHMETIC note
BOUND = 1 << 31                    # ceiling on every reserve, share count and stated amount
ID_MAX = 1 << 32                   # ids are slot keys: field·2^32 + id

# 30 bps to the LPs: the full input joins the reserve, but only FEE_NUM/FEE_DEN of it prices the output,
# so the difference stays in the pool and every share appreciates.
FEE_NUM, FEE_DEN = 9970, 10000


def build():
    c = zkpy.Contract()

    # open(pid, asset) — claim a pool id for a NADO/asset pair. Carries no value; an empty pool is just a
    # name until someone seeds it through a position.
    with c.method("open") as m:
        pid = m.arg(0)
        m.require(pid > 0)
        m.require(pid < ID_MAX)                        # slot-key bound
        m.require(m.in_asset() == 0)
        m.require(m.value() == 0)
        m.require(m.slot(AST, pid).get() == 0)         # id unused
        # `!= 0`, never `> 0`: an asset id is a full field element and `lt` RANGE-reverts at 2^62, which
        # would refuse most legitimate assets. EQ carries no range gate. (reserve.py, same trap.)
        m.require(m.arg(1) != 0)
        m.slot(AST, pid).set(m.arg(1))
        cnt = m.set(m.slot(0, m.const(0)).get(), "cnt")
        m.slot(LIST, cnt).set(pid)
        m.slot(0, m.const(0)).set(cnt + 1)
        m.ret(pid)

    # fundn(posId, pid, units)[NADO] — stage NATIVE liquidity into your position, binding it on first use.
    with c.method("fundn") as m:
        pos = m.arg(0)
        m.require(pos > 0)
        m.require(pos < ID_MAX)
        m.require(m.slot(AST, m.arg(1)).get() != 0)    # the pool exists
        m.require(m.in_asset() == 0)                   # native only
        u = m.set(m.arg(2), "u")
        m.require(u > 0)
        m.require(u < BOUND)
        m.require(m.value() == u * UNIT)               # stated, then verified by multiplication
        # BIND on first use, then it is yours: an unowned position takes the caller, an owned one must BE
        # the caller. Without the second check anyone could top up (and later exit) someone else's position.
        m.jnz(m.slot(POW, pos).get(), "bound")
        m.slot(POW, pos).set(m.caller())
        m.slot(PPOOL, pos).set(m.arg(1))
        m.label("bound")
        m.require(m.slot(POW, pos).get() == m.caller())
        m.require(m.slot(PPOOL, pos).get() == m.arg(1))
        m.require(m.slot(PPN, pos).get() + u < BOUND)
        m.slot(PPN, pos).set(m.slot(PPN, pos).get() + u)
        m.ret(m.slot(PPN, pos).get())

    # fundt(posId, units)[asset] — stage TOKEN liquidity into an already-bound position.
    with c.method("fundt") as m:
        pos = m.arg(0)
        m.require(m.slot(POW, pos).get() == m.caller())
        m.require(m.slot(PPOOL, pos).get() == m.arg(1))
        m.require(m.in_asset() == m.slot(AST, m.arg(1)).get())
        u = m.set(m.arg(2), "u")
        m.require(u > 0)
        m.require(u < BOUND)
        m.require(m.value() == u * UNIT)
        m.require(m.slot(PPT, pos).get() + u < BOUND)
        m.slot(PPT, pos).set(m.slot(PPT, pos).get() + u)
        m.ret(m.slot(PPT, pos).get())

    # refund(posId) — take back BOTH pending sides. Staged funds are always the depositor's; without this
    # a position funded on one side only would strand them forever.
    with c.method("refund") as m:
        pos = m.arg(0)
        m.require(m.slot(POW, pos).get() == m.caller())
        m.require(m.slot(PPOOL, pos).get() == m.arg(1))
        m.require(m.slot(AST, m.arg(1)).get() == m.arg(2))   # asset as a checked leaf (see exit)
        pn = m.set(m.slot(PPN, pos).get(), "pn")
        pt = m.set(m.slot(PPT, pos).get(), "pt")
        m.require(pn + pt > 0)
        m.slot(PPN, pos).set(m.const(0))
        m.slot(PPT, pos).set(m.const(0))
        m.pay(m.caller(), pn * UNIT)
        ptu = m.set(pt * UNIT, "ptu")
        m.apay(m.arg(2), m.caller(), ptu)
        m.ret(pn + pt)

    # join(posId) — consume the position's pending sides and mint shares.
    #   seed (SUP==0): both sides in full, shares = native units; the deposit IS the opening price.
    #   after:         the NATIVE side sets the mint and the token side must COVER its proportional part;
    #                  unused token stays pending (refundable) rather than being silently absorbed.
    with c.method("join") as m:
        # REGISTER BUDGET: a named temp (m.set) is pinned for the WHOLE method and only ~7 registers exist
        # (r7 is DIVMOD's). ARGS are leaves — they re-materialize into a transient register on each use and
        # pin nothing — so the pool id rides in as an arg (checked against the position) instead of being
        # held, and the token side is read from storage at each use. Only pn/sup/sh/ut are pinned.
        pos = m.arg(0)
        pid = m.arg(1)
        m.require(m.slot(POW, pos).get() == m.caller())
        m.require(m.slot(PPOOL, pos).get() == pid)     # the position's own pool, not a caller-chosen one
        m.require(m.slot(PPN, pos).get() > 0)
        m.require(m.slot(PPT, pos).get() > 0)
        sup = m.set(m.slot(SUP, pid).get(), "sup")

        m.jnz(sup != 0, "prop")
        m.slot(RN, pid).set(m.slot(PPN, pos).get())
        m.slot(RT, pid).set(m.slot(PPT, pos).get())
        m.slot(SUP, pid).set(m.slot(PPN, pos).get())
        m.slot(PSH, pos).set(m.slot(PSH, pos).get() + m.slot(PPN, pos).get())
        m.slot(PPN, pos).set(m.const(0))
        m.slot(PPT, pos).set(m.const(0))
        m.ret(m.slot(PSH, pos).get())

        m.label("prop")
        m.require(m.slot(RN, pid).get() > 0)           # live reserves ⇒ divisors in [1, 2^31)
        m.require(m.slot(RT, pid).get() > 0)
        m.require(m.slot(RN, pid).get() < BOUND)
        m.require(m.slot(RT, pid).get() < BOUND)
        m.require(sup < BOUND)
        sh = m.set(m.muldiv(m.slot(PPN, pos).get(), sup, m.slot(RN, pid).get()), "sh")
        m.require(sh > 0)
        ut = m.set(m.muldiv(sh, m.slot(RT, pid).get(), sup), "ut")   # token needed for those shares
        m.require(ut > 0)
        m.require(ut < m.slot(PPT, pos).get() + 1)     # you must have staged at least that much
        m.require(m.slot(RN, pid).get() + m.slot(PPN, pos).get() < BOUND)   # re-checked where they GROW
        m.require(m.slot(RT, pid).get() + ut < BOUND)
        m.require(sup + sh < BOUND)
        m.slot(RN, pid).set(m.slot(RN, pid).get() + m.slot(PPN, pos).get())
        m.slot(RT, pid).set(m.slot(RT, pid).get() + ut)
        m.slot(SUP, pid).set(sup + sh)
        m.slot(PSH, pos).set(m.slot(PSH, pos).get() + sh)
        m.slot(PPN, pos).set(m.const(0))               # native fully consumed
        m.slot(PPT, pos).set(m.slot(PPT, pos).get() - ut)   # unused token stays refundable
        m.ret(sh)

    # exit(posId, shares) — burn shares, take the pro-rata slice of BOTH reserves.
    with c.method("exit") as m:
        pos = m.arg(0)
        pid = m.arg(1)                                 # a leaf (see the REGISTER BUDGET note in join)
        m.require(m.slot(POW, pos).get() == m.caller())
        m.require(m.slot(PPOOL, pos).get() == pid)
        # The asset rides in as an arg and is CHECKED against the pool here, so the apay below spends a
        # leaf instead of a nested slot read — which is what makes its three operands fit at once.
        m.require(m.slot(AST, pid).get() == m.arg(3))
        sh = m.set(m.arg(2), "sh")
        m.require(sh > 0)
        m.require(sh < m.slot(PSH, pos).get() + 1)     # sh <= your shares
        # SUP is read inline at each use (see the REGISTER BUDGET note in join) — pinning it here
        # exhausted the file before the solvency checks below could be expressed.
        m.require(m.slot(SUP, pid).get() > 0)
        m.require(m.slot(SUP, pid).get() < BOUND)
        m.require(m.slot(RN, pid).get() < BOUND)
        m.require(m.slot(RT, pid).get() < BOUND)
        an = m.set(m.muldiv(sh, m.slot(RN, pid).get(), m.slot(SUP, pid).get()), "an")
        at = m.set(m.muldiv(sh, m.slot(RT, pid).get(), m.slot(SUP, pid).get()), "at")
        m.require(an < m.slot(RN, pid).get() + 1)      # solvency: never pay out past the reserve
        m.require(at < m.slot(RT, pid).get() + 1)
        m.slot(RN, pid).set(m.slot(RN, pid).get() - an)
        m.slot(RT, pid).set(m.slot(RT, pid).get() - at)
        m.slot(SUP, pid).set(m.slot(SUP, pid).get() - sh)
        m.slot(PSH, pos).set(m.slot(PSH, pos).get() - sh)
        m.pay(m.caller(), an * UNIT)
        # PARK the raw amount: apay materializes its three operands AT ONCE, and a pinned temp costs no
        # new register, so this is what lets asset+recipient+amount fit in the file at the same time.
        atu = m.set(at * UNIT, "atu")
        m.apay(m.arg(3), m.caller(), atu)
        m.ret(an)

    # swapn(pid, units, minOut)[NADO] — sell NADO for the pool's token.
    #   out = RT·dxf // (RN + dxf),  dxf = dx·9970//10000
    with c.method("swapn") as m:
        pid = m.arg(0)
        m.require(m.slot(AST, pid).get() != 0)
        m.require(m.slot(AST, pid).get() == m.arg(3))  # asset as a checked leaf (see exit)
        m.require(m.in_asset() == 0)
        dx = m.set(m.arg(1), "dx")
        m.require(dx > 0)
        m.require(dx < BOUND)
        m.require(m.value() == dx * UNIT)
        m.require(m.slot(RN, pid).get() > 0)
        m.require(m.slot(RT, pid).get() > 0)
        m.require(m.slot(RN, pid).get() < BOUND)
        m.require(m.slot(RT, pid).get() < BOUND)
        dxf = m.set(m.muldiv(dx, FEE_NUM, FEE_DEN), "dxf")
        m.require(dxf > 0)
        m.require(m.slot(RN, pid).get() + dxf < BOUND)   # DIVMODW divisor budget — enforced, not assumed
        out = m.set(m.muldiv(m.slot(RT, pid).get(), dxf, m.slot(RN, pid).get() + dxf), "out")
        m.require(out > 0)
        m.require(out < m.slot(RT, pid).get())         # a swap can never drain the whole side
        # SLIPPAGE: out >= minOut, written as `minOut < out+1`. NEVER `out > minOut-1`: field
        # arithmetic has no negatives, so minOut=0 wraps to P-1 and the check refuses every swap.
        m.require(m.arg(2) < out + 1)
        m.require(m.slot(RN, pid).get() + dx < BOUND)
        m.slot(RN, pid).set(m.slot(RN, pid).get() + dx)
        m.slot(RT, pid).set(m.slot(RT, pid).get() - out)
        outu = m.set(out * UNIT, "outu")
        m.apay(m.arg(3), m.caller(), outu)
        m.ret(out)

    # swapt(pid, units, minOut)[asset] — sell the pool's token for NADO. Mirror of swapn.
    with c.method("swapt") as m:
        pid = m.arg(0)
        m.require(m.slot(AST, pid).get() != 0)
        m.require(m.in_asset() == m.slot(AST, pid).get())
        dx = m.set(m.arg(1), "dx")
        m.require(dx > 0)
        m.require(dx < BOUND)
        m.require(m.value() == dx * UNIT)
        m.require(m.slot(RN, pid).get() > 0)
        m.require(m.slot(RT, pid).get() > 0)
        m.require(m.slot(RN, pid).get() < BOUND)
        m.require(m.slot(RT, pid).get() < BOUND)
        dxf = m.set(m.muldiv(dx, FEE_NUM, FEE_DEN), "dxf")
        m.require(dxf > 0)
        m.require(m.slot(RT, pid).get() + dxf < BOUND)
        out = m.set(m.muldiv(m.slot(RN, pid).get(), dxf, m.slot(RT, pid).get() + dxf), "out")
        m.require(out > 0)
        m.require(out < m.slot(RN, pid).get())
        m.require(m.arg(2) < out + 1)                  # SLIPPAGE (see swapn: no minOut-1 underflow)
        m.require(m.slot(RT, pid).get() + dx < BOUND)
        m.slot(RT, pid).set(m.slot(RT, pid).get() + dx)
        m.slot(RN, pid).set(m.slot(RN, pid).get() - out)
        m.pay(m.caller(), out * UNIT)
        m.ret(out)

    return c.build()


ABI = {
    "open":   {"args": ["poolId", "assetId"]},
    "fundn":  {"args": ["posId", "poolId", "units"], "value": True},
    "fundt":  {"args": ["posId", "poolId", "units"], "value": True},
    "join":   {"args": ["posId", "poolId"]},
    "refund": {"args": ["posId", "poolId", "assetId"]},
    "exit":   {"args": ["posId", "poolId", "shares", "assetId"]},
    "swapn":  {"args": ["poolId", "units", "minOut", "assetId"], "value": True},
    "swapt":  {"args": ["poolId", "units", "minOut"], "value": True},
    "_view": {"maps": {"ast": {"field": AST, "index": "pools"},
                       "rn":  {"field": RN,  "index": "pools"},
                       "rt":  {"field": RT,  "index": "pools"},
                       "sup": {"field": SUP, "index": "pools"}},
              "index": {"pools": {"count": 0, "list": LIST}}},
}
