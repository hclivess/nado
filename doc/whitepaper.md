# NADO: A Phone-Mineable, Fair-Launch, Post-Quantum Lightweight Blockchain

**2026, provisional draft.**

> **PROVISIONAL NOTICE.** This document is a provisional whitepaper for the NADO
> relaunch. It describes a design that is partly implemented and partly planned.
> Sections explicitly distinguish what is **live in code today** from what is
> **designed but not yet wired**. All numeric parameters are taken from
> `protocol.py`, the consensus source of truth, but are themselves marked
> *PROVISIONAL — simulate before lock-in* in code and may change before mainnet.
> NADO in its current form is a **testnet-stage alpha, not open-value-mainnet-safe**.
> Both waves of the consensus hardening plan **are now implemented**: the first wave
> (objective stake-weighted heaviest-chain fork-choice, an enforced finality floor,
> a grind-proof `cumulative_weight` header, a fail-loud epoch beacon, a detached
> optional winner block signature, and pubkey-once) **plus** the second wave —
> **equivocation slashing**, **FFG-lite stake-attested finality**, and a
> **commit-reveal RANDAO** mixed into the live beacon. A subsequent **adversarial
> security audit** (Section 7.4, `doc/security-audit.md`) found and **fixed every
> exploitable issue** it surfaced and confirmed the safety core sound, and the
> **unbond timelock is now enforced** (Section 4.4). Two honest caveats remain:
> (1) the **multi-node, epoch-crossing** behaviour of FFG and RANDAO is only
> *lightly exercised* empirically (unit-tested for correctness; the ~10 s/block
> cadence makes crossing 120+ blocks slow), and (2) a subset of **eclipse hardening**
> (ASN-level peer diversity, pinned multi-seed bootstrap, snapshot-bootstrap binding
> to a finalized signed checkpoint) is **still genuinely planned/post-launch**.
> Do not deploy this software to secure value of consequence yet. There is **no
> hardfork concern** — mainnet is not live. Where the older design docs
> (`doc/economics.md`, `doc/security-review.md`, `doc/mining.md`,
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
store. Both waves of consensus hardening are now **live in code**: objective
stake-weighted fork-choice, an enforced finality floor, a grind-proof chain-weight
header, a fail-loud beacon, a detached optional winner signature, and pubkey-once,
**plus** equivocation slashing, an additive FFG-lite stake-attested finality signal,
and a commit-reveal RANDAO mixed into the beacon. This paper documents the live
mechanism and is explicit about the two honest caveats that remain — the lightly-
exercised cross-epoch behaviour of FFG/RANDAO, and the post-launch eclipse-hardening
subset that is still unbuilt.

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

### 3.2 The live epoch beacon (finalized anchor + commit-reveal RANDAO)

The live beacon is **grind-resistant**, and now mixes a commit-reveal RANDAO into
the finalized anchor:

- Epochs 0–1 use a fixed `GENESIS_BEACON = blake2b_hash(["nado-genesis-beacon",
  CHAIN_ID])`.
- Epoch ≥ 2 mixes `GENESIS_BEACON` with the hash of the **first block of the
  previous epoch** (a deeply finalized, non-parent anchor at least one epoch back)
  **and the bonded validators' revealed RANDAO secrets for this epoch**:
  `epoch_beacon(E) = compute_beacon(GENESIS_BEACON, [anchor] + reveals)`. With **zero
  reveals** it falls back to the anchor-only value (liveness). Per-slot rotation comes
  from hashing `[beacon, slot]`.

Anchoring to a finalized prior-epoch block (rather than the parent block hash)
closes the grindable-seed weakness (audit item M6): a producer cannot grind the
parent hash to bias its own selection. Mixing in the reveals means **no single
anchor-producer controls the beacon** either (Section 3.3). The mix keeps the anchor
and is **non-recursive** (it does not chain `epoch_beacon(E−1)`), which keeps the
beacon snapshot-safe and the reveals immutable by the time block `E*EPOCH_LENGTH`
first needs it. *(implemented — `epoch_beacon`, `compute_beacon`)*

> **Now fail-loud.** `epoch_beacon` previously *silently* fell back to
> `GENESIS_BEACON` when the anchor block was missing locally — a consensus-split /
> eclipse hazard, since an under-synced node would draw a different producer set for
> the whole epoch. It now **raises instead of substituting** (a missing finalized
> anchor means this node is under-synced and must resync). The anchor is also kept
> un-reorgable by the **enforced** ordering `max_rollbacks (10) < FINALITY_DEPTH (30)
> < EPOCH_LENGTH (60)` (Section 7), so it is finalized before any epoch it governs
> goes live. *(implemented)*

### 3.3 Commit-reveal RANDAO (now wired into the live beacon)

The on-chain **commit-reveal RANDAO** is now wired (`#7`). Bonded validators publish
a `commit` (a secret's hash) in epoch **E−2** and a `reveal` (the secret) inside
epoch **E−1's finalized window** (the reveal's `target_block` is bounded to
`≤ E*EPOCH_LENGTH − FINALITY_DEPTH − 1`, so the seed is immutable before epoch E
begins). Both are fee-exempt, zero-amount transactions from bonded senders only;
`reveal` must open the sender's own prior `commit` (`beacon_commitment(secret) ==
commitment`), and `commit`/`reveal` are `UNIQUE(sender, target_epoch)`. The recorded
reveals are mixed into `epoch_beacon(E)` (Section 3.2), reveal-order-independent
because `compute_beacon` sorts its inputs. With zero reveals the beacon still advances
on the anchor alone (**liveness preserved**). Committing *before* the seeded beacon is
revealed kills just-in-time grinding, and because the fork-choice weight is already
**beacon-independent** (Section 7.2), a withholder cannot gain fork leverage by
declining to reveal. *(implemented — `commit`/`reveal` txns, `reflect_transaction`,
`compute_beacon`)*

> **Honest caveat.** The RANDAO primitives and the commit/reveal validation, recording,
> and revert paths are unit-tested for correctness, but the **multi-node, epoch-crossing**
> dynamics (a commit in E−2, a reveal in E−1, the secret influencing E's draw) are only
> **lightly exercised** empirically: the core loop's ~10 s/block cadence makes driving a
> full cross-epoch commit→reveal→beacon cycle slow. It engages as the chain crosses
> epochs. There is **no explicit withholder fidelity penalty** today (the design's
> deterministic withhold-dock is not wired); the deterrent is simply that a withholder
> forfeits influence over a beacon it can no longer grind. *(partial)*

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
  spendable balance and adds `amount` to the non-spendable `bonded` column.
  Releasing it is a **two-step, timelocked** flow (see "Unbond timelock"
  below), not an instant reversal. A guarded UPDATE keeps `bonded` non-negative
  (fails closed). *(implemented)*
- **Whale dampening (capital).** Selection weight is split-neutral and
  per-identity capped (Section 2.5): `min(bonded, BOND_CAP) // B_MIN`, capped at
  `MAX_SHARES = 100`. *(implemented)*
- **Whale dampening (time).** A fidelity ramp to scale a newcomer's bonded weight
  to full over `FIDELITY_CAP` epochs is designed but **dormant** on the bonded
  lane in v1 (live only on the open lane). *(partial)*
- **Unbond timelock (now enforced).** `BOND_UNLOCK_DELAY = 1440` blocks is now
  **enforced** via a two-step flow. `unbond` is a **release request**, not an
  instant refund: it records a maturity `release_block = current +
  BOND_UNLOCK_DELAY` and the requested amount, but the coins **stay in the
  `bonded` column and remain slashable**. A separate fee-exempt **`withdraw`**
  transaction then moves the matured amount to spendable balance, and is only
  valid once `target_block >= release_block` and its `data` (`amount`,
  `release_block`) matches the pending request. Keeping the stake bonded through
  the delay is precisely what keeps a **caught equivocator's stake slashable**
  while an unbond is in flight; at most one unbond may be pending per account.
  *(implemented — `unbond`/`withdraw` in `validate_transaction` / `reflect_transaction`)*
- **Fees** are **destroyed**, not paid to producers: they accumulate into each
  block's `cumulative_fees` header (which drives the elastic reward) rather than
  crediting any address. A deterministic integer floor `MIN_TX_FEE = 1000` raw
  applies to ordinary transfers and `bond`. (`register`, `heartbeat`, `unbond`,
  and `withdraw` are **fee-exempt** — they move no coins out; `unbond`/`withdraw`
  only retime the sender's own stake.) The legacy `burn` mechanic is entirely
  removed. *(implemented)*
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
  reserved recipients `{bond, unbond, withdraw, register, heartbeat, slash, attest,
  commit, reveal}` bypass the checksum rule and are valid only as a recipient/target,
  never as a sender. *(implemented)*
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
history, key-file download, and `localStorage` persistence. It also surfaces the
**live OPEN and BONDED lane participant counts** (`/mining_status`
`open_registry_size` / `bonded_registry_size`) alongside the miner's own bonded
shares, so a phone can see how contested each lane is. *(implemented)*

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
mainnet-safe. A deep **adversarial security audit** (Section 7.4,
[`doc/security-audit.md`](security-audit.md)) was run across six surfaces; **every
exploitable finding it surfaced is fixed and unit-tested**, and it confirmed the
safety core sound. The fixes are reflected throughout this section.

### 7.1 Threats and current posture

- **Sybil (zero-capital identity flooding).** Bounded *structurally* by the lane
  cap: the open lane is exactly `K_OPEN` slots/epoch regardless of identity count,
  so a free botnet can never exceed `OPEN_BPS` (20%) of blocks. **Strong, live.**
- **Grinding (biasing one's own selection).** Removed at the mining layer: one
  hash per slot, no nonce race; selection is seeded by a finalized prior-epoch
  anchor, not the grindable parent hash (audit M6), now **mixed with a commit-reveal
  RANDAO** so no single anchor-producer controls the beacon (Section 3.3). Signatures
  are never the randomness source, and the fork-choice weight is the *total* bonded
  registry weight (not the winner's share), so it is beacon-independent and cannot be
  ground. The beacon is also **fail-loud** (no silent fallback). **Live** (RANDAO
  cross-epoch dynamics only lightly exercised — Section 3.3).
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
  solved.** The fork-choice is the **objective stake-weighted heaviest chain** (peer
  IPs/trust carry zero weight), an **enforced finality floor** refuses to reorg below
  `tip − FINALITY_DEPTH`, and an **additive FFG-lite** stake-attested finality signal
  now records the stronger >2/3-bonded finality point on top (Section 7.2). So a
  zero-bond Sybil/IP fleet cannot reorg honest nodes and a long-range reorg is capped
  below one epoch. What remains is a **subset of eclipse hardening** (ASN-level
  diversity, pinned multi-seed bootstrap, snapshot-bootstrap binding — 7.2–7.3), and
  the cross-epoch behaviour of FFG is only lightly exercised, so this paper does not
  yet claim complete 51%/eclipse resistance.

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
- **#18 — Fail-loud epoch beacon + commit-reveal RANDAO.** `epoch_beacon` mixes the
  hash of the first block of the previous epoch (a finalized, non-parent anchor) with
  the bonded validators' **revealed RANDAO secrets** for the epoch, and **raises
  instead of silently substituting** `GENESIS_BEACON` when the anchor is missing
  (Sections 3.2–3.3). Zero reveals → anchor-only fallback (liveness).
- **#7 — Commit-reveal RANDAO.** Fee-exempt bonded-only `commit` (epoch E−2) and
  `reveal` (E−1's finalized window) transactions, `UNIQUE(sender, target_epoch)`,
  routed through `reflect_transaction` to revert-symmetric `commits`/`reveals`
  sub-DBs; `reveal` must open the sender's prior `commit`. The recorded reveals seed
  `epoch_beacon(E)` (order-independent — `compute_beacon` sorts), so **no single
  anchor-producer controls the beacon**. *(Cross-epoch dynamics lightly exercised; no
  explicit withholder fidelity dock — Section 3.3.)*
- **#15 — Detached optional winner block signature + equivocation slashing.** A winner
  *may* attach an ML-DSA signature over `blake2b([chain_id, height, parent_hash,
  block_hash])`, stored **outside** the hash preimage (`sign_block` /
  `verify_block_signature`). It never enters the block hash, `cumulative_weight`,
  validity, or reward, so a relay-built block for an **offline** winner (no signature)
  is fully accepted and credited — "win while offline" is preserved. A present
  signature must verify and the signer's pubkey must hash to `block_creator`; a
  present-but-invalid signature is rejected. **Two valid signatures over conflicting
  blocks at the same height+parent are a portable equivocation proof**: a fee-exempt
  `slash` transaction carrying it burns `SLASH_BOND_PENALTY` (= `B_MIN`, one bonded
  share) of the offender's **bonded** stake. Anyone may report (the unforgeable proof
  is the anti-spam); replay-guarded to **one slash per (offender, height)**, revert-
  symmetric, and the coins are **destroyed** (deterrent is the loss, not a bounty).
  `verify_equivocation_proof` / `apply_slash`.
- **#6 — FFG-lite stake-attested finality (additive).** Bonded validators emit one
  `attest` transaction per epoch for that epoch's checkpoint (its first block). A
  checkpoint **justifies** at *strictly* >2/3 of total bonded shares
  (`attesting*FFG_DEN > total*FFG_NUM`, integer, no floats) and **finalizes** on
  two-consecutive-justified; on-chain `UNIQUE(validator, epoch)` (attestation index +
  meta marker) prevents on-chain double-voting. It is exposed at **`/status.ffg_finalized`**.
  **Honest framing:** this is an **additive, observable, accountable** finality SIGNAL
  layered *on top of* the depth-based floor — it does **not** replace or advance the
  #17 `finalized_height` (which stays the time-based rollback bound and the liveness
  guarantee, `max(prev, tip − FINALITY_DEPTH)`). FFG can therefore **never stall the
  chain**; it only records the stronger, stake-attested finality point alongside the
  always-advancing floor. *(Cross-epoch justify→finalize lightly exercised — 7.3.)*
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

**Lightly exercised (implemented + unit-tested, cross-epoch dynamics not yet hardened):**

- **FFG-lite finality (#6)** and the **commit-reveal RANDAO (#7)** above are wired and
  unit-tested for correctness, but their **multi-node, epoch-crossing** behaviour is
  only **lightly exercised** empirically — the core loop's ~10 s/block cadence makes
  crossing the 120+ blocks needed for a full justify→finalize and a complete
  commit→reveal cycle slow. They engage as the chain crosses epochs; treat their
  cross-epoch dynamics as not-yet-battle-tested. There is also **no explicit RANDAO
  withholder fidelity dock** (Section 3.3).

**Planned (designed, NOT yet implemented — do not rely on these):**

- **Broader eclipse hardening.** Beyond the per-/16 subnet cap and the `/announce_peer`
  rate-limit (both already live): **ASN-level** (vs /16) peer-diversity caps, pinned
  anchor outbound slots, a **multi-seed** bootstrap list (replacing the single genesis
  seed), and **snapshot-bootstrap binding to a finalized signed checkpoint**. These are
  post-launch items.

### 7.3 Honest statement of current limits

Objective stake-weighted fork-choice and the enforced finality floor make a
zero-bond Sybil/IP reorg ineffective and bound the disagreement window below one
epoch; **equivocation slashing**, an **additive FFG-lite** stake-attested finality
signal, and a **commit-reveal RANDAO** now layer accountable finality and a non-
grindable beacon on top, and the beacon is fail-loud. But the **cross-epoch behaviour
of FFG/RANDAO is only lightly exercised** (Sections 3.3, 7.2), a subset of **eclipse
hardening** (ASN-level diversity, pinned multi-seed bootstrap, snapshot-bootstrap
binding) is still outstanding, and `check_ip` is still not applied before every
outbound `/status` probe (P2-1 open). NADO today is therefore a **testnet-stage
alpha, not open-value-mainnet-safe** (with no hardfork concern — mainnet is not live).
The threat model assumes `NADO_TESTNET` is unset.

### 7.4 Adversarial security audit (all exploitable findings fixed)

A deep adversarial audit was run across **six attack surfaces** —
fork-choice/51%/rollback/finality; Sybil/two-lane/selection;
slashing/equivocation/unbond; RANDAO/FFG/beacon; tx-validation/pubkey-once; and
KV atomicity/eclipse/DoS — against a chain that was **testnet-stage alpha with no
value at stake**. Each finding was verified against the code; **every exploitable
finding is now fixed and unit-tested** (`tests/test_inblock_uniqueness_audit.py`
plus the existing consensus suite). The full writeup, including severities and the
residuals, is [`doc/security-audit.md`](security-audit.md).

**Fixed (exploitable):**

- **In-block duplicate reserved transactions (CRITICAL/HIGH).** Uniqueness was
  validated only against **parent** state, and block assembly did **no dedup**, so
  duplicates of one reserved tx inside a **single** block could: drain `K×B_MIN`
  from one unbond via repeated `withdraw`s (**slash-escape + chain-halt**);
  over-burn / halt on a duplicate `slash` (which two honest reporters trigger
  organically); or collapse duplicate `heartbeat`/`reveal` rows in `DUPSORT` so a
  later reorg over-deletes the shared row → **registry/beacon desync fork** (and
  fidelity farming). One root fix closes all of them: a `reserved_uniqueness_key`
  with `dedupe_reserved` (block assembly drops in-block dups) and
  `assert_unique_reserved` (`verify_block` rejects them), plus cross-block
  `heartbeat_present` and reveal-secret uniqueness guards in validation.
- **Same-length fork-choice wedge (CRITICAL, liveness).** Because
  `cumulative_weight` is content-independent, two honest tips at one height tie,
  and the old switch fired only on strictly-**greater** weight — so equal-weight
  forks wedged forever (the empirical testnet churn). Fixed: a node now switches
  whenever the global-best tip by `(cumulative_weight DESC, block_hash ASC)` isn't
  its own — the deterministic **lowest-hash tie-break** every node computes
  identically, so they converge.
- **`quick_sync` skipped signature + spending validation (HIGH, opt-in).** A
  malicious sync peer could inject forged unsigned transfers in old blocks.
  `verify_block` now **always** runs `validate_transactions_in_block`; the bypass
  is removed.
- **Unauthenticated advertised `latest_block_weight` DoS (HIGH).** A single Sybil
  peer advertising a huge weight forced honest nodes into emergency-mode +
  wasteful rollbacks. Fixed by a bounded, auto-clearing **`rejected_tips`**
  exclusion: a tip we tried-and-failed to obtain a valid heavier chain for is
  excluded from the heaviest computation for a window, so a bogus weight can't
  loop a node.
- **Lower-severity fixes:** per-IP **rate limits** added to the heavy
  unauthenticated read endpoints (`/mining_status`,
  `/get_transactions_of_account`, `/get_blocks_after`/`/get_blocks_before`); an
  **honest re-signer guard** (a node only ever signs a *strictly higher* height
  via `last_signed_height`, so it cannot self-equivocate after a reorg and be
  slashed); the **per-/16 subnet cap now also gates the disk-reload path**
  (`subnet_diversity_ok` in `load_ips`); a malformed-tx guard in
  `merge_transaction`; and a dead `/get_blocks_before` (a literal
  `parent_hash=["parent_hash"]`) was fixed.

**Confirmed sound (audited, no change needed):** the **atomic incorporate/rollback**
window; the **monotonic finalized-height floor** (and the enforced
`max_rollbacks(10) < FINALITY_DEPTH(30) < EPOCH_LENGTH(60)` ordering); the tight
RANDAO reveal-immutability bound; **equivocation-proof unforgeability** with the
no-innocent-victim address binding; the **detached-signature-outside-the-hash**
property; and **pubkey-once** key→sender binding with full-body/replay binding.

**Documented residuals (NOT theft or fork vectors), scheduled before mainnet:** no
RANDAO withholder/reveal-censorship penalty (Section 3.3); FFG's "slashable-stake
backing" is **aspirational** — there is no **attestation-equivocation slashing**
yet (only block-authorship equivocation), so cross-fork double-voting beyond the
per-epoch `UNIQUE(validator, epoch)` marker is unpunished and FFG stays an
observational signal; the bonded `MAX_SHARES` cap is **per-identity, not aggregate**
(the bonded lane is capital-proportional by design, the cap only bounds
single-address variance); `register`/fee-exempt **state growth** (`GC_IDLE_EPOCHS`
defined but unwired — idle-account GC is future work); `FIDELITY_DECAY` unwired; and
snapshot bootstrap trusts an 80%-of-peers quorum with **no hardcoded finalized
checkpoint** (weak-subjectivity).

---

## 8. Roadmap

Both waves of consensus hardening have landed: **#16** objective stake-weighted
fork-choice + grind-proof `cumulative_weight`, **#17** the enforced finality floor,
the **#18** fail-loud beacon **now mixing a commit-reveal RANDAO**, the **#15** detached
optional winner signature **plus equivocation slashing**, **#6** additive FFG-lite
stake-attested finality (`/status.ffg_finalized`), **#7** the commit-reveal RANDAO,
**#19** pubkey-once, the `/announce_peer` rate-limit + per-/16 subnet cap, and the
**schemaless LMDB storage migration** (Section 6). The `max_rollbacks < FINALITY_DEPTH
< EPOCH_LENGTH` anchor invariant is enforced. Since then, an **adversarial security
audit** (Section 7.4) landed fixes for every exploitable finding (in-block reserved-tx
uniqueness, the lowest-hash fork-choice tie-break, always-validate sync, and the
bounded `rejected_tips` DoS guard), and the **unbond timelock** is now enforced via the
two-step `unbond`-request + fee-exempt `withdraw` flow (Section 4.4). What gates an
open-value mainnet now:

1. **Harden FFG/RANDAO across epochs** — the slashing/FFG/RANDAO mechanisms are wired
   and unit-tested, but their multi-node, epoch-crossing behaviour needs sustained
   live exercise (the ~10 s/block cadence makes crossing 120+ blocks slow).
2. **Broad eclipse hardening** — ASN-level peer-diversity caps (the per-/16 cap is
   live), pinned anchor outbound slots, a multi-seed bootstrap list, snapshot-bootstrap
   binding to a finalized signed checkpoint; apply `check_ip` to all outbound probes.
3. **RANDAO withholder penalty** — an explicit deterministic dock for a bonded
   validator that commits but withholds its reveal (today the only deterrent is the
   forfeited, un-grindable influence).

Additional hardening and feature items, all currently **planned/partial**:

- **Bonded-lane fidelity ramp** (time-dimension anti-instant-whale) activated
  (an on-chain bonded fidelity column).
- **Attestation-equivocation slashing** for FFG (today only block-authorship
  equivocation is slashable; FFG cross-fork double-voting beyond the per-epoch
  `UNIQUE(validator, epoch)` marker is unpunished, so FFG remains an observational
  signal — Section 7.4).
- **Idle-account GC** wiring `GC_IDLE_EPOCHS` to bound `register`/fee-exempt state
  growth (defined but unwired today — Section 7.4).
- **Absence-decay** for fidelity (currently `FIDELITY_DECAY` is defined but
  unwired).
- **Halving / issuance schedule** (none exists; emission is a perpetual floor +
  capped elastic term).
- **Snapshot-bootstrap hardening** items (allocation bound, quorum floor /
  state-root binding).

---

## 9. Open Problems and Disclaimer

- **Fork-choice is objective and FFG-lite finality is additive — but its cross-epoch
  behaviour is lightly exercised.** The heaviest-chain rule + the depth-based finality
  floor stop a zero-bond Sybil reorg, and FFG-lite >2/3-bonded-attestation finality now
  records a stronger, accountable finality point **on top of** (never replacing) the
  time-based floor. But its multi-node, epoch-crossing dynamics are not yet hardened on
  a live net, and broad eclipse hardening is incomplete, so full 51%/eclipse resistance
  is not yet claimed.
- **Winner signature is detached and optional; equivocation slashing is wired.**
  Authorship integrity is by deterministic recomputation; the #15 winner signature
  lives off the hash/validity/reward path, and two conflicting valid signatures now
  feed a `slash` transaction that burns one bonded share — revert-symmetric, replay-
  guarded, burned (no bounty).
- **Beacon is a fail-loud finalized anchor mixed with a commit-reveal RANDAO** (#7/#18):
  the silent fallback is removed and reveals are mixed in, but there is **no explicit
  withholder fidelity dock**, and the cross-epoch commit→reveal→beacon cycle is only
  lightly exercised.
- **Unbond is now timelocked.** `unbond` is a release *request* that keeps the
  stake bonded and slashable for `BOND_UNLOCK_DELAY = 1440` blocks; a fee-exempt
  `withdraw` claims it only at/after maturity (Section 4.4).
- **Bonded fidelity ramp dormant; no FFG attestation slashing; no absence decay;
  no idle-account GC; no halving schedule.** Treat these as not-present today
  (Section 7.4).
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
| `BOND_UNLOCK_DELAY` | `1440` blocks | Unbond timelock — **enforced**: `unbond` is a release request (stake stays bonded + slashable); fee-exempt `withdraw` claims it at/after `release_block = current + 1440`. |
| `REGISTER_POW_BITS` | `16` | One-time open-lane registration PoW (~1s in-browser); fee substitute, not the Sybil bound. |
| `OPEN_BASE_FLOOR` | `1` | Min open-lane weight for any present identity (never 0). |
| `OPEN_FID_BONUS` | `9` | Max open diligence bonus; open weight ranges 1..10. |
| `PRESENCE_WINDOW` | `3` epochs | Heartbeat recency to stay in the open registry; heartbeat-index GC window. |
| `GC_IDLE_EPOCHS` | `1000` | Intended idle-registry prune window (state-bloat bound) — **defined, not yet wired** (Section 7.4). |
| `FIDELITY_CAP` | `1000` epochs | Continuous presence to fully ramp the open bonus. |
| `FIDELITY_GAIN` | `1` | Fidelity increment per epoch present. |
| `FIDELITY_DECAY` | `1` | Intended absence decay — **defined, unwired** (planned). |
| `TREASURY_GENESIS` | `0` | **No premine** — treasury starts empty. |
| `TREASURY_BPS` | `1000` (10.00%) | Treasury share of each reward; producer gets 90%. |
| `BASE_SUBSIDY` | `1e9` (0.1 NADO) | Flat per-block emission floor (~144 NADO/day at 60s blocks). |
| `REWARD_WINDOW` | `100` | Trailing blocks averaged for the elastic fee reward. |
| `REWARD_CAP` | `5e9` (0.5 NADO) | Max reward per block. |
| `MIN_TX_FEE` | `1000` raw | Deterministic minimum fee floor (ordinary transfers and `bond`; `register`/`heartbeat`/`unbond`/`withdraw` are fee-exempt). |
| `TREASURY_ADDRESS` / `GENESIS_ADDRESS` | `_GENESIS_BODY + blake2b_hash(body, 2)` | Founder key-controlled treasury == genesis address. |
| ML-DSA-44 pubkey | `1312` bytes (from 32-byte seed) | Post-quantum public key (FIPS 204). |
| ML-DSA-44 signature | `~2420` bytes | Post-quantum signature length. |
| Address format | `"ndo"` + 42-hex pubkey prefix + 4-hex checksum (49 chars) | Checksum = `blake2b_hash(body, size=2)`. |
| `RESERVED_RECIPIENTS` | `{bond, unbond, withdraw, register, heartbeat, slash, attest, commit, reveal}` | Keyless pseudo-recipients; valid as recipient/target only. |
| `SLASH_BOND_PENALTY` | `B_MIN` (one share, 100 NADO) | Bonded stake burned per proven equivocation (#15 step 5C); revert-symmetric, one-per-(offender, height). |
| `FFG_NUM` / `FFG_DEN` | `2` / `3` | FFG-lite justify threshold: a checkpoint justifies at *strictly* >2/3 of total bonded shares (#6). Additive signal, exposed at `/status.ffg_finalized`. |
| Rate limit | `30 req / 60s` per IP | On `/submit_transaction` (GET+POST); HTTP 429 over the limit. |
| `transaction_pool_limit` | `150000` | Hard mempool cap (anti-OOM). |
| `FINALITY_DEPTH` | `30` | Enforced finality floor: rollback refuses to revert below `tip − 30` (`FinalityViolation`). |
| `max_rollbacks` | `10` (default; asserted `< FINALITY_DEPTH < EPOCH_LENGTH`) | Bounded reorg burst rate-limit; the finalized floor is the hard cap. |
| Announce rate limit | `10 req / 60s` per IP | On `/announce_peer` (eclipse-flood throttle); HTTP 429 over the limit. |

*Config-overridable values (e.g. `EPOCH_LENGTH`, block time, peer/rollback limits)
mean derived ratios such as `K_OPEN = 12` hold only at the defaults above.*
