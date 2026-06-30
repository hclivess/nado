# NADO Relaunch 1 — `nado-relaunch-1`

> ⚠️ **BREAKING — NOT COMPATIBLE WITH ANY PRIOR RELEASE (0.25–0.27).**
> This is a from-scratch consensus relaunch: new genesis, new signature scheme, new mining, new
> chain id (`nado-relaunch-1`). Old nodes, wallets, addresses, keys, and chain data **do not work**
> and cannot interoperate. There is no migration — it is a fresh chain. All prior releases are
> removed for this reason.

## Why a relaunch

The chain was redesigned around four goals: **mine on a phone with zero coins**, **fair launch (no
premine)**, **post-quantum security**, and **stay light enough to run on almost anything**.

## What's new

### Fair two-lane mining — mine with no coins, bonding only boosts
- Every epoch's blocks split into an **OPEN lane (20%)** anyone can win with **zero coins** and a
  **BONDED lane (80%)** won by locked, refundable stake. The split is a beacon-keyed permutation of
  slot *indices*, so it is **population-independent**: a zero-capital Sybil/botnet is structurally
  bounded to 20% of blocks no matter how many identities it spins up.
- **No premine.** Genesis mints zero coins. A flat **base block subsidy** lets a brand-new,
  zero-coin miner earn real spendable coins from block 1 (register → heartbeat → win → earn).
- **Whale-aware:** the bonded lane is per-identity capped; the open lane is capital-immune, so no
  amount of stake can take newcomers' guaranteed 20%.
- Producer selection is a deterministic hash draw over the epoch beacon (no Proof-of-Work, no
  mining rigs).

### Post-quantum signatures (ML-DSA-44, FIPS 204)
- Ed25519 is replaced by **ML-DSA-44** (NIST FIPS 204) via pure-Python `dilithium-py` — no native
  build, in keeping with the lightweight goal.
- The node's signing is **cross-validated both ways** against the browser's `@noble/post-quantum`,
  so a browser/phone miner and a full node verify each other's signatures.

### Wallets
- **Desktop wallet** (`pyside_wallet.py`, PySide6): overview, send, bond/unbond, register & mine,
  expected-time-to-mine, and a live selection-lane visualization.
- **Browser/mobile light-miner** (`static/miner.html`): phones mine through a web page — generate a
  key, register, heartbeat each epoch, and **win offline** (a relay builds the block for you). No
  full node, no heavy crypto on the device.

### Schemaless key-value storage (LMDB)
- The chain index moved from SQLite to a **schemaless key-value store (LMDB, the MDBX data model)** —
  account records are columnless msgpack documents, so adding a field needs no migration. The whole
  block mutation (balances, tx index, block index, totals, heartbeats) commits in **one atomic
  write transaction** (crash-atomic incorporate/rollback, byte-identical revert-symmetry). Stays
  embedded, memory-mapped, and lean ("runs on a 386").

### Lighter & leaner
- Transactions move over **HTTP POST + msgpack** (the old GET-query path couldn't fit a
  post-quantum tx); block storage is **zstd-compressed**; consensus hashing stays canonical JSON so
  a browser reproduces it byte-for-byte.

### Security hardening — full consensus-hardening plan now LIVE
The fork-choice was rebuilt to be **objective and Sybil-resistant**, and the accountability layer
(slashing, stake-attested finality, a non-grindable beacon) is now wired on top:
- **Stake-weighted heaviest-chain fork-choice.** Every block commits a grind-proof, beacon-independent
  `cumulative_weight` (running total of bonded stake) *inside its hash*, re-derived and enforced by
  every verifier. The canonical chain is the **heaviest verified weight** — and **peer IPs contribute
  zero weight**, so a Sybil peer-set can no longer swing which chain is canonical (replaces the old
  peer-count plurality).
- **Enforced finality.** A persisted, monotonic finalized-height floor; rollback **refuses** to cross
  it (no unbounded long-range / deep-reorg), and a forced-sync rollback-counter leak was closed.
