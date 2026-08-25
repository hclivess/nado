# Taxing the rich for the poor — what is and isn't enforceable

Investigation, 2026-08-25, prompted by the removal of the per-identity bond cap (`7c9bcee0`). Question:
can the protocol put a *progressive* levy on large stakers — a higher "dividend tax" — that funds the
capital-free open lane?

## 0. The one fact that decides everything

**Any rule keyed on a single identity's size is void, because identities are free.** The wallet derives
unlimited keys from one seed; a bonded identity costs nothing beyond its capital, a 30-epoch producer ramp
(one-time, ~3 h) and no ongoing work at all. A whale facing a progressive per-key levy splits into N keys
with stake `S/N` each, pays the lowest bracket on every one, and its total is untouched. This is *exactly*
the flaw the bond cap had — the cap was per key, so it never bound a whale, only the honest miner who did
not bother to split — and a progressive per-key tax would be the same mistake dressed as fairness.

The corollary: **the only levers that actually reach a whale are lane-level (global) parameters**, which
tax stake *as a class* and pay out by a metric that is Sybil-costly. The chain already has exactly one such
mechanism — the presence dividend — so the honest answer to "tax the rich for the poor" is "turn that dial",
not "add brackets".

## 1. Where the emission goes today

`BASE_SUBSIDY = 0.1 NADO/block` → ~1,440 NADO/day at 6 s blocks. Lanes: bonded 70 % of slots
(`OPEN_BPS = 3000`, pinned ≤ 33 % because the bonded lane must hold the 2/3 finality quorum).

| stream | split | NADO/day | who |
|---|---|---|---|
| bonded blocks (1,008/day) | producer 70 % · **dividend 20 %** · treasury 10 % | 705.6 / 201.6 / 100.8 | producers by stake |
| open blocks (432/day) | tip 20 % · **dividend 70 %** · treasury 10 % | 86.4 / 302.4 / 43.2 | present open miners (weight 2..10 by fidelity) |
| **dividend pool** | | **504 / day (35 % of emission)** | 238 present miners, fidelity-weighted |

Measured now (`/get_open_weights`): 238 present, weights only 2–3 (the chain is five days old, fidelity
has barely ramped), so the dividend is ~2.1 NADO/day per present miner. The bonded leader (272 NADO,
~13.5 % of shares) takes ~95 NADO/day from bonded blocks and compounds it at 99 % auto-bond. Rich ≈ 40× poor
per day, and the gap widens geometrically — that is plain proof-of-stake and the cap never changed it.

## 2. Options, ranked by whether they survive key-splitting

| option | enforceable? | verdict |
|---|---|---|
| **A. Raise `BONDED_DIVIDEND_BPS`** (flat levy on every bonded block, paid out fidelity-weighted) | **yes** — lane-level, key count irrelevant | the real lever |
| B. Progressive `BONDED_DIVIDEND_BPS` by the producer's share of total stake | no — split keys, drop to the bottom bracket | dead on arrival |
| C. Brackets by absolute bonded amount (income-tax style) | no — same; plus brackets need indexing as supply grows | dead |
| D. Levy on liquid+bonded wealth | no — split; and liquid coins move between keys the epoch a slot is known (beacon reveals slots an epoch ahead), so it is gameable within the rules | dead |
| E. Dividend weight discounted for present miners who also hold stake | weak — mine open from a fresh key; costs one fidelity ramp (30 d) once, forever | not worth the complexity |
| F. Raise `OPEN_BPS` | enforceable, but **pinned ≤ 3333** — the bonded lane must keep the 2/3 quorum | already at the ceiling |
| G. Demurrage on bonded stake | flat: hits the poor identically; progressive: split keys | dead |
| H. Lower `OPEN_TIP_BPS` (more of open blocks to the pool) | enforceable, but §6 of presence-dividend.md: the tip is the only reason an open producer bothers to build the block | tune with liveness data, not for redistribution |

