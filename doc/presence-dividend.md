# Presence dividend — smoothing the open lane from a jackpot into a stream

> **Status: design proposal (not implemented).** This describes *variant (b)* from the reward-redistribution
> discussion: keep open-lane block **production** decentralized, but split the open-lane block **reward** into a
> small producer tip plus a redistributed **presence dividend**, accrued off-L1 on the execution layer and
> withdrawn in aggregate. Locks nothing until we agree the parameters.

## 1. The problem

Block production is **winner-take-all per block**: each slot has exactly one producer who takes the whole
reward. With `P` open-lane miners, any individual wins a block roughly once every `P` slots. At populace scale
(tens of thousands to millions of phones) that means:

- expected take is still `emission / P`, but it arrives as a **rare jackpot**, not a steady wage;
- most miners see **nothing** for very long stretches — the lane *feels* empty even when it's working;
- the psychology is a lottery, which is the opposite of "open a link and everyone participates."

We want the open lane to feel like **participation**, not a lottery: many people getting a little, steadily.

## 2. The economic truth (state it up front)

Redistribution **does not create more reward.** With a fixed subsidy, everyone's expected take is `emission / P`
no matter how it's paid. What changes is **variance**: winner-take-all pays that as a rare jackpot; a dividend
pays the same amount as a smooth dust stream. So this is an **inclusion/variance** change — a *presence
dividend / universal basic mining* — not a "more people get more" change. Be honest about that in the UI.

## 3. Hard constraints (the two walls)

Any redistribution design MUST respect both, or it is dead on arrival:

1. **No `O(P)` L1 writes per block.** Crediting a million micro-balances every ~8 s bloats state without bound
   and stalls the node. The **L1 stays `O(1)` per block**; all per-capita accounting happens **off-L1**.
2. **No flat-per-identity payout.** A dividend that pays each present identity equally *pays by headcount* —
   exactly what the 20% cap, the PoSW lease, and fidelity exist to neutralize. Flat-per-identity is a **Sybil
   faucet** (a million masks each collect dust = the farm collects a lot). The dividend **must** be weighted by
   a Sybil-costly metric. We use **fidelity** (continuous presence), which already costs PoSW recurrence to fake.

## 4. Design (variant b)

### 4.1 Split the open-lane block reward
Today an open-lane block reward `R` is split producer/treasury via `protocol.split_block_reward` (90/10).
Change the **open-lane** split (bonded-lane blocks are unchanged) to three ways:

```
treasury  = R · TREASURY_BPS/10000            (unchanged, 10%)
tip       = R · OPEN_TIP_BPS/10000            (small — the producer's cut for actually building the block)
dividend  = R − treasury − tip                (the rest — goes to the presence-dividend pool)
```

- **`tip`** is credited to the selected open producer **on L1** (`O(1)`, exactly like today's producer credit) —
  this keeps block production a paying job, so the open lane stays a decentralized *producer* set, not just a
  crowd of dust collectors.
- **`dividend`** is credited on L1 to a single reserved recipient — the **dividend pool** (add `"dividend"` to
  `RESERVED_RECIPIENTS`). One account, so still `O(1)` on L1. The pool simply accrues the redistributed emission.

Bonded-lane blocks keep winner-take-all (those are real producers doing real work, `O(1)`, and Sybil-priced by
stake). Only the **open** lane is redistributed.

### 4.2 Accrue the dividend off-L1 (execution layer)
The execution node already tails L1 blocks and keeps cheap KV state off-L1 (Phase 1) and settles a state root to
L1 by bonded quorum (Phase 2). It becomes the **dividend accountant**:

- Each epoch it knows the present open registry and every present miner's **fidelity weight** `w_i`
  (`OPEN_BASE_FLOOR..OPEN_BASE_FLOOR+OPEN_FID_BONUS`, i.e. 1..10) — the same weight the lane draw already uses.
- It distributes that epoch's pooled `dividend` **pro-rata by `w_i`** into each miner's **off-L1** dividend
  balance.

**Scalability — the accumulator index.** Do NOT loop over all miners each block. Keep one global running sum:

```
rewardPerWeight += epochDividend / Σ w_i        // one add per epoch, O(1)
```

Each miner carries a checkpoint `(w_i, rewardPerWeight_at_checkpoint)`. Their **claimable** dividend is

```
claimable_i = w_i · (rewardPerWeight − rewardPerWeight_at_checkpoint_i)
```

computed lazily. The exec node already processes each miner's heartbeat once per epoch (to update
presence/fidelity) — **piggyback the checkpoint there**: when `w_i` changes, settle `claimable_i` into their
stored balance and re-snapshot. So the per-epoch cost is `O(active miners this epoch)` — the inherent cost of
tracking who's present — and it is **off the consensus path**, on a machine that isn't a phone. (Standard
Synthetix/Curve-style reward accounting; the only NADO-specific wrinkle is that `w_i` changes per epoch, which
the heartbeat-time re-checkpoint handles.)

