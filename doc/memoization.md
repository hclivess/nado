# Memoization and caches

Every cache in the codebase, what it memoizes, what invalidates it, and whether a stale or mis-keyed
entry can change consensus. Line numbers are as of 2026-08-24; grep the name if they drift.

The reason this document exists: five separate incidents were a cache that was **missing**, **keyed on
the wrong thing**, or **recomputed on a hot path** — the 31 %-CPU state-root walk, the 37 s/block
thundering herd on `latest_settled`, the claims-keyed settle-verdict memo that accepted tampered proofs,
the 5–12 h dividend-claim wait, and the 2026-08-24 exec stall where an *un*-memoized proof path pinned
the exec event loop (`/exec/dividend_proof` → `_sparse_stores` re-hashing 10 k slots per request, ~2
req/s → exec cursor 56/44 behind L1). A cache is a consensus component when it sits under a hash.

## The rules

1. **Key on the input's bytes, never on its claims.** A cache that answers for input it never saw is
   not a cache. (`settle_verify_key`, `provable.js _claimCache`.)
2. **Derived reads of committed L1 state key on `kv_ops.write_generation()`** and bypass themselves
   inside a write txn (`in_write_txn()`). Same discipline on the exec side with `ExecState._mut_gen`.
3. **Single-reference swap.** `(key, value)` stored as one tuple in a one-element list, so a reader can
   never pair a stale key with a newer value.
4. **Pure functions may be cached forever**; anything derived from mutable state needs a generation,
   a TTL, or a ring — and the eviction rule must be written down next to the cache.
5. **Herd-lock anything many readers can recompute at once** (`_latest_settled_lock`, the `/wealth_stats`
   scan locks). A generation-keyed cache with N concurrent readers is N recomputes at every bump.
6. **Never cache a miss for something that can become true later** (`nadodapp.horizonVerdict`,
   `core_loop._probe_memo` failures) — a cached miss converts a settleable stake into a refund.
7. **Anything under the exec event loop that touches `_sparse_stores` / builds a `SparseStore` must be
   memoized** — a synchronous O(state) handler is a tail stall in disguise.

---

## 1. L1 node (`nado.py`, `ops/`, `loops/`, `memserver.py`)

There is no `functools.lru_cache` anywhere in the node; every cache is hand-rolled.

### 1.1 Invalidation backbone

| name | file | what |
|---|---|---|
| `_write_gen` / `write_generation()` / `_bump_write_gen()` | `ops/kv_ops.py:116-145` | Counter bumped on every committed write, under `_write_gen_lock` ("a lost bump would leave a cache stale"). Every derived-read cache below keys on it. |
| `_local` (thread-local) / `in_write_txn()` | `ops/kv_ops.py:110` | The bypass signal: inside a write txn the caches are skipped, because the generation has not yet moved but the state has. |

### 1.2 Consensus-relevant (feeds a hash, root, registry or validation verdict)

