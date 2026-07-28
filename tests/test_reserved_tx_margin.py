"""RESERVED-TX PROPAGATION WINDOW.

Blocks in nado are DETERMINISTIC: every producer assembles the same block from the same mature tx set, so
a producer that holds a tx builds a DIFFERENT block than one that has not received it yet — and the chain
forks on the spot. Flexibly-landing txs are protected from this by the min_block inclusion delay, but the
node's own reserved txs (bond, register, duty) land at EXACTLY max_block and get no min_block, so
`max_block - tip` IS their entire propagation window.

It used to be tip+2 for bond and tip+5 for duty (~12-30s at 6s/block). On 2026-07-28 that forked
alphanet-12 three times in one afternoon: h12506 on an auto-bond minted after a node restart, h12605 on a
duty tx, splitting a 4-node fleet into three chains and collapsing FFG finality to 0. Restarts mint bonds
and every epoch mints a duty, so it fired routinely rather than as an edge case.

These checks pin the window itself, not the constant, so shrinking it back reintroduces the fork.
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from protocol import (RESERVED_TX_MARGIN, DUTY_TX_MARGIN, TX_LANDING_WINDOW,
                      EPOCH_LENGTH, FINALITY_DEPTH, BLOCK_TIME)

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


# A tx must survive long enough to gossip to every producer. Two block times is not "a window", it is a
# race — one slow hop and the producers disagree. Require at least a minute of headroom.
MIN_SECONDS = 60

check(RESERVED_TX_MARGIN * BLOCK_TIME >= MIN_SECONDS,
      f"bond/register window is >= {MIN_SECONDS}s ({RESERVED_TX_MARGIN} blocks x {BLOCK_TIME}s "
      f"= {RESERVED_TX_MARGIN * BLOCK_TIME}s)")
check(DUTY_TX_MARGIN * BLOCK_TIME >= MIN_SECONDS,
      f"duty window is >= {MIN_SECONDS}s ({DUTY_TX_MARGIN} blocks x {BLOCK_TIME}s "
      f"= {DUTY_TX_MARGIN * BLOCK_TIME}s)")

# The mempool gate admits a tx only while tip < max_block < tip + TX_LANDING_WINDOW. A margin at or over
# the window would be rejected at admission by any peer even slightly behind us.
check(RESERVED_TX_MARGIN < TX_LANDING_WINDOW, "bond/register margin fits under TX_LANDING_WINDOW")
check(DUTY_TX_MARGIN < TX_LANDING_WINDOW, "duty margin fits under TX_LANDING_WINDOW")

# Regression on the exact values that forked the chain.
check(RESERVED_TX_MARGIN > 2, "bond margin is no longer the tip+2 that forked h12506")
check(DUTY_TX_MARGIN > 5, "duty margin is no longer the tip+5 that forked h12605")


def duty_max_block(tip, X, reveal_due):
    """Mirror of the landing-height choice in core_loop.produce_epoch_duty."""
    reveal_hi = (X + 1) * EPOCH_LENGTH - FINALITY_DEPTH - 1
    epoch_hi = (X + 1) * EPOCH_LENGTH - 1
    hi = epoch_hi
    if reveal_due and reveal_hi > tip:
        hi = min(epoch_hi, reveal_hi)
    return min(tip + DUTY_TX_MARGIN, hi), reveal_hi, epoch_hi


X = 10
start = X * EPOCH_LENGTH

# A pending reveal must still fit inside the RANDAO reveal window — widening the margin must not silently
# start dropping reveal sections.
mb, reveal_hi, epoch_hi = duty_max_block(start, X, reveal_due=True)
check(mb <= reveal_hi and mb > start,
      f"duty minted at epoch start with a reveal due lands inside the reveal window "
      f"(max_block={mb} <= reveal_hi={reveal_hi})")

# ...but once the reveal deadline has PASSED, clamping to it would drag max_block below the tip and
# suppress the whole duty tx — attest and commit included. tip+5 never did that; neither may this.
late = reveal_hi + 5
mb, _, epoch_hi = duty_max_block(late, X, reveal_due=True)
check(mb > late,
      f"a passed reveal deadline does not suppress the duty tx (tip={late} -> max_block={mb}, "
      f"attest/commit still carried)")

# The duty tx must never outlive its epoch: the attestation targets epoch X and has to land inside it.
for tip in (start, start + 20, epoch_hi - 2, epoch_hi - 1):
    mb, _, _ = duty_max_block(tip, X, reveal_due=False)
    if not (tip < mb <= epoch_hi):
        check(False, f"duty at tip={tip} lands inside epoch {X} (got max_block={mb}, epoch_hi={epoch_hi})")
        break
else:
    check(True, f"duty always lands inside its own epoch (tip < max_block <= {epoch_hi})")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL RESERVED-TX MARGIN CHECKS PASSED")
