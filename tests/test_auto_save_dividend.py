"""AUTO-SAVE SWEEPS WHAT YOU EARN, WHICH INCLUDES THE PRESENCE DIVIDEND
(core_loop.maybe_auto_bond; mirrored by static/interface.js maybeAutoBond).

2026-09-19, reported: "I have auto savings set to 100% yet my spendable balance keeps increasing."
The gain was measured purely as a rise in `produced`, the chain's MINED counter. That keeps transfers,
faucet payouts, bridge deposits and matured withdrawals out — the 2026-08 fix, and it must stay — but a
presence dividend is none of those: it credits `balance` through a self-claimed dividend_withdraw and
never touches `produced`. So at ANY percentage, dividend income was never swept. Measured on the
operator's own account: 50 dividend claims worth 1.594 NADO landed in 5.7 h while its 50 auto-bonds
covered only the mined slice.

Pins, on a stubbed node: dividend-only income IS swept; a transfer in is still NOT (the property the
mined baseline exists for); mined and dividend sweep together; the dividend tally is spent before the
mined baseline, so the baseline never advances over coins `produced` did not count; a partial bond
leaves the remainder claimable; and the wallet mirrors all of it.
Run: python3 tests/test_auto_save_dividend.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_autosave_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import loops.core_loop as CL
from loops.core_loop import CoreClient
from protocol import AUTO_BOND_MIN_RAW, MIN_TX_FEE, AUTO_COLLECT_MIN_RAW, EPOCH_LENGTH

fails = []
def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond: fails.append(label)

class _Quiet:
    def __getattr__(self, _): return lambda *a, **k: None

ACCT = {"balance": 0, "bonded": 0, "produced": 0}
BONDED = []

class Stub:
    def __init__(self, pct=100, epoch=10):
        self.memserver = type("M", (), {})()
        self.memserver.auto_bond_percent = pct
        self.memserver.address = "me"
        self.memserver.keydict = {"address": "me"}
        self.memserver.latest_block = {"block_number": epoch * EPOCH_LENGTH}
        self.memserver.merge_transaction = lambda tx, user_origin=False: {"result": True}
        self.logger = _Quiet()
        self.last_auto_bond_epoch = -1
        self.auto_bond_baseline = None
        self.auto_bond_dividend = 0
        self.maybe_auto_bond = CoreClient.maybe_auto_bond.__get__(self)
    def at_epoch(self, e):
        self.memserver.latest_block = {"block_number": e * EPOCH_LENGTH}

CL.get_account = lambda addr, **kw: dict(ACCT)
CL.construct_bond_tx = lambda kd, amount, fee, max_block: BONDED.append(amount) or {"amount": amount}

RESERVE = AUTO_COLLECT_MIN_RAW + MIN_TX_FEE
BIG = 100 * AUTO_BOND_MIN_RAW

def run(stub, epoch, balance, produced, dividend=None):
    """One auto-bond pass at `epoch` against the given account state; returns what it bonded."""
    ACCT.update(balance=balance, produced=produced)
    if dividend is not None: stub.auto_bond_dividend = dividend
    stub.at_epoch(epoch); BONDED.clear(); stub.maybe_auto_bond()
    return BONDED[0] if BONDED else 0

# ---------------------------------------------------------------- the reported bug
s = Stub(pct=100)
run(s, 10, balance=0, produced=0)                                   # first pass only sets the baseline
check(s.auto_bond_baseline == 0, "the first pass baselines and bonds nothing")
s.auto_bond_dividend = BIG                                          # a dividend claim landed; nothing was MINED
got = run(s, 11, balance=BIG + RESERVE, produced=0)
check(got > 0, f"dividend-only income IS swept into savings (bonded {got})")
check(got == BIG, f"...all of it at 100% (bonded {got} of {BIG})")
check(s.auto_bond_dividend == 0, "...and the dividend tally is emptied by the sweep")
check(s.auto_bond_baseline == 0, "...while the MINED baseline never moved over coins `produced` did not count")

# ---------------------------------------------------------------- the property that must not regress
s2 = Stub(pct=100)
run(s2, 10, balance=0, produced=0)
got = run(s2, 11, balance=BIG * 5 + RESERVE, produced=0)            # a transfer in / matured withdraw arrived
check(got == 0, f"a credit that is neither mined nor a claimed dividend is still NEVER swept (bonded {got})")
check(s2.auto_bond_baseline == 0 and s2.auto_bond_dividend == 0, "...and it changes no counter")

# ---------------------------------------------------------------- both together
s3 = Stub(pct=100)
run(s3, 10, balance=0, produced=0)
s3.auto_bond_dividend = BIG
got = run(s3, 11, balance=3 * BIG + RESERVE, produced=BIG)          # BIG mined + BIG dividend
check(got == 2 * BIG, f"mined and dividend sweep together (bonded {got}, expected {2*BIG})")
check(s3.auto_bond_dividend == 0 and s3.auto_bond_baseline == BIG,
      f"...the dividend is spent first and the baseline advances only over the mined part "
      f"(div {s3.auto_bond_dividend}, baseline {s3.auto_bond_baseline})")

# ---------------------------------------------------------------- a percentage below 100 keeps the rest spendable
s4 = Stub(pct=50)
run(s4, 10, balance=0, produced=0)
s4.auto_bond_dividend = BIG
got = run(s4, 11, balance=BIG + RESERVE, produced=0)
check(got == BIG // 2, f"at 50% half the dividend is saved (bonded {got})")
check(s4.auto_bond_dividend == 0,
      f"...and the gain counts as fully handled — the other half is spendable BY CHOICE, not unswept ({s4.auto_bond_dividend})")

# ---------------------------------------------------------------- but a CLAMPED bond does leave a remainder
# the liquidity reserve cuts to_bond below pct% of the gain; what it could not cover must stay claimable,
# exactly as it does for mined coins (the "remainder stays claimable on a later pass" rule)
s4b = Stub(pct=100)
run(s4b, 10, balance=0, produced=0)
s4b.auto_bond_dividend = BIG
got = run(s4b, 11, balance=BIG + MIN_TX_FEE, produced=0)            # affords the fee, but not the reserve on top
short = AUTO_COLLECT_MIN_RAW
check(got == BIG - short, f"the reserve clamps the bond (bonded {got}, expected {BIG - short})")
check(s4b.auto_bond_dividend == short,
      f"...and the clamped remainder stays claimable on a later pass ({s4b.auto_bond_dividend}, expected {short})")

# ---------------------------------------------------------------- one sweep per epoch, unchanged
s5 = Stub(pct=100)
run(s5, 10, balance=0, produced=0)
s5.auto_bond_dividend = BIG
run(s5, 11, balance=BIG + RESERVE, produced=0)
s5.auto_bond_dividend = BIG
check(run(s5, 11, balance=BIG + RESERVE, produced=0) == 0, "a second pass in the same epoch bonds nothing")

# ---------------------------------------------------------------- the wallet mirrors it
js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "interface.js")).read()
check("autoBondDividend: 0n" in js, "wallet: the dividend tally exists")
check("state.autoBondDividend += BigInt(p.amount)" in js, "wallet: a landed claim adds to it")
check("const gain = minedGain + state.autoBondDividend;" in js, "wallet: the gain counts both")
check("state.autoBondDividend -= fromDiv" in js and "state.autoBondBaseline += (consumed - fromDiv)" in js,
      "wallet: the dividend is spent first and the baseline takes only the remainder")
check("state.autoBondDividend += state.autoBondPending.fromDiv" in js, "wallet: a timed-out bond gives the dividend slice back")

print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
