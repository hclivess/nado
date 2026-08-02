"""
Lend — zkVM port (doc/zk-execution-proofs.md). PEER-TO-PEER COLLATERALISED FIXED-TERM LOANS, no oracle.

WHAT IT IS, plainly: a lender posts an offer — "I will lend 100, I want 20 interest, you must post 150
collateral, you have 7 days". A borrower who likes those terms posts the 150 and walks away with the 100.
Repay 120 before the deadline and the 150 comes back. Miss the deadline and the lender takes the 150.

WHY THERE IS NO ORACLE, AND WHY THAT IS THE WHOLE DESIGN. Every "lending platform" that quotes a variable
APY and liquidates on a loan-to-value ratio needs to know what the collateral is WORTH, continuously, from
a price feed. A price feed is a trusted third party wearing a hat, and on a chain this size it would be the
single most attackable component in the system — cheaper to manipulate than to secure. So this does not
have one. Terms are FIXED and ABSOLUTE at offer time: interest is stated as an AMOUNT, not a rate, and the
only "liquidation" is a deadline passing, which the chain can see by itself. TIME and the loan's own stored
deadline are the entire risk model.

That choice buys arithmetic safety for free. No rate means no compounding, which means no repeated
multiply/divide over a balance — the class of bug that eats lending contracts. The only products here are
UNIT conversions against constants, and every amount is capped so they stay inside the DIVMODW soundness
window.

FUND SAFETY — the property this contract is actually about. Both fund-lock classes this codebase has been
bitten by are structurally absent, and that is deliberate:

  * NO PRIVILEGED ESCAPE HATCH. There is no method only the creator, a host or an admin can call. Every
    exit is available to the party ENTITLED to it, by their own transaction: an untaken offer is cancelled
    by its lender, a live loan is repaid by its borrower, an expired loan is defaulted by ANYONE. A
    counterparty who walks away can strand nothing, because nothing waits on them.
  * NO PIN-NOW / RESOLVE-LATER. Nothing here pins a block height and reads its hash later, so there is no
    horizon past which a position becomes unresolvable. The only time reference is CTX TIME compared
    against a deadline stored at take time, and that comparison keeps working forever.

Concretely, every state has a live exit for every party holding money in it:
    OPEN      lender: cancel() -> principal back.               (borrower has nothing in)
    TAKEN     borrower: repay() before due -> collateral back.   lender: default() after due -> collateral.
    REPAID    lender: claim() principal+interest.                borrower: claim() collateral.
    DEFAULTED lender: claim() collateral.                        (borrower kept the principal)
    CANCELLED lender: claim() principal.
Payouts are PULL-based (claim()), never pushed in a loop, so no counterparty can block settlement by being
unpayable, and the contract can never owe more than it holds.

THE DEADLINE IS HARD, and a borrower one second late loses the collateral. That is the deal a
collateralised fixed-term loan IS, and it is why collateral must exceed principal — repaying is then always
the rational move, so the honest path is also the profitable one. It is stated here rather than softened,
because the alternative (a grace period during which both parties have a claim) is a race, and races over
escrowed money are how these contracts lose funds.

zkVM data model: loan ids are ints < 2^32. Money is tracked in UNITs of 10^4 raw NADO (amounts must be UNIT
multiples) and capped at 2^31 UNITs each, so UNIT products stay well inside 2^62. Addresses are stored as
caller DIGESTS, compared by equality, never decoded on-chain.

Loan fields (key = loan id): 1 ln(exists) 2 lr(lender digest) 3 bw(borrower digest) 4 pr(principal, UNITs)
  5 it(interest, UNITs) 6 co(collateral, UNITs) 7 dr(duration secs) 8 dl(due time) 9 st(state)
  10 lc(lender claimable, UNITs) 11 bc(borrower claimable, UNITs)
Index: slot 0 count, field 40 list.
Methods: offer(id,principal,interest,collateral,duration)[principal] · cancel(id) · take(id)[collateral] ·
  repay(id)[principal+interest] · default(id) · claim(id) ·
  views: claimable_of(id,addr) · state_of(id) · due_of(id).
"""
from execnode import zkvmasm

