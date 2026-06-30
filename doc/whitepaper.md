# NADO: A Phone-Mineable, Fair-Launch, Post-Quantum Lightweight Blockchain

**2026, provisional draft.**

> **PROVISIONAL NOTICE.** This document is a provisional whitepaper for the NADO
> relaunch. It describes a design that is partly implemented and partly planned.
> Sections explicitly distinguish what is **live in code today** from what is
> **designed but not yet wired**. All numeric parameters are taken from
> `protocol.py`, the consensus source of truth, but are themselves marked
> *PROVISIONAL — simulate before lock-in* in code and may change before mainnet.
> NADO in its current form is **testnet-safe, not open-value-mainnet-safe**. The
> first wave of consensus hardening **is now implemented and testnet-validated**:
> objective stake-weighted heaviest-chain fork-choice, an enforced finality floor,
> a grind-proof `cumulative_weight` header, a fail-loud epoch beacon, a detached
> optional winner block signature, and pubkey-once. The remaining hardening —
> equivocation/attestation slashing actions, FFG-lite objective finality, a full
> commit-reveal RANDAO, and broader eclipse defenses — is **not yet implemented**.
> Do not deploy this software to secure value of consequence until that remaining
> milestone lands. Where the older
> design docs (`doc/economics.md`, `doc/security-review.md`, `doc/mining.md`,
> `doc/determinism-and-chain-id.md`) disagree with this paper, the **code** is
> authoritative and those docs are known to be stale.

---

## Abstract

NADO is a lightweight blockchain designed so that an ordinary phone, running a
pure-browser client with no full node, can participate in block production for
zero capital, on a fair launch with no premine, secured by post-quantum
signatures. It replaces grindable, hash-race mining with a **deterministic,
beacon-keyed weighted draw**: for each slot exactly one hash decides the
producer, so there is no nonce grinding and faster hardware confers no advantage
(ASIC/GPU-irrelevant). Production is split into two lanes per epoch — an **OPEN**
lane that anyone can win with zero coins, and a **BONDED** lane won in proportion
to locked, refundable stake. Because the lane split permutes *slot indices*
rather than per-identity weight, the zero-capital lane is a fixed fraction of
blocks (currently 20%) regardless of how many identities register, giving a
*population-independent* structural Sybil ceiling. Coins enter circulation only
through block rewards (a flat base subsidy plus a capped, fee-weighted elastic
term), split 90/10 between producer and a founder-held treasury that starts
empty. Consensus hashing is over canonical JSON so a vendored-crypto browser
client reproduces addresses, transaction IDs, and verification byte-for-byte.
Derived state lives in a single schemaless, memory-mapped, ACID **LMDB** key-value
store. The first wave of consensus hardening — objective stake-weighted fork-choice,
an enforced finality floor, a grind-proof chain-weight header, a fail-loud beacon, a
detached optional winner signature, and pubkey-once — is **live in code today**; this
paper documents the live mechanism and is explicit about the consensus hardening that
remains to be built.

---

## 1. Motivation

Most "anyone-can-mine" claims fail in one of four ways: mining is captured by
specialized hardware; launches are not fair (premines, insider allocations);
the cryptography is not quantum-resistant; or a "light" client still depends on
trusted infrastructure. NADO targets all four simultaneously.

- **Phone-mineable.** Block production is decided by a single hash per slot over
  a public beacon, not by a hash race. There is nothing to grind, so a phone
  competes on equal terms with a datacenter. A winner is credited *by address*,
  so a phone can win a slot while offline and a relay can assemble the block on
  its behalf.
- **Fair launch, no premine.** Genesis mints **zero** coins. There is no founder
  balance and no treasury seed; the chain bootstraps purely through the open
  mining lane.
- **Post-quantum.** Signatures are ML-DSA-44 (FIPS 204 / Dilithium), not
  elliptic-curve. The implementation is pure-Python with a vendored JS twin, so
  there is no native dependency to compile and the same crypto "runs on
  anything."
- **Lightweight and reproducible.** All consensus-hashed structures are integers
  and strings serialized as canonical JSON, so a browser client with BigInt-aware
  serialization reproduces every consensus byte. State is a single schemaless,
  memory-mapped key-value index (LMDB); block bodies are compact compressed blobs.

NADO is a relaunch. There is no live legacy network to migrate; `protocol.py`
defines genesis behavior directly, with no fork-height activation gates.

---

## 2. Two-Lane Diligence Mining

### 2.1 Epochs, slots, and lanes

Time is divided into **epochs** of `EPOCH_LENGTH = 60` slots. Each epoch is
keyed by a per-epoch **beacon** (Section 3). Within an epoch, the 60 slots are
partitioned into two lanes:

- the **OPEN lane** — `K_OPEN = 12` slots (~20%), winnable by any registered,
  present identity for **zero capital**; and
- the **BONDED lane** — the remaining 48 slots, won in proportion to locked,
  refundable stake.

`lane_of()` assigns each slot to a lane by a **beacon-keyed permutation of slot
indices**: it ranks slots by `blake2b([beacon, "lane", j])` and labels the
`K_OPEN` lowest-ranked slots OPEN, the rest BONDED. *(implemented —
`ops/mining_ops.py`)*

