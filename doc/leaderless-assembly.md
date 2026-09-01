# Leaderless block assembly — shared block production without a proposer

*Design document. Companion page: <https://nadochain.com/production> (live view + simulation).*

NADO has **no block proposer**. Every node assembles every block itself, from its own copy of the chain and
its own mempool, and the protocol is arranged so that honest nodes assembling the same height compute the
**identical block**. Nothing is proposed, nothing is voted on per block, no block is raced across the wire,
and no party can delay or censor a slot — because no party owns one.

This document is the complete description of that model: the block function and what makes it
deterministic, the one input that can differ (the mempool) and every layer that keeps it equal, what
happens when it still differs, how fork choice and finality sit on top, the threat model, the parameters,
and the incidents that shaped the current rules.

---

## 1. The model in one paragraph

A block at height *h* is a **pure function** `B(parent, beacon, registries, pool)`: the producer (the
*winner*) is a deterministic stake-and-fidelity-weighted draw keyed by the epoch beacon; the transaction set
is the mature subset of the pool targeting *h*, sorted by txid; reward, cumulative fees and fork weight are
recomputed from parent state; the block hash covers all of that and nothing local. Every node evaluates
`B` on its own tip as soon as its pacing slot arrives and incorporates the result. Two nodes with the same
parent and the same pool therefore produce the same hash without exchanging a byte. The winner is credited
by *address*, so it need not be online at all — a phone with its tab closed can win, because any node's
evaluation of `B` credits it.

Compare the proposer model (Tendermint, Tenderbake, Ethereum): one node is elected to build, everyone else
waits for its block and (in BFT variants) votes on it. That solves "which transactions?" by fiat — the
proposer's pool is the reference — at the cost of a party that can delay or censor its slot, of latency
while everyone waits, and of a signature every block depends on. NADO solves the same question by
**making the input equal**, which costs bandwidth (a few hundred bytes of txids per block) instead of trust.

---

## 2. The block function

`ops/block_ops.construct_block` / `get_block_candidate`; verification in `loops/core_loop.verify_block`
and `rebuild_block`.

| field | source | in the hash preimage? |
|---|---|---|
| `block_number`, `parent_hash` | local tip | yes |
| `block_creator` (the winner) | `select_producer_two_lane(open_registry, bonded_registry, beacon, slot)` — `ops/mining_ops.py` | yes |
| `block_transactions` | `match_transactions_target(pool, h)`: txs with `min_block ≤ h ≤ max_block` (or exact-landing txs targeting *h*), reserved txs de-duplicated, blobs capped to the per-block byte budget, **sorted by txid** | yes |
| `block_reward`, `cumulative_fees` | `get_block_reward()` (emission schedule), parent + this block's fees | yes |
| `cumulative_weight` | parent + `block_fork_weight(bonded_registry)` = bonded shares as-of-parent + 1 | yes |
| `state_root`, `exec_root`, `exec_cursor` | L1 state as-of-parent; settled exec root as-of-parent | yes |
| `block_timestamp` | local clock, clamped ≥ parent's | **no** |
| `chain_id` | label | **no** |
| `block_signature` | optional; only the winner may attach it | **no** |

The three "no" rows are what make cross-node identity possible: nothing that depends on a local clock,
a local key, or a label can change the hash. Verification (`verify_block`) re-derives every "yes" row from
its own state and refuses a block that disagrees — a peer cannot misattribute the winner, inflate the
reward, forge weight or claim a different state root. `rebuild_block` reconstructs an incoming block from
its transaction list and compares hashes, so the *only* information a block really carries is its tx set.

**Producer selection** (`doc/mining.md`): two lanes. `OPEN_BPS` = 30 % of slots go to the open lane
(presence-leased identities, weight 2..10 by fidelity, capital-free); the rest to the bonded lane (stake-
weighted, RANDAO-gated). Both draws are integer arithmetic over sorted registries and the epoch beacon —
the same on every node and in the browser wallet's JS mirror.

**Timestamps.** The only timestamp rule is `block_timestamp ≤ now + BLOCK_TIMESTAMP_DRIFT`. Since the
timestamp is outside the hash, honest nodes with skewed clocks still agree on the block; it exists for
display and for the `old_block` heuristic, not for consensus.

---

## 3. The one input that can differ: the mempool

If every node evaluates the same function, disagreement can only come from a different input. Parent,
beacon and registries are committed chain state — identical by construction. The mempool is not: it is a
distributed set that converges over a few hundred milliseconds per hop. **A transaction that reached node
A but not node B before the slot is the only way two honest NADO nodes build different blocks.**