- **Fail-loud epoch beacon.** A node missing the finalized beacon anchor now halts/resyncs instead of
  silently substituting a divergent producer set.
- **Detached winner block signature + equivocation slashing.** The selected winner may attach an
  *optional* ML-DSA signature **outside** the block hash (so "win-while-offline" is preserved — an
  offline winner's relay-built block is unsigned and still valid). Two valid signatures over *conflicting*
  blocks at the same height+parent are a portable proof: a fee-exempt `slash` tx burns
  `SLASH_BOND_PENALTY` (= `B_MIN`, one bonded share) of the offender's **bonded** stake — replay-guarded
  one-per-(offender, height), revert-symmetric, burned (no bounty).
- **FFG-lite stake-attested finality.** Bonded validators emit one `attest` tx per epoch; a checkpoint
  **justifies** at *strictly* >2/3 of total bonded shares and **finalizes** on two-consecutive-justified,
  exposed at `/status.ffg_finalized`. It is an **additive, observable** finality signal layered *on top
  of* the time-based floor — it does **not** replace the depth-based `finalized_height` (which stays the
  rollback bound and guarantees liveness), so FFG can never stall the chain.
- **Commit-reveal RANDAO.** Bonded validators `commit` a secret in epoch E−2 and `reveal` it in E−1's
  finalized window; `epoch_beacon` mixes the finalized anchor with the revealed secrets, so **no single
  anchor-producer controls the beacon** (zero reveals → anchor-only fallback, keeping liveness). Keeps
  the anchor (non-recursive) → snapshot-safe.
- **Pubkey-once.** The ~1.3 KB ML-DSA public key is excluded from the txid and stored once on first use,
  so later txs (e.g. every-epoch heartbeats) omit it; revert-symmetric.
- **Anti-DoS / eclipse throttles:** per-IP rate limiting on transaction submission *and* peer
  announcements; a per-/16 subnet-diversity cap; mempool cap; heartbeat GC.

## Validated
- 3-node testnet **converges and produces** with the full stack live (two-lane mining, ML-DSA keys,
  LMDB storage, zstd block bodies, POST wire, enforced finality, heaviest-weight fork-choice).
- Unit-tested: atomic incorporate→rollback byte-identical; finality floor refuses sub-floor rollback;
  cumulative_weight committed + verified; beacon fail-loud; equivocation proof verify + bond slash
  (apply/revert); FFG justify/finalize thresholds; RANDAO commit/reveal validation + beacon mix. Zero-coin
  miner wins ~20% (open lane) and earns; a Sybil swarm stays bounded to 20%; a zero-premine / zero-bond
  chain still produces.

## Known limitations (read before running anything of value)
This is a **testnet-stage alpha / not yet mainnet-launched** build. The full consensus-hardening plan
above — including equivocation slashing, FFG-lite stake-attested finality, and the commit-reveal RANDAO —
is now **wired and unit-tested**, with two honest caveats and one outstanding hardening area:
- **FFG-lite finality and the commit-reveal RANDAO are only LIGHTLY exercised on a multi-node net.**
  They are unit-tested for correctness, but their **epoch-crossing** behaviour has not been driven hard
  empirically — the ~10 s/block cadence makes crossing the 120+ blocks needed for a full justify→finalize
  and a complete commit→reveal cycle slow. They engage as the chain crosses epochs.
- **FFG is additive, not a rollback bound.** It is an observable, stake-attested finality *signal*
  (`/status.ffg_finalized`) layered on top of the time-based finality floor — it does **not** replace it.
  There is also **no explicit RANDAO withholder penalty** yet.
- **Broader eclipse hardening is still planned/post-launch** (see `doc/consensus-hardening-plan.md`):
  **ASN-level** (vs the live per-/16) peer-diversity caps, **pinned multi-seed bootstrap**, and
  **snapshot-bootstrap binding to a finalized signed checkpoint**.

Run it on a **testnet / at your own risk** only. Do not treat coins as having value yet. (No hardfork
concern — mainnet is not live.)

— Chain id `nado-relaunch-1` · `v1.0.0-alpha.1`.
