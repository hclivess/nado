# Theorem — the worst case: one miner trying to take every reward

This note states, as a theorem with proof, the maximum share of block rewards a **single adversary** can
capture in NADO — the "one miner grabs everything" worst case. The short version: **a zero-cost attacker
is capped at the open lane (30%), and every point above that must be *bought* with a proportional amount of
locked, at-risk stake — so total capture is possible only by owning essentially all the stake, at which
point there is no one else left to take from.** Monopoly has no cheap path.

Constants referenced (`protocol.py`): `OPEN_BPS = 3000` bps = **30%** of slots are the OPEN lane
(`K_OPEN = 18` of `EPOCH_LENGTH = 60`), the rest (**70%**) are the BONDED lane; `TREASURY_BPS = 1000` =
**10%** of every block reward goes to the treasury, **90%** to the producer; `B_MIN` = 1 000 NADO per bonded
selection share; `MAX_SHARES = 100` (per-identity bonded variance cap); `SLASH_BOND_PENALTY = B_MIN`.

---

## Model

Fix a long horizon of `N` slots. A single adversary **A** may:

- register an **unbounded** number of OPEN-lane Sybil identities (worst case: assume A defeats every
  Sybil friction — the per-IP cap, the registration PoW/PoSW — for free), giving A an open-lane
  selection-weight fraction `w = W_A / W_total ∈ [0,1)` that can be driven arbitrarily close to `1`;
- own a fraction `s = Σ_A shares / Σ_total shares ∈ [0,1]` of the **total bonded selection shares**
  (i.e. of all staked capital), spread over as many bonded identities as needed to bypass the
  per-identity `MAX_SHARES` cap;
- follow the protocol otherwise (it cannot forge ML-DSA signatures, grind the commit-reveal beacon,
  equivocate without being slashed, or reorg past finality — see *Assumptions*).

Let `ρ_A` be A's expected long-run share of **produced blocks**, and `E_A` its expected share of **reward
emission**.

## Theorem (bounded reward capture)

> For any adversary A controlling stake fraction `s` and open-weight fraction `w`,
>
> &nbsp;&nbsp;&nbsp;&nbsp;`ρ_A = OPEN_BPS · w + (1 − OPEN_BPS) · s`  →  **`ρ_A ≤ OPEN_BPS + (1 − OPEN_BPS) · s`**  (as `w → 1`),
>
> and A's share of reward **emission** is
>
> &nbsp;&nbsp;&nbsp;&nbsp;**`E_A = (1 − TREASURY_BPS) · ρ_A ≤ 0.9 · ( OPEN_BPS + (1 − OPEN_BPS) · s )`**,
>
> the remaining `TREASURY_BPS = 10%` of every reward accruing to the treasury regardless of who produces
> the block (so it is uncapturable by mining unless A *is* the treasury key holder). With the defaults
> `OPEN_BPS = 0.20`, `TREASURY_BPS = 0.10`:
>
> &nbsp;&nbsp;&nbsp;&nbsp;**`ρ_A ≤ 0.20 + 0.80·s`  and  `E_A ≤ 0.18 + 0.72·s`.**

## Proof

**1. Every slot belongs to exactly one lane, in fixed proportion.** The two-lane split permutes *slot
indices* by the epoch beacon: in every epoch of `EPOCH_LENGTH` slots, exactly `K_OPEN` are OPEN and the
rest are BONDED, so the fraction of OPEN slots is `K_OPEN / EPOCH_LENGTH = OPEN_BPS`, **independent of how
many identities exist**. Partition the `N` slots into `N·OPEN_BPS` open slots and `N·(1−OPEN_BPS)` bonded
slots.

**2. Open lane — capped at `OPEN_BPS`.** Each open slot's producer is a deterministic draw over the
present open registry, weighted by `open_shares ∈ [OPEN_BASE_FLOOR, OPEN_BASE_FLOOR+OPEN_FID_BONUS] =
[1,10]`. A's expected wins among open slots is its weight fraction `w`. Hence A takes `w · N·OPEN_BPS`
open slots. Because honest miners always hold some weight, `w < 1` strictly, but registering more Sybils
drives `w → 1`; the **supremum** of open-lane capture is therefore `N·OPEN_BPS` — i.e. at most **all of the
30% lane, and never one slot more**, no matter the identity count. This is the structural, population-
independent Sybil ceiling (whitepaper §2.2).

**3. Bonded lane — proportional to stake.** Each bonded slot's producer is a deterministic draw over the
bonded registry weighted by `selection_shares ∝ bonded stake`. A's expected wins among bonded slots equals
its stake fraction `s`, so A takes `s · N·(1−OPEN_BPS)` bonded slots. The per-identity `MAX_SHARES` cap
only bounds *one identity's* weight (an anti-whale variance limit); A can still reach any `s` by splitting
stake across identities, but it cannot reach a bonded share **exceeding** `s` — that would require owning
more than `s` of the shares, a contradiction.