| name | file | memoizes | key | eviction | lock |
|---|---|---|---|---|---|
| `_root_cache` | `ops/snapshot_ops.py:279` | `l1_state_root()` — the value in every block hash | `(env_path, home, write_gen)` | generation | single-ref swap |
| `_leaf_cache` | `ops/snapshot_ops.py:62` | `(db,key,value)` → blake2b leaf digest inside `merkle_root` | the triple | `clear()` at 500 k | none (pure) — "the per-block state-root walk was 31 % of ALL process CPU" |
| `_bonded_reg_cache` | `ops/account_ops.py:538` | bonded producer registry (input to `select_producer`) | `(env_path, write_gen)` | generation | single-ref; key captured *before* the scan |
| `_open_reg_cache` | `ops/account_ops.py:611` | open-lane registry per epoch | `(env_path, write_gen, epoch)` | generation | single-ref |
| `_duty_committee_cache` | `ops/block_ops.py:637` | FFG duty committee `{address: seats}` | `(env_path, write_gen, epoch)` | generation | single-ref |
| `_randao_elig_memo` | `ops/block_ops.py:601` | opened commitments per epoch | `(epoch, sorted secrets)` | one entry (clear on miss) | self-correcting: a reorg that removes a reveal changes the key |
| `_latest_settled_cache` | `ops/settlement_ops.py:76` | justified `(exec_cursor, state_root)` per ns | `(env_path, write_gen, ns)` | generation | **`_latest_settled_lock` — the only true herd lock**; 80 % of busy samples were parallel copies of this walk (2026-08-20, 37 s/block) |
| `_recent_settled_cache` | `ops/settlement_ops.py:135` | last k justified roots — the dividend-claim validity window | `(env_path, write_gen, ns, k)` | generation | single-ref + `_recent_settled_lock` (herd lock added a0dbdd8e) |
| `_SETTLE_VERIFY_MEMO` | `ops/transaction_ops.py:832` | settle proof → `(ok, why, kv_pre, kv_post)` STARK verdict | `settle_verify_key`: `("da", commitment)` or `("inline", blake2b(proof))` — **the bytes** | `clear()` at 64 | none. Was keyed on the proof's claims → accepted tampered proofs unverified. Pinned by `tests/test_settle_verify_memo_key.py`. |
| records-half verdict (same dict) | `ops/transaction_ops.py:1447` | `(ok, why)` for the records half | `(vk, rec, rec_post, blake2b(effects))` | shared | stored only after verification; `tests/test_records_verdict_memo.py` |
| `_pool_hash_cache` | `memserver.py:331` | blake2b of the sorted mempool (majority-vote signal) | `pool_gen` | pool mutation | — |
| `_upcoming_hash_cache` | `memserver.py:332` | next block's content hash | `(pool_gen, parent hash, write_gen)` | pool or commit | — |
| `_ENC_MATRIX_CACHE` | `ops/da.py:59` | Reed-Solomon generator matrix | `(k, n)` | never | pure; "~141 million modexps" without it |
| `_Ledger` (`_acct`, `_spent`, …) | `ops/transaction_ops.py:1873` | balances read once per validation pass | account | dies with the ledger | per-call object |
| `_HASH_ATTEST_CACHE` | `nado.py:698` | signed hash attestation per height | height (+ `as_of` tip) | tip change; `clear()` > 512 | bounds the free-signing oracle |
| `attest_memo` (LMDB db) | `ops/kv_ops.py:748-781` | epoch → target we attested | epoch | `attest_memo_prune`; **excluded from `wipe_non_carried_dbs`** | persistent anti-equivocation memo, not perf |

### 1.3 Read-path / perf / network

