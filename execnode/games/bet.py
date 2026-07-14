"""
Bet — zkVM port (doc/zk-execution-proofs.md). PARIMUTUEL sports betting with no house and no bookmaker.

WHAT "PARIMUTUEL" MEANS (plain language): all money bet on a match goes into ONE shared pot. Nobody offers
you odds and nobody takes the other side of your bet — you bet against the other bettors. When the result is
posted, everyone who picked the winning outcome splits the WHOLE pot in proportion to what they put in:

    your payout = your_stake × total_pot ÷ winning_side's_pool

That's it. If 800 was bet on Arsenal and 700 on Chelsea (pot 1500) and Arsenal wins, each Arsenal backer gets
their stake × 1500/800 ≈ 1.87×. The "odds" you see are just the live pot ratio — they move as people bet,
exactly like a racetrack tote board (that's where the word comes from: pari mutuel, "mutual bet", Paris 1867).
The contract only escrows and redistributes: it never mints, never profits, and can never owe more than the
pot it holds.

The one thing a chain can't know is the real-world result, so each market names its own RESOLVER set at
creation (up to 3 addresses, M-of-N threshold; default = the creator, 1-of-1). Bettor protections:
  · a resolver can void() a postponed match — every stake refunds 1:1;
  · past the market's deadline ANYONE can void it (a vanished resolver can't strand the pot);
  · if the posted winner had ZERO backers the market auto-voids instead of resolving to an unpayable pool.
Payouts are PULL-based (each bettor claim()s their own share) so a market scales to any number of bettors.

zkVM data model (this port): market ids are ints < 2^32. Metadata (the market title+outcome labels, source
name, event id) are STRING args — digested to field elements at the call boundary, stored as digests, and
resolved back to the original text by decode_view through the exec node's digest registry (the "hash
on-chain, text in the transaction" model). Money is tracked in UNITs of 10^4 raw NADO (stakes must be UNIT
multiples) so that stake×pot products stay inside the DIVMODW soundness window; a market's pot is capped at
2^31 UNITs (~26% of total supply). Per-user slots are alghash-keyed: slot = HASH(tag, market, [outcome,]
addr_digest) — the frontend reads them through /exec/view methods (claimable_of/stake_of/...), never by
computing slots itself.

Market fields (key = market id): 1 mk 2 no(outcomes) 3 lk(lock, epoch secs) 4 dl(deadline) 5 ds(desc digest:
  "title\\nlabel0\\n...\\nlabelN-1") 6 so(source digest) 7 ev(event digest) 8 rs(winner+1) 9 dn 10 vd
  11 tot(pot, UNITs) 12 mrc(resolver count) 13 mth(threshold) 14 mcr(creator digest)
Per-outcome boards (i < 8): pools 16+i, votes 24+i, keyed by market. Index: slot 0 count, field 40 list.
Hash slots: stk HASH(101,m,i,addr) · us HASH(102,m,addr) · cl HASH(103,m,addr) · vt HASH(104,m,addr) ·
  mres HASH(105,m,addr).
Methods: create_market(m,nout,lock,deadline,desc,source,ev,thr,r0,r1,r2) · bet(m,i)[stake] · resolve(m,i) ·
  void(m) · claim(m) · views: claimable_of(m,addr) · stake_of(m,i,addr) · total_of(m,addr) · claimed_of(m,addr).
"""
from execnode import zkvmasm

MK, NO, LK, DL, DS, SO, EV, RS, DN, VD, TOT, MRC, MTH, MCR = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14
PL_BASE, VC_BASE = 16, 24
MLIST = 40
TG_STK, TG_US, TG_CL, TG_VT, TG_RES = 101, 102, 103, 104, 105
UNIT = 10_000                     # raw NADO per pool unit (stakes must be UNIT multiples)
MAX_OUT = 8
POT_CAP = 1 << 31                 # per-market pot cap in UNITs — keeps stake×pot < 2^62 (DIVMODW-sound)

_2_32 = 1 << 32


def _sl(field):
    """asm: r4 = slot(field, m) with m in r0 (composite-int addressing)."""
    return [f"slot r4 {field} r0"]


def _mopen():
    """Market exists, not resolved, not void (uses r4/r5)."""
    return (_sl(MK) + ["sload r5 r4", "require r5"]
            + _sl(DN) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
            + _sl(VD) + ["sload r5 r4", "nez r5", "notb r5", "require r5"])


def _hash_slot(out, tag, *vals):
    """asm: out = HASH(tag, *vals) — the per-user slot derivation. Clobbers r4."""
    return [f"movi r4 {tag}", f"hash {out} <- r4 " + " ".join(vals)]


