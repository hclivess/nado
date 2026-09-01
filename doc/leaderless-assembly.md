# Leaderless block assembly — the model, its one weakness, and the touch-ups

NADO has no block proposer. A block is a **pure function of (parent, mempool)**: the producer/winner is a
deterministic draw from committed state, the tx set is the mature subset of the pool, the hash covers
neither timestamp nor signature. So **every node assembles every block** from its own pool and, when the
pools agree, every node computes the identical block — nothing is proposed, nothing is raced across the
wire, a winner can be asleep and still be credited, and there is nobody who can delay or censor a slot.
That is stronger and more decentralised than the proposer-and-quorum designs (Tendermint, Tenderbake) in
exactly the ways that matter to us, and the 2026-09-01 decision was to keep it and harden it rather than
bolt a leader on.

## The one weakness

Two nodes assembling the same height a few hundred milliseconds apart with pools that differ by one tx
produce two different blocks. Fork weight is content-independent (`shares + 1`), so that is an exact tie,
broken by the permanent lowest-hash rule on the first divergent block — a coin flip that ignores which
block was actually built from the more complete view. The 08-31 evening split (ancestor 76848, 24 deep)
was this class: branches differing only in `collect_dividend` / `dividend_withdraw` / contract-call txs,
weights 0.01% apart once a `bond` landed on one side, and a slow node applying blocks in 3 s at a 6 s block
time so the see-saw took 12 minutes to settle.

Every mitigation before this was "wait longer / sync harder" (`TX_INCLUSION_DELAY`, `FLEX_TX_MIN_MARGIN`,
push gossip, the pool warm-up gate). Those shrink the window; they cannot close it, because *first seen*
is node-local by definition. The touch-ups below attack the two halves of the problem directly: make the
pools agree **at the moment it matters**, and when they still don't, make the outcome **favour the more
complete pool** instead of a coin flip.

## Touch-up 1 — pre-assembly reconcile (`memserver.reconcile_next_block_set`)

Right before a node builds (once per tip, inside the production pacing slot) it asks its peers
`GET /next_block_txids`: *what would you put in the next block on this tip?* — the exact set their
`upcoming_block_hash` hashes, ~64 B per tx, 1.5 s budget. From every peer **on the same tip** it takes the
txids it lacks, fetches only those bodies (`POST /transactions_by_id`, 3 s budget), merges them through the
ordinary admission path (full validation; nothing is trusted), and *then* assembles. Every peer does the
same against us, so the mesh converges on the **union** of its next-block sets within the slot. A peer that
does not answer simply sits the pass out; the 1 s pull reconcile stays the backstop; nothing can hold
production beyond the budget.

Why this and not the status-pool agreement signal: `/status` is polled every ~10 s, slower than the block
time, so the "upcoming-block agreement %" is stale exactly when a decision is needed.

## Touch-up 2 — most-complete-pool tie-break (`fork_resolution.tie_winner`)

When a same-height split still happens, both sides fetch the *body* of the other's first divergent block
(they already probed its hash) and compare tx sets: a **strict superset wins**; incomparable sets go to
the larger one; equal-size sets fall back to the permanent lowest-hash rule; a missing body degrades to
the hash rule on both sides. Consequences: the block built from the more complete pool becomes canonical,
the node that lacked the tx can adopt at once (the block carries it), the tx lands instead of waiting for
a re-mine, and "propagate faster" is the winning strategy rather than a lottery. Deterministic — both sides
evaluate the same function of the same two blocks — and it never overrides weight: it only decides exact
ties, as before.

## Touch-up 3 — no sender-wide purge on an aggregate-spend refusal (`memserver.merge_transaction`)

A remote tx refused as "Overspending balance" used to purge **every** pooled tx of that sender. That
refusal is routinely branch/timing skew (a dividend credit or funding one node has applied and another
has not yet), not a double-spend attempt — and the purge made the refusing node's pool diverge from every
peer that kept the sender's other txs, which deterministic production turned straight into a split.
Now only the refused tx is declined (it cools briefly and is re-tried); double-spends still cannot land
because `verify_block` enforces whole-block spending and `_candidate_pool` keeps our own candidate within
balance.

## What was considered and rejected

A designated-assembler rule (per-slot ranked assemblers drawn from leased bonded nodes, rank-weighted
fork choice, block push, open fallback) was fully built and unit-tested on 2026-09-01 and then set aside:
it solves the same-height race by making one node's pool the reference, which is precisely the property
the leaderless model is valued for not having. The patch is kept out of tree; the block-push plumbing it
needed is not required by the touch-ups above.

## Measuring it

`Pre-build reconcile: {...}` lines appear in the log only when the reconcile fetched something or found a
same-tip peer disagreeing. Fork rate: `grep -c "Fork state: reorg" logs/log.log` per hour, and
`/rollback_stats`. Baseline before the perf fix + touch-ups (08-31): 5–14 reorgs/hour, 9–11 s/block.
