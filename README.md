<p align="center">
  <a href="https://nodeisok.com"><img src="https://nodeisok.com/media/bauhaus.png" /></a>
</p>

<p align="center">
    <a href="https://discord.gg/6aEBWTvcTV"><img src="https://nodeisok.com/media/discord.png" /></a>
    &emsp;
    <a href="https://twitter.com/nodeisok"><img src="https://nodeisok.com/media/twitter.png" /></a>
</p>

# NADO

**A phone-mineable, fair-launch, post-quantum, lightweight blockchain.**

NADO lets an ordinary phone — running nothing but a browser tab — take part in block production
for **zero capital**, on a **fair launch with no premine**, secured by **post-quantum signatures**.
It replaces the Proof-of-Work hash race with a **deterministic, beacon-keyed weighted draw**: one
hash decides each block's producer, so faster hardware (ASICs, GPUs) confers no advantage and there
is nothing to grind. Coins enter circulation only as block rewards.

> **Status: testnet-validated, NOT yet mainnet-launched.** The fair-mining economics and the first
> wave of consensus-security hardening (objective fork-choice, enforced finality, grind-proof chain
> weight) are implemented and validated on a local multi-node testnet. The remaining hardening
> (producer block signatures + slashing, FFG-lite finality, full commit-reveal RANDAO, broad eclipse
> defenses) is **not done yet** — see [Security](#security). Run it on testnet / at your own risk.
> Do not secure value of consequence with it yet. Chain id: `nado-relaunch-1`.

---

## Why NADO

Most "anyone-can-mine" coins fail in one of four ways: mining gets captured by specialized hardware;
the launch isn't fair (premines, insider allocations); the cryptography isn't quantum-resistant; or
a "light" client still leans on trusted infrastructure. NADO targets all four at once, and adds a
fifth goal — that **re-joining the network should never get harder as more people join**.

It is inspired by NANO, IDENA, NYZO and Vertcoin, and pushes the barrier to entry lower than any of
them: no puzzles to keep solving, no efficient rig to keep running, and no requirement to own coins.

## Key features

- **Phone-mineable.** Block production is one hash per slot over a public beacon, not a race — a
  phone competes on equal terms with a datacenter. Winners are credited **by address**, so a phone
  can win a block while its tab is closed and a relay assembles the block on its behalf.
- **Fair launch, no premine.** Genesis mints **zero** coins (`TREASURY_GENESIS = 0`). Every coin in
  existence was minted as a block reward. A flat base subsidy lets a brand-new, zero-coin miner earn
  spendable coins from block 1.
- **Two-lane "diligence" mining.** A free **OPEN lane** anyone can win with no coins (capped at ~20%
  of blocks, a *population-independent* Sybil ceiling) plus a **BONDED lane** won with refundable,
  whale-capped stake. Bonding is **optional** and only boosts the bonded lane — never required.
- **Post-quantum signatures.** ML-DSA-44 (NIST FIPS 204 / Dilithium) via pure-Python `dilithium-py`
  — no native build, in keeping with the lightweight goal. Cross-validated against the browser's
  `@noble/post-quantum` so a phone and a full node verify each other.
- **Lightweight & reproducible.** Consensus hashing is over canonical JSON, so a browser client
  reproduces every address, transaction id, and verification byte-for-byte. State is a single
  memory-mapped key-value store; block bodies are compact zstd-compressed blobs.
- **First-party clients.** A browser/mobile light-miner that is also a full wallet, a PySide6 desktop
  wallet, and browsable explorer endpoints on every node.

---

## How mining works

Time is divided into **epochs** of `EPOCH_LENGTH = 60` slots, each keyed by a per-epoch randomness
**beacon**. For each slot the protocol deterministically draws exactly one producer.

### Draw, not race

For a given slot the winner is a single computation over the public beacon:

```
draw   = int( blake2b([beacon, slot]) ) % total_weight
winner = the address whose cumulative-weight band contains `draw`
         (walking eligible addresses in canonical sorted order)
```

There is **no multi-attempt hash race and no nonce grinding** — one hash decides each slot. Faster
hashing hardware therefore confers *no advantage*, and any full node or browser client reproduces the
same winner from public chain state. Because the winner is chosen *by address*, an offline phone can
win a slot and a relay can build and broadcast the crediting block for it.

### Two lanes per epoch

Each epoch's 60 slots are split by a **beacon-keyed permutation of slot indices** into two lanes:

- **OPEN lane** — `K_OPEN = 12` slots (~20%, `OPEN_BPS = 2000`), winnable by any registered, present
  identity for **zero coins**.
- **BONDED lane** — the remaining 48 slots, won in proportion to locked, refundable stake.

The split is over *slot indices*, not per-identity weight, so there are always exactly `K_OPEN` open
slots **no matter how many identities register**. A zero-capital botnet of a million identities still
cannot win more than `OPEN_BPS` (20%) of blocks. This **population-independent structural ceiling** —
not a puzzle difficulty or an economic cost — is NADO's central Sybil defense. (Empty-lane policy is
one-directional and fail-closed: an empty open slot falls back to the bonded lane, but an empty
bonded slot is skipped, never the reverse, so the free lane can never absorb bonded slots.)