| name | file | memoizes | eviction | note |
|---|---|---|---|---|
| `_SIZE_CACHE` | `ops/pool_ops.py:18` | txid → byte size | `clear()` at 20 k | non-consensus by construction |
| `_txid_set_cache` | `memserver.py:63` | pool txid set for gossip dedup | `pool_gen` | O(1) dedup for the per-second re-gossip |
| `_tx_reject_cache` | `memserver.py:72` | txid → retry-after cooldown | per-entry TTL ~60 s; rebuilt > 20 k | local policy |
| `recent_tx_rejects` | `memserver.py:474` | last 20 gossip refusals | ring 20 | telemetry |
| `_attest_watch` | `memserver.py:546` | `(sender, epoch)` → attestation seen (equivocation) | pruned < epoch−2 | — |
| `_richest_cache`, `_wealth_cache`, `_rich_list_cache` | `nado.py:1006/1050/1372` | full account scans for `/wealth_stats`, rich list | block height | **`_scan_locks` with double-check** — 32 simultaneous requests at a boundary meant 32 scans |
| `_geo_state` + `index/geo_peers.json` | `nado.py:1115` | peer geolocation | TTL 6 h; single-flight `computing` flag | stale served while refreshing |
| `_js_epoch_cache` | `nado.py:1590` | newest `static/*.js` mtime | TTL 2 s | ran on every request before |
| `_static_body_cache` | `nado.py:1591` | stamped static body + ETag | `(mtime_ns, size, js_epoch)`; `clear()` > 48 MiB | `_static_cache_lock` on write; a cold i18n.js was 220 ms on the event loop |
| `genesis_hash_cached()` | `ops/block_ops.py` | block-0 hash (one memo; `/status` and the peer loop both call it) | never (a reroll restarts the process) | — |
| `_sync_donor` | `loops/core_loop.py:344` | last selected sync donor | dropped on gate/tip failure | re-verified with one `knows_block` dial |
| `_genesis_id_cache` | `loops/core_loop.py:1355` | peer → same-genesis verdict | TTL 600 s; expired peers reaped on insert | — |
| `_probe_memo` | `loops/core_loop.py:1489` | `(peer, height)` → signed hash probe | whole memo dropped after 90 s; **failures popped explicitly** | unmemoized: 65 s/pass, the 2026-08-18 fleet freeze |
| `_fork_state_cache` | `loops/core_loop.py:1413` | fork verdict | TTL `FORK_STATE_TTL_S`=60; nulled on tip/identity change | — |
| `_tie_theirs_cache` | `loops/core_loop.py:1592` | tie-break hash per ancestor | TTL 60 s | — |
| `_excluded_logged` | `loops/core_loop.py:353` | log-once guard | **never cleared** | small unbounded growth |
| `_snap_advert_cache` | `loops/consensus_loop.py:289` | checkpoint manifest hash | new checkpoint | — |
| `_IDX`, `_BEACONS` | `ops/mining_history.py:92-93` | reward attribution index (on disk) | `_reset()` on anchor-hash mismatch (reorg); `KEEP_DAYS` | "a display cache, never consensus state"; `_LOCK` |
| `_stores`, `read_files` | `ops/segment_store.py:51/86` | per-home store, per-segment fd | never / `reset()` | fd count unbounded |
| `_envs`, `_dbhandles` | `ops/kv_ops.py:100` | LMDB env + db handles | `close_all()` | `_envs_lock` |
| `_own_ip_cache`, `_own_addresses_cache` | `ops/peer_ops.py:662`, `loops/message_loop.py:76` | own IPs | manual refresh / never | — |
| `_repo_head_cache`, `_latest_remote`, `_hints`, `_RUNNING_HEAD`, `_stale_since` | `ops/self_update.py` | git state for `/status` and `/update` | TTL 60 s / daily / 3600 s / never / per head | "it cost 1.5 hours of frozen finality on 2026-07-20" to call git inline |
| `_buckets`, `_reg_levels` | `ops/ratelimit.py:13/34` | per-IP request windows | sliding window; sweep at 100 k keys | IOLoop-only, no lock by design; non-consensus on purpose |
| daily/treasury/rollback stats | `ops/daily_stats.py`, `treasury_history.py`, `rollback_stats.py` | per-day aggregates with a cursor + `CHAIN_ID/CHAIN_GENERATION` stamp | chain-stamp mismatch (or, for rollback_stats, a missing stamp) discards the whole file — these files sit on the purge allowlist and would otherwise carry a previous chain's reorg history across a reroll (seen 2026-08-25); retention caps | "a telemetry file must not be able to wedge the node" |

---

## 2. Exec node (`execnode/state.py`, `execnode/execnode.py`, shielded pools)

### 2.1 The consensus chain — four caches, one invalidator

`_touch()` (`state.py:369`) is called by every root-affecting mutator and by `_restore`. It clears
`_root_cache` and bumps `_mut_gen`. Everything below hangs off that.

| name | file | memoizes | key | eviction |
|---|---|---|---|---|
| `_mut_gen` | `state.py:366` | state version | — | monotonic |
| `_kv_store` / `_rec_store` | `state.py:364, 532-560` | the two depth-256 half-trees, diff-applied (`apply_projection`, O(changed·depth)) | — | never rebuilt after the cold build |
| `_stores_gen` | `state.py:550` | "the projections are already applied for this generation" | `_mut_gen` | generation. **Added 2026-08-24 (5016d732)**: without it every `_record_proof` re-derived `kv_projection` (one alghash2 `slot_key` per storage slot) on the event loop |
| `_root_cache` | `state.py:363, 696` | `state_root()` hex — the root settled on L1 | — | `_touch` |

`clone()` (`state.py:473`) inherits **none** of these — a provisional clone pays a cold `state_root()`,
which is why `h_root` refuses to compute one (`execnode.py` "the 20 s-freeze lesson").

### 2.2 Proof serving

