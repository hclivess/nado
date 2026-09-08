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
from ops import kv_ops
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
            # track the per-epoch dividend inflow (deterministic, revert-symmetric) so the exec node can
            # accrue an epoch-bound amount over weights_at_epoch instead of a live pool-balance delta.
            kv_ops.dividend_inflow_add(epoch_of(block["block_number"]), dividend, revert)
        if treasury:
            change_balance(address=TREASURY_ADDRESS, amount=treasury, revert=revert, logger=logger)
        increase_produced_count(address=creator, amount=tip, revert=revert, logger=logger)
    else:
        # BONDED lane: producer keeps the majority, a modest slice funds the presence dividend, treasury 10%.
        producer_cut, dividend, treasury = split_bonded_block_reward(reward)
        creator_share = _pool_split(block, creator, producer_cut, logger, revert)
        change_balance(address=creator, amount=creator_share, revert=revert, logger=logger)
        if dividend:
            change_balance(address=DIVIDEND_POOL, amount=dividend, revert=revert, logger=logger)
            # track the per-epoch dividend inflow (deterministic, revert-symmetric) so the exec node can
            # accrue an epoch-bound amount over weights_at_epoch instead of a live pool-balance delta.
            kv_ops.dividend_inflow_add(epoch_of(block["block_number"]), dividend, revert)
        if treasury:
            change_balance(address=TREASURY_ADDRESS, amount=treasury, revert=revert, logger=logger)
        increase_produced_count(address=creator, amount=creator_share, revert=revert, logger=logger)


def _pool_split(block, creator, producer_cut, logger, revert):
    """STAKING POOLS (protocol.POOL_HEIGHT): if the winning identity produced with delegated stake, pay the delegators
    their pro-rata portion minus the pool's fee IN THIS BLOCK and return what the pool itself keeps (own share + fee +
    rounding dust). The split is computed from the in-txn registry (the same bytes on every node at this point) and
    journaled per height (kv pool_revert "rw:<h>") so rollback subtracts the identical integers. Below the gate, or for
    a pool with nothing delegated, the whole cut is the creator's (the historical path, byte-identical)."""
    from protocol import POOL_HEIGHT, BPS_DENOM, POOL_RETIRE_HEIGHT
    h = int(block["block_number"])
    if revert:
        rec = kv_ops.pool_revert_pop(f"rw:{h}")
        if rec is None:
            return producer_cut                       # no split happened when this block was applied
        creator_share, payouts = int(rec[0]), rec[1]
        for addr, amt in payouts:
            change_balance(address=str(addr), amount=int(amt), revert=True, logger=logger)
        return creator_share
    if not POOL_HEIGHT or h < POOL_HEIGHT or (POOL_RETIRE_HEIGHT and h >= POOL_RETIRE_HEIGHT):   # retired: no split, ever
        return producer_cut
    from ops.account_ops import get_bonded_registry, get_account
    reg = get_bonded_registry()
    entry = reg.get(creator)
    if not entry or int(entry.get("pooled", 0)) <= 0:
        return producer_cut
    acc = get_account(creator, create_on_error=False) or {}
    members = [m for m in sorted(acc.get("pool_members") or []) if m in reg and reg[m].get("pool_to") == creator]
    stakes = {m: int(reg[m]["bonded"]) for m in members}
    pooled = sum(stakes.values())
    own = int(entry.get("bonded", 0))
    total = own + pooled
    if pooled <= 0 or total <= 0:
        return producer_cut
    fee_bps = int(acc.get("pool_fee_bps", 0) or 0)
    delegators_portion = producer_cut * pooled // total
    fee = delegators_portion * fee_bps // BPS_DENOM
    distributable = delegators_portion - fee
    payouts = []
    paid = 0
    for m in members:                                  # sorted: deterministic rounding
        amt = distributable * stakes[m] // pooled
        if amt > 0:
            payouts.append([m, amt]); paid += amt
    creator_share = producer_cut - paid                # own share + fee + dust
    for m, amt in payouts:
        change_balance(address=m, amount=amt, revert=False, logger=logger)
    kv_ops.pool_revert_put(f"rw:{h}", [creator_share, payouts])
    return creator_share


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