**4. Sum.** Adding the two lanes and dividing by `N`:
`ρ_A = OPEN_BPS·w + (1−OPEN_BPS)·s`. By the strong law of large numbers the realized share concentrates on
this expectation as `N → ∞` (variance `→ 0`; the `MAX_SHARES` cap further tightens the bonded-lane
variance). Taking `w → 1` gives the stated bound.

**5. Emission.** `split_block_reward` pays the producer `(BPS_DENOM − TREASURY_BPS)/BPS_DENOM = 90%` of
each block reward and the treasury `10%`, for *every* block regardless of producer. Since total emission
per block is fixed by the schedule (base subsidy + capped elastic term) and does **not** depend on who
produces, A's emission share is exactly `(1 − TREASURY_BPS) · ρ_A`, and the treasury's `10%` is never part
of any producer's cut. ∎

## Corollaries

1. **A free botnet can never exceed 30% of blocks (18% of emission).** Set `s = 0`: `ρ_A ≤ OPEN_BPS =
   30%` for *any* number of Sybil identities and *any* amount of IP spoofing. This is the entire ceiling
   on zero-capital capture — the concern of `doc/ip-spoofing-and-sybil.md` — and it holds even if every IP
   and Sybil-friction control is bypassed.

2. **Every point above 30% costs proportional locked stake.** To reach a block share `ρ`, A must hold
   `s ≥ (ρ − OPEN_BPS)/(1 − OPEN_BPS)` of *all* bonded capital:

   | target block share `ρ` | stake `s` A must own |
   |---|---|
   | 30% | 0% (free lane only) |
   | 50% | 37.5% |
   | 67% (a "majority-ish" grab) | 58.75% |
   | 90% | 87.5% |
   | ~100% | ~100% |

3. **Total monopoly ⇔ owning ~all the stake.** `ρ_A → 1` forces `s → 1`: A can take *every* reward only by
   being *the entire staking set*. That is not an attack on a distribution — it *is* the distribution;
   there is nobody else to take rewards from. There is no mechanism by which A monopolizes production while
   others still hold meaningful stake or open-lane presence.

4. **The treasury 10% is unreachable by mining.** Even a 100%-block adversary captures at most 90% of
   emission; the treasury cut is a protocol split, not a producer reward.

5. **No profit motive.** Reaching high `s` means *buying/earning and locking* ~all the stake; the rewards
   captured are denominated in the very coin A over-holds; the locked stake is exposed to slashing; and
   10% is unreachable. Attacking one's own network's distribution is economically self-defeating.

## Assumptions — and exactly what would break the bound

The bound `ρ_A = OPEN_BPS·w + (1−OPEN_BPS)·s` relies on five properties; each is a live mechanism, and the
theorem fails **only** if one is broken:

- **Structural lane split (`OPEN_BPS` enforced by slot permutation).** If the open lane could absorb bonded
  slots, step 2's cap would fail and a free botnet could exceed 30%. *(Enforced in genesis + selection.)*
- **Unbiasable beacon (commit-reveal RANDAO).** The proof credits A only its *weight share* of slots. If A
  could grind the beacon, it could steer *which/how many* slots fall to it and exceed its share. *(Commit
  in epoch E−2, reveal in E−1's finalized window — no just-in-time grinding.)*
- **No equivocation gain (slashing + fork-choice + finality).** Producing two blocks for one slot, or
  double-counting, is caught: one valid producer per slot, equivocation is slashed `SLASH_BOND_PENALTY`,
  and cumulative-weight fork-choice + the finality floor forbid rewriting history to re-award past slots.
- **Unforgeable authorship (ML-DSA / PQ signatures).** A cannot sign as another address to steal its slot.
- **Fixed emission schedule.** Total reward per block is independent of the producer, so capturing blocks
  redistributes emission but never *inflates* it — "taking all rewards" can never mean minting extra.

If all five hold, `30% + 70%·s` is a hard cap; if any is broken, that specific mechanism — not IP, not
identity count — is the thing to fix.

## Interpretation

"One miner takes all the rewards" is, in NADO, equivalent to "one miner owns all the stake." Short of that,
the worst a maximally-resourced, fully-Sybil, IP-spoofing, zero-cost attacker can do is **capture up to the
30% open lane** — a *fair-distribution* degradation (documented, and priced by the sequential-work
registration proof), never a monopoly and never a safety break. Every reward beyond the free 30% is
gated by real, proportional, slashable capital. There is no cheap path from "one miner" to "all the
rewards."

See also: `doc/ip-spoofing-and-sybil.md` (the free-lane / Sybil ceiling and how to price it),
whitepaper §2.2 (structural Sybil bound), `doc/mining.md` (two-lane selection, beacon, fidelity),
`doc/economics.md` (reward schedule, 90/10 split, treasury).