| name | file | memoizes | key | eviction |
|---|---|---|---|---|
| `_root_ring` | `state.py:335, 598-625` | root hex → `(kv half-root, records projection)` for the last 128 distinct roots | root | FIFO 128; populated by `note_root_point()` per applied block within 240 of finality |
| `_ring_stores` | `state.py:650` | root hex → rebuilt records `SparseStore` (4.5 s each) | root | pruned to the ring's keys |
| boot seed (`_seed_root_ring`) | `execnode.py` | L1's justified root inserted from its stash at startup (copy of the live KV tree diff-applied, checked against the stash root) | — | the ring is in-memory; a restart otherwise loses the settled root for one settle interval |
| `_l1_settled_hint` | `execnode.py` | `/get_settled` for the proof handlers | ns | TTL 6 s |

### 2.3 Provisional view and tail bookkeeping

| name | file | memoizes | key | eviction |
|---|---|---|---|---|
| `_prov_key` | `execnode.py:2657` | "the provisional build is current" | `(finalized, tip, tip_hash, Σ _mut_gen)` | key mismatch |
| `prov_states` / `_prov_last` / `_prov_since_full` | `execnode.py:2662` | finalized states + speculatively applied tail, **extended** not rebuilt | `(height, hash)` of the last tail block | forced full rebuild every `PROV_FULL_EVERY`=50 polls, audited root-for-root against the rebuild; reorg (anchor hash mismatch) |
| `_prov_div_epoch` | `execnode.py:2666` | the accrual fence | — | any dividend accrual retires the tail (8/8 drifts were preceded by accruals) |
| `_settled_snapshots`, `_settled_history` (6), on-disk stash | `execnode.py:883-995` | pre-serialized state at our last accepted settles — the prover's pre-state | `(ns, cursor)` | newest 6 per ns |
| rewind checkpoints | `execnode.py:197-241` | full state per ladder rung | `(ns, cursor)` | fine 500/2000, coarse 10000/100000 |
| `beacons` | `state.py:856` | epoch → RANDAO beacon (the `BEACON` opcode) | epoch | retention 4000 epochs |
| `block_hashes` | `state.py:925` | height → L1 hash (`BLOCKHASH` opcode) | height | ring 20000 |
| `attested` | `state.py:334` | our settle cursor → root | cursor | last 64 |
| `boundary_roots` | `state.py:337` | epoch-boundary root (hash-pool comparison point) | cursor | last 32 |
| `zk_addrs` | `state.py:355` | field digest → L1 address | digest | never (derivable, persisted, root-neutral) |
| `_settle_observed`, `_settle_conflict_logged` | `execnode.py:2957` | settles seen on L1 per `(ns, cursor, root)` | — | pruned < settled−2000 |
| `_anchor_is_self` | `execnode.py:3034` | tri-state | — | never |
| throttles: `_repair_last` 600 s, `_anchor_last` 1800 s, `_root_pool_last` 300 s, `_settle_skip_logged` 300 s, `_peer_cache` 600 s, `FOLD_SAVE_MIN_INTERVAL` 300 s | `execnode.py` | last-action timestamps | — | TTL |
| single-flight guards: `_settle_proving`, `_records_proving`, `_settle_publishing`, `_settle_pending`, `_DA_PREFETCHING`, `_inflight` (Semaphore 2) | `execnode.py:760-793, 3665` | not values — herd guards | — | cleared in `finally` / done-callbacks; "the guard's lifetime must match what it guards" |
| `DA` (`DaStore`) | `execnode.py:429` | commitment → blob/shards on disk | commitment | rolling window `DA_RETAIN`=24 (an unbounded one was 41 GB) |

### 2.4 Shielded pools

| name | file | memoizes | eviction |
|---|---|---|---|
| `_EMPTY` / `EMPTY_ROOT` | `shielded.py:53`, `shielded_field.py:26`, `shielded_state.py:91` | empty-subtree roots per depth | never (pure) |
| `_cached_root` | `shielded.py:158` | commitment-list Merkle root | invalidated on append |
| `anchor_list` / `anchors` | `shielded.py:159`, `shielded_field.py:69`, `shielded_state.py:227` | ring of roots a proof may target (`knows_root`) | last 128 (field pool hard-codes 128 instead of `ANCHOR_WINDOW`) |
| `_cmset` | `shielded_state.py:230` | commitment membership index | rebuilt from `trees`, never persisted |
| `FieldShieldedPool.root()`, `ShieldedStatePool.root()` | — | **deliberately not cached** (O(n) per call) | — |

---

## 3. STARK / native (`execnode/stark/`, `native/`)

