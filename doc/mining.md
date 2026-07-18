# Mining: bonded-registry selection (open / mobile / botnet-safe)

This is the redesign that opens mining beyond public-IP nodes to **anyone, including phones**,
without enabling botnet/Sybil farming. It came out of a red-teamed design study ("Option A");
the **primitives** (S4.1, S4.2) and the **live integration** (S4.3) are implemented and
testnet-validated; the **browser client** (S4b) is still pending.

> **Current model (2026-07 — supersedes the bond-only framing this doc was first written around).**
> Mining is now **two-lane**: an **OPEN lane** (zero-capital, hard-capped at `K_OPEN/EPOCH_LENGTH`
> = 18/60 ≈ **30%** of slots) and a **BONDED lane** (locked stake, ≈ 70%). Two things changed since
> the original "capped bonded chain" write-up below:
> - **The OPEN lane is genuinely zero-capital.** Its Sybil cost is a renewable **PoSW recert lease**,
>   not a bond: a `register` transaction carrying a fresh *sequential* proof-of-work
>   (`ops/posw.py`) grants open-lane eligibility for `POSW_LEASE_EPOCHS` (≈ 1 day); you renew by
>   re-registering before it lapses. The recert is the **single** presence + anti-Sybil signal —
>   there is **no per-epoch heartbeat** and no `PRESENCE_WINDOW` (both removed). See
>   doc/ip-spoofing-and-sybil.md and doc/node-service-reward.md.
> - **The BONDED lane keeps the split-neutral capped-share selection described here**, now with a
>   **bonded producer ramp** (a fresh bond's *producer-selection* weight ramps 0 → full over
>   `BOND_RAMP_EPOCHS`; see §"Bonded producer ramp" and doc/takeover-resistance.md).
>
> The ~30% open cap is population-independent (the reward-capture bound) and is machine-checked by
> `tests/test_open_cap_adversarial.py`; the live selector is `mining_ops.select_producer_two_lane`
> (`lane_of`, `open_shares`, `bond_ramp_weight`). See doc/reward-capture-theorem.md.

## Why the old model is being replaced

The legacy model selects the producer by lowest `get_penalty` over a set of **reachable
public-IP peers**. The audit confirmed it is **fully grindable**: `get_penalty` /
`get_hash_penalty` are a deterministic function of an attacker-chosen address and the
already-known previous block hash, so an attacker grinds keypairs offline to win blocks at
near-zero cost (one public IP suffices). The public-IP requirement also excludes NAT/mobile
nodes entirely. (`get_penalty` still exists, with burn-to-bribe removed, until S4.3 replaces it.)

## The iron triangle

You cannot have all three of {zero-cost entry, Sybil/botnet resistance, mobile participation}.
Mobile rules out the Sybil costs NADO could otherwise use (IP scarcity, reachability, heavy
PoW), leaving **a small refundable on-chain bond** as the only Sybil cost a phone can pay. So
the model is a **capped, fair-launch bonded chain**: lock coins (you keep them) to mine.

> **Superseded conclusion.** The "only a bond" step was too strong: it assumed the only phone-payable
> Sybil cost was capital. NADO now also uses a **farm-neutral sequential-work** cost — a hash-based
> **PoSW recert lease** (Douceur says a permissionless Sybil anchor must have *some* cost; the recert
> makes that cost *non-parallelizable serial time per identity per lease*, which a bot pays the same
> as a human). That opens a truly **zero-capital OPEN lane** alongside the bonded lane. The iron
> triangle still bites — the open lane is *bounded* (30%), not unbounded — but "lock coins to mine at
> all" is no longer the whole story. See doc/ip-spoofing-and-sybil.md §5b and doc/node-service-reward.md.

## The mechanism (Option A hybrid)

1. **Eligibility = a refundable BOND.** Lock coins into a separate `bonded` balance.
2. **Weight = split-neutral, capped shares**, optionally ramped by **fidelity** (continuity):
   `shares = min(bonded, BOND_CAP) // B_MIN`. Sharding capital across many addresses gives
   **zero** advantage, and a whale is capped at `MAX_SHARES`.
3. **Randomness = a commit-reveal RANDAO beacon**, chained with the previous beacon and
   produced by the always-on bonded set — **not** the grindable parent-hash, and **never** an
   grindable signature (a malleable signature scheme accepts non-unique encodings, so a signature is
   grindable and is used only for authenticating reveals/attestations). Entry must be committed
   **before** the epoch beacon is revealed (kills just-in-time bond grinding).
