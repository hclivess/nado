"""
Hamster Racing — zkVM game (doc/zk-execution-proofs.md). A provably-fair, PARIMUTUEL race between six
hamsters whose speed genes AND whole run are decided by future L1 block hashes — no house, no bookmaker,
no oracle. (Inspired by the old "hamster racing" bets on crypto Twitter, but here the hamsters are on-chain.)

HOW A RACE RUNS
  1. open(race)                — anyone starts a race. It pins three future L1 heights off the current tip:
        gh = cursor + GENE_DELAY        the GENE block: once mined, each hamster's SPEED (1..8) is fixed and
                                        VISIBLE (derived from BLOCKHASH(gh)) — the "form" you bet on.
        lk = gh + BET_BLOCKS            betting CLOSES at this height.
        fh = lk + RACE_LEN              the last RACE block.
  2. bet(race, hamster)[stake] — while gh <= cursor < lk (genes are locked & shown, betting still open),
        stake real NADO on one of the six hamsters. All stakes on a race join ONE pot.
  3. settle(race)              — once cursor >= fh (every race block exists), anyone settles. For each of the
        RACE_LEN race blocks (lk+1..fh) each hamster advances by  step = HASH(BLOCKHASH(b), race, h) %
        (speed_h + STEP_BASE); the hamster with the greatest total distance WINS (ties → lowest lane).
  4. claim(race)              — winning backers split the WHOLE pot pro-rata:
        your payout = your_stake × pot ÷ winning_hamster's_pool          (one DIVMODW, parimutuel)
     Pull-based, so a race scales to any number of bettors.

FAIRNESS. Genes come from a block mined BEFORE betting closes (public, re-derivable by anyone); the run comes
from blocks mined AFTER betting closes (unknown to every bettor). So knowing the genes never tells you the
winner — you're reading form + the live tote (the pool ratios), exactly like a racetrack. The contract only
escrows and redistributes: it never mints, never profits, never owes more than the pot it holds.

PROTECTIONS. If the chain-picked winner had ZERO backers the PARIMUTUEL pot is unpayable, so settle AUTO-VOIDS
the race (every stake refunds 1:1 via claim). A race traded only on the BOOK has no such pot and settles
normally, so the bank market still pays. And if a race is never settled within the safety window it can be
void()ed by anyone past fh + VOID_AFTER, so a pot can never be stranded.

zkVM data model: race ids are ints < 2^32. Money is tracked in UNITs of 10^4 raw NADO (stakes must be UNIT
multiples) so stake×pot stays inside the DIVMODW soundness window; a race's pot caps at 2^31 UNITs. Per-user
positions live in alghash-keyed slots the frontend reads via /exec/view (claimable_of / stake_of / total_of).

Race fields (key = race id): 1 ra(exists=1)  2 gh(gene height)  3 lk(bet-close height)  4 fh(finish height)
  5 tot(pot, UNITs)  6 sd(settled)  7 wn(winner lane +1)  8 vd(void)  9 bc(distinct bettors)
lk/fh are 0 until the SECOND distinct bettor bets — the countdown starts then, so a race can't run (and
can't be won by default) with one player. See BET.
Per-hamster boards (lane i < 6): pools 16+i, final distances 24+i, keyed by race. Index: slot 0 count, field 40 list.
Hash slots: stk HASH(101,race,lane,addr) · us HASH(102,race,addr) · cl HASH(103,race,addr).
Methods: open(race) · bet(race,lane)[stake] · settle(race) · claim(race) · void(race) ·
  views: claimable_of(race,addr) · stake_of(race,lane,addr) · total_of(race,addr) · claimed_of(race,addr).
"""
from execnode import zkvmasm
from execnode.games import _lib

