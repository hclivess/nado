from .data_ops import get_byte_size, sort_list_dict

# Fee-EXEMPT reserved txs. Each is gated so it cannot be spammed — register (sequential PoSW + per-IP cap),
# heartbeat (must be registered), unbond/withdraw (the sender's OWN stake), commit/reveal/attest/settle
# (a bonded validator's once-per-epoch duty), bridge_withdraw/dividend_withdraw (Merkle-proof-gated). So they
# are SAFE to protect from a byte-pressure cull; dropping them for a fee-bearing flood would be a DoS AND would
# strand consensus duties + fair-launch onboarding.
FEE_EXEMPT_RECIPIENTS = frozenset({
    "register", "heartbeat", "unbond", "withdraw", "commit", "reveal", "attest",
    "settle", "bridge_withdraw", "dividend_withdraw",
    # msgkey (bind ML-KEM messaging pubkey to the account) is fee-exempt + zero-value; it is NOT added to the
    # empty-account onboarding bypass, so the sender must already have an on-chain account (registered / holds
    # coins) — that gate replaces register's PoSW as the anti-spam bound, so it is safe from the cull too.
    "msgkey",
})


def cull_buffer(buffer, limit) -> list:
    """Keep a buffer under `limit` bytes (LOCAL anti-DoS policy, non-consensus). Evict only ORDINARY,
    fee-bearing txs — lowest fee first — and NEVER a fee-exempt reserved tx (see FEE_EXEMPT_RECIPIENTS): those
    are already un-spammable, so dropping them would let a min-fee flood evict registrations / consensus duties.
    (Previously it removed the global lowest-fee tx, i.e. the fee-0 reserved txs FIRST — a DoS.)
    PERF: per-tx sizes are computed ONCE and a running total decremented per drop — the old loop re-repr'd
    the ENTIRE remaining buffer once per dropped tx (O(drops × n × bytes)), so the flood that pushes the
    buffer over the limit was exactly the input that stalled the 1s core pass for minutes."""
    if get_byte_size(buffer) <= limit:
        return buffer
    sizes = {id(tx): get_byte_size(tx) for tx in buffer}
    total = sum(sizes.values())
    drop = set()
    for tx in sorted((t for t in buffer if t.get("recipient") not in FEE_EXEMPT_RECIPIENTS),
                     key=lambda t: t.get("fee", 0)):            # cheapest ordinary txs first
        if total <= limit:
            break
        drop.add(id(tx))
        total -= sizes[id(tx)]
    return [t for t in buffer if id(t) not in drop] if drop else buffer


def merge_buffer(from_buffer, to_buffer, block_max, block_min) -> dict:
    """Promote EVERY tx whose target_block is in (block_min, block_max] from `from_buffer` into `to_buffer`, and
    keep the rest in `from_buffer`. Single O(N) pass, order-independent.

    The old code re-selected the max-FEE tx each iteration and, when that tx did not match the window, left it
    in place and re-picked it — spinning on it and STARVING every lower-fee tx, so a due tx (e.g. a fee-0
    register at target == latest+1) could sit behind an undue higher-fee one and miss its target block. That is
    the 'accepted but never included' registration bug. Dedup is by txid (O(1)) rather than a deep list scan."""
    in_to = {tx.get("txid") for tx in to_buffer}
    kept = []
    for tx in from_buffer:
        tid = tx.get("txid")
        if tid in in_to:
            continue                                            # already in to_buffer — drop the duplicate
        if block_min < tx["target_block"] <= block_max:
            to_buffer.append(tx)
            in_to.add(tid)
        else:
            kept.append(tx)
    return {"from_buffer": sort_list_dict(kept), "to_buffer": sort_list_dict(to_buffer)}


def get_from_pool(pool, source, target):
    """project one field of the peer status pool into `target` IN PLACE: target[peer] =
    status[source] for every peer. Iterates a shallow copy so a concurrent status refresh from
    another loop cannot resize the dict mid-iteration. .get(): a peer status admitted WITHOUT the
    field (version skew, malicious minimal dict) must not KeyError — that aborted EVERY consensus
    pass forever (the peer answers /status fine, so it was never purged), freezing the majority +
    heaviest-tip refresh. A None value is already handled by the callers' None guards."""
    for item in pool.copy().items():
        target[item[0]] = item[1].get(source)