4. **Mobile/browser participation** is outbound-only and **passive**. On the **bonded** lane a
   phone bonds once and then does nothing online at all: there is **no heartbeat, no PoW/PoSW, no
   online requirement** — the winner is credited by address and an always-on relay builds the
   block, so the reward lands on-chain with no inbound connectivity and a browser closing
   mid-epoch is **never slashed**. On the **open** lane the only recurring action is renewing the
   **PoSW recert lease** — one `register` with a fresh sequential proof roughly once per
   `POSW_LEASE_EPOCHS` (≈ 1 day), *not* a per-epoch heartbeat. (The original per-epoch heartbeat
   tx and `PRESENCE_WINDOW` were removed; presence is now the renewable recert.)

### Sybil/botnet cost

To capture a fraction `f` of selection you must lock `f/(1-f)` of the honest bonded capital;
a 100k-host botnet and unlimited free addresses buy **nothing** (no per-host, no per-address
weight). The split-neutral cap means it degenerates to "be a large, capped, refundable
staker" — strictly less profitable than buying coins on the market.

## Implemented (S4.1, S4.2)

**S4.1 — bond state + transactions** (`ops/account_ops.py`):
- the `accounts` KV doc carries a `bonded` field (separate from spendable `balance`).
- `bond` / `unbond` reserved-recipient transactions move coins between `balance` and `bonded`
  (`reflect_transaction`), revert-symmetric; the fee is destroyed.
- Spending checks track balance vs bonded separately (`transaction_ops._spend_costs`,
  `validate_all_spending`): an `unbond` draws its amount from `bonded`, only the fee from
  `balance`; bonded stake is never spendable.

**S4.2 — selection + beacon** (`ops/mining_ops.py`, pure/deterministic/integer-only):
- `selection_shares(bonded, fidelity=None)` — split-neutral, capped at `MAX_SHARES`, optional
  linear fidelity ramp to full over `FIDELITY_CAP`.
- `select_producer(registry, beacon, slot)` — deterministic split-neutral weighted draw over
  `int(blake2b_hash([beacon, slot])) % total_shares`, canonical sorted-address walk.
- `beacon_commitment` / `verify_reveal` / `compute_beacon` — commit-reveal RANDAO; the beacon
  is chained with the previous beacon, reveal-order-independent, and withholding-sensitive.
- `epoch_of(block_number)` — epoch = `block_number // EPOCH_LENGTH`.

Tests (`tests/test_s4_1_bonding.py`, `tests/test_s4_2_selection.py`) prove: stake locking +
spendable separation + revert symmetry; **split-neutrality** (an entity wins with identical
probability whether it holds one bond or shards it); proportional-to-bond win rate; cap;
commit/reveal correctness; chained/withholding-sensitive beacon.

## S4.3 v1 — live integration (IMPLEMENTED & testnet-validated)

Bonded selection is now wired into the live production/verification path and validated on a
3-node local testnet (nodes produce block 1 via bonded selection and converge on the identical
tip):
- **Registry from chain state** — `account_ops.get_bonded_registry()` enumerates accounts with
  `bonded >= B_MIN` from the committed `accounts` KV store (parent state); it is the sole input (with the
  beacon) to `select_producer`. Agreed implicitly via block sync — no new gossip field.
- **Selection swap** — `block_ops.get_block_candidate` now calls
  `select_producer(get_bonded_registry(), epoch_beacon(epoch_of(n)), slot=n)` instead of the
  grindable `pick_best_producer`; `block_ip` is repurposed to the winner address so the hashed
  body is identical on every node. Returns `None` (skip) if no eligible bond.
- **Beacon (v1)** — `block_ops.epoch_beacon`: epochs 0-1 use the fixed `GENESIS_BEACON`; epoch≥2
  chains it with the hash of the first block of the previous epoch (a finalized, non-parent
  anchor — materially stronger than the M6 parent-hash seed, with bounded residual bias).
- **Fail-closed authorship** — `core_loop.validate_block_producer` recomputes the winner and
  rejects unless `block_creator == winner` (the old fail-open "unknown set → allow" path is
  gone); `rebuild_block` recomputes the winner from local parent state so a lying relay can't
  misattribute the reward.
- **Bootstrap** — in `NADO_TESTNET` mode, `genesis.make_genesis` seeds bonded accounts from a
  byte-identical genesis allocation (`genesis_data/genesis_alloc.dat` + `genesis_open.dat`) so there is an eligible producer set from block 1;
  startup logs the registry size + `total_shares` loudly.

### Deferred hardening (not in v1)
- Full **on-chain commit-reveal RANDAO** beacon (replace the epoch-boundary anchor with revealed
  secrets + a withholding penalty — the M6-grade fix; pure fns already in `mining_ops`).