| name | file | memoizes | key | eviction | note |
|---|---|---|---|---|---|
| `_FOLD_CACHE` | `stark/storage_tree.py:94` | `(depth, key, value)` → `(high-water level, digest)` singleton fold | the triple | `clear()` at 2¹⁷; **persisted** to `<state>.folds.json` | pure function → cannot change a root, only its cost (58.9 s cold vs 10.2 s warm settle prove). Not locked; KV and records halves prove in parallel threads — a lost update costs recompute, not correctness |
| `save_fold_cache` / `load_fold_cache` | `storage_tree.py:152/171` | the above across restarts | file fingerprint `(format, depth, WIDTH, CAPACITY, ROUNDS, blake2b(empty roots))` | fingerprint mismatch, malformed row, or one failed spot-recompute of 64 samples discards the **whole file** | "'pure function' protects against a STALE cache, not a WRONG file." `tests/test_fold_cache_persist.py` |
| `SparseStore._memo` | `storage_tree.py:264` | `(level, index)` → subtree digest | — | `set()` pops exactly the changed ancestor chain | per instance |
| `_E_CACHE` (`empty_roots`) | `storage_tree.py:40` | depth → empty-subtree digests | depth | never | pure |
| `_PER_LDE_CACHE` (32) / `_PER_LDE_SEEN` (256) | `stark/stark.py:181-183` | dense periodic column → coset LDE; admission on **second** use | `(N, T, blake2b(col))` | LRU | 97.6 % of verify was Horner-per-query on these (1267 s → 188 s). **Key omits `offset`** — correct only while every caller passes `OFF=F.GENERATOR` |
| `_PER_HINTED`, `_NATIVE_FALLBACKS` | `stark.py:193/389` | log-once sets | — | clear > 512 / never | diagnostics |
| `_NATIVE`, `_LIB` handles | `alghash2.py:78`, `air_ir.py:188`, `goldilocks_native.py:18`, `stark_native.py:17` | dlopen results, `False` sticky | — | never | guarded by `native_guard.is_stale`; see [native crate staleness] |
| `RC`, `IV`, `_MDS` | `alghash2.py:42-47` | consensus constants (BLAKE2b NUMS) | — | immutable | not a cache, but the Rust side mirrors them in `static mut` |
| `_Builder._intern` / `_cintern` | `air_ir.py:30-32` | SSA CSE / constant pool | `(op,a,b)` / value | per builder | exact structural CSE |
| `goldilocks_native._LOCK`, `stark_native._LOCK` | — | serialize the **static Rust scratch buffer / global arena** | — | — | "NOTHING EVER ACQUIRED IT" was a live bug: two proves clobbered each other's retained columns |
| `static ARENA`, `static FRI` | `native/starkprove/src/lib.rs:325, 1574` | retained LDE columns + Merkle trees by positional id; the FRI result between calls | integer ids — **no generation tag** | `sp_reset` wipes | a stale id after reset aliases a different column; safety rests entirely on the Python `_LOCK` |
| `static mut RC/IV/MDS` (+`HASH_READY` in starkprove only) | `native/alghash2/src/lib.rs:19`, `starkprove:204` | hash constants handed in by `init()` | — | overwritten by `init` | alghash2 has no init check: pre-init hashing would give well-formed wrong digests |
| **absent**: Python `field.domain`/`ntt` twiddles, Rust `ntt` twiddles, `compose_setup` batch inversions | `field.py:76-119`, `starkprove:134, 598` | recomputed per call | — | — | pure perf headroom, no staleness risk |

---

## 4. Browser (`static/*.js`)

The JS side is dominated by **inverted caches** — memos whose *absence* was the bug, because each
prevents a duplicate fee-bearing transaction.

### 4.1 Anti-duplicate-tx gates (stale = wrong on-chain action if missing)