### The OPEN lane (free)

1. **Register once** by solving a light one-time registration PoW (`REGISTER_POW_BITS = 16`, ~1–2 s
   in-browser, fee-exempt). This is an anti-spam throttle for zero-balance newcomers — **not** the
   Sybil defense (the lane cap is).
2. **Heartbeat** each epoch with a signed, fee-exempt, zero-amount transaction to stay present
   (`PRESENCE_WINDOW = 3` epochs).

Open-lane selection weight is **capital-free**: a flat floor (`OPEN_BASE_FLOOR = 1`) every present
identity always gets, plus a diligence ramp to `OPEN_FID_BONUS = 9` over `FIDELITY_CAP = 1000` epochs
of continuous presence (overall range 1..10). The single most effective thing you can do is **stay
present**. Mine to **one address** — splitting across addresses gains nothing.

### The BONDED lane (optional stake)

`bond`/`unbond` transactions move spendable balance into and out of a non-spendable `bonded` column.
Bonded selection weight is `min(bonded, BOND_CAP) // B_MIN`, capped at `MAX_SHARES = 100`:

- **Split-neutral** — weight depends only on total bonded capital, so sharding across many addresses
  gains nothing.
- **Whale-capped** — a single identity tops out at `BOND_CAP = 10,000 NADO` (`B_MIN = 100 NADO` per
  share), so no whale can monopolise the lane. The bond is **refundable** — you keep your coins.

> Note: `BOND_UNLOCK_DELAY = 1440` blocks is defined but **not yet enforced** — `unbond` currently
> releases stake immediately.

---

## Economics

`protocol.py` is the economic source of truth. All on-chain amounts are integers in raw units, where
**1 NADO = `DENOMINATION` = 10,000,000,000 raw** (the smallest unit is 0.0000000001 NADO).

- **No premine.** Genesis mints zero coins; the chain bootstraps purely through the open mining lane.
- **Per-block reward** = a flat **base subsidy** floor (`BASE_SUBSIDY = 0.1 NADO/block`, ~144 NADO/day
  at 60 s blocks) **plus** an elastic, fee-weighted term (the trailing `REWARD_WINDOW = 100`-block
  average fee), clamped to `REWARD_CAP = 0.5 NADO` per block. Emission tracks real activity instead of
  inflating regardless of demand; the floor keeps a no-premine chain from deadlocking at zero.
- **90 / 10 split.** The producer keeps 90 %; **10 % accrues to the treasury** (`TREASURY_BPS = 1000`).
  The treasury *is* the genesis address — a normal founder-key-controlled ML-DSA address that starts
  empty and fills only from this per-block cut.
- **Fees are destroyed**, not paid to producers — that is what drives the elastic reward (it is a fee
  mechanic, not a "burn"; the old burn-to-bribe mechanic was removed entirely). A deterministic floor
  `MIN_TX_FEE = 1000` raw applies to ordinary/bond/unbond transactions; register and heartbeat are
  fee-exempt.
- **No free→capital faucet.** Open-lane presence can never mint bonded stake; the only path from free
  to capital is the block subsidy an open miner actually earns — itself capped at `OPEN_BPS` (20 %).

---

## Quickstart — run a node

