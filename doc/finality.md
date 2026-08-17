# Finality & fork recovery — the two-floor model

**Status: BUILT and live fleet-wide since 2026-08-17** (commits `0386c269` → `e75b7642`, deployed by the
`/update` wave — no height gate; the new meta key is outside the consensus root, so a mixed fleet commits
identical roots during the rollout).

This document is the authoritative description of how NADO finalizes blocks and how a node recovers from
being on the wrong side of a fork. It replaces the older single-floor description scattered across
[consensus-hardening-plan.md](consensus-hardening-plan.md) (#17) and code comments.

---

## 1. Why one floor was wrong

The original rule: `finalized_height = max(prev, tip − FINALITY_DEPTH)` (45 blocks ≈ 4.5 min), monotonic,
and **un-crossable** — `rollback_one_block` raised `FinalityViolation` below it.

Depth is a **local observation** ("no reorg reached this deep in 4.5 minutes"), not an agreement. Treating
it as immutable meant that in *any* fork lasting longer than 4.5 minutes, **both branches locked their own
floor** above the common ancestor. From there no legal rollback could reach the divergence point, and every
recovery had to *cross* a floor — the escalated `floor=0` re-anchor, which imports a peer snapshot over the
local chain wholesale.

Measured on 2026-08-17, one day: eight floor-crossing recoveries, two of which **truncated this archive
node's history** (0→49735, then →56735 — blocks 0–49734 existed only on that box and are gone), and one
stranded the execution layer on an abandoned branch.

Meanwhile the FFG machinery — duty committee, ⅔-seat quorum with an inactivity leak, two-consecutive
justification, slashable attestations ([consensus-aggregation.md](consensus-aggregation.md)) — was fully
built and **could never win the floor `max()`**: `ffg_final ≤ tip − 60 < depth_final = tip − [45..59]`.
Quorum finality was observational; observation was law.

## 2. The two floors

| Floor | Value | Role | Crossable? |
|---|---|---|---|
| `hard_finality` (meta, **root-excluded**) | `max(prev, ffg_checkpoint, tip − FINALITY_HARD_BACKSTOP)` | What rollback refuses (`FinalityViolation`), what classifies a fork DEAD vs recoverable, the re-anchor candidate floor | **Never.** Reverting it means >⅓ of bonded seats equivocated — slashing's problem, not rollback's |
| `finalized_height` (depth, meta, root-excluded) | `max(prev, tip − FINALITY_DEPTH)` | Feeds the exec layer, pruning, snapshots, `/status` — the *latency-sensitive* consumers | **Yes**, above the hard floor: rollback lowers it as it crosses; incorporate re-derives it on the new branch (reading the **persisted** value, never the memserver mirror — a stale mirror would resurrect the old branch's floor one block later) |

- `FINALITY_HARD_BACKSTOP = 10 × EPOCH_LENGTH = 600` blocks (~1 h). The backstop is the liveness bound the
  old depth floor provided, minus the hair trigger: a stalled committee bounds long-range/51 % exposure at
  an hour instead of unbinding it, and an honest fork must persist a full hour — with the corroboration
  gate *also* failed throughout — before floors lock.
- **Both floors advance only through `_depth_floor_corroborated`**. This matters *more* with FFG
  load-bearing: the justification denominator leaks inactive seats out after `INACTIVITY_WINDOW` epochs, so
  the minority side of a >3-epoch partition would otherwise become >⅔ of its own "active" stake and
  FFG-finalize its own fork — a self-inflicted permanent wedge.
- `hard_finality` is in `ROOT_EXCLUDED_META_KEYS` **from its first deploy**. It is derived through the
  node-local corroboration gate, so two honest nodes at the same tip can hold different values; letting it
  into the root is the h10047 index-watermark fleet-split class. Tested through `_root_triples` itself,
  not just the constant.
- The escalated `floor=0` re-anchor **is gone**. The re-anchor floor is the hard floor, escalated or not:
  crossing a quorum-signed checkpoint is never recovery, it is joining an equivocation. On a young chain
  (`hard == 0`) this degenerates to the old behaviour exactly.
- `FINALITY_DEPTH` itself and every window derived from it (duty/reveal windows, status display) are
  unchanged, and so is exec-follow latency.

## 3. Fork recovery: measured evidence only

The one rule, enforced at every layer that can revert state (it has destroyed state twice when violated —
2026-08-03 exec wipe, 2026-08-17 archive truncations):

> **Absence of information is never evidence of divergence.** Only a parsed answer that *disagrees* is.

### 3a. Classification

`ops/fork_resolution.resolve` finds the highest height where our hash agrees with the peer majority (hash
probes, seeds first, ≥2 answers), then classifies against the **hard** floor:

| Verdict | Meaning | Action |
|---|---|---|
| `BEHIND` / `SYNCED` | our chain is a prefix of the majority's | forward sync — **never** a rollback |
| `REORG` | proven divergence, ancestor above the hard floor | roll back **toward the ancestor**, then fast-forward |
| `DEAD_FORK` | divergence at/below the hard floor | the re-anchor ladder, then the purge escape |
| `UNKNOWN` | could not measure | do nothing — ignorance never reverts |

The full verdict (including the ancestor) is cached 60 s (`FORK_STATE_TTL_S`) and **invalidated whenever
the tip it described stops existing** — on landing at the ancestor and after any fast-forward — so a stale
`REORG` can never roll back the majority chain a node just adopted.

### 3b. Emergency sync (`loops/core_loop.emergency_mode`)

Historically the reorg decision was a single donor's `knows_block` answer, and that call collapsed
"couldn't answer" into "doesn't know" — so a 5 s timeout reverted a real block, and a flaky donor could eat
a 40-block burst probing blindly (2026-08-17 baseline: 634 episodes, 2,609 rollbacks, 20 exhausted bursts,
on a healthy chain; historically 88 % of episodes end <10 s and are spurious — and emergency rollback
storms are the one mechanism that has actually corrupted state, h4260). Now:

1. **Verdict first, donor second.** Each pass evaluates the measured verdict *before* selecting a donor.
   `REORG` rolls straight toward the ancestor with **no donor round-trips** (donor selection keys off the
   heaviest *advertised* tip, which flip-flops between a split's sides — a same-fork donor "knows" our tip
   and fast-forward would re-inflate the fork just rolled back; observed live at the 62655 split).
2. **`knows_block` is tri-state.** `True` = the peer serves our hash; `False` = it **answered** with a
   different hash (positive evidence); `None` = unreachable / timeout / 404 (a donor momentarily behind us
   404s our height) / malformed — evidence of nothing. `None` never rolls back; three *consecutive*
   non-answers strike the advertised tip (a mute donor pool must not pin the node), never the chain.
3. **The burst is bounded by the proven ancestor.** Reaching it with the donor still disagreeing means a
   stale verdict or a lying donor; rolling past a proven ancestor is pure loss either way.
4. A positive mismatch with a non-`REORG` verdict is one peer against the probe quorum: strike the tip it
   advertised, never the chain.
5. **Ties resolve ONCE, at the first divergent block.** Weight increments are content-independent, so
   a same-height split is a *permanent exact tie* — and the old lowest-TIP-hash tie-break re-rolled every
   block, flipping which side should switch faster than any reorg could finish (the hours-long see-saws).
   `fork_resolution.tie_winner` compares the branches' blocks at ancestor+1 — a value that never changes
   as the branches grow — so both sides compute one permanent winner and exactly one side reorgs, once.
   The winning side keeps producing (see the production gate below), which starves the losing branch and
   makes the majority strictly heavier — repairing the very weight signal whose tie caused the stall.
6. **Possession before rollback** (`_adopt_branch`). The old order — roll toward the ancestor, then hope
   a donor serves the better chain — made disruption free: any advertisement surviving the verdict probes
   cost real rollbacks and churn even when nothing valid was ever served. Now the competing branch is
   FETCHED FIRST (walked by parent-hash from the advertised tip to the measured ancestor), pre-verified
   (content hash, linkage, the weight claim), and only then does the node roll to the ancestor and apply
   it through the one canonical apply path — `verify_block` re-derives and enforces everything the
   pre-check cannot know without state. A branch failing mid-apply costs the advertiser a benched tip and
   us seconds: our own bodies are still in the store and are re-applied. An attacker must now present a
   held, hash-consistent, heavier branch that survives full validation to cause ANY revert.
7. **Production is suppressed on a measured minority fork.** Deterministic production means both sides of
   a mempool split advance every slot at near-equal weight — the heavier-tip gate never fires, and both
   sides extend their forks for hours. The produce slot now consults the verdict when the peer majority's
   tip hash differs from ours *and* the mismatch has persisted `MINORITY_GRACE_S` (so block-boundary
   propagation lag never fires a probe): positive `REORG`/`DEAD_FORK` skips the slot; `UNKNOWN`/`BEHIND`
   never halt production (ignorance must not stall a partitioned node, and the seeds-first headcount
   resolves an even split toward the seeded side). Per-node suppression cannot stall the network —
   production is replicated, so any node on the majority branch builds the identical canonical block.

Live validation: under a real two-sided split at 62655, the final code burst-rolled 62663→62655 in one
second, the fresh probe flipped to `behind`, a majority donor attested, fast-forward converged (hash-
verified at 62748). Five-minute churn after: 0 rollbacks, 0 exhausted bursts.

## 4. Wedge recovery keeps the canonical chain

A fork above the finality floor means every block **below** the fork point is *common to both chains* —
the majority chain's own history, not fork debris. Re-anchoring used to wipe it (`adopt_new_identity`
reset the segment store; the windowed snapshot import replaced the deep number↔hash index; the backfill
refetched a fixed 265-block window). **An archive node must come out of recovery with every canonical
block it went in with** (operator requirement, 2026-08-17):

- Block bodies are **kept and reconciled**, not wiped: a body's hash covers its bytes, so a body on the
  adopted chain *is* vouched for by the new identity. `ops/canonical_restore` (pure, exhaustively tested)
  computes the fork point from the old index (captured before import) vs the new, keeps everything below
  it, unreferences only bodies it can positively name as fork bodies, re-puts the deep index rows the
  windowed import dropped, and lists what is canonical-and-missing — highest first.
- The rollback window is fetched synchronously; on an archive node the deep remainder fills in a
  background thread, extending past the lowest index row by parent-hash walk to genesis. Whatever a donor
  cannot supply stays missing and is re-requested — the plan is recomputed from what is actually on disk.
- **Archive self-repair** (`_maybe_refill_archive`): an archive whose history stops short of genesis
  looks for a peer that reaches deeper every 10 min and fills the gap, without waiting for a re-anchor.

## 5. The execution layer's side of a revert

The exec node applies only depth-finalized blocks — and the depth floor is now legally crossable, so exec
must survive its regression. See [rollups-and-settlement.md](rollups-and-settlement.md) §2b for the
mechanism: parent-linkage checked before every applied block, a hash-only probe every poll, rewind
checkpoints + settle-stash rungs, and a recovery ladder that only ever lands somewhere strictly better
(rewind → cold-replay iff the L1 archive is contiguous from genesis, keeping DA → bootstrap → STRANDED,
kept state, retried every poll and exposed machine-readably on `/exec/root`).

## 6. Honest limits (2026-08-18)

Stated so a reader trusts the right amount — over-trust is a worse failure than any single gap:

- **The math is PoS-grade; the decentralization isn't yet.** The fleet is eight nodes and the bonded
  registry is small: ⅓ of the seats — the equivocation threshold behind `hard_finality` — is a handful of
  validators, most operated by the same project. Every guarantee above should be read as "against this
  validator set". The mechanisms are built for the larger set; the larger set does not exist yet.
- **Verdicts are stake-weighted, but the stake is the same small registry.** `/hash_attest` +
  `probe_block_hash_signed` close the per-IP Sybil softness (a swarm adds headcount, a validator adds
  seats, seeds remain the unsigned liveness fallback) — bounded griefing is now bounded harder, but
  "⅔ of seats" still names a small club.
- **Slashing is now automatic, and lightly battle-tested.** The watchtower
  (`memserver.maybe_watchtower_slash`) turns an observed FFG double-vote into a submitted slash with no
  human in the loop, exercised end-to-end with real keys in `tests/test_watchtower_slash.py` — but it has
  never fired against a real adversary, and the penalty economics (SLASH_BOND_PENALTY vs what an attack
  earns) are untested at scale.
- **Forks are contained, not prevented.** Splits still originate in mempool divergence; the machinery
  above makes them resolve in seconds instead of hours and makes reverting cost an attacker a real
  branch. The known admission-order driver ("Empty account" while the funder is still in the pool) is
  fixed; sustained-load pool divergence (mempool-full eviction under pressure) is not exercised yet.

## 7. File / test map

| Piece | Code | Tests |
|---|---|---|
| Floors | `protocol.py` (`FINALITY_HARD_BACKSTOP`), `ops/account_ops.py` (`get/set_hard_finality`), `loops/core_loop.py` (two-floor advance), `rollback.py` (hard-floor refusal + depth lowering), `ops/snapshot_ops.py` (root exclusion) | `tests/test_two_floor_finality.py` |
| Classification | `ops/fork_resolution.py`, `core_loop._fork_state/_fork_verdict` | `tests/test_fork_resolution*.py`, `tests/test_dead_fork_*.py` |
| Emergency gating | `ops/block_ops.knows_block` (tri-state), `core_loop.emergency_mode` / `_rollback_one_for_reorg` | `tests/test_emergency_rollback_gating.py` |
| Canonical restore | `ops/canonical_restore.py`, `core_loop._restore_canonical_chain/_start_deep_fill/_maybe_refill_archive`, `ops/snapshot_ops.adopt_new_identity`, `ops/kv_ops.wipe_non_carried_dbs` | `tests/test_reanchor_archive_backfill.py`, `tests/test_canonical_restore_executor.py` |
| Exec revert/rewind | `execnode/execnode.py` (probe, linkage, checkpoints, ladder) | `tests/test_exec_finality_revert_probe.py`, `tests/test_exec_rewind_e2e.py` |

Every suite above is mutation-checked: the load-bearing rules were each broken deliberately and observed
to turn the suite red before any of this shipped.
