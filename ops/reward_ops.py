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
from protocol import (split_open_block_reward, split_bonded_block_reward, TREASURY_ADDRESS,
                      DIVIDEND_POOL)
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
        # BONDED lane: producer keeps the majority, a modest slice funds the presence dividend, treasury 10%.
        producer_cut, dividend, treasury = split_bonded_block_reward(reward)
        change_balance(address=creator, amount=producer_cut, revert=revert, logger=logger)
        if dividend:
            change_balance(address=DIVIDEND_POOL, amount=dividend, revert=revert, logger=logger)
        if treasury:
            change_balance(address=TREASURY_ADDRESS, amount=treasury, revert=revert, logger=logger)
        increase_produced_count(address=creator, amount=producer_cut, revert=revert, logger=logger)


def apply_treasury_burn(block, logger, revert=False):
    """Anti-hoard SELF-BURN (doc/treasury.md §3.2). Every TREASURY_SPEND_PERIOD blocks, DESTROY TREASURY_BURN_BPS
    of the treasury balance above TREASURY_RUNWAY_FLOOR, so an un-deployed treasury actively shrinks (the Bismuth
    fix). Burned coins leave existence, so the destruction is booked into the burned-supply counter (totals
    'fees', which total_supply subtracts) to keep the supply figure exact. The burned amount is STORED per height
    so rollback restores balance + supply exactly. Single source shared by incorporate_block + rollback_one_block
    + reindex, like credit_block_reward — so the paths can never drift. Runs INSIDE the block's write txn."""
    from protocol import (TREASURY_ADDRESS, TREASURY_SPEND_PERIOD, TREASURY_BURN_BPS,
                          TREASURY_RUNWAY_FLOOR, BPS_DENOM)
    from ops.account_ops import get_account, index_totals
    from ops import kv_ops
    h = int(block["block_number"])
    if h <= 0 or (h % TREASURY_SPEND_PERIOD) != 0:
        return
    if revert:
        burned = kv_ops.treasury_burn_get(h)
        if burned:
            change_balance(address=TREASURY_ADDRESS, amount=burned, revert=False, logger=logger)   # restore balance
            index_totals(produced=0, fees=-burned)                                   # restore supply
        kv_ops.treasury_burn_del(h)
        return
    acc = get_account(TREASURY_ADDRESS, create_on_error=False)
    bal = int(acc.get("balance", 0)) if acc else 0
    burned = max(0, bal - TREASURY_RUNWAY_FLOOR) * TREASURY_BURN_BPS // BPS_DENOM
    if burned > 0:
        # Don't burn a treasury that CANNOT be spent: with no ACTIVATED electorate the quorum can't execute any
        # payout, so burning would just strand + destroy funds (a griefer churning the electorate could bleed it).
        # Pause the burn until an electorate exists (e.g. at launch, or after a full stake rotation ages back in).
        from ops.account_ops import get_bonded_registry
        from ops.settlement_ops import _vote_activated
        from ops.mining_ops import epoch_of, selection_shares
        reg = get_bonded_registry()
        ep = epoch_of(h)
        if sum(selection_shares(i["bonded"]) for i in reg.values() if _vote_activated(i, ep)) == 0:
            return
        change_balance(address=TREASURY_ADDRESS, amount=-burned, revert=False, logger=logger)        # destroy
        index_totals(produced=0, fees=burned)                                         # book the burn
        kv_ops.treasury_burn_put(h, burned)
