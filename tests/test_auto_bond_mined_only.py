"""
Auto-bond compounds MINED coins. Not received ones, and above all not withdrawn ones.

THE BUG. core_loop.maybe_auto_bond (and its mirror, the wallet's autoBond) measured "newly-mined
earnings" as the rise in the account's spendable BALANCE since a baseline. Balance rises for reasons that
have nothing to do with mining, and every one of them was swept into a 24h-timelocked bond at the
operator's configured percentage — 99% by default on a node:

  * a plain transfer someone sent you
  * a faucet payout / bridge deposit
  * a collected dividend
  * a matured `withdraw` — the coins you had just DELIBERATELY taken out of savings

The last one is the sharp edge, because it is self-reversing. Leaving the bonded lane is two steps:
`unbond` records a request, and ~24h later a `withdraw` moves the coins to spendable. That withdraw reads
as a balance gain, so the compounder puts 99% of it straight back into savings behind another 24h lock.
The operator's own instruction to leave the lane is undone, silently, once per unbond, forever.

THE FIX is to baseline on `produced` — the consensus counter of what this address actually MINED (open +
bonded block rewards; increase_produced_count is revert-symmetric, so it tracks reorgs). It moves only
when the address wins a slot, which is exactly what the feature claims to compound.

These checks drive the real accounting arithmetic (a faithful transcription of the function's decision
path — the function itself needs a memserver, a live chain and a keydict) over the sequence that broke:
mine, receive, withdraw. What they pin is that only the mining step is ever bonded, that the baseline
moves forward only over mined coins, and that a clamped bond leaves its remainder claimable rather than
writing it off.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        _fails.append(name)


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from protocol import BOND_CAP, MIN_TX_FEE, AUTO_BOND_MIN_RAW, AUTO_COLLECT_MIN_RAW

        class Node:
            """The auto-bond decision path from core_loop.maybe_auto_bond, in isolation."""

            def __init__(self, pct):
                self.pct, self.baseline = pct, None

            def step(self, balance, bonded, mined):
                if self.baseline is None:
                    self.baseline = mined
                    return 0
                if bonded >= BOND_CAP:
                    self.baseline = mined
                    return 0
                gain = mined - self.baseline
                if gain <= 0:
                    self.baseline = mined
                    return 0
                to_bond = min((gain * self.pct) // 100, BOND_CAP - bonded)
                if to_bond < AUTO_BOND_MIN_RAW or balance < to_bond + MIN_TX_FEE:
                    return 0                                     # accrue, do NOT rebaseline
                if balance - (to_bond + MIN_TX_FEE) < AUTO_COLLECT_MIN_RAW:
                    to_bond = balance - MIN_TX_FEE - AUTO_COLLECT_MIN_RAW
                    if to_bond < AUTO_BOND_MIN_RAW:
                        return 0
                self.baseline += min(gain, (to_bond * 100) // self.pct)
                return to_bond

        NADO = 10 ** 10
        n = Node(99)

        # boot: only FUTURE mining counts
        check("first observation bonds nothing", n.step(balance=50 * NADO, bonded=0, mined=100 * NADO) == 0)

        # ---- mining IS compounded ---------------------------------------------------------------------
        got = n.step(balance=60 * NADO, bonded=0, mined=110 * NADO)      # mined 10 more
        check("10 NADO mined -> 9.9 bonded (99%)", got == 99 * NADO // 10)

        # ---- an incoming TRANSFER is not ---------------------------------------------------------------
        # balance jumps 40, `produced` does not move: somebody sent us coins.
        check("a 40 NADO transfer in bonds NOTHING",
              n.step(balance=100 * NADO, bonded=99 * NADO // 10, mined=110 * NADO) == 0)

        # ---- and neither is a matured WITHDRAW (the self-reversing one) ---------------------------------
        # The exact shape of the reported bug: unbond half, wait a day, withdraw lands.
        w = Node(99)
        w.step(balance=88 * NADO, bonded=369 * NADO, mined=37 * NADO)            # baseline
        withdrawn = 184 * NADO
        got = w.step(balance=88 * NADO + withdrawn, bonded=185 * NADO, mined=37 * NADO)
        check("a 184 NADO withdraw from savings is NOT re-bonded", got == 0)
        # under the old balance-baselined rule this would have been 99% of it, straight back into savings
        check("...which under the old rule would have re-locked 182.16 NADO",
              (withdrawn * 99) // 100 == 18216 * NADO // 100)

        # ---- the baseline only ever moves over MINED coins ----------------------------------------------
        b = Node(50)
        b.step(balance=0, bonded=0, mined=1000 * NADO)
        before = b.baseline
        b.step(balance=500 * NADO, bonded=0, mined=1000 * NADO)          # pure receive
        check("a receive leaves the baseline untouched", b.baseline == before)
        b.step(balance=500 * NADO, bonded=0, mined=1010 * NADO)          # mined 10
        check("mining advances the baseline by what it consumed", b.baseline == 1010 * NADO)

        # ---- a CLAMPED bond leaves its remainder claimable ----------------------------------------------
        # bonded is 1 NADO under the cap, so only 1 NADO of a 100 NADO mining gain can be bonded; the
        # other 99 must still be claimable later (it is not, if the baseline jumps the whole gain).
        c = Node(100)
        c.step(balance=500 * NADO, bonded=BOND_CAP - 1 * NADO, mined=0)
        got = c.step(balance=500 * NADO, bonded=BOND_CAP - 1 * NADO, mined=100 * NADO)
        check("a bond clamped by BOND_CAP bonds only the headroom", got == 1 * NADO)
        check("...and consumes only that much of the gain", c.baseline == 1 * NADO)

        # ---- dust accrues instead of emitting a fee-dominated tx ----------------------------------------
        e = Node(99)
        e.step(balance=10 * NADO, bonded=0, mined=0)
        check("a sub-dust mining gain bonds nothing", e.step(balance=10 * NADO, bonded=0, mined=1) == 0)
        check("...and does NOT rebaseline, so it accrues", e.baseline == 0)

        # ---- the shipped sources really are baselined on `produced` -------------------------------------
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        core = open(os.path.join(root, "loops", "core_loop.py")).read()
        seg = core[core.index("def maybe_auto_bond"):core.index("def maybe_auto_bond") + 4000]
        check("core_loop baselines on produced", 'mined = int(acc.get("produced", 0))' in seg)
        check("core_loop never baselines on balance again",
              "self.auto_bond_baseline = balance" not in seg)
        js = open(os.path.join(root, "static", "interface.js")).read()
        jseg = js[js.index("async function maybeAutoBond"):js.index("async function maybeAutoBond") + 4000]
        check("the wallet baselines on produced", "BigInt(acc.produced ?? 0)" in jseg)
        check("the wallet never baselines on balance again",
              "state.autoBondBaseline = balance" not in jseg)

    print()
    print("ALL AUTO-BOND CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
