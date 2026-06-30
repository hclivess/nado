# Security review — findings & status

> **Update (post-review).** This is a *historical audit snapshot*; the findings below stand as
> recorded. Several have since been addressed: the index store was migrated from SQLite to a
> schemaless **LMDB** key-value store (so the "Keep SQLite" recommendation is superseded — see
> [storage.md](storage.md) / [storage-kv-migration.md](storage-kv-migration.md)), and the first
> wave of consensus items **#15–#18** is now partially implemented (objective stake-weighted
> fork-choice, enforced finality floor, grind-proof chain weight, fail-loud beacon, a detached
> optional winner signature). See [consensus-hardening-plan.md](consensus-hardening-plan.md) for
> what is implemented vs. still planned.

A multi-agent review audited consensus/mining, P2P/sync, control-flow, ledger integrity, the
RPC/web surface, and storage; high/medium findings were adversarially verified (default-to-
refute). This summarises the verified findings and **what this relaunch fixes vs. what remains
open**. (Two review dimensions — ledger-integrity and web-surface — were re-run after the
agents returned stubs; the high-value consensus/P2P/control findings below stand.)

## Themes

1. **Bootstrap/eclipse is the soft underbelly** — most consensus risk is against a *joining*
   or *eclipsed* node (fail-open authorship, non-recomputed reward, a weak snapshot quorum).
2. **The economic engine was grindable and unenforced** — producer selection is a pure
   function of an attacker-chosen address vs. the known previous hash; the reward was only
   range-checked, not recomputed.
3. **The relaunch itself had to land determinism + atomicity fixes** or it would convert
   tolerated slop into hard consensus faults.

No confirmed finding steals funds from a fully-synced node behind an honest majority.

## Verified findings and status

| ID | Finding | Status in this relaunch |
|----|---------|--------------------------|
| M14 | `repr()`-based hashing → cross-build non-determinism | **FIXED** — canonical sorted-key JSON (`canonical_bytes`) |
| M3 | No chain-id in signed payload → cross-chain replay | **FIXED** — `chain_id` bound in tx + block, enforced |
| CO-3 / mining | `block_reward` only range-checked, never recomputed | **FIXED** — recomputed (ancestry-anchored) + enforced in `verify_block`; `rebuild_block` recomputes |
| "reward forks snapshot nodes" | tip-anchored reward walk would split full vs snapshot | **FIXED** — header `cumulative_fees`, parent-anchored, one lookback |
| LO-1 / CO-4 | `incorporate_block` not crash-atomic → double-credit on replay | **FIXED** — consolidated `index.db`, single transaction, marker committed atomically; rollback wrapped too |
| LO-2 | `rollback_one_block` spins forever on a missing parent | **FIXED** — raises `MissingParentError`; core loop resyncs |
| ~296× balance write amplification; per-call connect | perf / lock thrash / stuck nodes | **FIXED** — single guarded UPDATE; per-thread persistent connection |
| `set_latest_block_info` read-back-verify spin; `save_block`/`update_child` unbounded loops | stuck-node hazards | **FIXED** — atomic writes, bounded retries |
| CO-1 / M6 | Grindable producer selection (no VRF/stake/secret) | **DESIGN FIXED, NOT YET WIRED** — `mining_ops` provides split-neutral bonded selection over a RANDAO beacon (S4.2); replaces `pick_best_producer` in S4.3 |
| CO-2 / P2-4 | Fail-open authorship (`block_creator` not validated; IP check skipped for unknown set) | **OPEN** — fail-closed authorship is part of S4.3 (the reward half is already enforced) |
| CO-8 | Block hash sensitive to in-block tx **order**, network converges only the set | **OPEN** — needs canonical tx sort in `construct_block`/`verify_block` (planned in S4.3) |
| P2-5 / LO-3 | `reward_pool_consensus` grants +1 trust on agree **and** disagree | **OPEN** — consensus-pool reweight is part of S4.3 |
| P2-3 | Snapshot quorum trusts a vote with `min_peers` as low as 2; no state-root chain binding | **OPEN** — raise quorum floor / commit state-root in headers (future) |
| P2-1 | SSRF: outbound `/status` probe before `check_ip` | **OPEN** — filter candidates through `check_ip` before probing |
| P2-2 | Snapshot fetch allocates on attacker-controlled `chunk_count` before verification | **OPEN** — bound `chunk_count`/bytes before allocating |
| P2-8 / M10 | `/submit_transaction` does full sig-verify with no rate limit (CPU flood) | **OPEN** — per-IP rate limit + cheap pre-checks |
| (mining) | Burn-to-bribe permanent, non-decaying dominance | **REMOVED** — burn mechanics deleted entirely |

## "Wash-to-mint" (relaunch-specific)

A fee-weighted reward + grindable selection would let an attacker wash-trade high fees to pump
emission and (grindably) recapture ~90%. The defence is two-fold and **only fully holds once
S4.3 lands**: (a) reward is capped + window-averaged, and (b) selection becomes non-grindable
(bonded + RANDAO), removing the recapture path. Until S4.3, selection is still the legacy
grindable path, so the relaunch is not yet safe to run as an open-value mainnet — it is safe to
**testnet**.

## Database recommendation

**Keep SQLite; fix the usage** (done — see [storage.md](storage.md)). The latency was
connect-per-query + SELECT-then-UPDATE across separate DB files, not the engine. Consolidating
to one `index.db` + per-thread connections + single-statement updates + one-transaction
`incorporate_block` addresses all of it with zero new dependencies and preserves SQL +
pure-Python + `sqlite3`-CLI inspectability. LMDB is the only alternative worth keeping in
reserve (only if the millions of per-block files must later be folded into the DB).

## Net

The relaunch closes the determinism (M14/M3), reward-enforcement, crash-atomicity, and
stuck-node issues, and provides the *primitives* that close grindable selection. The remaining
open items (fail-closed authorship, canonical tx order, consensus-pool reweight, snapshot
quorum, SSRF/flood hardening) are concentrated in the **S4.3** integration and a small tail of
P2P hygiene — to be done and validated on a multi-node testnet before any value launch.