- ~~**Heartbeats + on-chain fidelity** column and enabling the `selection_shares` fidelity ramp.~~
  **Redesigned & shipped** — heartbeats were removed; presence is now the renewable **PoSW recert
  lease**. The open registry (`account_ops.get_open_registry`) is derived from the revert-safe
  recert index, and the continuity **fidelity** streak is driven by recerts (`apply_register`;
  continuous gap ≤ lease ⇒ +`FIDELITY_GAIN`, a lapse resets), feeding `open_shares` (range 2..10).
  The bonded lane keeps the `selection_shares` fidelity ramp OFF (`fidelity=None`) and instead uses
  the tenure-based **bonded producer ramp** (`bond_ramp_weight`, below).
- **Consensus-pool reweight** (today one vote per peer, `consensus_loop.py`) by trust/stake.
- Treasury-funded **faucet** + a real post-launch bond-from-balance path (so a non-testnet chain
  isn't deadlocked by fail-closed selection with an empty registry).
- **Canonical in-block tx order** (CO-8) and the as-of-parent re-verify guard for the
  rollback/snapshot paths (dormant in v1: empty mempool, no in-block bond txs, reward 0).
- Enforce/document the **`max_rollbacks < EPOCH_LENGTH`** invariant for the epoch≥2 beacon anchor.

### S4b — browser light-miner (pending)
Web-Crypto-hosted ML-DSA-44 (`@noble/post-quantum`), key in browser storage, `fetch()` to relays, reproducing the canonical
encoding + address derivation in JS (BigInt-safe), offline-at-win.

## Bonded producer ramp (anti-sudden-takeover)

A freshly-bonded identity does **not** get its full bonded-lane producer weight immediately. Its
**producer-selection** weight ramps linearly 0 → full over `BOND_RAMP_EPOCHS` (= 30), keyed by a
**stake-weighted bond age** (`bond_since`): a top-up re-ramps only the *new* stake (weighted
average), closing the "age a cheap address, then dump a whale into it" loophole, while auto-bond's
small trickle barely moves the age. So a sudden whale cannot control the *very next* epoch — it must
accrue weight over ~30 epochs, buying the network reaction time.

Crucially the ramp is applied **only** in the producer draw (`mining_ops.select_producer_two_lane`
via `bond_ramp_weight`). It deliberately does **not** touch **fork-choice chain weight** or the
**FFG / settlement quorum**, which keep the ramp-free `total_bonded_shares` — so finality is never
made tenure-dependent and the ramp can never stall the chain. It only *delays* a patient whale; the
hard bounds stay real capital cost + the per-address `MAX_SHARES` cap + slashing/finality. Full
rationale and the takeover math: **doc/takeover-resistance.md**.

## Provisional parameters (simulate before locking)

Bonded lane: `B_MIN = 1e11` (10 NADO), `BOND_CAP = 1e13` (1,000 NADO), `MAX_SHARES = 100`,
`EPOCH_LENGTH = 60`, `BOND_UNLOCK_DELAY = 1440`, `BOND_RAMP_EPOCHS = 30`.
Open lane: `OPEN_BPS = 3000` (30% ⇒ `K_OPEN = 18` slots/epoch), `OPEN_BASE_FLOOR = 2`,
`OPEN_FID_BONUS = 8` (open weight ranges 2..10), `POSW_LEASE_EPOCHS = 240` (≈ 1 day recert lease).
Continuity fidelity: `FIDELITY_CAP = 30` consecutive recerts (was 1000 in the heartbeat design),
`FIDELITY_GAIN = 1` per continuous recert — a lapse **resets** the streak (there is no separate
`FIDELITY_DECAY` constant any more, and no `FAUCET_STARTER_BOND`: free presence must never mint
bonded stake, so there is deliberately **no auto-bond faucet**).

Slashing is implemented (`SLASH_BOND_PENALTY = B_MIN`, one share burned per proven equivocation) and
now covers **both** equivocation types: block-authorship (two signed blocks at one height+parent) **and**
FFG-attestation double-votes (two conflicting `attest` txs for one epoch). It punishes **equivocation, not
Sybil-ness** — Sybil is bounded separately by the `OPEN_BPS` open-lane cap and the locked bonded shares.
FFG finality is likewise **enforced** now (a >2/3-attested checkpoint folds into the rollback floor,
un-reorgable), with an inactivity leak so a dark validator loses its finality vote (not its bond). Still
open for simulation: relay-commission cap, the exact fidelity/open-weight curve, and the bond floor.

> Burn note: the original design sketch had a "congestion-priced registration **burn**"; since
> burn was removed project-wide, S4.3 will use a refundable bond / destroyed fee instead.
