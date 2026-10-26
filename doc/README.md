# NADO relaunch documentation

This `doc/` set describes the NADO **relaunch** — a coordinated set of consensus, economic,
storage and determinism changes implemented directly as the new genesis behaviour (that
relaunch is now the live network — CHAIN_GENERATION 28, betanet-9 — and consensus changes since ride
generation-keyed gates: the GATE LEDGER in `protocol.py`, [reroll.md](reroll.md)).

It also records the multi-agent **security review** that motivated much of this work and the
**storage migration** from the old SQLite index to a schemaless **LMDB** key-value store.

> Units: **1 NADO = 10,000,000,000 raw** (`DENOMINATION = 1e10`). All on-chain amounts are
> integers in raw units. `to_readable_amount` divides by `1e10`.

## Documents

| Doc | Contents |
|-----|----------|
| [whitepaper.md](whitepaper.md) | **Authoritative overview** — two-lane mining, economics, PQ crypto, LMDB storage, the security model with an explicit implemented-vs-planned split, and the full constants table |
| [leaderless-assembly.md](leaderless-assembly.md) | **Leaderless block assembly** — why every node builds every block (no proposer to censor or wait for), the one weakness (same-height splits from pool skew), and the touch-ups: pre-assembly tx-set reconcile, most-complete-pool tie-break, no sender-wide purge |
| [relays.md](relays.md) | **Relays** — how the web wallet fails over between nodes (the relay pool: `/relays` discovery, chain + height checks, drift back home), why an HTTPS wallet can only use TLS relays, and how an operator publishes one (`public_relay_url`) |
| [economics.md](economics.md) | **Superseded** (its own header says so) by [tokenomics.md](tokenomics.md), [treasury.md](treasury.md) and [bond-elastic-emission.md](bond-elastic-emission.md): no premine, the keyless treasury, flat bond-elastic reward, fees, supply accounting |
| [mining.md](mining.md) | Bonded-registry mining (the open/mobile/botnet-safe redesign): bond/unbond, split-neutral selection, RANDAO beacon, fidelity, the browser miner — and exactly what is implemented vs. pending |
| [ip-spoofing-and-sybil.md](ip-spoofing-and-sybil.md) | **Fair distribution** of the open lane: why IP is out of consensus and spoofable, how Sybil skews (but can't enlarge) the free lane, and ranked ideas to tie one share to one real participant — incl. bonded-node sponsorship and the hash-based Proof of Sequential Work (Appendix A) |
| [reward-capture-theorem.md](reward-capture-theorem.md) | **Theorem** — the "one miner takes all the rewards" worst case: capture ≤ `20% + 80%·s`, so a free/Sybil attacker is capped at 20% and total monopoly requires owning ~all the stake. Proof, corollaries, and the five assumptions that hold it |
| [presence-dividend.md](presence-dividend.md) | **Design proposal** — smooth the open lane from a per-block jackpot into a fidelity-weighted *presence dividend*: split the open block reward into a small producer tip + a redistributed pool, accrued off-L1 on the execution layer and withdrawn in aggregate. `O(1)` on L1, Sybil-bounded by fidelity + the 20% cap, no dust bloat |
| [storage.md](storage.md) | The current schemaless **LMDB** key-value index (`ops/kv_ops.py`), atomic `incorporate_block`/rollback, snapshot sync, and the "stuck node" fixes |
| [memoization.md](memoization.md) | Every cache in the node, exec layer, STARK/native crates and browser — what it memoizes, its key, eviction rule, consensus relevance, and the incidents behind the rules |
| [progressive-levy.md](progressive-levy.md) | Can the protocol tax large stakers for the open lane? Per-identity progressivity is void (free keys — the bond cap's flaw); the enforceable lever is `BONDED_DIVIDEND_BPS`, sized and gated |
| [key-rotation.md](key-rotation.md) | **Design proposal (Roadmap Track H)** — account authentication as state: authenticators + `signing`/`reconfig` policies (`ID`/`THRESHOLD`, hard-capped), recovery = policy, proof of possession, `config_version`, 1-day pending + cancel/freeze |
| [storage-kv-migration.md](storage-kv-migration.md) | The SQLite → LMDB migration: engine decision (`py-lmdb`), the full sub-DB schema, atomicity, and the cut-over steps |
| [consensus-hardening-plan.md](consensus-hardening-plan.md) | The locked, ordered design for the consensus-security milestones (#15–#18); the first wave is implemented, the rest is planned |
| [finality.md](finality.md) | **Finality & fork recovery (two-floor model, BUILT)** — `hard_finality` (FFG quorum + wide backstop) is the un-crossable floor, depth is crossable cadence; measured-evidence fork recovery, canonical-chain-preserving re-anchor, the exec layer's revert/rewind interplay |
| [determinism-and-chain-id.md](determinism-and-chain-id.md) | Canonical hashing (audit M14), chain-id binding (M3), txid/signature scheme, address derivation, browser reproducibility |
| [security-review.md](security-review.md) | The reviewed findings, what this relaunch fixes, and what remains open (historical audit snapshot) |
| [protocol-constants.md](protocol-constants.md) | Reference table of every constant in `protocol.py` (values, meaning, which are provisional) |
| [execution-layer.md](execution-layer.md) | The separate **RISC-V execution layer** — sovereign (Phase 1) → settled (Phase 2), opaque `blob`s, one bounded proof verifier, PQ-sound proving; what touches L1 vs. never does |
| [l2-settlement.md](l2-settlement.md) | **Settlement layer / ultimate scaling** — NADO as a shared ordering + DA + settlement layer for L2 rollups; bonded-quorum settlement (built) → one STARK validity proof → recursive aggregation, where **L1 cost is O(1) per batch regardless of L2 throughput** |
| [settlement-layer.md](settlement-layer.md) | **Implementation spec** for the settlement layer — data/tx formats, the node↔execnode↔interface wiring, the `settlement_justified` verifier seam, namespaces, the mining-wallet Settlement tab, phased checklist + tests |
| [rollups-and-settlement.md](rollups-and-settlement.md) | **Complete architecture** — the exec node, blobs/DA, **namespaces (built)**, what a rollup is, settlement, and the **tunnels** (bridge + shielded + dividend + cross-rollup); security invariants + a built-vs-designed table + file map |
| [exchange-integration.md](exchange-integration.md) | **Exchange/custodian guide** — REST endpoints, `ndo` address checksums, credit-at-`finalized_height`, ML-DSA withdrawal signing; why the RPC is not Bitcoin/ETH JSON-RPC |
| [dex-bridge.md](dex-bridge.md) | **Decentralized exchange & bridge — no authority** — HTLC atomic-swap bridge + an ownerless on-chain order book (exec-layer contract), matching, cross-chain preimage settlement, intra-NADO atomic swaps, watchtowers, the free-option problem, MEV/ordering, and a phased build plan. The trustless alternative to a custodial/multisig bridge  — order book now `otc` (§4), shipped AMM noted, concrete BTC/ETH HTLC leg templates (§6.5) |
| [tokenomics.md](tokenomics.md) | Single-page reference for the monetary policy, read from the live constants |
| [bond-elastic-emission.md](bond-elastic-emission.md) | The live emission rule: a flat subsidy scaled down as the bonded ratio rises (super hard money) |
| [treasury.md](treasury.md) | The keyless treasury: 10 % of every block, spending by bonded-stake quorum (governance live) |
| [governance.md](governance.md) | **Draft policy** — the human layer of treasury governance (addendum to treasury.md) |
| [address-format.md](address-format.md) | How an address is derived (format 2: a hash of the whole key plus a checksum) |
| [aliases.md](aliases.md) | On-chain aliases: send to a name instead of an address |
| [referrals.md](referrals.md) | Referrals and funded invite links (live from `REFERRAL_HEIGHT`) |
| [signature-schemes.md](signature-schemes.md) | User-selectable post-quantum signature schemes — built, dormant on generation 28, live from block 1 on generation 29 |
| [htlc.md](htlc.md) | HTLC transactions (`htlc_lock` / `htlc_claim` / `htlc_refund`) for cross-chain atomic swaps |
| [tpm-attestation-without-a-ca.md](tpm-attestation-without-a-ca.md) | CA-free TPM enrolment: commit-reveal challengers instead of a certificate authority (live) |
| [windows-tpm-attester.md](windows-tpm-attester.md) | `nado-tpm-attest`, the helper that makes a TPM usable when Windows Hello will not attest |
| [become-a-validator.md](become-a-validator.md) | How to bond and run a validator |
| [api.md](api.md) | HTTP API reference for the node and the exec node |
| [cli.md](cli.md) | The CLI and headless automation: everything the wallet does except device attestation |
| [messaging.md](messaging.md) | Off-chain, end-to-end-encrypted messaging (live) |
| [forum.md](forum.md) | The NADO forum, wallet-signature login (live) |
| [faucet.md](faucet.md) | The faucet prize bank (live) |
| [jobs.md](jobs.md) | Every job the system runs, declared in `deploy/units/manifest.json` |
| [updates-and-rerolls.md](updates-and-rerolls.md) | How nodes self-update, chain generations, and what a reroll is |
| [reroll.md](reroll.md) | **Procedure** — the reroll runbook and the gate ledger |
| [testnet.md](testnet.md) | **Procedure** — repeatable local multi-node testnets |
| [consensus-mechanics-lessons.md](consensus-mechanics-lessons.md) | Consensus mechanics every engineer here must know, distilled from incidents |
| [index-pruning.md](index-pruning.md) | Bounding the number↔hash index (`INDEX_RETENTION_NUM` / `_HASH`, implemented) |
| [scaling-analysis.md](scaling-analysis.md) | Will NADO scale: analysis and change log |
| [consensus-aggregation.md](consensus-aggregation.md) | Consensus-load aggregation (native ML-DSA verify backend and the rest of the scaling envelope; implemented) |
| [scaling-open-lane.md](scaling-open-lane.md) | Scaling the open lane to millions of devices (phases 1a/1b live) |
| [takeover-resistance.md](takeover-resistance.md) | Why NADO cannot be Sybil-captured the way Nyzo was (architecture rationale) |
| [registration-difficulty.md](registration-difficulty.md) | Registration PoSW difficulty — **retired at gen 25**, kept as rationale |
| [node-service-reward.md](node-service-reward.md) | **Design proposal, not built** — paying public-IP infrastructure without a farmable loop |
| [runtime-upgrades.md](runtime-upgrades.md) | **Design draft for mainnet** — decentralized, atomic runtime upgrades |
| [exec-instructions.md](exec-instructions.md) | Exec-layer blob instructions — developer reference for the zkVM |
| [assets.md](assets.md) | Assets: a second value type on the exec layer (built) |
| [reserve.md](reserve.md) | Reserve vaults: back an asset with locked native value, redeemable pro rata |
| [storage-deposit.md](storage-deposit.md) | **Design (2026-10-18)** — pricing contract storage with deposits |
| [stablecoin.md](stablecoin.md) | **Design draft, nothing implemented** — the `nUSD` stablecoin |
| [game-finality.md](game-finality.md) | The four finality states a game move passes through, and what a game may do at each |
| [autogame.md](autogame.md) | Autogame — the March, a game paced by L1 blocks |
| [sovereign.md](sovereign.md) | Sovereign — a persistent nation-war game (live) |
| [age-of-gore.md](age-of-gore.md) | **Design, nothing built** — the Age of Gore recommendation |
| [debrand.md](debrand.md) | **Record** — the brand-string inventory; the rename it planned has been executed |
| [units.md](units.md) | The named sub-unit ladder (`dag`…`eli`) — a display convention over the raw-integer ledger, honoring the people behind NADO |

## Zero-knowledge / proof-system documents

**Start with [zk-components.md](zk-components.md)** — the complete map of every ZK component in the tree,
with a live-vs-capability-vs-research status for each and the measured numbers behind them.

| Doc | Contents |
|-----|----------|
| [zk-components.md](zk-components.md) | **The whole ZK surface at once** — arithmetic core, hashes, STARK proving, the execution zkVM, the shielded pool, state-root binding, recursion, the Rust crates, DA transport, consensus constants; what is load-bearing today and exactly where trustless settlement still stops |
| [zk-glossary.md](zk-glossary.md) | Plain-language definitions of every term used across `execnode/stark/*` and the `zk-*` docs — **read this first if the vocabulary is new** |
| [zk-execution-proofs.md](zk-execution-proofs.md) | Proving contract execution: the zkVM AIR that shows "running this public program on this input yields this output" |
| [zk-recursion.md](zk-recursion.md) | STARK recursion — verifying a proof inside a proof for **O(1) settlement verification**: alghash2, the in-circuit FRI/STARK verifier, in-circuit Fiat-Shamir, the K→1 fold and fold-of-folds |
| [zk-settlement-completion.md](zk-settlement-completion.md) | Trustless STARK settlement — the completion checklist and what each load-bearing piece still needs |
| [zk-signature-aggregation.md](zk-signature-aggregation.md) | **Post-mortem** — signature aggregation was built, measured, and removed. Kept deliberately: the idea is attractive and the measurements say no |
| [privacy.md](privacy.md) | The post-quantum zk-STARK **shielded pool** — join-split circuits, membership AIR, and the one place the full proof→DA→commitment→verify loop already works in production |
| [rust-only-proving.md](rust-only-proving.md) | **Binding policy** — why a hybrid prover is not a prover: Rust-only, no fallback, fail-stop rather than silent degradation |
| [settle-proof-transport.md](settle-proof-transport.md) | Getting a settle-with-proof onto the chain — measured payload sizes, why the proof can never ride inside a block, and the DA architecture that follows |
| [rolling-mode-and-da.md](rolling-mode-and-da.md) | Rolling mode (history pruning, idle-GC) and the DA store — **built**; DA sampling is design |
| [wasm-prover.md](wasm-prover.md) | On-device STARK proving in the browser (`static/stark/*.js`) |
| [quantum-resistance-and-vms.md](quantum-resistance-and-vms.md) | Why quantum resistance lives in the **proof system**, not the VM — a category confusion worth clearing up |
| [provable-practice.md](provable-practice.md) | Provable practice runs — leaderboards nobody can forge |
| [vision.md](vision.md) | The four goals the proof-system work is judged against |
| [state-merge.md](state-merge.md) | How two state-transition proofs compose (sequential and parallel merge) |
| [shielded-contracts.md](shielded-contracts.md) | Private application state — built, **paused** on the live chain since the 2026-09-24 review |
| [dividend-fraud-proof.md](dividend-fraud-proof.md) | The presence-dividend fraud proof: part A built, parts B/C (receipts, challenge) not |
| [execution-layer-vm-research.md](execution-layer-vm-research.md) | **Research note (2026-06-30)** — the VM / proving-system frontier survey; nothing built from it directly |
| [obfuscation-diamond-io.md](obfuscation-diamond-io.md) | Program obfuscation (**research goal**; nothing implemented, scheduled or promised) |
| [device-attestation.md](device-attestation.md) | **The live attestation design** — device classes, binding modes, "one device, one identity", and which classes bind permanently |
| [nado-key.md](nado-key.md) | **Design, not built** — a NADO-issued WebAuthn attestation device: the kernel needs no change, binding must read the per-device certificate rather than the credential, what the hash actually counts, the runnable Pi Pico spike, and why the recommendation is not to build it |
| [nado-hardware-wallet.md](nado-hardware-wallet.md) | **Design, not built** — a hardware wallet for NADO (none exists; the baseline is a key in a browser). The signer is a cross-compile; the real risk is a second byte-exact `create_txid` encoder on a microcontroller, because a device that signs a hash it was handed makes its screen decoration |

## Stwo migration (generation 29)

| Doc | Contents |
|-----|----------|
| [stwo-migration.md](stwo-migration.md) | **Start here** — moving settlement to Stwo/BLAKE2s and a reroll that carries everything; what is live on gen 28 and what waits for gen 29 |
| [stwo/g1-tree-shape.md](stwo/g1-tree-shape.md) | G1: the BLAKE2s exec-root tree shape, measured |
| [stwo/g3-vm-word.md](stwo/g3-vm-word.md) | G3: the contract VM's word after Goldilocks |
| [stwo/g4-settlement-statement.md](stwo/g4-settlement-statement.md) | G4: the generation-29 settlement statement and its Stwo prototype |
| [stwo/g5-carry.md](stwo/g5-carry.md) | G5: the carry that loses nothing (`tools/carry.py`) |
| [stwo/phase0-results.md](stwo/phase0-results.md) | **Record** — phase 0: our join-split prover against a Stwo prototype |
| [stwo/zk-argument.md](stwo/zk-argument.md) | **Record** — the zero-knowledge argument for the `stwo_zk` join-split prover |

## Records (historical — accurate for their date, not maintained)

| Doc | Contents |
|-----|----------|
| [security-audit.md](security-audit.md) | Consensus security audit, 2026-06-30 |
| [security-audit-2026-07-02.md](security-audit-2026-07-02.md) | Deep security audit, 2026-07-02 |
| [security-review-2026-09-23.md](security-review-2026-09-23.md) | Security review of contracts, exec layer, settlement, shielded pool and STARK, 2026-09-23 |
| [security-review-2026-09-24-zk.md](security-review-2026-09-24-zk.md) | Security review of the zero-knowledge stack, 2026-09-24 |
| [security-review-2026-09-27.md](security-review-2026-09-27.md) | Closing the 2026-09-24/25 audits: each finding checked against the deployed code, 2026-09-27 |
| [regdiff-v3-postmortem.md](regdiff-v3-postmortem.md) | Postmortem: the registration-difficulty v3 visibility fork, 2026-07-18 |
| [tpm-attestation-architecture-review.md](tpm-attestation-architecture-review.md) | Postmortem: what a day of real TPM hardware taught us, 2026-09-11 |
| [deployment-betanet5.md](deployment-betanet5.md) | Deployment runbook for the betanet-5 cutover, 2026-07-14 (superseded by reroll.md) |
| [release-betanet-14.md](release-betanet-14.md) | Release notes, betanet-14 |
| [previous-network-snapshot.md](previous-network-snapshot.md) | The previous NADO network's final account snapshot |
| [influencer-outreach.md](influencer-outreach.md) | Outreach: influencer list |
| [outreach-dms-tier0.md](outreach-dms-tier0.md) | Outreach: tier-0 DM drafts |

## Settlement model — a bonded quorum today, a validity proof by design

NADO settles its execution layer with a **bonded-stake quorum**, and that is what actually carries
settlement in production today. Alongside it, the consensus rule for **trustless settlement** — settling
the root on a STARK validity proof with *no* quorum — is implemented and switched on unconditionally
(`SETTLE_PROOF_TRUSTLESS`, no feature flags; they were deleted in `74957663`).

> **Honest status: one proof-carrying settle has landed** — block 43153 (2026-08-06) settled on a STARK proof a
> peer verified ([settle-proof-transport.md](settle-proof-transport.md)). Routine settlement still rides the
> quorum, because spans that move withdrawals, unshields or xmsgs cannot be proven yet
> ([stwo/g4-settlement-statement.md](stwo/g4-settlement-statement.md) §1). Before that landing, measured over 33 064 journal lines (2026-08-01 → 08-06): **89 proofs
> built and submitted, 0 accepted, 85 refused** with `HTTP 413, Maximum request body size 8388608
> exceeded` at 97.30–97.45 MiB. [zk-components.md](zk-components.md) §0 has the counts and §14 the five
> fixes that got it that far.

The weight difference is the reason the quorum remains the working path:

| | Exec-node quorum (carries settlement today) | Validity proof (rule live, landed once) |
|---|---|---|
| Settle a batch | run the zkVM (`execnode/zkvm.py`), attest the root | prove the epoch's state transition (STARK) |
| Compute | ~native (µs–ms) | **10.2 s warm / 58.9 s cold** — re-measured 2026-08-13 |
| L1 verify | **one integer compare** | one proof, ~0.3 s, independent of call count |
| Payload | a few hundred bytes | **97–118 MiB** — ~380× a full block, so it must go via DA |
| Trust | 2/3 honest bonded stake — **= NADO finality** | cryptographic soundness only |

The compute row is the one people get wrong: `storage_tree._FOLD_CACHE` makes a running prover's settle
cost O(slots the span changed), so a steady-state prove is **10.2 s**, while a fresh process (a restart,
or any verify outside a long-lived prover) pays a ~50 s singleton-fold rebuild on top. Older documents
quote ~250 s; that is the cold number from before the cache, and quoting it as the steady-state cost has
inverted a conclusion more than once — see [fri-parameters.md](fri-parameters.md) §4a.

A rollup is **as secure as L1 for ~free** under the quorum; the validity proof removes one assumption
(that 2/3 of bonded stake is honest — the same assumption already securing every balance) at a real cost
in proving time and transport. Full analysis + the lighter fraud-proof middle option:
[l2-settlement.md](l2-settlement.md) §3a.

## Implementation status (at a glance)

| Stage | Scope | Status |
|------|-------|--------|
| **S1** | Canonical hashing (M14), chain-id (M3), `protocol.py`, min-fee | ✅ implemented & unit-tested |
| **S2a** | "Stuck node" disk-I/O fixes (per-thread conn, atomic writes, no spin loops) | ✅ implemented & unit-tested |
| **S2b** | Consolidate to one index DB; crash-atomic `incorporate_block`/rollback | ✅ implemented & unit-tested (the index store was later migrated SQLite → LMDB, see #21) |
| **S3** | No premine → treasury; fee-weighted elastic reward (since replaced by flat bond-elastic emission); 90/10 split (since 50/40/10 bonded, 20/70/10 open); remove compat gates | ✅ implemented & unit-tested |
| **(burn)** | Remove burn mechanics entirely | ✅ implemented & unit-tested |
| **S4.1** | Bond/unbond transactions + `bonded` stake state | ✅ implemented & unit-tested |
| **S4.2** | Split-neutral selection math + commit-reveal RANDAO beacon (`ops/mining_ops.py`) | ✅ implemented & unit-tested |
| **S4.3 v1** | Bonded `select_producer` + epoch beacon wired into live production/verification; fail-closed authorship; testnet bonding | ✅ **implemented & testnet-validated** (3 nodes produce + converge via bonded mining) |
| **S4b** | Browser light-miner reference client | ✅ implemented (`static/interface.*`; the PySide6 desktop wallet was retired 2026-09-08) |
| **#21** | Schemaless **LMDB** key-value index replaces the SQLite `index.db` (`ops/kv_ops.py`; `ops/sqlite_ops.py` deleted) | ✅ implemented & testnet-validated (see [storage-kv-migration.md](storage-kv-migration.md)) |
| **#16/#17** | Objective stake-weighted heaviest-chain fork-choice + grind-proof `cumulative_weight` header + enforced finality floor (`FINALITY_DEPTH`, now 45, `FinalityViolation`; the un-crossable floor is now `hard_finality`, [finality.md](finality.md)) | ✅ implemented & testnet-validated |
| **#18 (partial)** | Fail-loud epoch beacon (silent `GENESIS_BEACON` fallback removed); `/announce_peer` rate-limit | ✅ implemented |
| **#15/#19 (partial)** | Detached **optional** winner block signature (off the hash/validity path); pubkey-once (`public_key` excluded from txid) | ✅ implemented |
| **Consensus hardening** | IMPLEMENTED: equivocation + attestation slashing (fee-exempt `slash` tx, bond burn), enforced FFG >2/3-bonded finality with the inactivity leak, on-chain commit-reveal RANDAO, `/announce_peer` rate-limit + per-/16 subnet diversity. Remaining (post-launch ops): ASN-level peer diversity, pinned anchor slots + multi-seed bootstrap, checkpoint-bound snapshot bootstrap | ✅ live (tail ⏳, see [consensus-hardening-plan.md](consensus-hardening-plan.md)) |

"Unit-tested" = verified by the stage suites `tests/test_s1_foundations.py` … `tests/test_s4_3_selection_integration.py`
under a temporary `$HOME`. S4.3 and the browser client have since been built and validated on a multi-node
testnet (rows above).

## Running the tests

System `pip` is PEP-668 locked, so use a venv with the **minimal** deps (the full
`requirements.txt` includes heavy build-only packages — `pandas`, `nuitka`,
`customtkinter` — that are not needed and may fail to build):

```bash
python3 -m venv venv
./venv/bin/pip install cryptography tornado aiohttp msgpack requests coloredlogs ordered-set zstandard psutil pympler lmdb
for t in tests/test_s[0-9]*.py; do ./venv/bin/python "$t"; done   # the stage suites above
scripts/run_tests.sh             # the whole suite, each test in its own HOME (--fast / --slow)
```

Each test file creates its own throwaway `$HOME` and `index/` so it never touches a real node.
`nado.py` is the **server entrypoint** and is intentionally **not import-safe** — don't import
it in unit tests.

## Key source files

- `protocol.py` — single source of truth for all protocol/economic/mining constants + the reward splits (`split_bonded_block_reward`, `split_open_block_reward`).
- `hashing.py` — `canonical_bytes` + the blake2b hash helpers.
- `ops/account_ops.py` — accounts, balances, bonded stake, totals.
- `ops/block_ops.py` — block construction, the flat bond-elastic reward, indexing, penalty.
- `ops/mining_ops.py` — bonded selection + RANDAO beacon (S4.2).
- `ops/transaction_ops.py` — tx validation, signing, spending checks.
- `ops/kv_ops.py` — the schemaless **LMDB** key-value index: env + named sub-DBs, key/value encoding, and the atomic `write_txn()` context (replaced the deleted `ops/sqlite_ops.py`).
- `loops/core_loop.py` — the node state machine; `incorporate_block`/`verify_block`.
- `rollback.py`, `genesis.py`, `ops/snapshot_ops.py`.

