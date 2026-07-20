"""
Reserve — back an asset with locked native value, redeemable pro-rata, releasable only after notice.
Full design + rationale in doc/reserve.md; the short version:

  floor = res / out        native per token unit, and a holder can always TAKE it

A creator opens a vault naming their asset, declares its supply, seeds a reserve and commits to a NOTICE
period. Any holder may `redeem` at any time — send tokens in as call value, the vault burns them and pays
the pro-rata share. The creator may only take the reserve back by `announce`-ing, waiting out the notice
they committed to, and then `release`-ing; redemption stays open for that whole window, which is the only
reason the notice is worth anything.

WHY A VAULT CAN DO THIS WITHOUT BEING THE ISSUER: burn is holder-side. `stage_asset_effects` checks
`bal(aid, actor) >= amt` on a burn and never consults the issuer, so a contract that merely HOLDS tokens can
destroy them. That is what lets an ordinary person issue with `asset_create` and back it here, instead of
needing `for: <cid>` deployer privilege.

WHAT IT CANNOT DO: read the asset's real supply or its mintable flag — there is no opcode for either
(doc/assets.md §3). `out` is DECLARED at open and only ever falls. The vault is never insolvent regardless
(payout is pro-rata and bounded by the reserve), but a UI must cross-check the declaration against
/exec/asset before it shows a floor. See doc/reserve.md §4.

Slot model: slot(field, vid) = field*2^32 + vid, vid a frontend int < 2^32.
Fields: 1 own · 2 ast · 3 res(UNITs) · 4 out · 5 ntc · 6 pnd(UNITs) · 7 rdy · 9 list; slot 0 = count.
"""
from execnode import zkpy

OWN, AST, RES, OUT, NTC, PND, RDY, LIST = 1, 2, 3, 4, 5, 6, 7, 9

# Reserve is held in UNITs, not raw. DIVMODW needs divisor < 2^31 and quotient < 2^32, and the pro-rata
# payout divides BY `out` and yields a value bounded by `res` — so both have to stay under 2^31 or the
# trace is unprovable. Scaling the reserve keeps a realistic balance inside that window: at RAW = 10^10,
# UNIT = 10^8 is 0.01 native of granularity and caps a vault at ~21.4M native. `bet.py` scales the same way
# and for the same reason.
UNIT = 10 ** 8
BOUND = 1 << 31                  # the hard ceiling on BOTH res(UNITs) and out — required, not advisory

# The shortest notice a vault may commit to. Only a floor: a creator picks their own at open() and it is
# immutable afterwards, so "this vault gives 30 days" is a real, rankable signal and can never be shortened.
# 14400 blocks is one day at the 6s cadence — the same order as BOND_UNLOCK_DELAY, which is the mechanic
# this deliberately mirrors.
MIN_NOTICE = 14400


def _c(m, field, vid):
    return m.slot(field, vid)


