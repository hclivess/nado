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

## S4.3 v1 — live integration (IMPLEMENTED & testnet-validated)

Bonded selection is now wired into the live production/verification path and validated on a
3-node local testnet (nodes produce block 1 via bonded selection and converge on the identical
tip):
- **Registry from chain state** — `account_ops.get_bonded_registry()` enumerates accounts with
  `bonded >= B_MIN` from the committed `acc_index` (parent state); it is the sole input (with the
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
  byte-identical `genesis_bonds.dat` manifest so there is an eligible producer set from block 1;
  startup logs the registry size + `total_shares` loudly.

### Deferred hardening (not in v1)
- Full **on-chain commit-reveal RANDAO** beacon (replace the epoch-boundary anchor with revealed
  secrets + a withholding penalty — the M6-grade fix; pure fns already in `mining_ops`).
- **Heartbeats + on-chain fidelity** column and enabling the `selection_shares` fidelity ramp.
- **Consensus-pool reweight** (today one vote per peer, `consensus_loop.py`) by trust/stake.
- Treasury-funded **faucet** + a real post-launch bond-from-balance path (so a non-testnet chain
  isn't deadlocked by fail-closed selection with an empty registry).
- **Canonical in-block tx order** (CO-8) and the as-of-parent re-verify guard for the
  rollback/snapshot paths (dormant in v1: empty mempool, no in-block bond txs, reward 0).
- Enforce/document the **`max_rollbacks < EPOCH_LENGTH`** invariant for the epoch≥2 beacon anchor.

### S4b — browser light-miner (pending)
Web-Crypto Ed25519, key in browser storage, `fetch()` to relays, reproducing the canonical
encoding + address derivation in JS (BigInt-safe), offline-at-win.

## Provisional parameters (simulate before locking)

`B_MIN = 1e12` (100 NADO), `BOND_CAP = 1e14` (10k NADO), `MAX_SHARES = 100`,
`EPOCH_LENGTH = 60`, `BOND_UNLOCK_DELAY = 1440`, `FIDELITY_CAP = 1000`, `FIDELITY_GAIN = 1`,
`FIDELITY_DECAY = 2`, `FAUCET_STARTER_BOND = B_MIN`. Open decisions for S4.3: slashing model,
relay-commission cap, the fidelity curve, and the exact bond floor.

> Burn note: the original design sketch had a "congestion-priced registration **burn**"; since
> burn was removed project-wide, S4.3 will use a refundable bond / destroyed fee instead.