So there is **one** honest instrument: **A**, a higher flat share of every bonded block into the dividend
pool. It is progressive in *effect* without being progressive in *form*: it moves emission from
stake-weighted payout to presence-weighted payout, and a whale cannot restructure its way out because the
levy is on the block, not on the key. The whale still gets its fidelity-weighted dividend share like anyone
present — one identity's worth, which is the point.

## 3. Sizing A

Constraint from `protocol.py` / presence-dividend.md: staking must stay "clearly the more profitable use of
capital" so the security budget (why anyone bonds) holds. Today it is not close: ~2,000 NADO bonded earns
705 NADO/day → the bonded lane yields ~35 %/**day**. Halving the producer's keep still leaves a return no
rational holder walks away from.

| `BONDED_DIVIDEND_BPS` | producer keep | bonded → pool/day | pool/day | per present miner/day (238) |
|---|---|---|---|---|
| 2000 (now) | 70 % | 202 | 504 | 2.1 |
| 3000 | 60 % | 302 | 605 | 2.5 |
| 4000 | 50 % | 403 | 706 | 3.0 |
| 5000 | 40 % | 504 | 806 | 3.4 |

Recommendation if you want to act: **4000** (a 50/40/10 bonded split). It doubles what stake sends to the
present set, keeps the producer the single largest claimant on its own block (so building it stays
rational), and leaves the lane's yield far above anything that threatens the security budget. Going past
50 % starts to make "why bond at all" a fair question for a small validator, whose bonded-block income is
already lottery-shaped.

Second-order effect worth wanting: the dividend is fidelity-weighted (2..10), so as the chain ages the
levy increasingly rewards *continuous presence* over headcount — the Sybil-costly metric §3 of
presence-dividend.md requires. With weights at 2–3 today the pool is nearly flat per identity, so the
PoSW entry cost (×32) is doing most of the anti-Sybil work right now; that improves by itself over the
next month.

## 4. What changing A requires — and why it cannot be ungated

Unlike the cap removal, this is **not** a historical no-op. `credit_block_reward` (`ops/reward_ops.py`) is
one function for apply, rollback *and* reindex, and `mining_history.py` mirrors the split for display. A
constant change applies the new split to every historical block on a fresh sync, so a joiner derives
different balances → different L1 state root → a fork against every node that applied the old split live.

Two correct ways:
1. **Height-gate the constant**: `bonded_dividend_bps(height)` returning 2000 below the activation height
   and the new value at/after it, used by both `split_bonded_block_reward` callers. Small, deterministic,
   and the repo's memory says gates were all deleted at gen-22 because they became dead weight — a gate
   here would be live, not dead.
2. **Ship with the next reroll**, unconditional, like the fidelity spacing rule was.

Either way the dividend fraud-proof replay (`dividend_ops.fidelity_at_epoch`, `weights_at_epoch`) is
unaffected — the levy changes the *inflow* per epoch, which is already recorded per epoch and
revert-symmetric (`dividend_inflow_add`), not the weights.

## 5. Status (2026-08-25, later the same day)

Built as one generation-keyed change activating at block 72,000 on gen 22 (`protocol.py` `_GEN22_RULES_ACTIVATION`):
`BONDED_DIVIDEND_BPS_V2 = 4000`, the dividend's own convex 1..25 weight curve (`dividend_weight`), and a
softened lapse (`fidelity_step`: halve, not reset). 1:25 rather than the 1:100 first floated: the Sybil math is
the same either way (a patient farm's masks ramp too), the honest cost of a lapse is not. The remaining lever
against a *patient* farm is the recurring per-identity recert cost (`POSW_T`), untouched here.

## 6. Bottom line

- A progressive tax by identity size is the bond cap's mistake again; do not build it.
- The enforceable version already exists: `BONDED_DIVIDEND_BPS`. Raising it to 4000 is the move if the goal
  is more emission to the present, capital-free set. It needs a height gate or a reroll.
- The actual concentration engine is 99 % auto-bond compounding on a lane that currently yields ~35 %/day.
  That is early-chain arithmetic, not a design flaw, and it dilutes as supply grows and more capital bonds.