| name | file | guards | released by | incident |
|---|---|---|---|---|
| `_divClaimGate` | `interface.js` (claim loop) | one `dividend_withdraw` per nonce per landing window | tip ≥ `latest + 2·TX_INCLUSION_DELAY` | 19 duplicate claims of one nonce in the mempool |
| `DIV_CLAIMS_PER_TICK`=10 | same | burst of claims per refresh tick | — | 53 pending nonces on one address, 2026-08-24 |
| `_unbondClaimTarget` | `interface.js:764` | one unbond withdraw | tip passes target−8 | ~20 duplicates (2026-08-19) |
| `_divInFlight` | `interface.js:812` | double collect click | amount changes or 10 min | — |
| `_renewSubmitted` | `interface.js:1662` | presence-lease renew | epoch advance / tip > target | 552 stuck registers from 37 senders |
| `_randaoDead`, `_dutyDone` | `interface.js:4092/4098` | deterministic reveal rejections, epoch duty | pruned on epoch | "same inputs give the same answer; never send one twice" |
| `_autoVoted` | `interface.js:6780` | treasury vote (fee-bearing) | session only — a reload re-arms; node `voted` flag is ground truth | — |
| `_autoTried` | `nadodapp.js:1359` | one settle attempt per key per 45 s | retry window | — |
| `LS_CLICK` pending registry | `nadodapp.js:1192` | every game's click-time pending tx | `PEND_TTL_MS`, or tip-age when `nv` opted in | early release double-posts a score |
| `_settleBlocked` phase scope | `nadodapp.js:1346` | a second settle of the same phase | per call | too-broad scope starved settles 5 min |
| `_anchDrive` | `provable.js:36` | daily anchor submit | 30 s + `busy("anchor")` | "re-submits the anchor every retry window forever, each burning a fee" |
| `nado_bet_pending_mktid`, `nado_bet_pending_bank` | `bet.js:337-362` | second market for one fixture / double bankroll | 15 min TTL; bank record removed **before** the post | "a record kept across the next 4 s tick would bank the market twice" |

### 4.2 Randomness and verdict caches

| name | file | rule |
|---|---|---|
| `_bh` / `_bhFinal` | `nadodapp.js:893-925` | finalized hashes frozen forever; provisional ones re-checked every fast fetch — a frozen provisional hash could change hidden info after a reorg |
| `horizonVerdict` | `nadodapp.js:940` | **the miss is never cached** — "remembering that as 'pruned forever' is exactly how a settleable stake gets refunded" |
| `_claimCache` | `provable.js:148` | keyed on claim **content**, not entry id — ids are re-issued to different claims after a rollback |
| `CHAIN_ID`, `FINALITY_DEPTH` | `interface.js:34, 7821` | re-adopted from `/status` before every automated signing; stale = tx the node rejects |

### 4.3 Chain-scoped and redirect-surviving localStorage

| name | file | note |
|---|---|---|
| `lsChainGet/Set` | `interface.js:5867` | `{chain, v}` envelope dropped when `CHAIN_ID` changes — a reroll must not replay old pendings; settings deliberately unscoped |
| `nado_pets_mintq` / `hatchall` / `collectall`, `nado_<slug>_dailywait` | `pets.js:768-854`, `provable.js:83` | intentionally **replay** a fee-bearing action after a wallet redirect |
| `nado.shieldf.<addr>`, `nado_<game>_secret_<gid>`, messaging ratchet state | `interface.js:6913`, `hexholm.js:34`, `messaging.js:185` | data-loss not staleness risk — the only copy of spendable notes / commit secrets / ratchet keys; correctly never evicted |
| `autogame_words` (80), `battleship` shot sets (never shrink), `chess_pos` | game clients | replay / anti-flash memories |

### 4.4 Pure perf

`_twCache` (NTT twiddles, `stark/field.js:55`), `_perCache` (`joinsplit2.js:101`), `_perLdeCache`
(WeakMap by periodic array, `stark/stark.js:11`), `_geneCache` (`pets.js:598`, immutable gene strings),
`_wealthCache` 15 s, `_mineData` 60 s, `_aliasCache`/`_abAlias`, `_exTipSeen`, `_exPoolHtml`,
`chipOffCache`, wasm init singletons.

### 4.5 Explicit anti-caches

Every chain read uses `{ cache: "no-store" }` (57 in `interface.js`, 8 in `nadodapp.js`): every input
to a proof, a signature or a landing-block calculation bypasses the HTTP cache by construction. The one
`force-cache` fetch is the favicon SVG. Build fingerprints (`?v=<hash>`, `versioner.py`) bust module
caches on deploy.

---

## 5. Asymmetries found by the inventory — resolved 2026-08-25 (`a0dbdd8e`)