### 2.2 The Sybil bound is structural and population-independent

The key property is that the split is over **slot indices, not per-identity
weight**. There are exactly `K_OPEN` open slots per epoch no matter how many
identities register. A zero-capital botnet of a million identities still cannot
win more than `OPEN_BPS = 2000` basis points (20%) of blocks. The Sybil defense
is therefore the **lane cap itself**, a fixed structural ceiling, not a puzzle
difficulty or an economic cost. `OPEN_BPS` is the project's central security
dial. *(implemented)*

### 2.3 No hash race: ASIC/GPU-irrelevance via draw-not-race

For a given slot, once the lane is fixed, a **single** `blake2b` hash over
`[beacon, slot]` selects the winner from that lane's registry via a
cumulative-weight band walk over canonically sorted addresses (Section 3.1).
There is **no multi-attempt hash race and no nonce grinding** — one hash decides
each slot. Consequently, faster hashing hardware confers *no advantage*: the
design is ASIC/GPU-irrelevant by construction, and the same draw is trivially
reproducible by a browser client. *(implemented)*

### 2.4 OPEN lane: free entry, diligence-weighted

Open-lane participation costs no coins. An identity:

1. **Registers** once by solving a light registration proof-of-work
   (`REGISTER_POW_BITS = 16`; hash must be `< 2**(256-16)`, with the nonce bound
   to the sender address). This substitutes for the network fee that a
   zero-balance newcomer cannot pay. It is an **anti-spam throttle, not the Sybil
   defense** — the lane cap is. *(implemented)*
2. **Heartbeats** each epoch with a signed, fee-exempt, zero-amount transaction.
   Presence is required: `get_open_registry` includes only registered addresses
   with a heartbeat within the last `PRESENCE_WINDOW = 3` epochs. Membership is
   derived from the heartbeat index, so an abandoned registration simply drops
   out with no decay bookkeeping. *(implemented)*

An open identity's selection weight is **capital-free**: a flat floor
`OPEN_BASE_FLOOR = 1` that every present identity always receives (never scaled
to zero), plus a **diligence bonus** that ramps linearly to `OPEN_FID_BONUS = 9`
over `FIDELITY_CAP = 1000` epochs of continuous presence — an overall range of
**1..10**. The open registry reads a real on-chain `fidelity` column, so this
ramp is live. *(implemented)*

> Note: `FIDELITY_DECAY = 1` is defined in `protocol.py` as an intended
> per-epoch absence decay, but no decay path is wired in code today. Fidelity
> grows via heartbeats and reverses only on rollback; there is currently no
> active absence-decay mechanism. *(planned)*

### 2.5 BONDED lane: split-neutral, whale-capped stake

`bond` and `unbond` transactions move spendable balance into and out of a
non-spendable `bonded` column. Bonded-lane selection weight is:

```
shares = min(bonded, BOND_CAP) // B_MIN      (0 below B_MIN)
```

with `B_MIN = 100 NADO` per share and `BOND_CAP = 10,000 NADO`. Two consequences:

- **Split-neutral.** Sharding capital across many addresses gives *zero*
  advantage — weight depends only on total bonded capital, capped per identity.
- **Whale-capped.** A single identity tops out at `MAX_SHARES = BOND_CAP // B_MIN
  = 100` shares, so no whale can monopolize the bonded lane. *(implemented)*

> **v1 limitation.** The bonded lane runs with **no time ramp**:
> `get_bonded_registry` passes `fidelity = None`, so a bonded identity receives
> full capped weight immediately. The anti-instant-whale fidelity ramp exists as
> a pure function but is **dormant** on the bonded lane today; only the OPEN lane
> uses it. *(partial)*

### 2.6 Empty-lane policy (one-directional, fail-closed)

If an OPEN slot has an empty open lane, it **falls back to the BONDED lane** (the
safe capital lane over-produces). If a BONDED slot has an empty bonded lane, it
is **skipped — never falling back to OPEN**. This asymmetry preserves the
`OPEN_BPS` ceiling: the free lane can never absorb bonded slots. *(implemented —
`select_producer_two_lane`)*

---

## 3. Producer Selection and Randomness

### 3.1 The deterministic weighted draw

For a slot, the winner is chosen by:

```
draw   = int(blake2b_hash([beacon, slot]), 16) % total_weight
winner = the address whose cumulative-weight band contains `draw`,
         walking addresses in canonical sorted order
```

This is a single integer-only computation over a public beacon — no signatures
feed the randomness, no grinding is possible, and any full node or browser client
reproduces the same winner. *(implemented — `_weighted_draw`)*