NADO runs on Python 3.10+. The entrypoint is `nado.py`; the node serves its API and web UI on port
**9173**.

```bash
git clone https://github.com/hclivess/nado
cd nado
python3.10 -m venv nado_venv
source nado_venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python nado.py
```

Once running, open <http://127.0.0.1:9173> for the node's web interface and JSON endpoints. To join a
network, announce your node to a peer:

```
http://127.0.0.1:9173/announce_peer?ip=<peer-ip>
```

For public reachability and rewards, forward **port 9173**. Close the node cleanly with **CTRL+C** or
`http://127.0.0.1:9173/terminate` (never the window's **X**, to avoid database corruption). To wipe
local data and resync from scratch, run `python3.10 purge.py`.

### Local multi-node testnet

A self-contained harness spins up N nodes on `127.0.0.x` loopback IPs, meshes them, and reports
whether they converge and produce blocks:

```bash
python scripts/testnet/run_testnet.py [num_nodes=3] [run_seconds=240]
```

It uses throwaway temp dirs and sets `NADO_TESTNET=1` per child (relaxes the SSRF guard for loopback).
**Never set `NADO_TESTNET` on a real node.**

### Ubuntu notes

For a production-style node, raise the open-file limit (`/etc/security/limits.conf`:
`root soft/hard nofile 65535`, `fs.file-max = 100000` via `sysctl`), run inside `screen`, and use the
`deadsnakes` PPA for `python3.10-venv`. Update an existing install with `git reset --hard origin/main
&& git pull origin main`.

### Windows

Install [Python](https://www.python.org/downloads/), `python -m pip install -r requirements.txt`, then
`python nado.py`. Run the console as Administrator and close with **CTRL+C** or `/terminate`.

---

## Mine from a phone

Open the running node's light-miner in any browser:

```
http://<node-ip>:9173/static/miner.html
```

The light-miner (`static/miner.html` + `static/miner.js`) is also a **full wallet**: it generates or
imports a key, solves the registration PoW in pure JS, registers and heartbeats against the node, and
**wins blocks even while offline** (a relay assembles the crediting block). It can send/receive with QR
payment links and `#pay` deep links, bond/unbond, and show history — all from a phone. Crypto is
**vendored** (`static/vendor/nado-crypto.js`: blake2b + ML-DSA-44) so it works offline, and an in-page
self-test asserts byte-equality of its canonical encoding against the live repo on boot.

> The light-miner keeps its private key in browser `localStorage` in **plaintext** (disclosed in the
> UI). Treat it like a hot wallet.

## Clients

- **Browser / mobile light-miner & wallet** — `static/miner.html` (see above).
- **Desktop wallet** — `python3.10 pyside_wallet.py` (PySide6): overview, send, bond/unbond, register
  & mine, expected-time-to-mine, and a live selection-lane visualization. PySide6 is wallet-only; the
  node itself does not need it.
- **Block explorer** — every node exposes browsable JSON endpoints (`/get_account`, `/get_block`,
  `/get_transaction`, `/get_transactions_of_account`, `/get_supply`, `/status`, …), with a
  `readable=true` argument for human-friendly formatting, indexed from the homepage at `/`.

---

## Security

NADO's security rests on the two-lane selection design plus anti-DoS/anti-Sybil hygiene. The split
between **implemented** and **planned** below is the difference between testnet-safe and mainnet-safe —
read it before running anything of value.

### Implemented (live in production and verification paths)

- **Structural Sybil bound** — the open lane is exactly `K_OPEN` slots/epoch regardless of identity
  count, so a free botnet can never exceed 20 % of blocks. One-directional fail-closed empty-lane
  policy preserves the ceiling.
- **Fail-closed deterministic authorship** — `validate_block_producer`, called inside `verify_block`
  *before* incorporation, recomputes the two-lane winner from parent state + the epoch beacon and
  **rejects** any block whose producer isn't that winner (block integrity is by deterministic
  recomputation, optionally authenticated by the detached winner signature below).
- **Objective stake-weighted heaviest-chain fork-choice** — the canonical tip is `argmax
  cumulative_weight` among tips whose chain contains the node's finalized block, switching only on
  strictly-greater weight (lowest-hash tie-break). **Peer IPs, trust, and uptime carry exactly zero
  weight**, so a Sybil fleet of zero-bond IPs cannot reorg honest nodes. Replaces the old peer-IP
  plurality fork-choice.
- **Grind-proof `cumulative_weight` header** — committed inside the block-hash preimage as
  `parent.cumulative_weight + total_bonded_shares(as-of-parent)`. It is the *total* bonded registry
  weight (not the slot winner's share), so it is **beacon-independent**: a proposer can't grind the
  beacon to inflate fork weight. Recomputed in `rebuild_block` and verified as-of-parent.
- **Enforced finality floor** — a block at height H finalizes everything at/below `H - FINALITY_DEPTH`
  (`FINALITY_DEPTH = 30`); rollback **refuses** to cross the persisted, monotonic finalized height
  (raises `FinalityViolation`). The ordering `max_rollbacks (10) < FINALITY_DEPTH (30) < EPOCH_LENGTH
  (60)` means honest reorgs never hit the floor while a long-range reorg is capped below one epoch.
- **Fail-loud epoch beacon** — `epoch_beacon` chains from the hash of the first block of the previous
  epoch (a finalized, non-parent anchor), and now **raises instead of silently substituting**
  `GENESIS_BEACON` when the anchor is missing (a missing anchor means this node is under-synced).
- **Detached winner block signature** — when the selected winner is online it attaches an *optional*
  ML-DSA signature **outside** the hash preimage (so it never affects the hash, weight, validity, or
  reward); verifiers reject a present-but-forged or wrong-signer signature. An offline winner's
  relay-built block is simply unsigned and still valid — **"win-while-offline" is preserved**. (The
  *slashing action* on a double-signer's bond is still planned.)
- **Pubkey-once** — the 1312-byte ML-DSA `public_key` is **excluded from the txid** and stored once in
  account state on an address's first tx, so later txs (notably every-epoch heartbeats) omit it;
  validators recover it from committed state. Store/clear is byte-identically revert-symmetric.
- **Reward recompute-and-enforce**, **registration-PoW enforcement**, **canonical in-block tx
  ordering** (txid-sorted before hashing, so honest nodes selecting the same tx set produce an
  identical block hash).
- **Anti-DoS / eclipse throttles** — per-IP sliding-window rate limits on `/submit_transaction`
  (30 req/60 s) **and** `/announce_peer` (10 req/60 s), a **per-/16 peer-diversity cap** (at most
  `MAX_PEERS_PER_SUBNET = 4` peers per /16 in the live slots, so one network can't fill a victim's
  peer view), a hard mempool cap (150,000), heartbeat-index GC, and an SSRF guard (`check_ip` rejects
  own-IP and all non-globally-routable addresses).

### Planned (designed, NOT yet implemented — do not rely on these)

- **Equivocation slashing action** — the detached winner signature (now live) already yields a portable
  proof when a winner double-signs two blocks at the same height; the on-chain action that *docks the
  double-signer's bond/fidelity* is not yet implemented.
- **FFG-lite objective finality** — bonded checkpoint attestations advancing the finalized height at
  >2/3 bonded shares, beyond today's depth-based floor.
- **Full commit-reveal RANDAO** — on-chain commit/reveal with a withholder penalty (the primitives are
  written and unit-tested but **not** wired into the live beacon, which is the single chained anchor).
- **Broader eclipse hardening** — ASN-level peer-diversity caps (the per-/16 cap is already live),
  pinned anchor outbound slots, a multi-seed bootstrap list, and snapshot-bootstrap binding to a
  finalized signed checkpoint.

### Honest statement of current limits

Objective fork-choice and enforced finality make a zero-bond Sybil/IP reorg ineffective and bound the
disagreement window below one epoch — a substantial improvement over the previous peer-count
fork-choice. But without producer signatures, FFG finality, a full RANDAO, and eclipse hardening, NADO
remains **testnet-safe, not open-value-mainnet-safe**. All mining/economic parameters are
**provisional** and flagged *simulate-before-lock-in* in code.

---

## Cryptography & determinism

- **Signatures** — ML-DSA-44 (FIPS 204, post-quantum) via `dilithium-py`. Keys are a **32-byte seed**
  from which the 1312-byte public key and ~2420-byte signatures are deterministically regenerated.
  Consensus only ever checks `verify(sig, pk, msg) == True`, never signature-byte equality, so hedged
  signatures interoperate across implementations. Signatures authenticate transactions/heartbeats and
  are **deliberately never** the randomness source (a malleable signature would be grindable).
- **Addresses** — `"ndo"` + 42-hex public-key prefix + a 4-hex `blake2b` checksum (49 chars). The
  keyless reserved recipients `{bond, unbond, register, heartbeat}` are valid as a recipient/target
  only, never as a sender.
- **Hashing & serialization** — BLAKE2b over `canonical_bytes()` (compact, sorted-key, ASCII JSON,
  float-free). Every consensus integer is a raw integer, so a browser reproduces identical bytes with
  BigInt-aware serialization. Transaction ids and blocks bind `CHAIN_ID = "nado-relaunch-1"`, blocking
  cross-chain / pre-relaunch replay.
- **Wire** — transactions submit over **HTTP POST + msgpack** (an ML-DSA-44 tx is too large for a GET
  URL); msgpack is wire/transport only and never the hashed preimage.

## Storage

State lives in a single **schemaless, memory-mapped, ACID key-value store (LMDB)** — `ops/kv_ops.py`,
which **replaced the prior SQLite index**. Account/state records are schemaless msgpack documents
(no columns, no DDL), so adding a field needs no migration. A whole block's mutations (account docs,
tx index, block index, totals, heartbeats) commit in **one** write transaction, so a crash leaves a
block either fully applied or not at all, and replay is idempotent. Block bodies stay as `zstd(msgpack)`
files under `blocks/`, and consensus hashing stays canonical JSON — neither is touched by the index.

## Private key storage

Keys are post-quantum **ML-DSA-44 (FIPS 204)**; what is stored is the 32-byte seed. Your `ndo…` address
shape is unchanged (49 chars).

- Linux: `~/nado/private/keys.dat`
- Windows: `C:\Users\<username>\nado\private`

---

## Learn more

- **Whitepaper** — [`doc/whitepaper.md`](doc/whitepaper.md): the authoritative, accuracy-reviewed
  overview of the mechanism, with a full constants table and an explicit implemented-vs-planned split.
- **Consensus hardening plan** — [`doc/consensus-hardening-plan.md`](doc/consensus-hardening-plan.md):
  the locked, ordered design for the remaining security milestones.
- **Storage design** — [`doc/storage-kv-migration.md`](doc/storage-kv-migration.md).
- **Release notes** — [`RELEASE_NOTES.md`](RELEASE_NOTES.md).
- Project site: <https://nodeisok.com>

`protocol.py` and the `ops/` modules are the source of truth; where an older companion doc disagrees,
the code wins.

## Related repositories

- [NADO .NET SDK](https://github.com/blocksentinel/nado-dotnet-sdk)
- [NADO Media Kit](https://github.com/hclivess/nado-media-kit)
- [NADO Web Repository](https://github.com/hclivess/nado-web)

---

## For developers

### Design philosophy

New functionality should be driven by the existing routines/loops rather than instant invocation of
functions — every function should have its place in the routine responsible for it. Functions should
be small, independent, and named after the small task they perform; prefer returning values to mutating
objects passed as arguments. Use the existing compounder for multi-target loops rather than synchronous
loops.

### How NADO is structured

- **Level III** — `nado.py` runs all loops and governs API endpoints.
- **Level II** — a central memory element, `memserver.py`, holds shared state accessed by the main
  loops (`consensus_loop.py`, `core_loop.py`, `message_loop.py`, `peer_loop.py`).
- **Level I** — `*_ops.py` modules (`block_ops.py`, `account_ops.py`, `transaction_ops.py`,
  `mining_ops.py`, `kv_ops.py`, `peer_ops.py`, …) hold minimal low-level operations.

### Block production

A block is built with `construct_block()`, then produced via `produce_block()` →
`verify_block()` (with `rebuild_block()` to recompute hashes/weights for remotely received blocks) →
`incorporate_block()`. The mempool has three levels: `user_tx_buffer` (direct user submissions) →
`tx_buffer` (merged with other nodes' pools for the next block) → `transaction_pool` (merged in before
block production).

### Contributing

Fork the repository, make your changes, and open a merge request.