# create_market(m, nout, lock, deadline, desc, source, ev, thr, r0, r1, r2)
# ARG-on-demand register discipline: r0 = m throughout; every other arg is pulled by index when needed,
# so registers r1..r7 stay free scratch (the pattern the ARG opcode exists for).
CREATE = "\n".join(
    # m > 0 and m < 2^32 (keys must fit the composite-slot model)
    ["movi r1 0", "lt r1 r0", "require r1",
     f"movi r1 {_2_32}", "mov r2 r0", "lt r2 r1", "require r2"]
    # fresh id
    + _sl(MK) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    # nout in [2, MAX_OUT]
    + ["movi r1 1", "arg r2 r1",                                     # r2 = nout
       "movi r3 2", "lt r2 r3", "notb r2", "require r2",             # hmm: lt clobbers r2 — see below
       ]
) + "\n" + "\n".join(
    # NOTE: the block above consumed r2 in the comparison; re-load args cleanly here.
    # lock > TIME, deadline > lock
    ["movi r1 2", "arg r2 r1",                                       # lock
     "ctx r3 time", "lt r3 r2", "require r3",                        # TIME < lock
     "movi r1 3", "arg r3 r1",                                       # deadline
     "movi r1 2", "arg r5 r1",                                       # lock again
     "lt r5 r3", "require r5"]                                       # lock < deadline
    # store nout/lk/dl/ds/so/ev (each: arg -> slot store)
    + sum(([f"movi r1 {idx}", f"arg r5 r1"] + _sl(f) + ["sstore r4 r5"]
           for idx, f in ((1, NO), (2, LK), (3, DL), (4, DS), (5, SO), (6, EV))), [])
    # nout <= MAX_OUT (checked after store; revert discards)
    + ["movi r1 1", "arg r2 r1", f"movi r3 {MAX_OUT + 1}", "lt r2 r3", "require r2",
       "movi r1 1", "arg r2 r1", "movi r3 1", "lt r3 r2", "require r3"]                 # nout >= 2
    # creator
    + ["ctx r6 caller"] + _sl(MCR) + ["sstore r4 r6"]
    # resolver membership: r3 = count; for k in 8..10: v = arg k; if v != 0: mres[HASH]=1, count++
    + ["movi r3 0"]
    + sum((["movi r1 " + str(k), "arg r5 r1", "mov r2 r5", "nez r2", "jnz r2 @res" + str(k),
            "jmp @skip" + str(k), "res" + str(k) + ":"]
           + _hash_slot("r6", TG_RES, "r0", "r5")
           + ["movi r5 1", "sstore r6 r5", "movi r5 1", "add r3 r5", "skip" + str(k) + ":"]
           for k in (8, 9, 10)), [])
    # no resolver named -> the creator resolves it (count 0 -> 1)
    + ["mov r2 r3", "nez r2", "jnz r2 @have_res",
       "ctx r6 caller"] + _hash_slot("r5", TG_RES, "r0", "r6")
    + ["movi r6 1", "sstore r5 r6", "movi r3 1", "have_res:"]
    # threshold: thr==0 -> 1; require thr <= count
    + ["movi r1 7", "arg r2 r1", "mov r5 r2", "nez r5", "notb r5", "add r2 r5",         # thr += (thr==0)
       "mov r5 r2", "mov r6 r3", "movi r7 1", "add r6 r7", "lt r5 r6", "require r5"]    # thr < count+1
    + _sl(MTH) + ["sstore r4 r2"] + _sl(MRC) + ["sstore r4 r3"]
    # mark live + append to the market index
    + _sl(MK) + ["movi r5 1", "sstore r4 r5"]
    + ["movi r4 0", "sload r5 r4", f"slot r6 {MLIST} r5", "sstore r6 r0",
       "movi r3 1", "add r5 r3", "sstore r4 r5", "ret r0"])

# bet(m, outcome)[stake]: stake joins the outcome's pool. UNIT-multiple stakes; pot capped (see header).
BET = "\n".join(
    ["ctx r3 value", "movi r2 0", "lt r2 r3", "require r2",
     f"movi r5 {UNIT}", "divmod r3 r5",                              # r3 = units, r7 = remainder
     "mov r2 r7", "nez r2", "notb r2", "require r2",                 # stake % UNIT == 0
     "movi r2 0", "lt r2 r3", "require r2"]                          # units > 0
    + _mopen()
    + ["ctx r5 time"] + _sl(LK) + ["sload r6 r4", "lt r5 r6", "require r5"]      # TIME < lock
    + ["mov r5 r1"] + _sl(NO) + ["sload r6 r4", "lt r5 r6", "require r5"]        # i < nout
    # pool[i] += units  (pool slot = (PL_BASE+i)*2^32 + m, i is runtime -> MUL by 2^32)
    + [f"movi r4 {PL_BASE}", "add r4 r1", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
       "sload r5 r4", "add r5 r3", "sstore r4 r5"]
    # tot += units ; require tot < POT_CAP
    + _sl(TOT) + ["sload r5 r4", "add r5 r3", "sstore r4 r5",
                  f"movi r6 {POT_CAP}", "lt r5 r6", "require r5"]
    # stk[HASH(TG_STK, m, i, caller)] += units ; us[HASH(TG_US, m, caller)] += units
    + ["ctx r6 caller"]
    + _hash_slot("r2", TG_STK, "r0", "r1", "r6")
    + ["sload r5 r2", "add r5 r3", "sstore r2 r5"]
    + _hash_slot("r2", TG_US, "r0", "r6")
    + ["sload r5 r2", "add r5 r3", "sstore r2 r5", "ret r0"])

