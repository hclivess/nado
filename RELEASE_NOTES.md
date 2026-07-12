# Alphanet fix — 2026-07-13 (settlement inactivity leak: dividends claimable again)

> **Consensus-affecting** (changes what L1 accepts as the settled exec root) — update all nodes.

Dividend (and bridge/unshield) claims were failing with *"no settled execution-layer root yet"*:
the settlement quorum denominator was **all bonded stake**, and only one validator runs an
exec+settle node — the moment non-settling validators bonded past 1/3 of shares (day one), no
root could ever be justified. Users' `collect_dividend` burns landed in exec-side withdrawal
records that could never be claimed (funds stuck, not lost — 406 records, ~131.8 NADO).

Fix: settlement now uses the **same inactivity leak FFG finality already has** — the denominator
is the bonded shares of validators that posted a settle attestation within
`SETTLE_ACTIVITY_CURSORS` (1440 exec cursors ≈ 2.4 h) of the newest one. Validators that don't
settle leak out of the quorum instead of freezing it, and re-enter the moment they attest.
Trust: the settled root is now controlled by >2/3 of *participating* settlers (today: the genesis
operator's node — equivalent to the chain's first days); the optimistic dividend fraud proof
remains the planned trust upgrade. `latest_settled` also now walks cursors newest-first instead
of scanning the whole attestation history per claim validation.

All previously stuck dividend withdrawal records become claimable as soon as a post-fix root
settles — no user action was lost; wallets can simply re-claim.

---

# Alphanet update — 2026-07-12 (scale & storage pass)

> Applies to `alphanet-4`. **No legacy tolerance:** all nodes must update together — the wire
> (mempool set reconciliation), the exec settled root (state-shape changes), and the idle-GC
> consensus sweep (activates ~epoch 1000) are not interoperable with older builds.

## Storage
- **Append-only SEGMENT block store** (`ops/segment_store.py`): block bodies are crc-guarded,
  self-describing records in `blocks/seg-*.dat` (64 MB target, ~300 files/year instead of one
  inode per block), addressed by LMDB locators (node-local `block_loc` sub-DB, snapshot-excluded).
  Crash contract preserved: append + fsync BEFORE the locator commits; torn tails truncated at
  startup; rollback drops the locator INSIDE the rollback txn (stronger than the old file unlink).
  One-time idempotent startup migration folds legacy per-file bodies in. `child_hash` is now
  DERIVED from the number→hash index at read time (more reorg-correct; the parent-rewrite is gone).
  Rolling mode unreferences bodies and reclaims whole dead segments (blob bodies copied forward).
  Fully portable file I/O (a Windows joiner surfaced an `os.pread` dependency — fixed, and the
  test suite now emulates Windows for the storage layer).

## Consensus / state growth
- **Idle-account GC** (`ops/gc_ops.py`): deterministic in-block sweeps at epoch boundaries —
  trivially-empty account docs idle > `GC_IDLE_EPOCHS` (1000) are deleted; recert rows drop past
  `RECERT_HISTORY_EPOCHS` (10 000) with a fidelity-saturation proof that keeps every still-served
  dividend weight byte-exact. Revert-safe (node-local `gc_revert` records), bounded per boundary,
  snapshot-root-identical on every node. `/get_open_weights` refuses epochs whose lookback would
  cross the pruned horizon.
- **Exec settled-checkpoint bootstrap**: cold exec nodes adopt a donor's last-settled snapshot
  (`/exec/state_snapshot` + `NADO_EXEC_BOOTSTRAP=<donor>`), verified against the L1-settled
  `(cursor, root)` — replaces genesis replay once ancient history prunes.

## Networking
- **Mempool set reconciliation**: divergent peers exchange txid lists (`GET /transaction_ids`)
  and fetch only the missing bodies (`POST /transactions_by_id`, ≤1000/req) — ~100× less
  bandwidth than the old full-pool re-download with ~7 KB ML-DSA txs. The legacy
  `/transaction_buffer` endpoints are removed.

## Execution layer (settled root CHANGES — deploy all exec nodes together)
- Claimed bridge/dividend/unshield exit records are GC'd when their finalized L1 claim burns the
  nullifier; the outbox is seq-keyed with consumed-message GC; the field-nullifier set is
  committed as ONE digest leaf. `state_root`/`_leaves` cached (12 ms → 0.004 ms per read),
  provisional rebuilds skipped when nothing changed, VM storage copies ~150× faster.

## Node performance
- Producer registries cached per committed-write generation (no more ~5 full account-table scans
  per block); per-second mempool hashing O(1) between pool changes; `/get_recommended_fee` fixed
  (the old helper re-read the tip 250×) and served from memory.

---

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
- **Unbond is now timelocked (enforced).** `unbond` is a **release request** — the stake **stays
  bonded and slashable** and a maturity block `release_block = current + BOND_UNLOCK_DELAY (1440)` is
  recorded; a new fee-exempt **`withdraw`** tx moves the matured amount to spendable balance only
  **at/after** maturity. Keeping the stake bonded through the delay is what keeps a *caught
  equivocator's* stake slashable while an unbond is in flight. (`unbond`/`withdraw` are now fee-exempt;
  `MIN_TX_FEE` applies to ordinary transfers and `bond`.)

