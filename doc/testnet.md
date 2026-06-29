# Multi-node testnet

The testnet is how S4.3 (live bonded-mining integration) and the broader relaunch get
validated end-to-end — unit tests prove the primitives, but consensus convergence, sync,
snapshot bootstrap, reward enforcement across nodes, and fail-closed authorship can only be
trusted on a real mesh of nodes.

## Status

**Not yet run.** It depends on S4.3 being wired AND on a few local-networking blockers below.
This document is the plan and the harness contract.

## What a node needs to boot

`nado.py` starts a Tornado HTTP server plus four daemon threads (core/consensus/peer/message).
To bring one up programmatically a node needs, under its own `$HOME/nado`:
- `private/config.dat` (created by `config.create_config`) — `port`, `ip`, `server_key`,
  `min_peers`, `promiscuous`, `quick_sync`, …
- `private/keys.dat` (an Ed25519 keypair → `ndo…` address).
- genesis (`genesis.make_genesis`) + the consolidated `index.db` (`create_indexers`).
- at least one seed peer to discover the mesh.

## Blockers to running a LOCAL testnet (must be addressed)

1. **Port is hardcoded.** `config.get_port()` returns `9173`; several call sites use it
   directly. A local testnet needs N nodes on N ports → route the port through config
   everywhere (or a `NADO_PORT` env override).
2. **`check_ip` rejects loopback/private IPs.** `peer_ops.check_ip` (correctly, for mainnet)
   refuses `127.0.0.1`/RFC1918, so localhost nodes can't peer. A testnet needs a **test mode**
   that allows private IPs (e.g. honour the existing `promiscuous` config flag, or a
   `NADO_TESTNET=1` env that relaxes `check_ip`). Do **not** relax it on mainnet.
3. **`get_public_ip` calls out to the internet** (`api.ipify.org`). In an offline/local run the
   node must take its IP from config instead of fetching it.
4. **Shared genesis.** Every node must start from the *same* genesis block hash; either run
   `make_genesis` with identical params per node, or copy one node's genesis block file +
   `block_ends.dat` to the others.
5. **Bonded eligibility (S4.3).** With bonded mining, the genesis/treasury (seeded) must bond,
   and/or the faucet must grant starter bonds, or no node is eligible to produce. Until S4.3 is
   wired, the testnet exercises the legacy IP-based producer path with all the S1–S3 + S2b +
   burn-removal changes (still a valuable integration smoke test).

## Harness plan (`scripts/testnet/`, to be added)

A driver that:
1. Creates `N` temp data dirs, each with config (distinct port, `ip=127.0.0.x` or `127.0.0.1`
   + port, test mode on), a fresh key, and a **shared** genesis.
2. Launches `N` `nado.py` processes (or an in-process variant) seeded with each other's
   `ip:port`.
3. Polls `/status` on each until they converge on a common `latest_block` hash and height.
4. Asserts: blocks are produced and propagate; all nodes agree on the tip hash (no fork);
   the **reward equals the deterministic value** on every node; a transaction submitted to one
   node lands in a block all nodes accept; bond/unbond changes `bonded` consistently; a freshly
   **snapshot-bootstrapped** node reaches the same tip; an injected bad-reward / bad-author /
   wrong-`chain_id` block is **rejected**.
5. Tears all nodes down and reports.

## Acceptance criteria (S4.3 gate)

Per the design study, S4.3 ships only behind a passing multi-node + snapshot test asserting:
a block accepted by a full node is also accepted by a freshly snapshot-bootstrapped node under
reward recompute-enforcement, and producer authorship is fail-closed. Golden cross-node
determinism vectors (beacon, registry root, winner, block hash) should be checked in CI before
any value launch.