# resolve(m, outcome): one vote per named resolver; the first outcome to reach the market's threshold
# finalizes — as a RESOLUTION if it had backers, as an AUTO-VOID if its pool is empty (unpayable).
RESOLVE = "\n".join(
    ["ctx r6 caller"]
    + _hash_slot("r5", TG_RES, "r0", "r6")
    + ["sload r5 r5", "require r5"]                                  # caller is a resolver of THIS market
    + _mopen()
    + ["ctx r5 time"] + _sl(LK) + ["sload r6 r4", "lt r5 r6", "notb r5", "require r5"]   # TIME >= lock
    + ["mov r5 r1"] + _sl(NO) + ["sload r6 r4", "lt r5 r6", "require r5"]                # i < nout
    # one vote per resolver: vt[HASH(TG_VT,m,caller)] must be 0, then = i+1
    + ["ctx r6 caller"] + _hash_slot("r2", TG_VT, "r0", "r6")
    + ["sload r5 r2", "nez r5", "notb r5", "require r5",
       "mov r5 r1", "movi r6 1", "add r5 r6", "sstore r2 r5"]
    # vc[i]++ -> r3
    + [f"movi r4 {VC_BASE}", "add r4 r1", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
       "sload r3 r4", "movi r5 1", "add r3 r5", "sstore r4 r3"]
    # reached = vc >= mth -> r5 ; backed = pool[i] > 0 -> r6
    + _sl(MTH) + ["sload r5 r4", "mov r2 r3", "lt r2 r5", "notb r2"]                     # r2 = reached
    + [f"movi r4 {PL_BASE}", "add r4 r1", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
       "sload r6 r4", "nez r6"]                                                          # r6 = backed
    # dn = reached·backed ; vd = reached·(1-backed) ; rs = dn·(i+1)
    + ["mov r5 r2", "mul r5 r6"] + _sl(DN) + ["sstore r4 r5",
       "mov r3 r5",                                                                      # r3 = dn
       "mov r5 r6", "notb r5", "mul r5 r2"] + _sl(VD) + ["sstore r4 r5"]
    + ["mov r5 r1", "movi r6 1", "add r5 r6", "mul r5 r3"] + _sl(RS) + ["sstore r4 r5", "ret r0"])

# void(m): a resolver anytime before resolution; ANYONE once the deadline passes. Refunds via claim().
VOID = "\n".join(
    _mopen()
    + ["ctx r6 caller"] + _hash_slot("r5", TG_RES, "r0", "r6")
    + ["sload r2 r5",                                                # r2 = is-resolver
       "ctx r5 time"] + _sl(DL) + ["sload r6 r4", "lt r5 r6", "notb r5",   # r5 = TIME >= deadline
       "add r2 r5", "nez r2", "require r2"]
    + _sl(VD) + ["movi r5 1", "sstore r4 r5", "ret r0"])

# The payout expression shared by claim() and the claimable_of view. Leaves raw NADO in r3.
#   void:     r3 = us · UNIT
#   resolved: r3 = stk[winner] · tot // pool[winner] · UNIT   (parimutuel pro-rata, one DIVMODW)
# `caller_reg` holds the bettor's digest.
def _payout(caller_reg):
    return (
        _sl(VD) + ["sload r2 r4", "jnz r2 @voided"]
        # winner w = rs - 1 -> r5
        + _sl(RS) + ["sload r5 r4", "movi r6 1", "sub r5 r6"]
        # stk = HASH(TG_STK, m, w, caller) -> r3
        + _hash_slot("r2", TG_STK, "r0", "r5", caller_reg)
        + ["sload r3 r2"]
        # r3 = stk·tot // pool[w]
        + _sl(TOT) + ["sload r6 r4", "mul r3 r6"]
        + [f"movi r4 {PL_BASE}", "add r4 r5", f"movi r6 {_2_32}", "mul r4 r6", "add r4 r0",
           "sload r6 r4", "divmodw r3 r6", "jmp @units"]
        + ["voided:"] + _hash_slot("r2", TG_US, "r0", caller_reg) + ["sload r3 r2"]
        + ["units:", f"movi r6 {UNIT}", "mul r3 r6"])

