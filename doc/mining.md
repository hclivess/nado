# Mining: bonded-registry selection (open / mobile / botnet-safe)

This is the redesign that opens mining beyond public-IP nodes to **anyone, including phones**,
without enabling botnet/Sybil farming. It came out of a red-teamed design study ("Option A");
the **primitives** (S4.1, S4.2) are implemented and unit-tested, the **live integration**
(S4.3) and the **browser client** (S4b) are not yet wired.

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

## The mechanism (Option A hybrid)

1. **Eligibility = a refundable BOND.** Lock coins into a separate `bonded` balance.
2. **Weight = split-neutral, capped shares**, optionally ramped by **fidelity** (continuity):
   `shares = min(bonded, BOND_CAP) // B_MIN`. Sharding capital across many addresses gives
   **zero** advantage, and a whale is capped at `MAX_SHARES`.
3. **Randomness = a commit-reveal RANDAO beacon**, chained with the previous beacon and
   produced by the always-on bonded set — **not** the grindable parent-hash, and **never** an
   Ed25519 signature (`Curve25519.verify` accepts non-unique `(R,S)`, so a signature is
   grindable and is used only for authenticating heartbeats/reveals). Entry must be committed
   **before** the epoch beacon is revealed (kills just-in-time bond grinding).
4. **Mobile/browser participation** is outbound-only: a phone bonds once, posts signed
   heartbeats to relays while a tab is open, and **wins offline** — the reward lands on its
   on-chain address with no inbound connectivity. The beacon is produced by always-on relays,
   so a browser closing mid-epoch is **never slashed**.

### Sybil/botnet cost

To capture a fraction `f` of selection you must lock `f/(1-f)` of the honest bonded capital;
a 100k-host botnet and unlimited free addresses buy **nothing** (no per-host, no per-address
weight). The split-neutral cap means it degenerates to "be a large, capped, refundable
staker" — strictly less profitable than buying coins on the market.

## Implemented (S4.1, S4.2)

**S4.1 — bond state + transactions** (`ops/account_ops.py`):
- `acc_index` has a `bonded` column (separate from spendable `balance`).
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

## Not yet implemented (S4.3, S4b) — needs a multi-node testnet

- **S4.3 — live integration:** build the on-chain bonded registry from account state; record
  commits/reveals in blocks and penalise withholders; replace
  `pick_best_producer`/`get_penalty` with `select_producer` over the beacon; make authorship
  **fail-closed** in `verify_block` (`block_creator` == the selected winner); relay-batched
  `/submit_heartbeat` + offline-at-win payout; automated fidelity from heartbeats; reweight the
  consensus pool by trust/stake (today it is one vote per peer, `consensus_loop.py`); a
  treasury-funded, rate-limited onboarding **faucet** (no manual step, anti-IDENA).
- **S4b — browser light-miner:** Web-Crypto Ed25519, key in browser storage, `fetch()` to
  relays, reproducing the canonical encoding + address derivation in JS (BigInt-safe).

## Provisional parameters (simulate before locking)

`B_MIN = 1e12` (100 NADO), `BOND_CAP = 1e14` (10k NADO), `MAX_SHARES = 100`,
`EPOCH_LENGTH = 60`, `BOND_UNLOCK_DELAY = 1440`, `FIDELITY_CAP = 1000`, `FIDELITY_GAIN = 1`,
`FIDELITY_DECAY = 2`, `FAUCET_STARTER_BOND = B_MIN`. Open decisions for S4.3: slashing model,
relay-commission cap, the fidelity curve, and the exact bond floor.

> Burn note: the original design sketch had a "congestion-priced registration **burn**"; since
> burn was removed project-wide, S4.3 will use a refundable bond / destroyed fee instead.