RA, GH, LK, FH, TOT, SD, WN, VD = 1, 2, 3, 4, 5, 6, 7, 8
BC = 9                                              # distinct bettors so far — the countdown starts at 2
PL_BASE, DI_BASE = 16, 24
RLIST = 40
TG_STK, TG_US, TG_CL = 101, 102, 103
# --- FIXED-ODDS BOOK (play against a bank, no waiting for a second punter) ---
BK, BR, BS, BD = 10, 11, 12, 13        # bank digest · bankroll(UNITs) · stakes taken(UNITs) · swept flag
OD_BASE = 30                            # 30..35: quoted odds per lane, in PERCENT (100 = 1.00x)
BP_BASE = 41                            # 41..46: per-lane TOTAL committed payout (UNITs)
TG_BSTK, TG_BPAY, TG_BCL = 104, 105, 106
ODDS_CAP = 100_000                      # 1000x — a sane bound so odds*stake stays far inside the field
# --- free Daily Derby board (provable practice, faucet-rewarded — doc/provable-practice.md) ---
DCNT_SLOT, ECNT_SLOT = 2, 3                         # bare index-count slots (slot 0 = races count)
E_DAY, E_ADDR, E_SCORE, E_N = 50, 51, 52, 53       # per-entry fields
E_TS = 54                                          # UTC-seconds post-time (board shows day + time)
ELIST, EW_BASE = 60, 64                            # entry-id index; packed picks live at EW_BASE (1 word)
A_H, A_V, DLIST = 70, 71, 72                       # day anchor: pinned height / resolved hash / day index
DAILY_WORDS = 1

NH = 6                      # six lanes — a fixed field keeps settle fully unrolled (no variable loop)
GENE_DELAY = 2             # blocks from open() to the gene block (genes lock ~12s later)
BET_BLOCKS = 50           # betting window once the countdown starts (~5 min). The SECOND distinct bettor
                          # starts this clock — it is a COUNTDOWN, not a start gun: everyone else still has
                          # the whole window to join the same race. At 20 blocks (~2 min) that window was so
                          # short it read as "the second bet starts the race", which is the opposite of the
                          # intent. Races already counting down keep their stored lk/fh, so nothing in
                          # flight changes.
RACE_LEN = 10            # race blocks — each block's hash advances every hamster by its own step; ~60s at 6s/block
GENE_SPREAD = 8          # speed = 1 + gene % GENE_SPREAD  -> 1..8
STEP_BASE = 6            # per-block step = roll % (speed + STEP_BASE)
UNIT = 10_000            # raw NADO per pool unit (stakes must be UNIT multiples)
POT_CAP = 1 << 31        # per-race pot cap in UNITs — keeps stake×pot DIVMODW-sound
_2_32 = 1 << 32


def _sl(field):
    """asm: r4 = slot(field, race) with race in r0."""
    return [f"slot r4 {field} r0"]


def _hash_slot(out, tag, *vals):
    """asm: out = HASH(tag, *vals) — a per-user slot address. Clobbers r4."""
    return [f"movi r4 {tag}", f"hash {out} <- r4 " + " ".join(vals)]


def _race_open():
    """Race exists, not settled, not void (uses r4/r5)."""
    return (_sl(RA) + ["sload r5 r4", "require r5"]
            + _sl(SD) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
            + _sl(VD) + ["sload r5 r4", "nez r5", "notb r5", "require r5"])


# open(race): pin the GENE height off the current tip; permissionless, value-free. lk/fh stay 0 — the
# betting countdown is started by the second distinct bettor (BET), not by opening the race, so an empty
# or one-player race never runs down a clock nobody is racing against.
OPEN = "\n".join(
    ["movi r1 0", "lt r1 r0", "require r1",                              # race > 0
     f"movi r1 {_2_32}", "mov r2 r0", "lt r2 r1", "require r2"]         # race < 2^32
    + _sl(RA) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]      # fresh id
    # gh = cursor + GENE_DELAY
    + ["ctx r5 cursor", f"movi r6 {GENE_DELAY}", "add r5 r6"] + _sl(GH) + ["sstore r4 r5"]
    # mark live + append to the race index
    + _sl(RA) + ["movi r5 1", "sstore r4 r5"]
    + ["movi r4 0", "sload r5 r4", f"slot r6 {RLIST} r5", "sstore r6 r0",
       "movi r3 1", "add r5 r3", "sstore r4 r5", "ret r0"])