Everything in this section exists to make that window as small as possible, and §4 handles what remains.

### 3.1 Push gossip (`ops/gossip.py`, `nado._gossip_worker`)
A node that accepts a transaction for the first time POSTs it to all its peers immediately (minus the one
it came from). First-sight only: a duplicate returns "Already present" and is never re-pushed, so the
epidemic terminates the moment every node has the tx. One hop per edge; ~100 ms mesh-wide. Best-effort —
a failed push is picked up by 3.2.

### 3.2 Pull reconcile (`memserver.merge_remote_transactions`, every ~1 s)
Nodes advertise a pool hash in `/status`. For each peer whose hash differs, a node fetches the peer's txid
list (`/transaction_ids`, ~64 B per tx), diffs against what it holds and what is already mined, and fetches
only the missing bodies (`/transactions_by_id`). This is the correctness backstop for anything push missed
(a node that was down, a dropped packet, a late joiner). Refused transactions cool down by reason
(`reject_cooldown_s`): terminal refusals (bad signature, already mined…) for 60 s; transient ones ("not
funded *yet*", exec-settle skew) briefly or not at all, so pools re-converge as soon as the refusal resolves.

### 3.3 Inclusion delay (`protocol.TX_INCLUSION_DELAY`, `FLEX_TX_MIN_MARGIN`)
A flexibly-landing transaction carries a signed `min_block` — the earliest height any node may include it —
set by the submitter to *tip + 8* (user txs) or *tip + 30* (per-epoch system txs). That gives 3.1/3.2 a
head start of several blocks over assembly: by the time any node is *allowed* to include the tx, it has
been everywhere for most of a minute. `max_block` is the expiry. Exact-landing txs (bond, register, duty,
settle) instead target a height far enough ahead (`RESERVED_TX_MARGIN` = 30 blocks) for the same reason.

### 3.4 Pool warm-up (`memserver.pool_warmed`)
A freshly restarted node has an empty pool, and "my pool differs" turns straight into a same-height fork
under deterministic production. A node does not mint until it has completed one pull reconcile with a
peer (or 60 s have passed with a mute mesh, for liveness).

### 3.5 Pre-assembly reconcile (`memserver.reconcile_next_block_set`, `GET /next_block_txids`) — 2026-09-01
The layers above converge pools in ~1 s passes; the `/status` agreement signal is polled every ~10 s. Both
are slower than a 6-second block. So, **once per tip, right before it builds**, a node asks its peers the
exact question that matters: *what would you put in the next block on this tip?* — the set their
`upcoming_block_hash` hashes, served from the same cache, ~64 B per tx, 1.5 s budget. From every peer **on
the same tip** it takes the txids it lacks (never one already mined), fetches those bodies (3 s budget,
`asyncio.wait_for`), merges them through the ordinary admission path — every fetched tx is fully validated,
nothing is trusted — and only then evaluates `B`. Every peer does the same against us, so the mesh
converges on the **union** of its next-block sets inside the slot. A peer that does not answer in time
simply sits the pass out; nothing can hold production beyond the budget.

Logged as `Pre-build reconcile: {...}` only when it fetched something or found a same-tip peer disagreeing;
a quiet mesh stays quiet.

### 3.6 Admission that does not diverge on its own
A refusal is itself a divergence if some nodes refuse what others accept. Two rules follow:
- **No sender-wide purge** (2026-09-01). An "Overspending balance" refusal of a remote tx used to purge
  every pooled tx of that sender. Such a refusal is routinely branch/timing skew — a dividend credit or a
  funding tx one node has applied and another has not yet — not a double-spend attempt, and the purge made
  the refusing node's pool diverge from every peer that kept the sender's other txs. Now only the refused
  tx is declined; it cools briefly and is re-tried. Double-spends still cannot land: `verify_block` enforces
  whole-block spending and `_candidate_pool` keeps our own candidate within balance.
- **Never reject for timing on some nodes only.** A "min_block too close to my tip" admission floor was
  considered and rejected: the nodes ahead would refuse a tx the stale relay keeps, which *creates* the
  split it meant to prevent. The consensus boundary is `min_block` itself, agreed by everyone.

---

## 4. When two blocks still appear at one height

With everything in §3, a same-height split requires a tx to arrive at one assembler in the last few
hundred milliseconds before the slot and at another just after. It happens; the protocol resolves it
deterministically and cheaply.

### 4.1 Fork choice is weight
`cumulative_weight` = Σ (bonded shares as-of-parent + 1). Between branches of different weight, the heavier
wins, always. A same-height split from a mempool difference is an **exact tie** — weight is content-
independent — and stays one until something (a `bond` landing on one side) breaks it.

### 4.2 The tie-break: the more complete pool wins (`ops/fork_resolution.tie_winner`)
For an exact tie both sides look at the **first divergent block** (ancestor + 1) — it never changes as the
branches grow, so the answer is permanent — and compare:

1. **strict superset of transaction ids wins**;
2. otherwise the **larger** set wins;
3. equal-size sets: the **lowest block hash** wins (the pre-2026-09 rule, kept as the last resort);
4. if either body is unavailable, both sides use rule 3 (never one-sided).

Symmetry: `tie_winner(a, b, X, Y) == "ours"` iff `tie_winner(b, a, Y, X) == "theirs"` — both nodes compute
one answer; exactly one side reorgs, once (`tests/test_leaderless_touchups.py`). Consequences: the block
built from the more complete pool becomes canonical; the losing node can validate and adopt it immediately
because the block *carries* the transaction it lacked; the transaction lands instead of waiting for a
re-mine; and "propagate faster" is the winning strategy rather than a lottery. A one-block split resolves
inline (`_inline_tip_swap`) without entering emergency mode, so finality never freezes over it.

Why not the old hash-only rule: it ignored which block was actually built from the better view, so the
tx in the losing block was dropped and re-mined, and a bond landing on either side later flipped the
verdict mid-reorg (the 08-31 see-saw, §7).

### 4.3 Deeper splits
If branches have grown, the measured verdict machinery (`fork_resolution`, `core_loop._fork_verdict`)
locates the ancestor by probing peers, weight decides, and `_adopt_branch` fetches and pre-verifies the
whole competing branch **before** rolling back a single block (possession-before-rollback), then applies
it through the one canonical path. Rollbacks are budgeted by the measured span and hard-capped by the
finality floor.

### 4.4 Finality (`doc/finality.md`)
Two floors: the stake-signed FFG checkpoint plus a liveness backstop (`hard_finality`, un-crossable), and a
depth floor. A split can never undo what is final; a node asked to roll below the floor refuses and
re-anchors instead. Nothing in the tie-break touches this.

---

## 5. Why not a leader — the decision (2026-09-01)

A designated-assembler rule was fully built and unit-tested that day: per-slot ranked assemblers drawn
stake-weighted from leased bonded *nodes* (69 % of bonded stake is browser auto-bond that can never
assemble), rank folded into fork weight so a rank-0 block strictly outweighs a rank-1 block, blocks pushed
to peers on acceptance, and an open unsigned fallback after the last rank for liveness. It was set aside.

The reasoning: it fixes the same-height race by making **one node's pool the reference**, which is
precisely the property the leaderless model is valued for *not* having — a slot owner who can delay or
exclude, a signature the chain depends on, latency spent waiting. The race is better attacked at its source
(pool agreement at the slot, §3.5) and at its resolution (favour the more complete pool, §4.2). Both ship
as node behaviour with no change to block validity, and both preserve: any node builds the canonical
block, the winner may be offline, no signature is required, no party is special.

---

## 6. Threat model

| threat | outcome |
|---|---|
| **Censorship of a transaction** | No slot owner to bribe or coerce. A node that omits a mature tx builds a block that is a strict *subset* of its honest peers' — it loses every tie (§4.2) and, since peers also assemble, its omission is simply not the canonical block. |
| **Withholding** (build, don't share) | Meaningless: peers do not need your block, they compute their own identical one. |
| **Grinding** (choose txs to steer the winner) | The winner depends on the beacon and registries only, never on the tx set (`doc/mining.md`, RANDAO commit-reveal with withholding penalties). |
| **Timestamp games** | The timestamp is outside the hash; only `≤ now + drift` is enforced. |
| **Equivocation** | A winner who signs two different blocks at one height produces an equivocation proof (`verify_equivocation_proof`, slashing). Unsigned blocks carry no authorship claim to equivocate on. |
| **Pool poisoning** (feed one node a tx nobody else has) | The tx is valid (or it is refused at admission), it is gossiped onward (§3.1), and a block that includes it is a superset — the network adopts it. The attacker paid a fee to have their tx included. |
| **Flooding the reconcile** | `/next_block_txids` and `/transactions_by_id` are rate-limited per IP (peers exempt), id lists are bounded (≤ 200 fetched per peer per pass, ≤ 1000 per request), bodies are size-capped, budgets are 1.5 s + 3 s per slot. |
| **Sybil in the open lane** | Bounded structurally by `OPEN_BPS` (30 % of slots regardless of identity count) and priced by the sequential PoSW lease (`doc/ip-spoofing-and-sybil.md`). Unrelated to assembly. |

---

## 7. Incidents that shaped the rules

- **Same-height splits from restart waves** (blob h67007, bond h68376, duty h68345): an empty pool after
  restart → the warm-up gate (§3.4).
- **Fork seed h67761**: a sweep tx eligible ~6 s after submit through a stale relay → `FLEX_TX_MIN_MARGIN`
  30 for per-epoch system txs (§3.3).
- **Hours-long see-saws at 62655/62895** (2026-08-17/18): the tie-break compared *tip* hashes, which
  re-rolled every block → the permanent first-divergent-block rule (§4.2, rule 3).
- **Fleet freeze 2026-08-23**: graft-point mismatch, fixed rollback budget, mid-branch abandonment,
  headcount suppressing the heaviest branch → the possession-before-rollback adoption and weight-first
  rules (§4.3; `doc/testnet.md` for the repeatable scenarios).
- **2026-08-31 21:55, ancestor 76848, 24 deep**: branches differing only in `collect_dividend` /
  `dividend_withdraw` / contract-call txs, weights 0.01 % apart once a `bond` landed on one side, and this
  node applying blocks in 3 s at a 6 s block time (a full-state walk per block; fixed the same day). Three
  branch adoptions and 12 minutes to settle. → the pre-assembly reconcile (§3.5), the most-complete-pool
  tie-break (§4.2), no sender-wide purge (§3.6).

---

## 8. Parameters

| parameter | value | where |
|---|---|---|
| block time (pacing, not consensus) | 6 s | `protocol.BLOCK_TIME` |
| `TX_INCLUSION_DELAY` | 8 blocks | user txs' `min_block` = tip + 8 |
| `FLEX_TX_MIN_MARGIN` | 30 blocks | per-epoch system txs |
| `RESERVED_TX_MARGIN` | 30 blocks | exact-landing txs |
| `TX_LANDING_WINDOW` | 360 blocks | admission cap on `max_block` |
| pull reconcile cadence | ~1 s | `loops/peer_loop.py` |
| pre-assembly probe / fetch budgets | 1.5 s / 3 s | `memserver.reconcile_next_block_set` |
| ids fetched per peer per pass | ≤ 200 | same |
| `/next_block_txids` rate limit | 120/min per IP, peers exempt | `nado.next_block_txids` |
| `OPEN_BPS` | 30 % | `protocol.py` |
| `BLOCK_TIMESTAMP_DRIFT` | 30 s | `protocol.py` |
| `FORK_STATE_TTL_S` | verdict / tie cache | `protocol.py` |

---

## 9. Operating and measuring it

- `GET /next_block_txids` on any node: `{tip, height, txids}` — ask several nodes on the same tip; the lists
  must be identical when the mesh is converged.
- `GET /status`: `upcoming_block_hash` (the hash of that set) and, in the consensus loop's debug log,
  `Upcoming-block agreement: N%` across same-tip peers.
- `grep "Pre-build reconcile" logs/log.log` — non-empty only when the reconcile fetched something or saw
  disagreement; `grep -c "Fork state: reorg"` per hour and `/rollback_stats` for the fork rate.
- Baseline before the 2026-09-01 changes (08-31): 5–14 reorgs/hour, 9–11 s effective block time.
  After the perf fix alone (13:21): 6.3 s/block. Track the reorg rate over the following days to judge the
  touch-ups; the expected steady state is a handful of one-block inline swaps per day, no deep reorgs.

---

## 10. Test coverage

- `tests/test_leaderless_touchups.py` — tie-break rules and symmetry, next-block set == the hashed set,
  wiring (reconcile before build, once per tip, same-tip filter, mined-tx exclusion, time bounds,
  ordinary admission, no purge).
- `tests/test_fork_resolution.py`, `test_productive_fork_escape.py`, `test_emergency_*` — verdicts,
  adoption, budgets, escapes.
- `tests/test_mempool_reject_cooldown.py`, `test_mempool_at_most_once.py` — admission behaviour.
- `scripts/testnet/test_fork_resolution.py` — multi-node scenarios on loopback (`doc/testnet.md`).