- `_recent_settled_cache` got the herd lock its sibling had.
- `_PER_LDE_CACHE`'s key now binds the coset `offset`.
- Rust arena: `sp_reset` returns a generation and `sp_gen()` reads it; `stark_native._guard()` refuses
  arena calls after another thread's reset (a stale id would otherwise alias another prove's column).
- `native/alghash2` has a `READY` flag + `ready()` export; the loader rejects a library whose `init` did
  not land.
- `_genesis_id_cache` reaps expired peers; segment read handles are capped at 64 (`_READ_FILES_MAX`).
- One `genesis_hash_cached()` instead of two module memos; the memserver comment matches its `pool_gen` key.
- `_excluded_logged` and `self_update._hints` were already bounded — the first inventory was wrong there.
- Found along the way: `wasm/goldilocks` had been stale since 2026-08-21 (manifest edit after the build;
  cargo uplifts the `.so` by hard-link so its mtime never moved) — fixed with a full `cargo clean`.

Still open: old wallets (pre-`?root=`) request one dividend proof per nonce per tick; the exec side now
answers each in ~1 ms against the settled root, so they claim and drain.

[native crate staleness] |
| `RC`, `IV`, `_MDS` | `alghash2.py:42-47` | consensus constants (BLAKE2b NUMS) | — | immutable | not a cache, but the Rust side mirrors them in `static mut` |
| `_Builder._intern` / `_cintern` | `air_ir.py:30-32` | SSA CSE / constant pool | `(op,a,b)` / value | per builder | exact structural CSE |
| `goldilocks_native._LOCK`, `stark_native._LOCK` | — | serialize the **static Rust scratch buffer / global arena** | — | — | "NOTHING EVER ACQUIRED IT" was a live bug: two proves clobbered each other's retained columns |
| `static ARENA`, `static FRI` | `native/starkprove/src/lib.rs:325, 1574` | retained LDE columns + Merkle trees by positional id; the FRI result between calls | integer ids — **no generation tag** | `sp_reset` wipes | a stale id after reset aliases a different column; safety rests entirely on the Python `_LOCK` |
| `static mut RC/IV/MDS` (+`HASH_READY` in starkprove only) | `native/alghash2/src/lib.rs:19`, `starkprove:204` | hash constants handed in by `init()` | — | overwritten by `init` | alghash2 has no init check: pre-init hashing would give well-formed wrong digests |
| **absent**: Python `field.domain`/`ntt` twiddles, Rust `ntt` twiddles, `compose_setup` batch inversions | `field.py:76-119`, `starkprove:134, 598` | recomputed per call | — | — | pure perf headroom, no staleness risk |

---

## 4. Browser (`static/*.js`)

The JS side is dominated by **inverted caches** — memos whose *absence* was the bug, because each
prevents a duplicate fee-bearing transaction.

### 4.1 Anti-duplicate-tx gates (stale = wrong on-chain action if missing)

| name | file | guards | released by | incident |
|---|---|---|---|---|
| `_divClaimGate` | `interface.js` (claim loop) | one `dividend_withdraw` per nonce per landing window | tip ≥ `latest + 2·TX_INCLUSION_DELAY` | 19 duplicate claims of one nonce in the mempool |
| `DIV_CLAIMS_PER_TICK`=10 | same | burst of claims per refresh tick | — | 53 pending nonces on one address, 2026-08-24 |
| `_unbondClaimTarget` | `interface.js:764` | one unbond withdraw | tip passes target−8 | ~20 duplicates (2026-08-19) |
| `_divInFlight` | `interface.js:812` | double collect click | amount changes or 10 min | — |
| `_renewSubmitted` | `interface.js:1662` | presence-lease renew | epoch advance / tip > target | 552 stuck registers from 37 senders |
| `_randaoDead`, `_dutyDone` | `interface.js:4092/4098` | deterministic reveal rejections, epoch duty | pruned on epoch | "same inputs give the same answer; never send one twice" |
| `_autoVoted` | `interface.js:6780` | treasury vote (fee-bearing) | session only — a reload re-arms; node `voted` flag is ground truth | — |
| `_autoTried` | `nadodapp.js:1359` | one settle attempt per key per 45 s | retry window | — |
| `LS_CLICK` pending registry | `nadodapp.js:1192` | every game's click-time pending tx | `PEND_TTL_MS`, or tip-age when `nv` opted in | early release double-posts a score |
| `_settleBlocked` phase scope | `nadodapp.js:1346` | a second settle of the same phase | per call | too-broad scope starved settles 5 min |
| `_anchDrive` | `provable.js:36` | daily anchor submit | 30 s + `busy("anchor")` | "re-submits the anchor every retry window forever, each burning a fee" |
| `nado_bet_pending_mktid`, `nado_bet_pending_bank` | `bet.js:337-362` | second market for one fixture / double bankroll | 15 min TTL; bank record removed **before** the post | "a record kept across the next 4 s tick would bank the market twice" |