# bet(race, lane)[stake]: stake joins the lane's pool while genes are locked and betting is open.
BET = "\n".join(
    ["ctx r3 value", "movi r2 0", "lt r2 r3", "require r2",
     f"movi r5 {UNIT}", "divmod r3 r5",                                 # r3 = units, r7 = remainder
     "mov r2 r7", "nez r2", "notb r2", "require r2",                    # stake % UNIT == 0
     "movi r2 0", "lt r2 r3", "require r2"]                             # units > 0
    + _race_open()
    # genes locked (cursor >= gh)
    + ["ctx r5 cursor"] + _sl(GH) + ["sload r6 r4", "lt r5 r6", "notb r5", "require r5"]
    # betting open: while lk == 0 the countdown has not started (fewer than 2 bettors) and bets are always
    # accepted; once it has started the usual cursor < lk window applies.
    + _sl(LK) + ["sload r6 r4", "mov r2 r6", "nez r2", "notb r2", "jnz r2 @betopen",
                 "ctx r5 cursor", "lt r5 r6", "require r5",
                 "betopen:"]
    # lane in [0, NH)
    + ["mov r5 r1", f"movi r6 {NH}", "lt r5 r6", "require r5"]
    # pool[lane] += units   (slot = (PL_BASE+lane)*2^32 + race, lane is runtime -> MUL)
    + [f"movi r4 {PL_BASE}", "add r4 r1", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
       "sload r5 r4", "add r5 r3", "sstore r4 r5"]
    # tot += units ; require tot < POT_CAP
    + _sl(TOT) + ["sload r5 r4", "add r5 r3", "sstore r4 r5",
                  f"movi r6 {POT_CAP}", "lt r5 r6", "require r5"]
    # stk[HASH(TG_STK, race, lane, caller)] += units ; us[HASH(TG_US, race, caller)] += units
    + ["ctx r6 caller"]
    + _hash_slot("r2", TG_STK, "r0", "r1", "r6")
    + ["sload r5 r2", "add r5 r3", "sstore r2 r5"]
    + _hash_slot("r2", TG_US, "r0", "r6")
    # us += units, but read the PRIOR total first: 0 means this caller is a NEW distinct bettor. (r1 held
    # the lane and is free from here on.)
    + ["sload r5 r2", "mov r1 r5", "nez r1", "notb r1",                 # r1 = (prior == 0) -> new bettor
       "add r5 r3", "sstore r2 r5",
       "jnz r1 @newbettor", "jmp @betdone", "newbettor:"]
    # bc += 1; the SECOND distinct bettor starts the countdown: lk = cursor + BET_BLOCKS, fh = lk + RACE_LEN.
    # Guarded on lk == 0 so a third/fourth bettor can never restart (and extend) a running clock.
    + _sl(BC) + ["sload r5 r4", "movi r6 1", "add r5 r6", "sstore r4 r5",
                 "movi r6 2", "lt r5 r6", "jnz r5 @betdone"]            # bc < 2 -> nothing to start yet
    + _sl(LK) + ["sload r5 r4", "nez r5", "jnz r5 @betdone"]            # already running
    + ["ctx r5 cursor", f"movi r6 {BET_BLOCKS}", "add r5 r6"] + _sl(LK) + ["sstore r4 r5"]
    + [f"movi r6 {RACE_LEN}", "add r5 r6"] + _sl(FH) + ["sstore r4 r5"]
    + ["betdone:", "ret r0"])


