"""
PUSH transaction gossip — the flood side of mempool propagation.

Nado blocks are DETERMINISTIC: every node rebuilds the identical block from the same mempool + the
same producer, so blocks are never raced across the wire — they are reconstructed locally. The only
thing that must propagate fast is the TRANSACTIONS themselves: if node A holds a tx that node B has
not seen when the next block is built, the two produce different blocks at that height and the
network reorgs. So the propagation latency that matters is tx latency, and the lever is to PUSH a tx
to peers the instant it is accepted, instead of waiting for a peer to pull-reconcile it.

This module is the decision layer, kept pure (no node import) so the flood-control rules are unit
tested directly:

  * FIRST-SIGHT ONLY (should_gossip): a node re-broadcasts a tx only the first time it accepts it.
    merge_transaction returns "Success" on a genuinely-new accept and "Already present" on a dup, so
    the epidemic terminates the moment every peer has seen the tx — no TTL, no seen-set, no storm.
  * ECHO SUPPRESSION (gossip_targets): never push a tx straight back to the peer it came from.

The actual send (POST codec.pack(tx) -> peers' /submit_transaction) and the drain thread live in
nado.py; the txid-diff pull reconcile (memserver.merge_remote_transactions, peer_loop) stays as the
backstop for anything a push misses (a peer that was down, a late joiner, a dropped packet) — which
is why push is a pure latency optimisation and never a correctness gate.
"""


def should_gossip(merge_result) -> bool:
    """True only when merge_transaction NEWLY accepted this tx (first sight). A dup returns
    "Already present" and a reject returns result False — neither re-floods, which is exactly what
    makes the broadcast terminate once the tx is everywhere."""
    return bool(isinstance(merge_result, dict)
                and merge_result.get("result")
                and merge_result.get("message") == "Success")


def gossip_targets(peers, exclude_ip=None):
    """The peers to push a newly-accepted tx to: every linked peer except the one we received it
    from (echo suppression) and any falsy entry. Order-preserving, de-duplicated."""
    seen = set()
    out = []
    for p in peers or ():
        if p and p != exclude_ip and p not in seen:
            seen.add(p)
            out.append(p)
    return out