### Post-quantum signatures (ML-DSA-44, FIPS 204)
- Ed25519 is replaced by **ML-DSA-44** (NIST FIPS 204) via pure-Python `dilithium-py` — no native
  build, in keeping with the lightweight goal.
- The node's signing is **cross-validated both ways** against the browser's `@noble/post-quantum`,
  so a browser/phone miner and a full node verify each other's signatures.

### Wallets
- **Desktop wallet** (`pyside_wallet.py`, PySide6): overview, send, bond/unbond, register & mine,
  expected-time-to-mine, and a live selection-lane visualization.
- **Browser/mobile NADO Interface** (`static/interface.html`): phones mine through a web page — generate a
  key, register, heartbeat each epoch, and **win offline** (a relay builds the block for you). No
  full node, no heavy crypto on the device. It now also shows **live OPEN/BONDED lane participant
  counts** (from `/mining_status` `open_registry_size` / `bonded_registry_size`) so you can see how
  contested each lane is.

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

### Security audit — every exploitable finding fixed
A deep **adversarial security audit** (full writeup: `doc/security-audit.md`) was run across **six
surfaces** (fork-choice/51%/rollback/finality; Sybil/two-lane/selection; slashing/equivocation/unbond;
RANDAO/FFG/beacon; tx-validation/pubkey-once; KV atomicity/eclipse/DoS) against a chain that was
testnet-stage alpha with **no value at stake**. Every exploitable finding is now **fixed and
unit-tested**:
- **In-block duplicate reserved-tx bugs (CRITICAL/HIGH).** Uniqueness was checked only vs *parent*
  state with no block-assembly dedup, so duplicate reserved txs in **one** block could drain an unbond
  via repeated `withdraw`s (slash-escape/chain-halt), over-burn on a duplicate `slash` (two honest
  reporters trigger it organically), or collapse duplicate `heartbeat`/`reveal` rows so a reorg
  over-deletes the shared row → **registry/beacon desync fork**. Fixed by **per-reserved-tx in-block
  uniqueness** (`reserved_uniqueness_key` + `dedupe_reserved` + `assert_unique_reserved`) plus
  cross-block `heartbeat`/`reveal`-secret guards.
- **Same-length fork-choice wedge (CRITICAL, liveness).** Equal-weight honest tips could wedge forever;
  fixed by a deterministic **lowest-hash tie-break** (`weight DESC, hash ASC`) so nodes converge.
- **`quick_sync` validation bypass (HIGH).** `verify_block` now **always** validates signatures +
  spending; the old-block bypass is removed.
- **Unauthenticated advertised-weight DoS (HIGH).** A bogus huge `latest_block_weight` forced emergency
  rollbacks; fixed by a bounded, auto-clearing **`rejected_tips`** exclusion.
- Plus per-IP **rate limits** on the heavy read endpoints (`/mining_status`,
  `/get_transactions_of_account`, `/get_blocks_after`/`before`), an **honest re-signer guard** (only
  ever signs a strictly higher height), the **per-/16 subnet cap on the disk-reload path**, and a dead
  `/get_blocks_before` fix.

The audit **confirmed the safety core sound** (atomic incorporate/rollback, the monotonic finality
floor, equivocation-proof unforgeability, the detached-signature-outside-the-hash property, and
pubkey-once key→sender binding). Remaining items are documented residuals (see Known limitations) — none
a theft or fork vector.

## Validated
- 3-node testnet **converges and produces** with the full stack live (two-lane mining, ML-DSA keys,
  LMDB storage, zstd block bodies, POST wire, enforced finality, heaviest-weight fork-choice).
- Unit-tested: atomic incorporate→rollback byte-identical; finality floor refuses sub-floor rollback;
  cumulative_weight committed + verified; beacon fail-loud; equivocation proof verify + bond slash
  (apply/revert); FFG justify/finalize thresholds; RANDAO commit/reveal validation + beacon mix;
  **in-block reserved-tx uniqueness** (`tests/test_inblock_uniqueness_audit.py`) and the **unbond-request
  + matured `withdraw` timelock**. Zero-coin miner wins ~20% (open lane) and earns; a Sybil swarm stays
  bounded to 20%; a zero-premine / zero-bond chain still produces.

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
  **snapshot-bootstrap binding to a finalized signed checkpoint** (no hardcoded checkpoint cross-check
  today — weak-subjectivity).
- **Documented audit residuals (none a theft/fork vector — see `doc/security-audit.md`):** FFG's
  "slashable-stake backing" is **aspirational** — no **attestation-equivocation slashing** yet (only
  block-authorship equivocation), so cross-fork double-voting beyond the per-epoch `UNIQUE(validator,
  epoch)` marker is unpunished; the bonded `MAX_SHARES` cap is **per-identity, not aggregate** (the
  bonded lane is capital-proportional by design); `register`/fee-exempt **state growth** is bounded but
  `GC_IDLE_EPOCHS` idle-account GC is unwired; and `FIDELITY_DECAY` is defined but unwired.

Run it on a **testnet / at your own risk** only. Do not treat coins as having value yet. (No hardfork
concern — mainnet is not live.)

— Chain id `nado-relaunch-1` · `v1.0.0-alpha.1`.