def _settle():
    """settle(race): derive every hamster's total distance from the block hashes, pick the winner (auto-void
    if the winner had no backers), record final distances. Fully unrolled over NH lanes × RACE_LEN blocks."""
    L = _race_open()
    # all race blocks must exist: cursor >= fh
    # fh != 0 FIRST: an unstarted clock stores fh = 0, and "cursor >= 0" would otherwise settle a race that
    # never ran. (r6 must survive the check, so the zero test goes through r2.)
    L += (["ctx r5 cursor"] + _sl(FH)
          + ["sload r6 r4", "mov r2 r6", "nez r2", "require r2",
             "lt r5 r6", "notb r5", "require r5"])
    # Phase A — per lane h: speed from BLOCKHASH(gh), distance = Σ step over the race blocks -> DI[h]
    for h in range(NH):
        # speed_h -> r3
        L += _sl(GH) + ["sload r5 r4", "bhash r6 r5",              # r6 = BLOCKHASH(gene block)
                        f"movi r5 {h}", "hash r6 <- r6 r5", "lo32 r6",
                        f"movi r5 {GENE_SPREAD}", "rem r6 r5", "movi r5 1", "add r6 r5", "mov r3 r6"]
        L += ["movi r2 0"]                                          # total distance accumulator
        for bi in range(1, RACE_LEN + 1):
            L += (_sl(LK) + ["sload r5 r4", f"movi r6 {bi}", "add r5 r6", "bhash r6 r5",   # r6 = BLOCKHASH(lk+bi)
                             f"movi r5 {h}", "hash r6 <- r6 r0 r5", "lo32 r6",             # r6 = roll(block,race,lane)
                             "mov r5 r3", f"movi r4 {STEP_BASE}", "add r5 r4", "rem r6 r5", # r6 = roll % (speed+base)
                             "add r2 r6"])                                                  # distance += step
        L += [f"slot r4 {DI_BASE + h} r0", "sstore r4 r2"]         # DI[h] = total distance
    # Phase B — argmax over DI[0..NH-1] (strict > keeps the lowest lane on a tie) -> r2 = winning lane, r1 = best
    L += ["movi r1 0", "movi r2 0"]
    for h in range(NH):
        L += [f"slot r4 {DI_BASE + h} r0", "sload r5 r4",
              "mov r6 r1", "lt r6 r5", f"jnz r6 @better{h}", f"jmp @next{h}",
              f"better{h}:", "mov r1 r5", f"movi r2 {h}", f"next{h}:"]
    # AUTO-VOID: a parimutuel pot whose winning lane has no backers is unpayable, so the race voids and
    # every stake refunds. But that must NOT fire when there is no parimutuel pot at all — a race can be
    # traded purely on the BOOK (bank vs punters), and voiding it would cancel a market that is perfectly
    # payable. So: vd = (pot > 0) AND (pool[winner] == 0). Both terms are 0/1, so mul is the AND.
    L += [f"movi r4 {PL_BASE}", "add r4 r2", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
          "sload r5 r4", "nez r5", "notb r5"]                        # r5 = winner pool is empty
    L += _sl(TOT) + ["sload r6 r4", "nez r6", "mul r5 r6"]           # AND there was a pot to strand
    L += _sl(VD) + ["sstore r4 r5"]
    # wn = winner + 1 ; sd = 1
    L += ["mov r5 r2", "movi r6 1", "add r5 r6"] + _sl(WN) + ["sstore r4 r5"]
    L += _sl(SD) + ["movi r5 1", "sstore r4 r5", "ret r0"]
    return L


SETTLE = "\n".join(_settle())

# void(race): a safety refund path — anyone, once the race is stale and still unsettled.
VOID_AFTER = 20000
STALE_AFTER = 600        # a race that never drew a 2nd bettor: refundable ~1h after the gene lock
VOID = "\n".join(
    _sl(RA) + ["sload r5 r4", "require r5"]
    + _sl(SD) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    + _sl(VD) + ["sload r5 r4", "nez r5", "notb r5", "require r5"]
    # Two deadlines, because a race whose countdown never started has no finish height to count from. With
    # the clock running: fh + VOID_AFTER. Never started (fh == 0): gh + STALE_AFTER — a lone bettor gets
    # their stake back in about an hour instead of being stranded waiting for a second player forever.
    + ["ctx r5 cursor"] + _sl(FH) + ["sload r6 r4", "mov r2 r6", "nez r2", "jnz r2 @fhset"]
    + _sl(GH) + ["sload r6 r4", f"movi r3 {STALE_AFTER}", "add r6 r3", "jmp @voidchk"]
    + ["fhset:", f"movi r3 {VOID_AFTER}", "add r6 r3"]
    + ["voidchk:", "lt r6 r5", "require r6"]                          # cursor > deadline
    + _sl(VD) + ["movi r5 1", "sstore r4 r5", "ret r0"])


