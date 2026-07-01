"""
Lane-aware block-reward crediting — the SINGLE source used by the apply (core_loop.incorporate_block),
rollback (rollback.py) and reindex paths, so they can never drift by a unit or a lane.

BONDED-lane block: producer gets the 90% cut, treasury 10% (unchanged, winner-take-all).
OPEN-lane block:   producer gets a small tip (OPEN_TIP_BPS), treasury 10%, and the REST accrues to the
                   DIVIDEND_POOL account for fidelity-weighted redistribution off-L1 (doc/presence-dividend.md).

The lane is a property of the SLOT, decided by lane_of(slot, epoch_beacon(...)). The beacon chains off the
first block of the PRIOR epoch — deeply finalized and never reorged out from under its epoch — so block_lane()
is deterministic and identical at apply, rollback and reindex time. The split functions live in protocol.py
(pure integer math, treasury+tip floors + exact remainder) so apply and rollback subtract identical integers.
"""
from protocol import (split_block_reward, split_open_block_reward, TREASURY_ADDRESS, DIVIDEND_POOL)
from ops.account_ops import change_balance, increase_produced_count
from ops.mining_ops import lane_of, epoch_of
from ops.block_ops import epoch_beacon


def block_lane(block) -> str:
    """Deterministic lane ('open'|'bonded') of a block's slot — the same computation validation uses to
    check the producer. Stable across apply/rollback/reindex (beacon anchors on a finalized prior-epoch block)."""
    n = block["block_number"]
    return lane_of(n, epoch_beacon(epoch_of(n)))


def credit_block_reward(block, logger, revert=False):
    """Apply (revert=False) or reverse (revert=True) a block's reward with the lane-aware split. Reverting
    passes the SAME integers to change_balance(..., revert=True), so a rollback returns every balance exactly
    to its prior value. The producer's 'produced' metric tracks only what the producer itself earned."""
    reward = block["block_reward"]
    creator = block["block_creator"]
    if block_lane(block) == "open":
        tip, dividend, treasury = split_open_block_reward(reward)
        change_balance(address=creator, amount=tip, revert=revert, logger=logger)
        if dividend:
            change_balance(address=DIVIDEND_POOL, amount=dividend, revert=revert, logger=logger)
        if treasury:
            change_balance(address=TREASURY_ADDRESS, amount=treasury, revert=revert, logger=logger)
        increase_produced_count(address=creator, amount=tip, revert=revert, logger=logger)
    else:
        producer_cut, treasury = split_block_reward(reward)
        change_balance(address=creator, amount=producer_cut, revert=revert, logger=logger)
        if treasury:
            change_balance(address=TREASURY_ADDRESS, amount=treasury, revert=revert, logger=logger)
        increase_produced_count(address=creator, amount=producer_cut, revert=revert, logger=logger)