CLAIM = "\n".join(
    # settled (resolved or void)?
    _sl(DN) + ["sload r5 r4"] + _sl(VD) + ["sload r6 r4", "add r5 r6", "nez r5", "require r5"]
    # not yet claimed
    + ["ctx r1 caller"] + _hash_slot("r2", TG_CL, "r0", "r1")
    + ["sload r5 r2", "nez r5", "notb r5", "require r5"]
    + _payout("r1")
    + ["movi r5 0", "lt r5 r3", "require r5"]                        # something to pay
    + _hash_slot("r2", TG_CL, "r0", "r1") + ["movi r5 1", "sstore r2 r5"]
    + ["pay r1 r3", "ret r3"])

# ---- read-only views (the frontend's window into hash-keyed slots, via /exec/view) ----------------
# claimable_of(m, addr): the raw amount addr could claim right now (0 if unsettled/claimed/nothing).
CLAIMABLE_OF = "\n".join(
    _sl(DN) + ["sload r5 r4"] + _sl(VD) + ["sload r6 r4", "add r5 r6", "nez r5", "jnz r5 @go",
               "movi r3 0", "ret r3", "go:"]
    + _hash_slot("r2", TG_CL, "r0", "r1")
    + ["sload r5 r2", "nez r5", "notb r5", "jnz r5 @calc", "movi r3 0", "ret r3", "calc:"]
    + _payout("r1") + ["ret r3"])

STAKE_OF = "\n".join(_hash_slot("r3", TG_STK, "r0", "r1", "r2")
                     + ["sload r3 r3", f"movi r5 {UNIT}", "mul r3 r5", "ret r3"])
TOTAL_OF = "\n".join(_hash_slot("r3", TG_US, "r0", "r1")
                     + ["sload r3 r3", f"movi r5 {UNIT}", "mul r3 r5", "ret r3"])
CLAIMED_OF = "\n".join(_hash_slot("r3", TG_CL, "r0", "r1") + ["sload r3 r3", "ret r3"])
VOTE_OF = "\n".join(_hash_slot("r3", TG_VT, "r0", "r1") + ["sload r3 r3", "ret r3"])
RESOLVER_OF = "\n".join(_hash_slot("r3", TG_RES, "r0", "r1") + ["sload r3 r3", "ret r3"])

SRC = {"create_market": CREATE, "bet": BET, "resolve": RESOLVE, "void": VOID, "claim": CLAIM,
       "claimable_of": CLAIMABLE_OF, "stake_of": STAKE_OF, "total_of": TOTAL_OF,
       "claimed_of": CLAIMED_OF, "vote_of": VOTE_OF, "resolver_of": RESOLVER_OF}

ABI = {
    "create_market": {"args": ["marketId", "outcomes", "lock", "deadline", "desc", "source", "event",
                               "threshold", "resolver1", "resolver2", "resolver3"]},
    "bet": {"args": ["marketId", "outcome"], "value": True},
    "resolve": {"args": ["marketId", "outcome"]},
    "void": {"args": ["marketId"]},
    "claim": {"args": ["marketId"]},
    "claimable_of": {"args": ["marketId", "addr"]},
    "stake_of": {"args": ["marketId", "outcome", "addr"]},
    "total_of": {"args": ["marketId", "addr"]},
    "claimed_of": {"args": ["marketId", "addr"]},
    "vote_of": {"args": ["marketId", "addr"]},
    "resolver_of": {"args": ["marketId", "addr"]},
    "_view": {
        "maps": {"mk": {"field": MK, "index": "markets"}, "no": {"field": NO, "index": "markets"},
                 "lk": {"field": LK, "index": "markets"}, "dl": {"field": DL, "index": "markets"},
                 "ds": {"field": DS, "index": "markets"}, "so": {"field": SO, "index": "markets"},
                 "ev": {"field": EV, "index": "markets"}, "rs": {"field": RS, "index": "markets"},
                 "dn": {"field": DN, "index": "markets"}, "vd": {"field": VD, "index": "markets"},
                 "tot": {"field": TOT, "index": "markets"}, "mrc": {"field": MRC, "index": "markets"},
                 "mth": {"field": MTH, "index": "markets"}, "mcr": {"field": MCR, "index": "markets"}},
        "indexes": {"markets": {"cnt": 0, "list": MLIST}},
        "addr": ["ds", "so", "ev", "mcr"],
        "board": {"name": "pl", "base": PL_BASE, "cells": MAX_OUT, "stride": MAX_OUT, "index": "markets"},
    },
}
ABI["_view"]["board2"] = {"name": "vc", "base": VC_BASE, "cells": MAX_OUT, "stride": MAX_OUT,
                          "index": "markets"}


def build():
    return zkvmasm.assemble_contract(SRC)