# The payout expression shared by claim() and claimable_of. Leaves raw NADO in r3. `caller_reg` = bettor digest.
#   void:     r3 = us · UNIT
#   settled:  r3 = stk[winner] · tot // pool[winner] · UNIT
def _payout(caller_reg):
    return (
        _sl(VD) + ["sload r2 r4", "jnz r2 @voided"]
        # winner lane w = wn - 1 -> r5
        + _sl(WN) + ["sload r5 r4", "movi r6 1", "sub r5 r6"]
        # stk = HASH(TG_STK, race, w, caller) -> r3
        + _hash_slot("r2", TG_STK, "r0", "r5", caller_reg)
        + ["sload r3 r2"]
        # r3 = stk · tot // pool[w]
        + _sl(TOT) + ["sload r6 r4", "mul r3 r6"]
        + [f"movi r4 {PL_BASE}", "add r4 r5", f"movi r6 {_2_32}", "mul r4 r6", "add r4 r0",
           "sload r6 r4", "divmodw r3 r6", "jmp @units"]
        + ["voided:"] + _hash_slot("r2", TG_US, "r0", caller_reg) + ["sload r3 r2"]
        + ["units:", f"movi r6 {UNIT}", "mul r3 r6"])

CLAIM = "\n".join(
    # settled (won or void)?
    _sl(SD) + ["sload r5 r4"] + _sl(VD) + ["sload r6 r4", "add r5 r6", "nez r5", "require r5"]
    # not yet claimed
    + ["ctx r1 caller"] + _hash_slot("r2", TG_CL, "r0", "r1")
    + ["sload r5 r2", "nez r5", "notb r5", "require r5"]
    + _payout("r1")
    + ["movi r5 0", "lt r5 r3", "require r5"]                        # something to pay
    + _hash_slot("r2", TG_CL, "r0", "r1") + ["movi r5 1", "sstore r2 r5"]
    + ["pay r1 r3", "ret r3"])

# ---- read-only views ------------------------------------------------------------------------------
CLAIMABLE_OF = "\n".join(
    _sl(SD) + ["sload r5 r4"] + _sl(VD) + ["sload r6 r4", "add r5 r6", "nez r5", "jnz r5 @go",
               "movi r3 0", "ret r3", "go:"]
    + _hash_slot("r2", TG_CL, "r0", "r1")
    + ["sload r5 r2", "nez r5", "notb r5", "jnz r5 @calc", "movi r3 0", "ret r3", "calc:"]
    + _payout("r1") + ["ret r3"])

STAKE_OF = "\n".join(_hash_slot("r3", TG_STK, "r0", "r1", "r2")
                     + ["sload r3 r3", f"movi r5 {UNIT}", "mul r3 r5", "ret r3"])
TOTAL_OF = "\n".join(_hash_slot("r3", TG_US, "r0", "r1")
                     + ["sload r3 r3", f"movi r5 {UNIT}", "mul r3 r5", "ret r3"])
CLAIMED_OF = "\n".join(_hash_slot("r3", TG_CL, "r0", "r1") + ["sload r3 r3", "ret r3"])

# ---- free Daily Derby: provable off-chain solo run + faucet rewards (static/hamster-daily.js) -----
# post(day, score, n, w0): records the packed picks; every verifier REPLAYS the run and drops any claim whose
# replay doesn't reproduce the score (the trust is reproducibility, not a signature). anchor(day) pins the
# day's grind-proof seed on-chain. Both value-free; the faucet distributor pays yesterday's top placers.
POST = _lib.daily_post(ECNT_SLOT, E_DAY, E_ADDR, E_SCORE, E_N, ELIST, EW_BASE, DAILY_WORDS, max_n=8, max_score=200000, e_ts=E_TS)
ANCHOR = _lib.daily_anchor(A_H, A_V, DCNT_SLOT, DLIST)

# ---- FIXED-ODDS BOOK ------------------------------------------------------------------------------
# The parimutuel race needs a crowd: your money is only matched by other punters, so a lone player waits.
# A BOOK fixes that by putting a bank on the other side — it posts a bankroll, quotes a price per lane,
# and anyone can back a hamster immediately at that price. Both markets run on the SAME race and the same
# block-hash result; they only differ in who your counterparty is.
#
# The bank is NOT the house in the "trust us" sense: it can lose. Solvency is enforced per bet — after
# every stake the contract requires this lane's TOTAL committed payout to be covered by bankroll + all
# stakes taken (only one lane can win, so that is exactly the worst case) — and the quoted odds are public
# on-chain, so the client can show the fair price beside them and let a player see the margin they accept.