def build():
    c = zkpy.Contract()

    # open(vid, asset, supply, notice)[native] — claim a vault and seed it.
    with c.method("open") as m:
        vid = m.arg(0)
        m.require(vid > 0)
        m.require(_c(m, OWN, vid).get() == 0)          # vid unused
        m.require(m.in_asset() == 0)                   # the SEED is native; the asset is named, not sent

        # Args and ctx are LEAVES — re-materializing one costs an instruction, while parking it in a named
        # temp costs a register for the whole method. There are only six, so validate straight off the leaf.
        # `!= 0`, NOT `> 0`. An asset id is a full field element, uniform in [0, P) with P ~ 2^64, but the
        # `lt` macro RANGE-checks both operands and RANGE reverts at 2^62 (`_decomp62` — that bound is what
        # makes a comparison unforgeable). So `arg(1) > 0` REVERTS for roughly three of every four assets,
        # and the vault would have refused most of the tokens it exists to back. EQ carries no range gate.
        # Rule: never order-compare a hash-derived value; only test it for equality.
        m.require(m.arg(1) != 0)                       # asset id
        m.require(m.arg(2) > 0)                        # supply
        m.require(m.arg(2) < BOUND)
        m.require(m.arg(3) + 1 > MIN_NOTICE)           # notice >= MIN_NOTICE, without a `ge`

        # The caller STATES the reserve in UNITs and the contract checks it by MULTIPLYING. Deriving it
        # instead — `value // UNIT` — was wrong twice over: `//` is DIVMOD, whose divisor must be < 2^15
        # while UNIT is 10^8, and reaching for DIVMODW instead would put an unbounded `value` over a
        # quotient budget the contract cannot check until after the divide. An oversized quotient does not
        # revert; it emits a trace no prover can close, which is a denial of service dressed as arithmetic.
        # Multiplying is total: `units` is bounded FIRST, and units·UNIT < 2^31·2^27 stays well inside the
        # field. Equality also rejects dust, so a stray remainder can never be silently swallowed.
        m.require(m.arg(4) > 0)                        # reserve, in UNITs
        m.require(m.arg(4) < BOUND)
        m.require(m.value() == m.arg(4) * UNIT)

        _c(m, OWN, vid).set(m.caller())
        _c(m, AST, vid).set(m.arg(1))
        _c(m, RES, vid).set(m.arg(4))
        _c(m, OUT, vid).set(m.arg(2))
        _c(m, NTC, vid).set(m.arg(3))

        n = m.set(m.slot(0, 0).get(), "n")             # append to the index, 0-indexed
        m.slot(LIST, n).set(vid)
        m.slot(0, 0).set(n + 1)
        m.ret(vid)

    # back(vid)[native] — anyone may add reserve. This is the ONLY way the floor goes up.
    with c.method("back") as m:
        vid = m.arg(0)
        m.require(_c(m, OWN, vid).get() != 0)
        m.require(m.in_asset() == 0)
        m.require(m.arg(1) > 0)                        # added reserve, in UNITs — stated, then multiplied
        m.require(m.arg(1) < BOUND)
        m.require(m.value() == m.arg(1) * UNIT)
        res = m.set(_c(m, RES, vid).get() + m.arg(1), "res")
        m.require(res < BOUND)                         # re-checked here: this is the one path that GROWS res
        _c(m, RES, vid).set(res)
        m.ret(res)

    # redeem(vid)[asset] — burn what you sent, take amt*res//out. Floor-NEUTRAL: both terms fall together.
    with c.method("redeem") as m:
        vid = m.arg(0)
        m.require(_c(m, AST, vid).get() != 0)
        m.require(m.in_asset() == _c(m, AST, vid).get())   # the right token, and not native
        m.require(m.value() > 0)

        out = m.set(_c(m, OUT, vid).get(), "out")
        m.require(m.value() < out + 1)                 # amt <= out
        res = m.set(_c(m, RES, vid).get(), "res")
        # DIVMODW budget, ENFORCED not assumed: the divisor `out` lands in [1, 2^31) because out >= amt > 0
        # and every writer bounds it, and the quotient is <= res < 2^31 < 2^32. Out of range would not
        # revert — it would emit a trace no prover can close.
        m.require(out < BOUND)
        m.require(res < BOUND)
        pay = m.set(m.muldiv(m.value(), res, out), "pay")

        _c(m, RES, vid).set(res - pay)
        _c(m, OUT, vid).set(out - m.value())
        m.aburn(_c(m, AST, vid).get(), m.value())
        m.pay(m.caller(), pay * UNIT)
        m.ret(pay)

    # announce(vid, amt) — owner starts the clock. Re-announcing RESTARTS it, so a pending small amount can
    # never be swapped for the whole reserve at the last second.
    with c.method("announce") as m:
        vid = m.arg(0)
        m.require(_c(m, OWN, vid).get() == m.caller())
        amt = m.set(m.arg(1), "amt")
        m.require(amt > 0)
        m.require(amt < _c(m, RES, vid).get() + 1)     # amt <= res
        _c(m, PND, vid).set(amt)
        _c(m, RDY, vid).set(m.cursor() + _c(m, NTC, vid).get())
        m.ret(amt)

    with c.method("cancel") as m:
        vid = m.arg(0)
        m.require(_c(m, OWN, vid).get() == m.caller())
        m.require(_c(m, PND, vid).get() > 0)
        _c(m, PND, vid).set(m.const(0))
        _c(m, RDY, vid).set(m.const(0))
        m.ret(m.const(1))

    # release(vid) — after the notice, take min(pnd, res). Clamped because redemptions during the window may
    # have taken the reserve below what was announced, and making the creator restart the wait for that would
    # punish them for the exits the notice is designed to enable.
    with c.method("release") as m:
        vid = m.arg(0)
        m.require(_c(m, OWN, vid).get() == m.caller())
        pnd = m.set(_c(m, PND, vid).get(), "pnd")
        m.require(pnd > 0)
        m.require(_c(m, RDY, vid).get() > 0)
        m.require(m.cursor() + 1 > _c(m, RDY, vid).get())        # cursor >= rdy

        res = m.set(_c(m, RES, vid).get(), "res")
        # branch-free min(pnd, res): (res < pnd) is 0/1, so this selects one side without a jump. The
        # comparison is recomputed rather than parked in a temp — registers are scarcer than instructions.
        amt = m.set(res * (res < pnd) + pnd * (m.const(1) - (res < pnd)), "amt")

        _c(m, RES, vid).set(res - amt)
        _c(m, PND, vid).set(m.const(0))
        _c(m, RDY, vid).set(m.const(0))
        m.pay(m.caller(), amt * UNIT)
        m.ret(amt)

    return c.build()


ABI = {
    "open": {"args": ["vid", "asset", "supply", "notice", "units"], "value": True},
    "back": {"args": ["vid", "units"], "value": True},
    "redeem": {"args": ["vid"], "value": True},
    "announce": {"args": ["vid", "amt"]},
    "cancel": {"args": ["vid"]},
    "release": {"args": ["vid"]},
    "_view": {"maps": {"own": OWN, "ast": AST, "res": RES, "out": OUT,
                       "ntc": NTC, "pnd": PND, "rdy": RDY},
              "index": {"cnt": 0, "list": LIST}, "addr": ["own"]},
}