### 4.3 Withdraw in aggregate (no dust on L1)
Dividend balances live **off-L1** and only touch L1 when a miner **withdraws an amount worth the fee** — via the
Phase-2 path already built: the exec state root is settled on L1 by bonded quorum, and a **Merkle proof** of the
miner's accrued balance against that root releases the aggregate to their L1 balance (mirror of the bridge
withdrawal + a nullifier so each accrual epoch is claimed once). So:

- no per-block, per-miner L1 writes — ever;
- dust never bloats L1 state — it accumulates off-L1 and **materializes only once it's meaningful**;
- the withdrawal is trust-minimized (proved against the quorum-settled root), not a custodial promise.

## 5. Why this doesn't reopen the Sybil hole

- The dividend is **fidelity-weighted**, and fidelity is continuous-presence — a fresh mask starts at the floor
  (`w=1`) and only ramps with real elapsed epochs of presence, each of which now costs a **PoSW recert** to
  sustain (see [ip-spoofing-and-sybil.md](ip-spoofing-and-sybil.md)). So a flood of new masks splits a floor-weighted
  sliver, not an equal cut.
- The dividend is drawn **only from the open lane's `OPEN_BPS` (20%)** emission. The [reward-capture theorem](reward-capture-theorem.md)
  still holds: a free/Sybil actor cannot pull more than ~20% of emission, redistributed or not. Redistribution
  changes *who inside the 20% gets paid and how smoothly* — it does **not** enlarge the 20%.
- Net: the dividend inherits the exact Sybil bound the architecture already proves. It is **not** "outside" the
  security architecture — it is deliberately *coupled* to it (fidelity + the 20% cap), which is the only way a
  per-capita payout can be safe.

## 6. The one incentive to tune: the producer tip

If `OPEN_TIP_BPS` is too low, an open producer has little reason to actually assemble and broadcast the block
(they'd collect their dividend share whether they produce or not) → liveness/censorship-resistance weakens. Too
high, and it's just winner-take-all again with extra steps. The tip must be **the smallest cut that reliably
motivates producing** given the ~1 block/`P` chance of being selected. Start with a modest value (e.g.
`OPEN_TIP_BPS = 2000` → the producer keeps 20% of the open block, 70% is redistributed, 10% treasury) and tune
from observed liveness. An alternative that removes the question entirely: pay the tip as a **flat per-open-block
constant** rather than a fraction, so it's predictable regardless of `R`.

## 7. Proposed constants (draft — all tunable)

| constant | draft | meaning |
|---|---|---|
| `TREASURY_BPS` | `1000` (unchanged) | treasury cut of every block |
| `OPEN_TIP_BPS` | `2000` | open producer's cut of an open-lane block (the rest, minus treasury, is the dividend) |
| `DIVIDEND` recipient | `"dividend"` | reserved L1 pool address the dividend accrues to (`O(1)` on L1) |
| dividend weight | `fidelity` (`w=1..10`) | per-miner pro-rata weight (Sybil-costly); **not** flat-per-identity |
| min withdraw | e.g. `≥ 100× MIN_TX_FEE` | client-side floor so a withdrawal is always worth its fee |

## 8. Trade-offs & open questions

- **Weight granularity.** Per-epoch fidelity re-checkpointing is `O(active)` per epoch. If that's too heavy at
  extreme scale, coarsen to fidelity *tiers* (change rarely) or a decaying EMA so re-checkpoints are infrequent.
- **Unclaimed dividend.** If a miner never withdraws (leaves forever), their off-L1 balance sits unclaimed. Do we
  expire it back to the pool/treasury after a long TTL, or leave it claimable forever? (Leaning: claimable
  forever; it's their earned share.)
- **Dust meaningfulness.** At true populace scale the per-epoch share is genuinely tiny; accumulation is what
  makes it spendable. The UI should show *accrued* (off-L1) balance separately from *spendable* (L1) and nudge a
  withdraw once it clears the fee floor.
- **Does the open lane still need to *produce*?** Variant (a) — bonded produces everything, open lane is pure
  dividend — is simpler but shrinks the decentralized producer set. Variant (b) keeps open producers (this doc).
  If liveness of open-lane production ever proves fragile, (a) is the fallback.
- **Client UX.** "Presence dividend: +0.0007 NADO this epoch · accrued 0.041 (withdraw when ≥ 0.1)" reads as
  *participation*, which is the whole point.

## 9. Rollout

Pre-mainnet alpha — a reward-split + reserved-recipient change is a clean consensus break, free to make now:

1. Add `OPEN_TIP_BPS` + the `"dividend"` reserved recipient; extend `split_block_reward` for the open lane's
   three-way split (bonded unchanged).
2. Execution node: dividend accumulator index + per-heartbeat checkpoint + off-L1 balance store.
3. Withdrawal path: Merkle-proof claim of accrued dividend against the settled exec root (+ nullifier), mirroring
   the bridge.
4. Client: show accrued vs spendable, and an aggregate "withdraw dividend" action.
5. Tests: split correctness + revert-symmetry (L1); accumulator/claim math + double-claim rejection (exec).

Nothing here weakens the two-lane security model — it only changes how the open lane's *already-capped* 20% is
paid out: from a per-block jackpot to a fidelity-weighted, off-L1, withdraw-when-worthwhile stream.