LN, LR, BW, PR, IT, CO, DR, DL, ST, LC, BC = 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11
LLIST = 40

ST_OPEN, ST_TAKEN, ST_REPAID, ST_DEFAULT, ST_CANCELLED = 1, 2, 3, 4, 5

UNIT = 10_000                      # raw NADO per unit (amounts must be UNIT multiples)
AMT_CAP = 1 << 31                  # per-amount cap in UNITs — keeps UNIT*amount < 2^62
_2_32 = 1 << 32


def _sl(field):
    """asm: r4 = slot(field, id) with the loan id in r0."""
    return [f"slot r4 {field} r0"]


def _load(field, reg):
    """asm: reg = loan[field]. Clobbers r4."""
    return _sl(field) + [f"sload {reg} r4"]


def _store(field, reg):
    """asm: loan[field] = reg. Clobbers r4."""
    return _sl(field) + [f"sstore r4 {reg}"]


def _require_state(want, reg="r5"):
    """asm: require loan.st == want."""
    return _load(ST, reg) + [f"movi r6 {want}", f"eq {reg} r6", f"require {reg}"]


def _value_units(dest):
    """asm: dest = CTX value / UNIT, requiring value > 0 and an exact UNIT multiple.

    Scratches r1/r5/r7 ONLY, so `dest` may be any other register — including r2, which an earlier version
    used as the fixed scratch. That made `_value_units("r2")` zero the value it had just read, one
    instruction after reading it, and every take/repay reverted while the offer path (which passed r3)
    worked fine. The assert makes the constraint fail at build time instead of as a mystery revert.
    """
    assert dest not in ("r1", "r5", "r7"), f"_value_units scratches r1/r5/r7; dest={dest} would self-clobber"
    return [f"ctx {dest} value",
            "movi r1 0", f"lt r1 {dest}", "require r1",
            f"movi r5 {UNIT}", f"divmod {dest} r5",
            "mov r1 r7", "nez r1", "notb r1", "require r1"]


def _require_caller_is(field, scratch="r5"):
    """asm: require CTX caller == loan[field]."""
    return _load(field, scratch) + ["ctx r6 caller", f"eq {scratch} r6", f"require {scratch}"]


def _credit(field, amount_reg, scratch="r5"):
    """asm: loan[field] += amount_reg (a claimable balance in UNITs)."""
    return _load(field, scratch) + [f"add {scratch} {amount_reg}"] + _store(field, scratch)


# ---- offer(id, principal, interest, collateral, duration) [value = principal * UNIT] ------------------
# The lender escrows the principal HERE, at offer time, so a borrower who takes the offer is never taking
# an IOU — the money is already in the contract. That is also what makes cancel() a pure refund rather
# than a promise to unwind.
OFFER = "\n".join(
    # id in (0, 2^32)
    ["movi r1 0", "lt r1 r0", "require r1",
     f"movi r1 {_2_32}", "mov r2 r0", "lt r2 r1", "require r2"]
    # fresh id
    + _load(LN, "r5") + ["nez r5", "notb r5", "require r5"]
    # escrowed principal, in UNITs -> r3
    + _value_units("r3")
    # the declared principal (arg 1) must equal what was actually escrowed. Without this the offer could
    # advertise 100 while escrowing 1, and the borrower would post collateral against nothing.
    + ["movi r1 1", "arg r2 r1", "eq r2 r3", "require r2"]
    # principal < CAP
    + ["mov r2 r3", f"movi r5 {AMT_CAP}", "lt r2 r5", "require r2"]
    # interest (arg 2) < CAP
    + ["movi r1 2", "arg r2 r1", f"movi r5 {AMT_CAP}", "lt r2 r5", "require r2"]
    # collateral (arg 3) > 0 and < CAP
    + ["movi r1 3", "arg r2 r1", "movi r5 0", "lt r5 r2", "require r5",
       "movi r1 3", "arg r2 r1", f"movi r5 {AMT_CAP}", "lt r2 r5", "require r2"]
    # COLLATERAL MUST EXCEED PRINCIPAL. This is the whole incentive: repaying must be cheaper than walking
    # away, or the "loan" is just a sale and the lender is guaranteed to be the one holding the loss.
    + ["movi r1 3", "arg r2 r1", "mov r5 r3", "lt r5 r2", "require r5"]
    # duration (arg 4) > 0
    + ["movi r1 4", "arg r2 r1", "movi r5 0", "lt r5 r2", "require r5"]
    # persist terms
    + _store(PR, "r3")
    + ["movi r1 2", "arg r5 r1"] + _store(IT, "r5")
    + ["movi r1 3", "arg r5 r1"] + _store(CO, "r5")
    + ["movi r1 4", "arg r5 r1"] + _store(DR, "r5")
    + ["ctx r6 caller"] + _store(LR, "r6")
    + [f"movi r5 {ST_OPEN}"] + _store(ST, "r5")
    + ["movi r5 1"] + _store(LN, "r5")
    # append to the loan index
    + ["movi r4 0", "sload r5 r4", f"slot r6 {LLIST} r5", "sstore r6 r0",
       "movi r3 1", "add r5 r3", "sstore r4 r5", "ret r0"])

