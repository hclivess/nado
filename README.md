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

> **Status: testnet-stage alpha, NOT yet mainnet-launched.** The fair-mining economics and the full
> consensus-security hardening plan (objective fork-choice, enforced finality, grind-proof chain
> weight, detached winner signatures + **equivocation slashing**, **FFG-lite stake-attested finality**,
> **commit-reveal RANDAO**) are now implemented; the multi-node, epoch-crossing behaviour of the last
> three is still only lightly exercised empirically (see [Security](#security)). What genuinely remains
> is a subset of **eclipse hardening** (ASN-level peer diversity, pinned multi-seed bootstrap, snapshot-
> bootstrap binding to a finalized signed checkpoint). Run it on testnet / at your own risk; do not
> secure value of consequence with it yet. Chain id: `nado-relaunch-1`.

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

A `bond` transaction moves spendable balance into a non-spendable `bonded` column; an `unbond`/`withdraw`
pair moves it back out after a timelock (see below). Bonded selection weight is
`min(bonded, BOND_CAP) // B_MIN`, capped at `MAX_SHARES = 100`:

- **Split-neutral** — weight depends only on total bonded capital, so sharding across many addresses
  gains nothing.
- **Whale-capped** — a single identity tops out at `BOND_CAP = 10,000 NADO` (`B_MIN = 100 NADO` per
  share), so no whale can monopolise the lane. The bond is **refundable** — you keep your coins.

> **Unbond is now timelocked (enforced).** `unbond` is a **release request**, not an instant refund:
> the stake **stays in the `bonded` column — still slashable** — and a maturity block
> `release_block = current + BOND_UNLOCK_DELAY (1440)` is recorded. A separate fee-exempt **`withdraw`**
> transaction moves the matured amount to spendable balance only **at/after** `release_block`. Keeping
> the stake bonded through the delay is what keeps a *caught equivocator's* stake slashable while the
> unbond is in flight. One unbond may be pending at a time.

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
  `MIN_TX_FEE = 1000` raw applies to ordinary transfers and `bond`; `register`, `heartbeat`, `unbond`,
  and `withdraw` are fee-exempt (they move no coins out — `unbond`/`withdraw` only retime the sender's
  own stake).
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
payment links and `#pay` deep links, bond/unbond, and show history — all from a phone. It also shows
**how busy each lane is right now** — live **OPEN** and **BONDED** participant counts (from
`/mining_status` `open_registry_size` / `bonded_registry_size`) alongside your own bonded shares — so a
miner can see the field it is competing against. Crypto is **vendored** (`static/vendor/nado-crypto.js`:
blake2b + ML-DSA-44) so it works offline, and an in-page self-test asserts byte-equality of its canonical
encoding against the live repo on boot.

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

### Security audit (all exploitable findings fixed)

A deep adversarial audit was run across **six surfaces** (fork-choice/51%/rollback/finality;
Sybil/two-lane/selection; slashing/equivocation/unbond; RANDAO/FFG/beacon; tx-validation/pubkey-once;
KV atomicity/eclipse/DoS), against a chain that was **testnet-stage alpha with no value at stake**.
Every **exploitable** finding it surfaced is now **fixed and unit-tested** — full writeup in
[`doc/security-audit.md`](doc/security-audit.md). In brief:

- **In-block duplicate reserved-tx bugs (CRITICAL/HIGH).** Uniqueness was checked only against
  *parent* state and block assembly did no dedup, so duplicates of a reserved tx in **one** block could
  drain a single unbond via repeated `withdraw`s (slash-escape / chain-halt), over-burn on a duplicate
  `slash` (which two honest reporters trigger organically), or collapse duplicate `heartbeat`/`reveal`
  rows so a reorg over-deletes the shared row → **registry/beacon desync fork**. Fixed by **per-reserved-tx
  in-block uniqueness** (`reserved_uniqueness_key` + `dedupe_reserved` in assembly + `assert_unique_reserved`
  in `verify_block`), plus cross-block `heartbeat`/`reveal`-secret guards.
- **Same-length fork-choice wedge (CRITICAL, liveness).** Two equal-weight honest tips at one height
  could wedge forever because the switch was strictly-greater-weight only. Fixed by the deterministic
  **lowest-hash tie-break**: every node now switches to the global-best tip by `(weight DESC, hash ASC)`,
  so they converge.
- **`quick_sync` validation bypass (HIGH).** Old-block sync skipped signature + spending checks. `verify_block`
  now **always** runs `validate_transactions_in_block` — the bypass is gone.
- **Unauthenticated advertised-weight DoS (HIGH).** A single Sybil peer advertising a huge
  `latest_block_weight` forced honest nodes into emergency rollbacks. Fixed by a bounded, auto-clearing
  **`rejected_tips`** exclusion so a bogus weight can't loop a node.
- Plus: **per-IP rate limits** on the heavy unauthenticated read endpoints (`/mining_status`,
  `/get_transactions_of_account`, `/get_blocks_after`/`/get_blocks_before`); an **honest-signer guard**
  (a node only ever signs a *strictly higher* height, so an honest re-signer can't be slashed for its own
  reorg); the **per-/16 subnet cap now also gates the disk-reload path**; and a dead `/get_blocks_before`
  was fixed.

The audit also **confirmed the safety core sound** with no change needed: the atomic
incorporate/rollback window, the monotonic finality floor, equivocation-proof unforgeability (and the
no-innocent-victim address binding), the detached-signature-outside-the-hash property, and pubkey-once
key→sender binding. The remaining items are documented **residuals / future hardening** (below and in
[`doc/security-audit.md`](doc/security-audit.md)), none of which is a theft or fork vector in the current
code.

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
  relay-built block is simply unsigned and still valid — **"win-while-offline" is preserved**.
- **Equivocation slashing** — two valid winner signatures over *different* blocks at the *same*
  height+parent form a portable proof that an identity double-authored a slot. A fee-exempt `slash`
  transaction carrying that proof burns `SLASH_BOND_PENALTY` (= `B_MIN`, one bonded share) of the
  offender's **bonded** stake. Anyone may report it (the unforgeable proof is the anti-spam); it is
  replay-guarded to **one slash per (offender, height)**, revert-symmetric on rollback, and the coins
  are **destroyed** (the deterrent is the loss, not a bounty). Validation requires the offender still
  hold the penalty so the dock never floors.
- **FFG-lite stake-attested finality** — bonded validators emit one `attest` transaction per epoch for
  that epoch's checkpoint (its first block). A checkpoint **justifies** at *strictly* >2/3 of total
  bonded shares (`FFG_NUM/FFG_DEN = 2/3`) and **finalizes** on two-consecutive-justified; on-chain
  `UNIQUE(validator, epoch)` prevents double-voting. This is exposed as **`/status.ffg_finalized`**.
  It is an **additive, observable, accountable** finality signal layered *on top of* the depth-based
  floor — it does **not** replace the time-based `finalized_height` (which stays the deeper rollback
  bound and guarantees liveness), so FFG can never stall the chain.
- **Commit-reveal RANDAO** — bonded validators `commit` a secret's hash in epoch E−2 and `reveal` it
  in E−1's finalized window; `epoch_beacon` now mixes the finalized prior-epoch anchor with the
  revealed secrets, so **no single anchor-producer controls the beacon**. With zero reveals it falls
  back to the anchor-only value (liveness). It keeps the anchor (non-recursive), so the beacon stays
  snapshot-safe and the reveals are immutable by the time the beacon is needed.
- **Pubkey-once** — the 1312-byte ML-DSA `public_key` is **excluded from the txid** and stored once in
  account state on an address's first tx, so later txs (notably every-epoch heartbeats) omit it;
  validators recover it from committed state. Store/clear is byte-identically revert-symmetric.
- **Reward recompute-and-enforce**, **registration-PoW enforcement**, **canonical in-block tx
  ordering** (txid-sorted before hashing, so honest nodes selecting the same tx set produce an
  identical block hash).
- **Anti-DoS / eclipse throttles** — per-IP sliding-window rate limits on `/submit_transaction`
  (30 req/60 s) **and** `/announce_peer` (10 req/60 s), **plus the heavy unauthenticated read endpoints**
  (`/mining_status`, `/get_transactions_of_account`, `/get_blocks_after`/`/get_blocks_before`, added in
  the audit), a **per-/16 peer-diversity cap** (at most `MAX_PEERS_PER_SUBNET = 4` peers per /16 — now
  enforced on the disk-reload path too, so one network can't fill a victim's peer view), a hard mempool
  cap (150,000), heartbeat-index GC, and an SSRF guard (`check_ip` rejects own-IP and all
  non-globally-routable addresses).

### Lightly exercised (implemented + unit-tested, but not yet hardened on a live multi-node net)

The equivocation slashing, FFG-lite finality, and commit-reveal RANDAO above are **wired and
unit-tested for correctness**, but their **multi-node, epoch-crossing** behaviour has only been
**lightly exercised empirically**: the core loop's ~10 s/block cadence makes crossing the 120+ blocks
needed to observe a full justify→finalize and a complete commit→reveal cycle slow. They engage as the
chain crosses epochs; treat their cross-epoch dynamics as not-yet-battle-tested.

### Planned (designed, NOT yet implemented — do not rely on these)

- **Broader eclipse hardening** — beyond the per-/16 subnet cap and the `/announce_peer` rate-limit
  (both already live): **ASN-level** (vs /16) peer-diversity caps, pinned anchor outbound slots, a
  **multi-seed** bootstrap list (replacing the single genesis seed), and **snapshot-bootstrap binding
  to a finalized signed checkpoint**. These are post-launch items.

### Honest statement of current limits

Objective fork-choice, enforced finality, equivocation slashing, FFG-lite stake-attested finality, and
the commit-reveal RANDAO make a zero-bond Sybil/IP reorg ineffective, bound the disagreement window
below one epoch, and layer accountable finality and a non-grindable beacon on top — a substantial
hardening over the previous peer-count fork-choice. Beyond the lightly-exercised cross-epoch behaviour
of FFG/RANDAO and the outstanding eclipse hardening above, the **documented residuals** from the audit
(see [`doc/security-audit.md`](doc/security-audit.md)) — none a theft or fork vector — are:

- **No RANDAO withholder penalty.** A producer suppressing its own reveals has up to `2^m` grinding
  combinations; defeated whenever ≥1 honest secret is revealed after the anchor. A withholder fidelity
  dock + minimum-reveal rule is future work.
- **FFG "slashable-stake backing" is aspirational** — there is **no attestation-equivocation slashing**
  yet (only block-authorship equivocation is slashable). On-chain double-voting is blocked by the
  per-epoch `UNIQUE(validator, epoch)` marker, but cross-fork attestation equivocation is unpunished;
  FFG remains an observational signal.
- **The bonded `MAX_SHARES` cap is per-identity, not aggregate** — sharding capital above `BOND_CAP`
  across addresses recovers full proportional weight. The bonded lane is **capital-proportional by
  design**; the cap only limits single-address variance, not aggregate stake.
- **Registration / fee-exempt state growth** — `register` writes a permanent account doc; `GC_IDLE_EPOCHS`
  is defined but **not yet wired**. Bounded today by the lane cap, per-IP rate limit, mempool cap, and the
  in-block one-register-per-sender dedup; idle-account GC is future work.
- **`FIDELITY_DECAY` is unwired** (absent identities keep accumulated fidelity), bounded by the open-lane
  ceiling.
- **Snapshot bootstrap** trusts an 80%-of-peers quorum with **no hardcoded finalized checkpoint**
  cross-check (weak-subjectivity); a pinned checkpoint is future eclipse hardening.

All mining/economic parameters are **provisional** and flagged *simulate-before-lock-in* in code. NADO
remains a **testnet-stage alpha, not open-value-mainnet-safe**. (No hardfork concern: mainnet is not
live.)

---

## Cryptography & determinism

- **Signatures** — ML-DSA-44 (FIPS 204, post-quantum) via `dilithium-py`. Keys are a **32-byte seed**
  from which the 1312-byte public key and ~2420-byte signatures are deterministically regenerated.
  Consensus only ever checks `verify(sig, pk, msg) == True`, never signature-byte equality, so hedged
  signatures interoperate across implementations. Signatures authenticate transactions/heartbeats and
  are **deliberately never** the randomness source (a malleable signature would be grindable).
- **Addresses** — `"ndo"` + 42-hex public-key prefix + a 4-hex `blake2b` checksum (49 chars). The
  keyless reserved recipients `{bond, unbond, withdraw, register, heartbeat, slash, attest, commit,
  reveal}` are valid as a recipient/target only, never as a sender.
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