Selection integrity in the live system rests on **deterministic recomputation,
not a producer signature**: every verifier recomputes the winner from committed
parent state and the epoch beacon. A winner *may* additionally attach a **detached,
optional** ML-DSA signature (Section 7.2, #15), but that signature lives **outside**
the hashed block body and the validity/weight/reward path — it is never required, so
"win while offline" is preserved and block integrity never depends on it.

### 3.2 The live epoch beacon (v1: chained anchor)

The live beacon is **grind-resistant but not yet a full RANDAO**:

- Epochs 0–1 use a fixed `GENESIS_BEACON = blake2b_hash(["nado-genesis-beacon",
  CHAIN_ID])`.
- Epoch ≥ 2 chains `GENESIS_BEACON` with the hash of the **first block of the
  previous epoch** — a deeply finalized, non-parent anchor at least one epoch
  back. Per-slot rotation comes from hashing `[beacon, slot]`.

Anchoring to a finalized prior-epoch block (rather than the parent block hash)
closes the grindable-seed weakness (audit item M6): a producer cannot grind the
parent hash to bias its own selection. *(implemented — `epoch_beacon`)*

> **Now fail-loud.** `epoch_beacon` previously *silently* fell back to
> `GENESIS_BEACON` when the anchor block was missing locally — a consensus-split /
> eclipse hazard, since an under-synced node would draw a different producer set for
> the whole epoch. It now **raises instead of substituting** (a missing finalized
> anchor means this node is under-synced and must resync). The anchor is also kept
> un-reorgable by the **enforced** ordering `max_rollbacks (10) < FINALITY_DEPTH (30)
> < EPOCH_LENGTH (60)` (Section 7), so it is finalized before any epoch it governs
> goes live. *(implemented)*

### 3.3 Planned: full commit-reveal RANDAO

A full on-chain **commit-reveal RANDAO** — chained, reveal-order-independent, and
withholding-sensitive (a single withholder can bias at most one bit) — is
**designed**, and its pure functions (`beacon_commitment`, `verify_reveal`,
`compute_beacon`) are written and unit-tested. It is **NOT wired into the live
beacon**: there are no on-chain commit/reveal transactions and no withholder
penalty today. The live `epoch_beacon` uses only the single chained anchor. This
paper does **not** present the full RANDAO as live. *(planned)*

---

## 4. Economics

`protocol.py` is the economic source of truth. All amounts are integers in raw
units where `1 NADO = DENOMINATION = 1e10` raw. There are **no fork-height
activation gates** — these values define genesis directly.

### 4.1 No premine

Genesis mints **zero** coins: `TREASURY_GENESIS = 0`. There is no founder
allocation and no treasury seed. The chain bootstraps purely through the open
mining lane — register for free, earn the base subsidy from block 1. *(implemented)*

> The testnet path may *seed bonded/open accounts* off-chain (from local files
> or env), but this does **not** alter the genesis block hash and is **not** a
> coin allocation: `TREASURY_GENESIS` stays 0. Account seeding must not be
> conflated with a balance premine.

### 4.2 Per-block reward: base subsidy + elastic fee term

Every block reward is:

1. a flat **base subsidy floor** `BASE_SUBSIDY = 0.1 NADO/block` (~144 NADO/day
   at 60s blocks), independent of fees. Without a floor, a no-premine chain
   deadlocks (0 coins → 0 fees → 0 reward forever); plus
2. a **fee-weighted elastic term** equal to the **trailing 100-block
   (`REWARD_WINDOW = 100`) average fee per block**, computed from the block's own
   ancestry via a single indexed cumulative-fee lookback (not a tip-anchored
   walk) so full and pruned/snapshot nodes agree;

clamped to `REWARD_CAP = 0.5 NADO` per block. *(implemented)*

> `BASE_SUBSIDY` is explicitly *tunable*; **no halving or issuance schedule
> exists yet** — emission today is a perpetual flat floor plus a capped elastic
> term. A halving schedule is noted as future work. *(planned)*

### 4.3 Treasury tax (90/10 split)

Each reward is split **90% producer / 10% treasury** (`TREASURY_BPS = 1000`).
`split_block_reward` floors the producer cut and gives the treasury the exact
remainder, so incorporate and rollback subtract identical integers and never
desync. The **treasury *is* the genesis address**: a normal, founder
key-controlled ML-DSA address (not a keyless protocol label), re-checksummed
under the canonical hash. It starts empty and fills only from the per-block cut;
the 10% is effectively founder revenue. *(implemented)*

### 4.4 Bonding, whale dampening, and fees

- **Bonding** is refundable locked stake: `bond` debits `amount + fee` from
  spendable balance and adds `amount` to the non-spendable `bonded` column;
  `unbond` reverses it (fee destroyed). A guarded UPDATE keeps `bonded`
  non-negative (fails closed). *(implemented)*
- **Whale dampening (capital).** Selection weight is split-neutral and
  per-identity capped (Section 2.5): `min(bonded, BOND_CAP) // B_MIN`, capped at
  `MAX_SHARES = 100`. *(implemented)*
- **Whale dampening (time).** A fidelity ramp to scale a newcomer's bonded weight
  to full over `FIDELITY_CAP` epochs is designed but **dormant** on the bonded
  lane in v1 (live only on the open lane). *(partial)*
- **Unbond timelock.** `BOND_UNLOCK_DELAY = 1440` blocks is **defined but not
  enforced** — `unbond` currently releases stake to spendable balance
  *immediately*. Do not assume withdrawals are time-locked. *(planned)*
- **Fees** are **destroyed**, not paid to producers: they accumulate into each
  block's `cumulative_fees` header (which drives the elastic reward) rather than
  crediting any address. A deterministic integer floor `MIN_TX_FEE = 1000` raw
  applies to ordinary/bond/unbond transactions. (Register/heartbeat are
  fee-exempt and zero-amount.) The legacy `burn` mechanic is entirely removed.
  *(implemented)*
- **No auto-bond faucet.** Free open-lane presence can never mint bonded stake.
  The only free→capital path is the block subsidy an open miner actually earns —
  itself capped at `OPEN_BPS` (20%). Genesis enforces this with an explicit
  faucet guard. *(implemented)*

---

## 5. Post-Quantum Cryptography and Determinism

NADO's consensus crypto rests on three live pillars.

### 5.1 Post-quantum signatures (ML-DSA-44)

Signatures are **ML-DSA-44 (FIPS 204 / Dilithium)**, via the pure-Python
`dilithium-py` library (no native build). The module is still named
`Curve25519.py` only for import stability — the algorithm is **not** Ed25519.
Keys use a **32-byte seed** from which the 1312-byte public key and the ~2420-byte
signatures are deterministically regenerated via `KeyGen_internal(seed)`. Signing
uses ML-DSA **INTERNAL** mode with a fresh 32-byte hedge, chosen to match
`@noble/post-quantum`'s default so a browser client and a node interoperate.
`verify()` returns `False` on any exception (fail-closed). *(implemented)*

Crucially, consensus **only ever checks `verify(sig, pk, msg) == True`, never
signature-byte equality**. Hedged/randomized signatures therefore need not be
reproducible across implementations — only hashes and transaction IDs are
reproduced. Signatures authenticate heartbeats/reveals and transactions; they are
**deliberately never used as the randomness source** (a malleable
`(R,S)`-style signature would be grindable). *(implemented)*

### 5.2 Canonical serialization and hashing

All consensus hashing/signing inputs are serialized by `canonical_bytes()` =
compact, sorted-key, ASCII JSON with **no floats** (`json.dumps(..,
sort_keys=True, separators=(',',':'), ensure_ascii=True)`), replacing a prior
non-deterministic `repr()` encoding (audit M14). `blake2b_hash` (digest size 32)
hashes those bytes; `blake2b_hash_link(a, b)` hashes the two-element **list**
`[a, b]` (a list, not a tuple, for JSON/browser reproducibility). Because
serialization must be float-free, every consensus integer — amounts, fees,
timestamps, block numbers, rewards, cumulative fees — is a raw integer. A
browser reproduces identical bytes with BigInt-aware `JSON.stringify` over
recursively sorted keys (BigInt is required because raw amounts exceed JS's
`2**53` safe-integer limit). *(implemented)*

### 5.3 Addresses, transactions, and chain binding

- **Address** = `"ndo"` + `public_key[:42]` (hex) + a 4-hex `blake2b` checksum;
  total 49 chars. `validate_address` recomputes the checksum. The keyless
  reserved recipients `{bond, unbond, register, heartbeat}` bypass the checksum
  rule and are valid only as a recipient/target, never as a sender. *(implemented)*
- **Transaction binding.** `txid = blake2b_hash(canonical body)`, including
  `CHAIN_ID = "nado-relaunch-1"`; the signature is taken over `unhex(txid)`.
  `validate_txid` independently recomputes the txid so any field tamper is
  rejected, and `validate_origin` checks both the signature and
  `make_address(public_key) == sender`. `CHAIN_ID` binding prevents
  cross-chain/pre-relaunch replay (audit M3). *(implemented)*
- **Validation.** The sender must be a real keyed address (`allow_reserved=False`);
  recipient/target must be checksum-valid *or* reserved; `amount` and `fee` must
  be integers (not bool, not float) with `amount >= 0`. Register requires a valid
  one-time PoW and not-already-registered; heartbeat requires
  `epoch == block_height // EPOCH_LENGTH` (anti-replay) from a registered address.
  *(implemented)*

---

## 6. Storage, Serialization, and Clients

NADO separates three concerns that are easy to conflate.

### 6.1 Block bodies (local, non-consensus)

Block bodies are persisted as `zstd(msgpack(block))` files at
`blocks/<hash>.block` (zstd level 3, to recover the ~2x redundancy of hex
signature/pubkey strings — important for PQ-sized signatures). A 4-byte zstd frame
magic is sniffed on read so legacy raw-msgpack bodies still decode. Writes are
crash-safe: write to `<hash>.block.tmp`, flush+fsync, then atomic
`os.replace` (bounded to 60 retries, then raise). This on-disk format is **purely
local**: the block hash is computed over **canonical JSON**, never over the stored
file, so the storage encoding can change with no fork. *(implemented)*

### 6.2 State index (one schemaless LMDB key-value store)

Derived state lives in a single **schemaless, memory-mapped, ACID key-value store
(LMDB)** — `ops/kv_ops.py`, which **replaced** the prior SQLite index. There is one
LMDB environment (`index/state/`) with named sub-DBs: `accounts`, `totals`,
`block_by_num`, `block_by_hash`, `tx`, `tx_by_sender`, `tx_by_recipient`,
`heartbeats`, and `meta`. Account/state records are **schemaless msgpack documents
with no columns** (`{balance, produced, bonded, registered, fidelity, …}`), so adding
a field — as the relaunch did with `registered`/`fidelity`/`public_key` — needs **no
DDL and no migration**. Integer keys are 8-byte big-endian so range scans
(`block_by_num`, `heartbeats` presence window, `tx_by_*` history) preserve numeric
order; the `heartbeats`, `tx_by_sender`, and `tx_by_recipient` sub-DBs are `DUPSORT`,
giving auto-deduped multi-value keys (one heartbeat per `(address, epoch)` enforced
for free). `incorporate_block` and `rollback_one_block` wrap **all** of a block's
mutations — account docs, tx index, block index, totals, heartbeats — in **one**
`env.begin(write=True)` transaction, so a crash leaves a block either fully applied
or not at all; replay is idempotent (`block_already_indexed`), preventing
double-credit. Because LMDB is single-writer + copy-on-write and the document
encoding is canonicalized (deterministic field order), every revert returns a
document **byte-identical** to its pre-apply state. The KV store is a *derived,
rebuildable index* — block bodies and consensus hashing are not touched by it (6.1,
5.2). *(implemented)*

### 6.3 Wire transport vs. consensus preimage

`msgpack` is used **only** as wire/transport encoding (RPC `?compress=msgpack`,
block sync, and the POST submit body for PQ-sized transactions) and as the local
block-body container — **never** as the hashed preimage, which is always canonical
JSON. A `POST /submit_transaction` endpoint was added because an ML-DSA-44
transaction (~7.8 KB) does not fit a GET URL; both GET and POST paths are
rate-limited (Section 7). *(implemented)*

### 6.4 Browser light-miner and full wallet

`static/miner.js` + `static/miner.html` let a phone mine and transact with **no
full node**. It reproduces the node's canonical encoding and crypto exactly
(addresses, txids, ML-DSA-44 signatures), solves the registration PoW in pure JS
(16-bit, chunked/cancellable), then registers and heartbeats against a relay that
assembles the crediting block. Crypto is **vendored** (`./vendor/nado-crypto.js`,
blake2b + ML-DSA-44) so it works offline, with a CDN fallback only if the local
bundle is absent. An in-page self-test asserts byte-equality of canonical
encoding against vectors generated from the live repo, on boot. It is a full
wallet: generate/import keys, transfer, bond/unbond, QR + `#pay` deep links,
history, key-file download, and `localStorage` persistence. *(implemented)*

> **Client caveats.** The private key is stored in browser `localStorage` in
> **plaintext** (explicitly disclosed in the UI). Permissive CORS
> (`Access-Control-Allow-Origin: *`) is emitted **only** by the static-asset
> handler; the JSON RPC endpoints set no CORS headers, so a custom cross-origin
> relay must be same-origin or add CORS itself (the wallet warns about this).
> *(partial)*

### 6.5 The schemaless KV storage migration (done)

The schemaless **LMDB** replacement for the SQLite index — so adding account fields
needs no DDL/migration while keeping one atomic write transaction per block — is
**implemented and live** in `ops/kv_ops.py` (6.2); the migration rationale and the
full sub-DB schema are in `doc/storage-kv-migration.md`. It is built on `py-lmdb`
(the same data model as MDBX, with a safe binding); `map_size` is provisioned large
(16 GiB) and a full map surfaces as a clean error, never corruption. Block bodies and
canonical hashing were explicitly **out of scope** for the migration and are
unchanged. *(implemented)*

---

## 7. Security Model

NADO's security rests on the two-lane selection design plus anti-DoS/anti-Sybil
hygiene. This section is explicit about what is **implemented** versus
**planned**, because the distinction is the difference between testnet-safe and
mainnet-safe.

### 7.1 Threats and current posture

- **Sybil (zero-capital identity flooding).** Bounded *structurally* by the lane
  cap: the open lane is exactly `K_OPEN` slots/epoch regardless of identity count,
  so a free botnet can never exceed `OPEN_BPS` (20%) of blocks. **Strong, live.**
- **Grinding (biasing one's own selection).** Removed at the mining layer: one
  hash per slot, no nonce race; selection is seeded by a finalized prior-epoch
  anchor, not the grindable parent hash (audit M6). Signatures are never the
  randomness source, and the fork-choice weight is the *total* bonded registry
  weight (not the winner's share), so it is beacon-independent and cannot be ground.
  The beacon is now **fail-loud** (no silent fallback). **Live**, pending the full
  commit-reveal RANDAO (Section 7.2).
- **Wash-to-mint / reward inflation.** The block reward is **recomputed and
  enforced for equality** in `verify_block` (not merely range-checked), so a
  producer cannot claim an arbitrary reward ≤ cap. **Live.**
- **Reward misattribution.** Fail-closed authorship (Section 7.2). **Live.**
- **DoS.** Per-IP sliding-window rate limits on the unauthenticated
  `/submit_transaction` (**30 requests / 60s**, GET+POST, HTTP 429 over the limit)
  **and** on `/announce_peer` (**10 requests / 60s**, an eclipse-flood throttle); a
  **hard mempool cap** of 150,000 rejects floods (including fee-exempt
  register/heartbeat spam) before OOM; heartbeat-index GC bounds state growth.
  **Live.**
- **SSRF / internal-target seeding.** `check_ip` rejects the node's own IP and all
  non-globally-routable addresses (loopback, RFC1918, link-local, reserved,
  multicast, unspecified). The `NADO_TESTNET` env var bypasses this and the
  public-IP lookup and **must never be set on mainnet**. **Live but not uniformly
  applied** before all outbound probes (see 7.3). *(partial)*
- **51% / rollback / long-range / eclipse.** **Substantially hardened, not fully
  solved.** The fork-choice is now the **objective stake-weighted heaviest chain**
  (peer IPs/trust carry zero weight), and an **enforced finality floor** refuses to
  reorg below `tip − FINALITY_DEPTH`, so a zero-bond Sybil/IP fleet cannot reorg
  honest nodes and a long-range reorg is capped below one epoch. Full objective
  finality (FFG-lite attestations) and broad eclipse hardening are **still pending**
  (7.2–7.3), so this paper does not yet claim complete 51%/eclipse resistance.

### 7.2 Implemented vs. Planned (consensus integrity)

**Implemented (live in production and verification paths):**

- **Two-lane producer selection** (`select_producer_two_lane`) wired into both
  block production (`get_block_candidate` / `rebuild_block`) and verification.
- **Structural Sybil bound** (lane cap) and **one-directional fail-closed
  empty-lane policy**.
- **Deterministic-winner fail-closed authorship.** `validate_block_producer`,
  called inside `verify_block` *before* `incorporate_block`, recomputes the
  two-lane winner from parent state + the epoch beacon and **rejects** any block
  whose `block_creator` is not that winner (and rejects when no eligible producer
  exists). This closes the old fail-OPEN "unknown set → allow" gap.
- **#16 — Objective stake-weighted heaviest-chain fork-choice.** The canonical tip
  is `argmax cumulative_weight` among tips whose chain contains the node's finalized
  block, switching only on **strictly-greater** weight (lowest-hash tie-break)
  (`consensus_loop.refresh_heaviest_tip` / `minority_block_consensus`). **Peer IPs,
  trust, and uptime carry exactly zero weight**, so a Sybil fleet of zero-bond IPs
  cannot reorg honest nodes. This **replaces** the old Sybil-swingable peer-IP
  plurality (`get_majority`); trust is demoted to an advisory transport hint in
  `qualifies_to_sync`.
- **#16/#17 — Grind-proof `cumulative_weight` header.** Committed **inside** the
  block-hash preimage as `parent.cumulative_weight + total_bonded_shares(as-of-
  parent)` — the *total* bonded registry weight, not the slot winner's share, so it
  is **beacon-independent** (a proposer can't grind the beacon to inflate fork
  weight). Recomputed in `rebuild_block` and **verified for equality** as-of-parent
  in `verify_block`, so a relay cannot forge a heavier chain.
- **#17 — Enforced finality floor.** A block at height H finalizes everything
  at/below `H − FINALITY_DEPTH` (`FINALITY_DEPTH = 30`); the persisted, monotonic
  `finalized_height` (KV `meta`) is advanced by `incorporate_block` as
  `max(prev, tip − FINALITY_DEPTH)`, and `rollback_one_block` **raises
  `FinalityViolation`** rather than revert below it. The enforced ordering
  `max_rollbacks (10) < FINALITY_DEPTH (30) < EPOCH_LENGTH (60)` keeps honest reorgs
  clear of the floor while capping a long-range reorg below one epoch.
- **#18 (partial) — Fail-loud epoch beacon.** `epoch_beacon` chains from the hash of
  the first block of the previous epoch (a finalized, non-parent anchor) and now
  **raises instead of silently substituting** `GENESIS_BEACON` when the anchor is
  missing (Section 3.2).
- **#15 (partial) — Detached optional winner block signature.** A winner *may* attach
  an ML-DSA signature over `blake2b([chain_id, height, parent_hash, block_hash])`,
  stored **outside** the hash preimage (`sign_block` / `verify_block_signature`). It
  never enters the block hash, `cumulative_weight`, validity, or reward, so a
  relay-built block for an **offline** winner (no signature) is fully accepted and
  credited — "win while offline" is preserved. A present signature must verify and
  the signer's pubkey must hash to `block_creator`; a present-but-invalid signature
  is rejected.
- **#19 — Pubkey-once.** `create_txid` **excludes** `public_key` from the txid
  preimage; the sender's ML-DSA pubkey is stored once in its account doc on first use
  and recovered thereafter, so later transactions may omit the ~1.3 KB key and still
  reproduce the same txid (revert-symmetric: the stored pubkey is cleared on
  rollback).
- **Reward recompute-and-enforce**, **registration PoW enforcement**, **canonical
  in-block transaction ordering** (txid-sorted before hashing, so two honest nodes
  selecting the same tx set produce an identical block hash), **per-IP rate
  limiting** (`/submit_transaction` + `/announce_peer`), and the **mempool cap**.
- **Trust reweight on disagreement.** A peer that disagrees with the
  (super)majority now *loses* trust (previously both branches gained it),
  removing a free-to-accrue uptime counter for an eclipse/Sybil attacker.

**Planned (designed, NOT yet implemented — do not rely on these):**

- **Equivocation / attestation slashing actions.** The detached winner signature
  gives a *portable* equivocation proof (two valid signatures over conflicting
  blocks at the same height+parent), but the **slashing action** that docks a
  double-signer's bond/fidelity is **not yet wired**.
- **FFG-lite objective finality.** Bonded checkpoint attestations advancing the
  finalized height once attesting bonded shares exceed **>2/3** of total bonded
  shares — beyond today's depth-based floor — is designed, not built.
- **Full commit-reveal RANDAO.** On-chain `commit`/`reveal` transactions with a
  withholder penalty. The RANDAO primitives (`beacon_commitment`, `verify_reveal`,
  `compute_beacon`) are written and unit-tested but **not** wired into the live
  beacon, which is still the single chained anchor (Section 3.3).
- **Broader eclipse hardening.** IP/subnet/**ASN** peer-diversity caps, pinned
  anchor outbound slots, a **multi-seed** bootstrap list, and snapshot-bootstrap
  binding to a finalized signed checkpoint. (The `/announce_peer` rate-limit is the
  one piece already shipped.)

### 7.3 Honest statement of current limits

Objective stake-weighted fork-choice and the enforced finality floor make a
zero-bond Sybil/IP reorg ineffective and bound the disagreement window below one
epoch — a substantial improvement over the previous peer-count fork-choice — and the
beacon is now fail-loud. But without **equivocation slashing actions**, **FFG-lite
objective finality**, a **full commit-reveal RANDAO**, and **broad eclipse hardening**
(and with `check_ip` still not applied before every outbound `/status` probe, P2-1
open), NADO today is **testnet-safe, not open-value-mainnet-safe**. The threat model
assumes `NADO_TESTNET` is unset.

---

## 8. Roadmap

The first wave of consensus hardening has landed: **#16** objective stake-weighted
fork-choice + grind-proof `cumulative_weight`, **#17** the enforced finality floor,
the **#18** fail-loud beacon, the **#15** detached optional winner signature, **#19**
pubkey-once, the `/announce_peer` rate-limit, and the **schemaless LMDB storage
migration** (Section 6). The `max_rollbacks < FINALITY_DEPTH < EPOCH_LENGTH` anchor
invariant is now enforced. The remaining milestone that gates an open-value mainnet:

1. **Equivocation / attestation slashing actions** — turn the portable
   equivocation proof (already available from the #15 detached signature) into a
   bond/fidelity slash.
2. **#18 cont. — Full commit-reveal RANDAO wiring**: on-chain commit/reveal
   transactions with a withholder penalty, over the already-written RANDAO
   primitives, replacing the single chained anchor.
3. **FFG-lite objective finality** — bonded checkpoint attestations advancing the
   finalized height at **>2/3** bonded shares, beyond today's depth-based floor.
4. **Broad eclipse hardening** — IP/subnet/ASN peer-diversity caps, pinned anchor
   outbound slots, a multi-seed bootstrap list, snapshot-bootstrap binding to a
   finalized signed checkpoint; apply `check_ip` to all outbound probes.

Additional hardening and feature items, all currently **planned/partial**:

- **Bonded-lane fidelity ramp** (time-dimension anti-instant-whale) activated
  (an on-chain bonded fidelity column).
- **Unbond timelock** `BOND_UNLOCK_DELAY = 1440` actually enforced (task #11).
- **Absence-decay** for fidelity (currently `FIDELITY_DECAY` is defined but
  unwired).
- **Halving / issuance schedule** (none exists; emission is a perpetual floor +
  capped elastic term).
- **Snapshot-bootstrap hardening** items (allocation bound, quorum floor /
  state-root binding).

---

## 9. Open Problems and Disclaimer

- **Fork-choice is objective, but objective *finality* is not complete.** The
  heaviest-chain rule + the depth-based finality floor stop a zero-bond Sybil reorg,
  but FFG-lite >2/3-bonded-attestation finality and equivocation *slashing actions*
  are not yet wired, so full 51%/eclipse resistance is not yet claimed.
- **Winner signature is detached and optional.** Authorship integrity is by
  deterministic recomputation; the #15 winner signature exists but lives off the
  hash/validity/reward path and its equivocation-slashing action is not yet wired.
- **Beacon is a fail-loud chained anchor, not yet a full RANDAO** (#18): the
  silent fallback is removed, but the on-chain commit-reveal is not wired.
- **Bonded fidelity ramp dormant; unbond timelock unenforced; no absence decay;
  no halving schedule.** Treat these as not-present today.
- **All mining/economic parameters are PROVISIONAL** and flagged
  *simulate-before-lock-in* in code; exact ratios (e.g. `K_OPEN = 12`) hold only
  at default `EPOCH_LENGTH` / `OPEN_BPS`, several of which are config-overridable.
- **Stale companion docs.** `doc/economics.md`, `doc/security-review.md`,
  `doc/mining.md`, and `doc/determinism-and-chain-id.md` lag the code on headline
  facts (e.g. premine amount, treasury address, fail-open authorship,
  Ed25519-vs-ML-DSA naming, in-block ordering). **The code in `protocol.py` and
  the `ops/` modules is authoritative.**

This is a provisional draft for technically literate evaluation, not an offer,
investment solicitation, or security guarantee. The software is testnet-grade and
should not secure value of consequence until the Section 8 milestone is complete.

---

## Appendix: Constants

All values from `protocol.py` (and noted modules) at this revision. **Provisional
— subject to change before mainnet.** Raw units: `1 NADO = 1e10 raw`.

| Constant | Value | Meaning |
|---|---|---|
| `CHAIN_ID` | `"nado-relaunch-1"` | Bound into every signed tx/block (replay protection, M3). |
| `DENOMINATION` | `10_000_000_000` (1e10) | Raw units per 1 NADO; all consensus amounts are integers. |
| `GENESIS_BEACON` | `blake2b_hash(["nado-genesis-beacon", CHAIN_ID])` | Seed for epochs 0–1 and chaining base for epoch ≥ 2. |
| `EPOCH_LENGTH` | `60` | Slots per epoch; beacon/RANDAO epoch; per-slot rotation period. |
| `OPEN_BPS` | `2000` (20.00%) | Open-lane share of slots — the structural Sybil ceiling. |
| `K_OPEN` | `12` (= `EPOCH_LENGTH*OPEN_BPS//BPS_DENOM`) | Open slots/epoch; the other 48 are bonded. |
| `BPS_DENOM` | `10000` | Basis-point denominator. |
| `B_MIN` | `1e12` (100 NADO) | Capital per bonded selection share; 0 shares below this. |
| `BOND_CAP` | `1e14` (10,000 NADO) | Max effective bond per identity (anti-whale). |
| `MAX_SHARES` | `100` (= `BOND_CAP//B_MIN`) | Variance cap; max bonded shares one identity wields. |
| `BOND_UNLOCK_DELAY` | `1440` blocks | Intended unbond lock — **defined, NOT enforced** (planned). |
| `REGISTER_POW_BITS` | `16` | One-time open-lane registration PoW (~1s in-browser); fee substitute, not the Sybil bound. |
| `OPEN_BASE_FLOOR` | `1` | Min open-lane weight for any present identity (never 0). |
| `OPEN_FID_BONUS` | `9` | Max open diligence bonus; open weight ranges 1..10. |
| `PRESENCE_WINDOW` | `3` epochs | Heartbeat recency to stay in the open registry; heartbeat-index GC window. |
| `GC_IDLE_EPOCHS` | `1000` | Prune registry rows idle this long (state-bloat bound). |
| `FIDELITY_CAP` | `1000` epochs | Continuous presence to fully ramp the open bonus. |
| `FIDELITY_GAIN` | `1` | Fidelity increment per epoch present. |
| `FIDELITY_DECAY` | `1` | Intended absence decay — **defined, unwired** (planned). |
| `TREASURY_GENESIS` | `0` | **No premine** — treasury starts empty. |
| `TREASURY_BPS` | `1000` (10.00%) | Treasury share of each reward; producer gets 90%. |
| `BASE_SUBSIDY` | `1e9` (0.1 NADO) | Flat per-block emission floor (~144 NADO/day at 60s blocks). |
| `REWARD_WINDOW` | `100` | Trailing blocks averaged for the elastic fee reward. |
| `REWARD_CAP` | `5e9` (0.5 NADO) | Max reward per block. |
| `MIN_TX_FEE` | `1000` raw | Deterministic minimum fee floor (ordinary/bond/unbond txs). |
| `TREASURY_ADDRESS` / `GENESIS_ADDRESS` | `_GENESIS_BODY + blake2b_hash(body, 2)` | Founder key-controlled treasury == genesis address. |
| ML-DSA-44 pubkey | `1312` bytes (from 32-byte seed) | Post-quantum public key (FIPS 204). |
| ML-DSA-44 signature | `~2420` bytes | Post-quantum signature length. |
| Address format | `"ndo"` + 42-hex pubkey prefix + 4-hex checksum (49 chars) | Checksum = `blake2b_hash(body, size=2)`. |
| `RESERVED_RECIPIENTS` | `{bond, unbond, register, heartbeat}` | Keyless pseudo-recipients; valid as recipient/target only. |
| Rate limit | `30 req / 60s` per IP | On `/submit_transaction` (GET+POST); HTTP 429 over the limit. |
| `transaction_pool_limit` | `150000` | Hard mempool cap (anti-OOM). |
| `FINALITY_DEPTH` | `30` | Enforced finality floor: rollback refuses to revert below `tip − 30` (`FinalityViolation`). |
| `max_rollbacks` | `10` (default; asserted `< FINALITY_DEPTH < EPOCH_LENGTH`) | Bounded reorg burst rate-limit; the finalized floor is the hard cap. |
| Announce rate limit | `10 req / 60s` per IP | On `/announce_peer` (eclipse-flood throttle); HTTP 429 over the limit. |

*Config-overridable values (e.g. `EPOCH_LENGTH`, block time, peer/rollback limits)
mean derived ratios such as `K_OPEN = 12` hold only at the defaults above.*