# book(race)[value]: post (or top up) the bankroll. First caller becomes the bank; only they may add more.
BOOK = "\n".join(
    ["ctx r3 value", "movi r2 0", "lt r2 r3", "require r2",
     f"movi r5 {UNIT}", "divmod r3 r5",
     "mov r2 r7", "nez r2", "notb r2", "require r2",                 # value % UNIT == 0
     "movi r2 0", "lt r2 r3", "require r2"]                          # units > 0
    + _race_open()
    + ["ctx r6 caller"]
    + _sl(BK) + ["sload r5 r4", "mov r2 r5", "nez r2", "notb r2", "jnz r2 @setbank",
                 "eq r5 r6", "require r5", "jmp @addroll",           # a bank exists -> must be the caller
                 "setbank:"]
    + _sl(BK) + ["sstore r4 r6", "addroll:"]
    + _sl(BR) + ["sload r5 r4", "add r5 r3", "sstore r4 r5", "ret r0"])

# quote(race, lane, odds): the bank's price for one lane, in percent (250 = 2.5x). Bank only, and only
# while the race is still open — a price can be moved as the book fills, but never after the off.
QUOTE = "\n".join(
    _race_open()
    + ["ctx r6 caller"]
    + _sl(BK) + ["sload r5 r4", "mov r3 r5", "nez r3", "require r3",  # a book exists
                 "eq r5 r6", "require r5"]                            # caller is the bank
    + ["mov r5 r1", f"movi r3 {NH}", "lt r5 r3", "require r5"]        # lane in range
    + ["movi r5 100", "lt r5 r2", "require r5",                       # odds > 1.00x
       f"movi r5 {ODDS_CAP}", "mov r3 r2", "lt r3 r5", "require r3"]  # and sane
    + [f"movi r4 {OD_BASE}", "add r4 r1", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
       "sstore r4 r2", "ret r0"])

# back(race, lane)[stake]: take the bank's price. Locks YOUR payout at the odds quoted right now, so a
# later re-quote cannot change what you are owed.
BACK = "\n".join(
    ["ctx r3 value", "movi r2 0", "lt r2 r3", "require r2",
     f"movi r5 {UNIT}", "divmod r3 r5",
     "mov r2 r7", "nez r2", "notb r2", "require r2",
     "movi r2 0", "lt r2 r3", "require r2"]                          # r3 = stake units
    + _race_open()
    # genes must be locked: the price only means something once the speeds are public
    + ["ctx r5 cursor"] + _sl(GH) + ["sload r6 r4", "lt r5 r6", "notb r5", "require r5"]
    # betting open (lk == 0 means the clock has not started yet)
    + _sl(LK) + ["sload r6 r4", "mov r2 r6", "nez r2", "notb r2", "jnz r2 @bopen",
                 "ctx r5 cursor", "lt r5 r6", "require r5", "bopen:"]
    + ["mov r5 r1", f"movi r6 {NH}", "lt r5 r6", "require r5"]        # lane in range
    # payout = stake * odds / 100, at the CURRENT quote
    + [f"movi r4 {OD_BASE}", "add r4 r1", f"movi r5 {_2_32}", "mul r4 r5", "add r4 r0",
       "sload r6 r4", "movi r5 100", "lt r5 r6", "require r5",        # lane must be priced
       "mov r2 r3", "mul r2 r6", "movi r5 100", "divmod r2 r5",       # r2 = payout units
       "movi r5 0", "lt r5 r2", "require r5"]
    # SOLVENCY, checked on every bet: this lane's total payout must be covered by bankroll + all stakes.
    # Only one lane can win, so covering each lane separately covers every outcome.
    + _sl(BS) + ["sload r5 r4", "add r5 r3", "sstore r4 r5"]          # r5 = stakes after this one
    + [f"movi r4 {BP_BASE}", "add r4 r1", f"movi r6 {_2_32}", "mul r4 r6", "add r4 r0",
       "sload r6 r4", "add r6 r2", "sstore r4 r6"]                    # r6 = this lane's payout after this
    + _sl(BR) + ["sload r4 r4", "add r4 r5", "movi r5 1", "add r4 r5",
                 "lt r6 r4", "require r6"]                            # lanePayout <= bankroll + stakes
    # per-punter record: stake and the payout locked at this price
    + ["ctx r5 caller", f"movi r4 {TG_BSTK}", "hash r6 <- r4 r0 r1 r5",
       "sload r4 r6", "add r4 r3", "sstore r6 r4",
       "ctx r5 caller", f"movi r4 {TG_BPAY}", "hash r6 <- r4 r0 r1 r5",
       "sload r4 r6", "add r4 r2", "sstore r6 r4"]
    # THE POINT OF ALL THIS: one backed bet starts the race. With a bank on the other side there is nobody
    # left to wait for, so a lone player is never parked in front of a clock that will not start.
    + _sl(LK) + ["sload r5 r4", "nez r5", "jnz r5 @bdone"]
    + ["ctx r5 cursor", f"movi r6 {BET_BLOCKS}", "add r5 r6"] + _sl(LK) + ["sstore r4 r5"]
    + [f"movi r6 {RACE_LEN}", "add r5 r6"] + _sl(FH) + ["sstore r4 r5"]
    + ["bdone:", "ret r0"])

