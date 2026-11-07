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

THE LAUNCHPAD (doc/launchpad.md — "create it now, i think by upgrading the existing dex contract and updating it in
place", operator 2026-11-07). A launch is a pool with KIND = 1: a bonding curve over the coin's WHOLE supply, priced by
constant product over the NADO it has raised plus a fixed virtual amount (VN0) against the coins it still holds.
  prelaunch(pid)[NADO]          the creation fee (CREATE_FEE, sealed — see FEES) reserves the id for the caller
  launch(pid, units, vn)[asset] the creator sends the coin's whole supply and chooses the curve's scale (VN, the
                                graduation target over 4); the curve opens at this block
  buy(pid, order, units)[NADO]  sell(pid, order, units)[asset]   an order into the curve's OPEN BATCH
  settle(pid)                   clear a closed batch (anyone; buy/sell/claim do it themselves when needed)
  claim(order)                  the order's share of its cleared batch
FAIRNESS BY BATCH, NOT BY ORDER (§2a there). Every order joins its curve's open batch; the opening window (WINDOW
blocks from launch) is ONE batch, after it each block is one. The first call in a later block clears the batch: buys
and sells net against each other at the curve's spot price and only the remainder trades through the curve — so EVERY
buyer in a batch gets one price and every seller another, and in-block position (txid order, grindable) is worth
nothing: no sniping the first block, no sandwich inside a block. The clearing is O(1): two sums in, two totals out;
each order then claims `amount · total // sum` — the work never grows with the number of traders.
GRADUATION when the curve has sold 4/5 of the supply (CT <= GRAD): the curve becomes a KIND = 2 pool at its own price —
RN = the NADO raised, RT = the coins that price needs (the rest of the curve's coins are BURNED) — with NO SHARES
(SUP = 0), so nobody can ever withdraw its liquidity; swapn/swapt trade it from then on.
FEES — 1 % of every order: a buy's in NADO, a sell's in the coin (burned, ABURN). There is no burn for native NADO, so
the NADO fee and the creation fee are SEALED: the contract keeps them, no method can pay them out, and FEEB (slot
FEEB·2^32) counts them in public. The protocol and the creator take nothing.
ARITHMETIC (the same DIVMODW budget): the curve keeps at least supply/5 (it graduates there), so coins a batch sells
back are at most 4·CT and their spot value S·x//CT < 4·x; the NADO raised is capped (RAISE_CAP = 2^28) and
VN < VN_MAX = 2^26, so x = VN + CN < 2^29 and that value < 2^31. A net-sell batch's coins-at-spot B·CT//x < S. Every payout is a share of
its side's total. A seller is never paid past the NADO actually raised (required).
CARRY: a batch closes when the cursor is merely DIFFERENT from its key (never "later"), so a carried chain whose
cursor restarted lower closes every open batch instead of freezing it; the window test (cursor - LBLK < WINDOW)
wraps past the field's top for a lower cursor and reads "closed" too. Orders and batches are plain-id slot-keyed.
"""
from execnode import zkpy

AST, RN, RT, SUP, LIST = 1, 2, 3, 4, 9
POW, PPOOL, PSH, PPN, PPT = 5, 6, 7, 10, 11

UNIT = 10 ** 8                     # 10^8 raw = 0.01 NADO — see the ARITHMETIC note
BOUND = 1 << 31                    # ceiling on every reserve, share count and stated amount
ID_MAX = 1 << 32                   # ids are slot keys: field·2^32 + id
MIN_SEED = 1000                    # units each side must stage to SEED a pool (review 2026-09-23, medium): a
                                   # 1-unit seed makes sup = 1, so every later joiner's share rounds to 0 or 1
                                   # and the seeder captures the rounding — the first-provider inflation shape

# 30 bps to the LPs: the full input joins the reserve, but only FEE_NUM/FEE_DEN of it prices the output,
# so the difference stays in the pool and every share appreciates.
FEE_NUM, FEE_DEN = 9970, 10000

# ---- the launchpad (see the header) ----
KIND, CN, CT, VN, GRAD, LBLK, OPEN, CREATOR = 12, 13, 14, 15, 16, 17, 18, 19     # per pool (curve)
FEEB = 20                                      # slot 0: NADO fees sealed (creation + 1 % of buys), in UNITs
BCNT, BKEY, BPOOL, BNIN, BTIN, BTOUT, BNOUT, BDONE = 21, 22, 23, 24, 25, 26, 27, 28   # per batch (slot 0 of BCNT = count)
OOWN, OBAT, OSIDE, OAMT = 29, 30, 31, 32       # per order
BX, BD = 33, 34                                # per batch: scratch for the clearing (x at clearing, the netted delta)
CURVE, GRADUATED = 1, 2
VN0 = 50_000                                   # the DEFAULT virtual NADO (500 NADO; the page's default): it sets the
                                               # opening price (VN / supply) and the raise at graduation (4·VN)
VN_MIN, VN_MAX = 100, 1 << 26                  # the creator chooses VN — the graduation target over 4 — within these:
                                               # 1 NADO (a 4-NADO raise) up to ~671k NADO; x = VN + CN stays < 2^29
WINDOW = 10                                    # the opening batch: 10 blocks (~70 s) at one price
CREATE_FEE = 1_000                             # 10 NADO, sealed — the price of a launch, against spam
MIN_SUPPLY = 1_000                             # units a launch must carry (dust curves would round to nothing)
RAISE_CAP = 1 << 28                            # NADO a curve may raise, in UNITs: keeps x < 2^29 (ARITHMETIC)
ORDER_FEE = 100                                # 1 % — `units // ORDER_FEE`


# ---- the carry (tools/carry.py, doc/stwo/g5-carry.md) ------------------------------------------------------------
# CARRY_STORAGE: nothing this contract stores names the old chain in a way that can strand funds. The pool methods read
# no cursor, block hash or TIME. The LAUNCHPAD stores two block numbers — a curve's launch block (LBLK) and each batch's
# key (BKEY) — and is carry-safe BY CONSTRUCTION: a batch is open only while the cursor EQUALS its key, and the opening
# window is `cursor - LBLK < WINDOW`, which wraps past the field's top for a lower cursor; so on a carried chain, whose
# cursor restarted lower, every open batch is closed (claimable, settleable) and every window over — nothing waits for a
# block that will not come (tests/test_the_dex_launchpad_… pins it).
# positions are SLOT-keyed by a plain id (no hash key, no owner-keyed field); a position's owner is a caller digest
# (remapped by the carry) and a pool's asset an asset id (remapped by the carry's asset map). Every quantity — reserves,
# shares, supply and the pending sides — is in UNITs and bounded below 2^31 by the methods, so no value needs a word
# declaration. Pending (staged) liquidity is not in flight: refund() returns it at any time, on either chain, with no
# deadline. So the pools, the shares and the pot cross as they are, and every LP exits on gen 29 for exactly the slice
# they would have taken on gen 28.
CARRY_STORAGE = True

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
        m.require(m.slot(CREATOR, pid).get() == 0)     # …and not reserved for a launch (prelaunch)
        # `!= 0`, never `> 0`: an asset id is a full hash word, and on the gen-28 field VM `lt` RANGE-reverted at
        # 2^62, which refused most legitimate assets. zkvm2's LT is exact; EQ is the same test. (reserve.py, same trap.)
        m.require(m.arg(1) != 0)
        m.slot(AST, pid).set(m.arg(1))
        cnt = m.set(m.slot(0, m.const(0)).get(), "cnt")
        m.slot(LIST, cnt).set(pid)
        m.slot(0, m.const(0)).set(cnt + 1)
        m.ret(pid)

    # fundn(posId, pid, units)[NADO] — stage NATIVE liquidity into your position, binding it on first use.
    with c.method("fundn") as m:
        m.require(m.arg(1) < ID_MAX)                   # C2 (2026-09-23): the pool id is a slot key too
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
        m.require(m.arg(0) < ID_MAX)                   # C2 (2026-09-23)
        m.require(m.arg(1) < ID_MAX)
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
        m.require(m.arg(0) < ID_MAX)                   # C2 (2026-09-23)
        m.require(m.arg(1) < ID_MAX)
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
        m.require(m.arg(0) < ID_MAX)                   # C2 (2026-09-23)
        m.require(m.arg(1) < ID_MAX)
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
        # a curve is never seeded by hand, and a graduated pool (reserves, no shares) never RE-seeded: its locked
        # liquidity would be overwritten. Seeding needs an empty, ordinary pool.
        m.require(m.slot(KIND, pid).get() == 0)
        m.require(m.slot(RN, pid).get() == 0)
        m.require(m.slot(PPN, pos).get() + 1 > MIN_SEED)   # seeding needs real size on BOTH sides (MIN_SEED)
        m.require(m.slot(PPT, pos).get() + 1 > MIN_SEED)
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
        m.require(m.arg(0) < ID_MAX)                   # C2 (2026-09-23)
        m.require(m.arg(1) < ID_MAX)
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
        m.require(m.arg(0) < ID_MAX)                   # C2 (2026-09-23)
        pid = m.arg(0)
        m.require(m.slot(AST, pid).get() != 0)
        m.require(m.slot(KIND, pid).get() != CURVE)    # a curve trades by batch (buy/sell) until it graduates
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
        m.require(m.arg(0) < ID_MAX)                   # C2 (2026-09-23)
        pid = m.arg(0)
        m.require(m.slot(AST, pid).get() != 0)
        m.require(m.slot(KIND, pid).get() != CURVE)    # a curve trades by batch (buy/sell) until it graduates
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

    # ---- THE LAUNCHPAD ----------------------------------------------------------------------------------------
    # prelaunch(pid)[NADO] — pay the creation fee and reserve the id for the caller.
    with c.method("prelaunch") as m:
        pid = m.arg(0)
        m.require(pid > 0)
        m.require(pid < ID_MAX)
        m.require(m.slot(AST, pid).get() == 0)
        m.require(m.slot(CREATOR, pid).get() == 0)
        m.require(m.in_asset() == 0)
        m.require(m.value() == CREATE_FEE * UNIT)
        m.slot(CREATOR, pid).set(m.caller())
        m.slot(FEEB, m.const(0)).set(m.slot(FEEB, m.const(0)).get() + CREATE_FEE)
        m.ret(pid)

    # launch(pid, units, vn)[asset] — the creator sends the coin's WHOLE supply; the curve opens now. The page calls it a
    # fair launch only when the settled root proves the asset is not mintable and this is all of its supply.
    with c.method("launch") as m:
        pid = m.arg(0)
        m.require(pid < ID_MAX)
        m.require(m.slot(CREATOR, pid).get() == m.caller())
        m.require(m.slot(AST, pid).get() == 0)
        m.require(m.in_asset() != 0)
        u = m.set(m.arg(1), "u")
        m.require(u + 1 > MIN_SUPPLY)
        m.require(u < BOUND)
        m.require(m.value() == u * UNIT)
        # the curve's scale is the creator's: VN = the graduation target / 4 ("a small community coin need not raise
        # 2,000 NADO to graduate"), bounded so the ARITHMETIC holds
        m.require(m.arg(2) + 1 > VN_MIN)
        m.require(m.arg(2) < VN_MAX)
        m.slot(AST, pid).set(m.in_asset())
        m.slot(KIND, pid).set(m.const(CURVE))
        m.slot(CT, pid).set(u)
        m.slot(VN, pid).set(m.arg(2))
        m.slot(GRAD, pid).set(u // 5)
        m.slot(LBLK, pid).set(m.cursor())
        cnt = m.set(m.slot(0, m.const(0)).get(), "cnt")
        m.slot(LIST, cnt).set(pid)
        m.slot(0, m.const(0)).set(cnt + 1)
        m.ret(u)

    def _key(m, pid):
        """The open batch's key for curve `pid` now: its launch block through the opening window, else this block.
        (cursor - LBLK wraps past the field's top for a lower cursor — a carried chain — and reads closed.)"""
        return m.cursor() - m.slot(LBLK, pid).get() < WINDOW

    def _clear(m, b, tag):
        """Clear batch `b` (pinned by the caller — the ONLY register this holds): net buys and sells at the curve's
        spot price, trade the remainder through the curve, record both sides' totals, graduate the curve if it has
        sold down to GRAD. REGISTER BUDGET: ~7 registers and r7 is DIVMOD's, so every intermediate is PARKED in the
        batch's scratch slots (BX: x at clearing; BD: the netted delta) and re-read, never pinned."""
        def P(f):
            return m.slot(f, m.slot(BPOOL, b).get())   # the curve's field f (pid re-read: a leaf chain, not a pin)
        def Bt(f):
            return m.slot(f, b)
        m.require(Bt(BDONE).get() == 0)
        Bt(BX).set(P(VN).get() + P(CN).get())                                   # x = VN + CN < 2^29
        Bt(BNOUT).set(m.muldiv(Bt(BTIN).get(), Bt(BX).get(), P(CT).get()))      # S at spot (CT >= GRAD > 0)
        m.jnz(Bt(BNIN).get() < Bt(BNOUT).get(), f"{tag}_netsell")
        # NET BUY: sellers get S at spot (BNOUT); dB = B - that buys from the curve; buyers get S plus the curve's coins
        Bt(BD).set(Bt(BNIN).get() - Bt(BNOUT).get())
        m.require(Bt(BX).get() + Bt(BD).get() < BOUND)
        Bt(BTOUT).set(m.muldiv(P(CT).get(), Bt(BD).get(), Bt(BX).get() + Bt(BD).get()))      # dy
        m.require(Bt(BTOUT).get() < P(CT).get())
        P(CN).set(P(CN).get() + Bt(BD).get())
        P(CT).set(P(CT).get() - Bt(BTOUT).get())
        Bt(BTOUT).set(Bt(BTOUT).get() + Bt(BTIN).get())
        m.jmp(f"{tag}_cleared")
        m.label(f"{tag}_netsell")
        # NET SELL: buyers get their NADO's worth at spot (btok < S); dS = S - btok sells to the curve; sellers get the
        # buyers' NADO plus the curve's — never past the NADO it actually raised
        Bt(BTOUT).set(m.muldiv(Bt(BNIN).get(), P(CT).get(), Bt(BX).get()))       # btok
        Bt(BD).set(Bt(BTIN).get() - Bt(BTOUT).get())                            # dS
        m.require(P(CT).get() + Bt(BD).get() < BOUND)
        Bt(BNOUT).set(m.muldiv(Bt(BX).get(), Bt(BD).get(), P(CT).get() + Bt(BD).get()))      # dx
        m.require(Bt(BNOUT).get() < P(CN).get() + 1)   # solvency
        P(CT).set(P(CT).get() + Bt(BD).get())
        P(CN).set(P(CN).get() - Bt(BNOUT).get())
        Bt(BNOUT).set(Bt(BNOUT).get() + Bt(BNIN).get())
        m.label(f"{tag}_cleared")
        Bt(BDONE).set(m.const(1))
        P(OPEN).set(m.const(0))
        # GRADUATION: sold down to GRAD — the curve becomes a share-less pool at its own price; the coins that price
        # does not need are burned
        m.jnz(P(GRAD).get() < P(CT).get(), f"{tag}_live")
        P(RN).set(P(CN).get())
        Bt(BX).set(P(VN).get() + P(CN).get())
        P(RT).set(m.muldiv(P(CN).get(), P(CT).get(), Bt(BX).get()))
        m.require(P(RT).get() > 0)
        Bt(BD).set((P(CT).get() - P(RT).get()) * UNIT)
        m.aburn(P(AST).get(), Bt(BD).get())
        P(KIND).set(m.const(GRADUATED))
        P(CN).set(m.const(0))
        P(CT).set(m.const(0))
        m.label(f"{tag}_live")

    def _order(m, side, tag):
        """Place an order (args: pid, order, units; value verified by the caller method) into the curve's open
        batch — clearing a closed one first, opening a new one if none is open."""
        pid = m.arg(0)
        m.require(pid < ID_MAX)
        m.require(m.slot(KIND, pid).get() == CURVE)
        o = m.arg(1)
        m.require(o > 0)
        m.require(o < ID_MAX)
        m.require(m.slot(OOWN, o).get() == 0)          # a fresh order id
        # the open batch, if its key is no longer the key now, is closed: clear it here
        m.jnz(m.slot(OPEN, pid).get() == 0, f"{tag}_new")
        m.jnz(m.slot(BKEY, m.slot(OPEN, pid).get()).get() == m.slot(LBLK, pid).get(), f"{tag}_inwin")
        m.jnz(m.slot(BKEY, m.slot(OPEN, pid).get()).get() == m.cursor(), f"{tag}_join")
        m.jmp(f"{tag}_close")
        m.label(f"{tag}_inwin")                        # the opening batch: open while the window is
        m.jnz(_key(m, pid), f"{tag}_join")
        m.label(f"{tag}_close")
        bc = m.set(m.slot(OPEN, pid).get(), "bc")
        _clear(m, bc, tag)
        m.label(f"{tag}_new")
        # the new batch's id is read back from the counter (a pin here would starve the clearing above)
        m.slot(BCNT, m.const(0)).set(m.slot(BCNT, m.const(0)).get() + 1)
        m.require(m.slot(BCNT, m.const(0)).get() < ID_MAX)
        m.slot(BPOOL, m.slot(BCNT, m.const(0)).get()).set(pid)
        m.slot(OPEN, pid).set(m.slot(BCNT, m.const(0)).get())
        m.jnz(_key(m, pid), f"{tag}_wkey")
        m.slot(BKEY, m.slot(OPEN, pid).get()).set(m.cursor())
        m.jmp(f"{tag}_join")
        m.label(f"{tag}_wkey")
        m.slot(BKEY, m.slot(OPEN, pid).get()).set(m.slot(LBLK, pid).get())
        m.label(f"{tag}_join")
        m.slot(OOWN, o).set(m.caller())
        m.slot(OBAT, o).set(m.slot(OPEN, pid).get())
        m.slot(OSIDE, o).set(m.const(side))

    # buy(pid, order, units)[NADO]
    with c.method("buy") as m:
        m.require(m.in_asset() == 0)
        u = m.arg(2)                                   # a leaf, not a pin: the clearing in _order needs the registers
        m.require(u + 1 > ORDER_FEE)                   # at least 1 unit of fee: no fee-free dust orders
        m.require(u < BOUND)
        m.require(m.value() == u * UNIT)
        _order(m, 1, "b")
        m.slot(FEEB, m.const(0)).set(m.slot(FEEB, m.const(0)).get() + u // ORDER_FEE)
        m.slot(OAMT, m.arg(1)).set(u - u // ORDER_FEE)
        m.require(m.slot(CN, m.arg(0)).get() + m.slot(BNIN, m.slot(OPEN, m.arg(0)).get()).get() + m.slot(OAMT, m.arg(1)).get() < RAISE_CAP)
        m.slot(BNIN, m.slot(OPEN, m.arg(0)).get()).set(m.slot(BNIN, m.slot(OPEN, m.arg(0)).get()).get() + m.slot(OAMT, m.arg(1)).get())
        m.ret(m.slot(OAMT, m.arg(1)).get())

    # sell(pid, order, units)[asset]
    with c.method("sell") as m:
        m.require(m.in_asset() == m.slot(AST, m.arg(0)).get())
        u = m.arg(2)                                   # a leaf (see buy)
        m.require(u + 1 > ORDER_FEE)
        m.require(u < BOUND)
        m.require(m.value() == u * UNIT)
        _order(m, 2, "s")
        m.slot(OAMT, m.arg(1)).set(u - u // ORDER_FEE)
        fee = m.set((u // ORDER_FEE) * UNIT, "fee")
        m.aburn(m.slot(AST, m.arg(0)).get(), fee)      # the coin's 1 % is burned
        # sells back are bounded by what the curve has sold (supply - CT), which keeps S < 4·CT (ARITHMETIC)
        m.require(m.slot(BTIN, m.slot(OPEN, m.arg(0)).get()).get() + m.slot(OAMT, m.arg(1)).get() + m.slot(CT, m.arg(0)).get() < BOUND)
        m.slot(BTIN, m.slot(OPEN, m.arg(0)).get()).set(m.slot(BTIN, m.slot(OPEN, m.arg(0)).get()).get() + m.slot(OAMT, m.arg(1)).get())
        m.ret(m.slot(OAMT, m.arg(1)).get())

    # settle(pid) — clear the curve's closed batch (anyone may; buy, sell and claim do it themselves)
    with c.method("settle") as m:
        pid = m.arg(0)
        m.require(pid < ID_MAX)
        m.require(m.slot(OPEN, pid).get() != 0)
        m.require(m.slot(BKEY, m.slot(OPEN, pid).get()).get() != m.cursor())
        # the opening batch stays open through its window
        m.jnz(m.slot(BKEY, m.slot(OPEN, pid).get()).get() != m.slot(LBLK, pid).get(), "go")
        m.require(_key(m, pid) == 0)
        m.label("go")
        bs = m.set(m.slot(OPEN, pid).get(), "bs")
        _clear(m, bs, "c")
        m.ret(bs)

    # claim(order[, asset]) — the order's share of its cleared batch; clears it first if it has closed.
    with c.method("claim") as m:
        o = m.arg(0)
        m.require(o < ID_MAX)
        m.require(m.slot(OOWN, o).get() == m.caller())
        m.require(m.slot(OAMT, o).get() > 0)
        b = m.set(m.slot(OBAT, o).get(), "b")
        m.require(m.slot(AST, m.slot(BPOOL, b).get()).get() == m.arg(1))   # the coin as a checked leaf (apay)
        m.jnz(m.slot(BDONE, b).get(), "done")
        # not yet cleared: it must be its curve's open batch, and closed
        m.require(m.slot(OPEN, m.slot(BPOOL, b).get()).get() == b)
        m.require(m.slot(BKEY, b).get() != m.cursor())
        m.jnz(m.slot(BKEY, b).get() != m.slot(LBLK, m.slot(BPOOL, b).get()).get(), "late")
        m.require(_key(m, m.slot(BPOOL, b).get()) == 0)
        m.label("late")
        _clear(m, b, "k")
        m.label("done")
        m.jnz(m.slot(OSIDE, o).get() == 2, "seller")
        # a buyer: coins = amount · BTOUT // BNIN
        m.require(m.slot(BNIN, b).get() > 0)
        m.require(m.slot(BNIN, b).get() < BOUND)
        pay = m.set(m.muldiv(m.slot(OAMT, o).get(), m.slot(BTOUT, b).get(), m.slot(BNIN, b).get()) * UNIT, "pay")
        m.slot(OAMT, o).set(m.const(0))
        m.apay(m.arg(1), m.caller(), pay)
        m.ret(pay)
        m.label("seller")
        # a seller: NADO = amount · BNOUT // BTIN
        m.require(m.slot(BTIN, b).get() > 0)
        m.require(m.slot(BTIN, b).get() < BOUND)
        npay = m.set(m.muldiv(m.slot(OAMT, o).get(), m.slot(BNOUT, b).get(), m.slot(BTIN, b).get()) * UNIT, "npay")
        m.slot(OAMT, o).set(m.const(0))
        m.pay(m.caller(), npay)
        m.ret(npay)

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
    "prelaunch": {"args": ["poolId"], "value": True},
    "launch": {"args": ["poolId", "units", "virtualNado"], "value": True},
    "buy":    {"args": ["poolId", "orderId", "units"], "value": True},
    "sell":   {"args": ["poolId", "orderId", "units"], "value": True},
    "settle": {"args": ["poolId"]},
    "claim":  {"args": ["orderId", "assetId"]},
    "_view": {"maps": {"ast": {"field": AST, "index": "pools"},
                       "rn":  {"field": RN,  "index": "pools"},
                       "rt":  {"field": RT,  "index": "pools"},
                       "sup": {"field": SUP, "index": "pools"},
                       # the launchpad: a pool's kind (0 pool, 1 curve, 2 graduated), the curve's NADO raised, coins
                       # held, virtual NADO, graduation level, launch block, open batch and creator
                       "kind": {"field": KIND, "index": "pools"}, "cn": {"field": CN, "index": "pools"},
                       "ct": {"field": CT, "index": "pools"}, "vn": {"field": VN, "index": "pools"},
                       "grad": {"field": GRAD, "index": "pools"}, "lblk": {"field": LBLK, "index": "pools"},
                       "open": {"field": OPEN, "index": "pools"}, "creator": {"field": CREATOR, "index": "pools"}},
              # NOTE the exact key names decode_view requires: "indexes" (plural) keyed by the index NAME
              # each map references, and "cnt" (not "count") for the counter slot. This shipped as
              # "index": {"pools": {"count": ...}} — read as the SIMPLE single-index schema, whose enum()
              # found no "cnt" key, returned 0, and made EVERY map decode empty. The pools existed on
              # chain the whole time; the frontend just could never see one.
              "indexes": {"pools": {"cnt": 0, "list": LIST}}},
}