# ---- cancel(id): the lender withdraws an offer nobody took -------------------------------------------
CANCEL = "\n".join(
    _require_state(ST_OPEN)
    + _require_caller_is(LR)
    + _load(PR, "r3")
    + _credit(LC, "r3")
    + [f"movi r5 {ST_CANCELLED}"] + _store(ST, "r5")
    + ["ret r3"])

# ---- take(id) [value = collateral * UNIT]: borrow ----------------------------------------------------
# The principal is PAID OUT here rather than credited, because the borrower's whole reason to be here is to
# leave with it; making them claim() would be a second transaction for no benefit. The collateral stays
# escrowed and becomes claimable by exactly one party once the loan ends.
TAKE = "\n".join(
    _require_state(ST_OPEN)
    # the offer must still be funded (defensive: an OPEN loan always is, but this costs one load and makes
    # the invariant explicit rather than inherited)
    + _load(PR, "r3") + ["movi r5 0", "lt r5 r3", "require r5"]
    # escrowed collateral, in UNITs -> r2; must equal the required collateral exactly
    + _value_units("r2")
    + _load(CO, "r5") + ["eq r5 r2", "require r5"]
    # a lender must not take their own offer: it would move money in a circle and mint a fake repayment
    # history, and there is no honest reason to do it
    + _load(LR, "r5") + ["ctx r6 caller", "eq r5 r6", "notb r5", "require r5"]
    # borrower + due time = now + duration
    + ["ctx r6 caller"] + _store(BW, "r6")
    + ["ctx r5 time"] + _load(DR, "r6") + ["add r5 r6"] + _store(DL, "r5")
    + [f"movi r5 {ST_TAKEN}"] + _store(ST, "r5")
    # pay the principal out to the borrower, in RAW
    + _load(PR, "r3") + [f"movi r5 {UNIT}", "mul r3 r5", "ctx r1 caller", "pay r1 r3", "ret r3"])

# ---- repay(id) [value = (principal + interest) * UNIT] -----------------------------------------------
REPAY = "\n".join(
    _require_state(ST_TAKEN)
    + _require_caller_is(BW)
    # STRICTLY BEFORE the deadline. At or past it the lender's claim on the collateral has vested and
    # allowing a repayment too would give two parties a claim on the same escrow.
    + ["ctx r5 time"] + _load(DL, "r6") + ["lt r5 r6", "require r5"]
    # exact repayment: principal + interest, in UNITs
    + _value_units("r2")
    + _load(PR, "r3") + _load(IT, "r5") + ["add r3 r5", "eq r3 r2", "require r3"]
    # lender is owed principal+interest; borrower gets the collateral back
    + _load(PR, "r3") + _load(IT, "r5") + ["add r3 r5"] + _credit(LC, "r3")
    + _load(CO, "r3") + _credit(BC, "r3")
    + [f"movi r5 {ST_REPAID}"] + _store(ST, "r5")
    + ["ret r3"])