# bclaim(race): a punter collects. Settled -> the payout locked on the winning lane; void -> every stake back.
BCLAIM = "\n".join(
    _sl(SD) + ["sload r5 r4"] + _sl(VD) + ["sload r6 r4", "add r5 r6", "nez r5", "require r5"]
    + ["ctx r1 caller", f"movi r4 {TG_BCL}", "hash r2 <- r4 r0 r1",
       "sload r5 r2", "nez r5", "notb r5", "require r5",              # not already collected
       "movi r5 1", "sstore r2 r5"]
    # BRANCH ON WHETHER THE RACE RAN, not on the void flag. A race can be auto-voided because the
    # PARIMUTUEL pot was unpayable (winner had no pool backers) while still having a perfectly good
    # result — settle recorded the winner. Refunding the book there would hand punters a free option:
    # back a lane, and if some unbacked lane happens to win, get the stake back instead of losing it.
    # So the book pays on the result whenever sd is set, and only refunds when there is NO result at
    # all (the void() timeout path, where the race never settled).
    + _sl(SD) + ["sload r2 r4", "nez r2", "notb r2", "jnz r2 @bvoid"]
    + _sl(WN) + ["sload r5 r4", "movi r6 1", "sub r5 r6"]             # r5 = winning lane
    + ["ctx r6 caller", f"movi r4 {TG_BPAY}", "hash r2 <- r4 r0 r5 r6", "sload r3 r2", "jmp @bpay"]
    + ["bvoid:", "movi r3 0"]
    + [op for L in range(NH) for op in
       ["ctx r6 caller", f"movi r4 {TG_BSTK}", f"movi r5 {L}", "hash r2 <- r4 r0 r5 r6",
        "sload r5 r2", "add r3 r5"]]
    + ["bpay:", "movi r5 0", "lt r5 r3", "require r5",
       f"movi r6 {UNIT}", "mul r3 r6", "ctx r1 caller", "pay r1 r3", "ret r3"])

# bsweep(race): the bank takes back what the result left it — bankroll plus every losing stake, minus what
# the winning lane owes. On a void the punters reclaim their own stakes, so the bank simply gets its roll.
BSWEEP = "\n".join(
    _sl(SD) + ["sload r5 r4"] + _sl(VD) + ["sload r6 r4", "add r5 r6", "nez r5", "require r5"]
    + ["ctx r6 caller"]
    + _sl(BK) + ["sload r5 r4", "mov r3 r5", "nez r3", "require r3", "eq r5 r6", "require r5"]
    + _sl(BD) + ["sload r5 r4", "nez r5", "notb r5", "require r5",    # once only
                 "movi r5 1", "sstore r4 r5"]
    + _sl(BR) + ["sload r3 r4"]                                       # r3 = bankroll
    + _sl(SD) + ["sload r2 r4", "nez r2", "notb r2", "jnz r2 @bswvoid"]   # no result -> just the roll back
    + _sl(BS) + ["sload r5 r4", "add r3 r5"]                          # + every stake taken
    + _sl(WN) + ["sload r5 r4", "movi r6 1", "sub r5 r6"]             # winning lane
    + [f"movi r4 {BP_BASE}", "add r4 r5", f"movi r6 {_2_32}", "mul r4 r6", "add r4 r0",
       "sload r6 r4", "sub r3 r6"]                                    # - what that lane is owed
    + ["bswvoid:", "movi r5 0", "lt r5 r3", "require r5",
       f"movi r6 {UNIT}", "mul r3 r6", "ctx r1 caller", "pay r1 r3", "ret r3"])