### 4.2 Randomness and verdict caches

| name | file | rule |
|---|---|---|
| `_bh` / `_bhFinal` | `nadodapp.js:893-925` | finalized hashes frozen forever; provisional ones re-checked every fast fetch — a frozen provisional hash could change hidden info after a reorg |
| `horizonVerdict` | `nadodapp.js:940` | **the miss is never cached** — "remembering that as 'pruned forever' is exactly how a settleable stake gets refunded" |
| `_claimCache` | `provable.js:148` | keyed on claim **content**, not entry id — ids are re-issued to different claims after a rollback |
| `CHAIN_ID`, `FINALITY_DEPTH` | `interface.js:34, 7821` | re-adopted from `/status` before every automated signing; stale = tx the node rejects |

### 4.3 Chain-scoped and redirect-surviving localStorage

| name | file | note |
|---|---|---|
| `lsChainGet/Set` | `interface.js:5867` | `{chain, v}` envelope dropped when `CHAIN_ID` changes — a reroll must not replay old pendings; settings deliberately unscoped |
| `nado_pets_mintq` / `hatchall` / `collectall`, `nado_<slug>_dailywait` | `pets.js:768-854`, `provable.js:83` | intentionally **replay** a fee-bearing action after a wallet redirect |
| `nado.shieldf.<addr>`, `nado_<game>_secret_<gid>`, messaging ratchet state | `interface.js:6913`, `hexholm.js:34`, `messaging.js:185` | data-loss not staleness risk — the only copy of spendable notes / commit secrets / ratchet keys; correctly never evicted |
| `autogame_words` (80), `battleship` shot sets (never shrink), `chess_pos` | game clients | replay / anti-flash memories |

### 4.4 Pure perf

`_twCache` (NTT twiddles, `stark/field.js:55`), `_perCache` (`joinsplit2.js:101`), `_perLdeCache`
(WeakMap by periodic array, `stark/stark.js:11`), `_geneCache` (`pets.js:598`, immutable gene strings),
`_wealthCache` 15 s, `_mineData` 60 s, `_aliasCache`/`_abAlias`, `_exTipSeen`, `_exPoolHtml`,
`chipOffCache`, wasm init singletons.

### 4.5 Explicit anti-caches

Every chain read uses `{ cache: "no-store" }` (57 in `interface.js`, 8 in `nadodapp.js`): every input
to a proof, a signature or a landing-block calculation bypasses the HTTP cache by construction. The one
`force-cache` fetch is the favicon SVG. Build fingerprints (`?v=<hash>`, `versioner.py`) bust module
caches on deploy.

---

## 5. Known asymmetries and follow-ups

- `_recent_settled_cache` has no herd lock while its sibling `_latest_settled_cache` does.
- `_PER_LDE_CACHE` key omits `offset`; a future caller with a different coset shift gets another
  coset's LDE silently.
- Rust arena ids carry no generation; a generation counter would turn aliasing into `-1`.
- `native/alghash2` `static mut` constants have no `HASH_READY`-style init check.
- Unbounded key growth: `core_loop._genesis_id_cache`, `_excluded_logged`, `self_update._hints`,
  `segment_store.read_files` fd count.
- `memserver.py:324` comment describes the old list-object key; the code keys on `pool_gen`.
- `_GENESIS_HASH_CACHE` and `_OUR_GENESIS_CACHE` memoize the same value in two modules.
- Old wallets (pre-`?root=`) still request one proof per nonce per tick; the exec side now answers
  each in ~1 ms against the settled root, so they claim and drain.

[native crate staleness]: ./updates-and-rerolls.md