# ---- default(id): the deadline passed unrepaid -------------------------------------------------------
# PERMISSIONLESS ON PURPOSE. Anyone may call it, and the collateral is credited to the LENDER regardless of
# who called. If only the lender could trigger it, a lender who lost their key would strand the borrower's
# collateral forever — the exact privileged-escape-hatch shape that has locked funds in this codebase
# before. The caller gains nothing by calling, so there is no incentive to grief, only to tidy.
DEFAULT = "\n".join(
    _require_state(ST_TAKEN)
    + ["ctx r5 time"] + _load(DL, "r6") + ["lt r5 r6", "notb r5", "require r5"]   # TIME >= due
    + _load(CO, "r3") + _credit(LC, "r3")
    + [f"movi r5 {ST_DEFAULT}"] + _store(ST, "r5")
    + ["ret r3"])

# ---- claim(id): pull whatever the caller is owed -----------------------------------------------------
# One method for both sides: it pays the caller's own bucket and zeroes it before paying, so a re-entrant
# or repeated call finds nothing left. Requires a non-zero amount, so a claim that would pay 0 reverts
# loudly instead of succeeding silently and looking like the money is gone.
CLAIM = "\n".join(
    ["ctx r1 caller", "movi r3 0"]
    # lender bucket
    + _load(LR, "r5") + ["mov r6 r1", "eq r5 r6", "jnz r5 @lender", "jmp @borrower", "lender:"]
    + _load(LC, "r3") + ["movi r5 0"] + _store(LC, "r5") + ["jmp @pay", "borrower:"]
    # borrower bucket
    + _load(BW, "r5") + ["ctx r6 caller", "eq r5 r6", "require r5"]
    + _load(BC, "r3") + ["movi r5 0"] + _store(BC, "r5")
    + ["pay:", "movi r5 0", "lt r5 r3", "require r5"]
    + [f"movi r5 {UNIT}", "mul r3 r5", "ctx r1 caller", "pay r1 r3", "ret r3"])

# ---- read-only views ---------------------------------------------------------------------------------
# claimable_of(id, addr): raw amount `addr` could claim right now (0 if none). addr arrives as a digest.
CLAIMABLE_OF = "\n".join(
    _load(LR, "r5") + ["mov r6 r1", "eq r5 r6", "jnz r5 @l", "jmp @b", "l:"]
    + _load(LC, "r3") + ["jmp @out", "b:"]
    + _load(BW, "r5") + ["mov r6 r1", "eq r5 r6", "jnz r5 @b2", "movi r3 0", "ret r3", "b2:"]
    + _load(BC, "r3")
    + ["out:", f"movi r5 {UNIT}", "mul r3 r5", "ret r3"])

STATE_OF = "\n".join(_load(ST, "r3") + ["ret r3"])
DUE_OF = "\n".join(_load(DL, "r3") + ["ret r3"])

SRC = {"offer": OFFER, "cancel": CANCEL, "take": TAKE, "repay": REPAY, "default": DEFAULT,
       "claim": CLAIM, "claimable_of": CLAIMABLE_OF, "state_of": STATE_OF, "due_of": DUE_OF}

ABI = {
    "offer": {"args": ["loanId", "principal", "interest", "collateral", "duration"], "value": True},
    "cancel": {"args": ["loanId"]},
    "take": {"args": ["loanId"], "value": True},
    "repay": {"args": ["loanId"], "value": True},
    "default": {"args": ["loanId"]},
    "claim": {"args": ["loanId"]},
    "claimable_of": {"args": ["loanId", "addr"], "view": True},
    "state_of": {"args": ["loanId"], "view": True},
    "due_of": {"args": ["loanId"], "view": True},
    "_view": {
        "fields": {"ln": {"field": LN, "index": "loans"}, "lr": {"field": LR, "index": "loans"},
                   "bw": {"field": BW, "index": "loans"}, "pr": {"field": PR, "index": "loans"},
                   "it": {"field": IT, "index": "loans"}, "co": {"field": CO, "index": "loans"},
                   "dr": {"field": DR, "index": "loans"}, "dl": {"field": DL, "index": "loans"},
                   "st": {"field": ST, "index": "loans"}, "lc": {"field": LC, "index": "loans"},
                   "bc": {"field": BC, "index": "loans"}},
        "indexes": {"loans": {"cnt": 0, "list": LLIST}},
        "addr": ["lr", "bw"],
    },
}


def build():
    return zkvmasm.assemble_contract(SRC)