SRC = {"open": OPEN, "bet": BET, "settle": SETTLE, "claim": CLAIM, "void": VOID,
       "book": BOOK, "quote": QUOTE, "back": BACK, "bclaim": BCLAIM, "bsweep": BSWEEP,
       "claimable_of": CLAIMABLE_OF, "stake_of": STAKE_OF, "total_of": TOTAL_OF, "claimed_of": CLAIMED_OF,
       "post": POST, "anchor": ANCHOR}

ABI = {
    "open": {"args": ["raceId"]},
    "bet": {"args": ["raceId", "lane"], "value": True},
    "settle": {"args": ["raceId"]},
    "claim": {"args": ["raceId"]},
    "void": {"args": ["raceId"]},
    "book": {"args": ["raceId"], "value": True},
    "quote": {"args": ["raceId", "lane", "odds"]},
    "back": {"args": ["raceId", "lane"], "value": True},
    "bclaim": {"args": ["raceId"]},
    "bsweep": {"args": ["raceId"]},
    "claimable_of": {"args": ["raceId", "addr"]},
    "stake_of": {"args": ["raceId", "lane", "addr"]},
    "total_of": {"args": ["raceId", "addr"]},
    "claimed_of": {"args": ["raceId", "addr"]},
    "post": {"args": _lib.daily_post_abi(DAILY_WORDS)},
    "anchor": {"args": ["day"]},
    "_view": {
        "maps": {"ra": {"field": RA, "index": "races"}, "gh": {"field": GH, "index": "races"},
                 "lk": {"field": LK, "index": "races"}, "fh": {"field": FH, "index": "races"},
                 "tot": {"field": TOT, "index": "races"}, "sd": {"field": SD, "index": "races"},
                 "wn": {"field": WN, "index": "races"}, "vd": {"field": VD, "index": "races"},
                 "bc": {"field": BC, "index": "races"},
                 "bk": {"field": BK, "index": "races"}, "br": {"field": BR, "index": "races"},
                 "bs": {"field": BS, "index": "races"}, "bd": {"field": BD, "index": "races"},
                 # Daily Derby board: per-entry fields + the day anchor
                 "eday": {"field": E_DAY, "index": "entries"}, "eaddr": {"field": E_ADDR, "index": "entries"},
                 "escore": {"field": E_SCORE, "index": "entries"}, "en": {"field": E_N, "index": "entries"},
                 "ets": {"field": E_TS, "index": "entries"},
                 "ew0": {"field": EW_BASE, "index": "entries"},
                 "ah": {"field": A_H, "index": "days"}, "av": {"field": A_V, "index": "days"}},
        "indexes": {"races": {"cnt": 0, "list": RLIST}, "entries": {"cnt": ECNT_SLOT, "list": ELIST},
                    "days": {"cnt": DCNT_SLOT, "list": DLIST}},
        "board": {"name": "pl", "base": PL_BASE, "cells": NH, "stride": NH, "index": "races"},
        "addr": ["eaddr", "bk"],
    },
}
ABI["_view"]["board2"] = {"name": "di", "base": DI_BASE, "cells": NH, "stride": NH, "index": "races"}
# the BOOK's two per-lane boards: the bank's quoted price and what it has already committed there,
# so a client can show the price beside the tote AND how much room is left before the bank is full.
ABI["_view"]["board3"] = {"name": "od", "base": OD_BASE, "cells": NH, "stride": NH, "index": "races"}
ABI["_view"]["board4"] = {"name": "bp", "base": BP_BASE, "cells": NH, "stride": NH, "index": "races"}


def build():
    return zkvmasm.assemble_contract(SRC)
