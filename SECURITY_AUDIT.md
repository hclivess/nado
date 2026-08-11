# NADO pre-release security audit

**Started:** 2026-08-11 · **Driver:** self-paced audit loop · **Scope:** whole tree (~105K LOC Python + 4 Rust crates)

Severity: **CRITICAL** (funds/consensus/soundness break, exploitable) · **HIGH** (exploitable under conditions) ·
**MEDIUM** (defense-in-depth / hard-to-hit) · **LOW** (hygiene). Each finding: `file:line`, scenario, fix.

**Status: COMPLETE + FIXES APPLIED** — all 10 domains audited (2 waves × 5 parallel auditors). Items
marked *CONFIRMED* were re-verified by hand against the code.

### Correction (post-audit): `SETTLE_PROOF_TRUSTLESS` is `True`, not `False`
The proof-soundness auditor read `settlement_ops.py:60` (a *reader*, near a stale "FALSE on alphanet-10"
comment) as the definition. The real definition is `protocol.py:663 = True`. **Trustless settlement is
ALREADY live**, so finding #2 (query-count forgery) was **live-exploitable, not latent** — the applied
fix closes an actively-exploitable root-forgery.

### Fixes applied this session (node-side — effective on push/restart)
1. ✅ CRITICAL pubkey-once revert wedge — re-applied `942f41f1` (journal + pop). `test_pubkey_revert.py` PASS.
2. ✅ CRITICAL settlement query-count forgery — `verify_transition` pins None→`NUM_QUERIES` for both counts.
3. ✅ HIGH unbounded `data` — capped at `BLOB_MAX_BYTES` for non-reserved (ordinary) recipients.
4. ✅ HIGH 192 MiB body-cap DoS — per-path body-cap middleware + raw-length guards on `/message`,`/msg_key`.
5. ✅ HIGH peer rate-limit bypass — finite peer bucket (300/min) + strict 6/min for large submits (all IPs).
6. ✅ MEDIUM native ML-DSA self-test — added negative vectors (flip/wrong-msg/wrong-key/garbage/truncated).
   Native backend re-verified: still passes interop, correctly rejects the negatives.
7. ✅ MEDIUM assert-stripping — `protocol.py` hard-fails under `python -O`/PYTHONOPTIMIZE.
8. ✅ MEDIUM `/transaction_pool` + `/transaction_ids` event-loop DoS — offloaded to `to_thread`, rate-limited.
9. ✅ MEDIUM `da_proxy` — added 60/min rate limit.
10. ✅ MEDIUM snapshot `chunk_count` sync-DoS — require every chunk rows>0 (forces cc ≤ ec ≤ cap).
11. ✅ MEDIUM `msgkey` spam — added `("msgkey", sender)` to `reserved_uniqueness_key`. Uniqueness test PASS.
12. ✅ LOW asset supply-cap off-by-one — mint now strict `>=` (keeps every balance < 2^62).

### Fixes applied — CONTRACT source (require a redeploy to take effect; deployed bytecode is unchanged)
13. ✅ HIGH game unbounded-id lock — `require id < 2^32` in `_lib.open_table` (7 banked games) + `reserve`.
14. ✅ MEDIUM mines `reap` horizon 1200→18000 (matches siblings; residual gh-vs-ge deep fix flagged).
    **→ ACTION: redeploy the affected game contracts (`deploy.py --upgrade`) — see closing notes.**

### Deferred (need coordination / deeper design — NOT applied, flagged)
- MEDIUM grindable epoch beacon → enforcing RANDAO can halt the chain if reveals aren't produced; needs
  coordinated activation, not a blind flip. HIGH-3 unauth settle-verify-at-admission is now partially
  mitigated by the 6/min large-submit limit; the full off-hot-path verify queue is a larger refactor.
  LOW items: `save_block` hashed-field skip, treasury per-block cap, DA-carried `proven` marker,
  pets challenge-EX, per-bet/PvP id guards on the remaining board games — see per-domain findings.

## Executive summary — prioritized fix list

**Must fix before release (block the release on these):**

1. **CRITICAL — Pubkey-once revert wedge** (determinism). The h15076 fleet-wedge fix (`942f41f1`) was
   reverted at the alphanet-14 reroll; a reorg on a snapshot-synced node deletes an established pubkey a
   full node keeps → divergent accounts root → permanent split-brain. *CONFIRMED.* Fix = re-apply
   `942f41f1` (one commit, no schema change).
2. **HIGH→CRITICAL — Settlement query-count forgery** (soundness). `verify_transition` reads the FRI
   query count (= the soundness) from the prover's bundle; a bonded settler binds an arbitrary settled
   root at a single spot-check. *CONFIRMED.* Neutered ONLY by `SETTLE_PROOF_TRUSTLESS=False` today —
   **so do NOT enable trustless settlement in this release until fixed.** Fix = pin `verify_transition`
   to `NUM_QUERIES` (strictly tightening; honest provers unaffected).
3. **HIGH — Game unbounded-id fund lock.** `SLOT` opcode doesn't range-check the key; any non-participant
   permanently locks a banker's bankroll (7 banked games via `open_table` + `reserve`) for ~1 unit+fee.
   *CONFIRMED.* Fix = `require id < 2^32` on every id-keyed creation method (mechanical, the pattern 6
   contracts already use).
4. **HIGH — 192 MiB body cap DoS cluster.** The global cap (raised for inline settle proofs) lets an
   unauthenticated request OOM/stall a node (`/message`, `/msg_key`, `/transaction_pool`, peer-exempt
   submit, settle-verify-at-admission). Fix = scope the large cap to `/submit_transaction`, enforce true
   per-endpoint pre-decode caps, move dumps + proof-verify off the HTTP/event-loop path.

**Should fix before release:**

5. **HIGH — Unbounded `data` on ordinary transfers evades DA blob pricing** at flat `MIN_TX_FEE`.
6. **MEDIUM — Native ML-DSA self-test has no negative vectors** (crypto + Rust auditors, same gap): a
   native verifier that over-accepts (or a broken build) ships silently → chain-wide forgery, no fork.
   Fix = add reject/KAT vectors to `_interop_ok`.
7. **MEDIUM — Consensus verification runs on bare `assert`** (stripped under `python -O`). Fix = `raise`.
8. **GOVERNANCE — Games deploy `upgradable=True`**; deployer key can drain any unlocked game. Recommend
   `lock`-ing every game before release, or deployer → multisig/governance.

**Post-release / hardening:** grindable epoch beacon (MEDIUM, enforce RANDAO), snapshot `chunk_count`
sync-DoS (MEDIUM), mines `reap` horizon (MEDIUM, +EV dodge), `da_proxy` rate limit, asset supply-cap
off-by-one, plus assorted LOW items (see per-domain findings).

**Came back CLEAN (verified, not just unexamined):** shielded pool & asset ledger (unbacked-mint,
nullifier, membership, conservation all closed); snapshot state-forgery / fresh-sync determinism; DA
commitment soundness; Rust memory-safety (no OOB / panic / bypass on untrusted input); the historically
dangerous consensus classes (rollback→root asymmetry, reward/weight forgery, FFG-finalize-a-fork,
double-spend, supply inflation).

**Cross-cutting theme:** the *inline settle-proof* design (192 MiB caps) is the root of finding 4's
entire DoS cluster and interacts with finding 2. The *native-backend self-test gap* (finding 6) is
load-bearing for signature soundness and worth closing regardless.

## Coverage tracker

| Domain | Key surface | Status |
|---|---|---|
| Crypto / signatures / auth | signatures.py, ops/address_ops, ops/multisig_ops, validate_origin | ✅ done |
| Consensus / block validation | ops/block_ops, ops/fork_resolution, ops/mining_ops, ops/reg_difficulty, ops/posw | ✅ done |
| zkVM / STARK proof soundness | execnode/stark/* (verify paths), vm_circuit, settlement_proofs | ✅ done |
| Settlement / state-root determinism | ops/settlement_ops, snapshot_ops, rollback.py, records_bind, exec_state_bind | ✅ done |
| Transaction / spending / economic | ops/transaction_ops, ops/account_ops, ops/reward_ops, ops/dividend_ops | ✅ done |
| Shielded pool & assets | execnode/shielded.py, execnode/state.py asset ops, joinsplit* | ✅ done — clean (1 LOW) |
| Game contracts money-code | execnode/games/* (fund locks, solvency, float) | ✅ done |
| Network / RPC / DoS | nado.py (67 endpoints), ops/gossip, ops/net_ops, memserver, ratelimit, forum/server.py | ✅ done |
| Native crates (Rust) | native/{alghash2,mldsa44,starkcompose,starkprove} — unsafe, panics, overflow | ✅ done |
| DA / snapshot / rollback transport | ops/da.py, ops/da_store, ops/snapshot_ops | ✅ done |

## Findings

### Game contracts money-code (wave 2)

- **HIGH — Unbounded game/table id → cross-entity storage aliasing → permanent permissionless fund
  lock.** ***Core mechanism CONFIRMED by direct code read.*** `zkvmasm.py:81-88`: `SLOT` opcode →
  `MOVI d, field<<32; ADD d, k` with NO range-check on key `k`; comment at :85 states the UNENFORCED
  assumption "Keys ... are frontend ints < 2^32". `runtimes.zkvm_statement` (`runtimes.py:57-77`) bounds
  args only to `[0, P≈2^64)`, and ABI is "non-consensus UX metadata" — so a hand-crafted tx passes
  `k ≥ 2^32`, and `slot(field, victim_id + m·2^32) = slot(field+m, victim_id)` aliases attacker writes
  onto a victim entity's higher fields. `_lib.open_table` (CONFIRMED) guards only `id > 0`, no upper
  bound: a non-participant opens table `id_A = id_V + m·2^32, value=1`, aliasing onto the victim table's
  `tz` (closed) field → `close_table` (requires `tz==0`) reverts → **banker bankroll+pot locked
  forever**. Theft mostly blocked by contiguous field layout (aliased guard-read hits an occupied field →
  revert), but the LOCK is clean, ~1 unit+fee, permanent. **Confirmed unguarded: the 7 banked games via
  `open_table` (coinflip/dice/roulette/slots/mines/blackjack/farkle) + `reserve` (asset vault, only
  `vid>0`, docstring claims the bound but never enforces it).** *Correction to agent: tictactoe DOES
  carry `4294967296` guards — the exact affected list among PvP board games needs per-contract
  confirmation; 6 contracts (battleship/holdem/bet/hamster/lend/pets) already enforce `id<2^32`, proving
  the guard is the intended pattern.* **Fix (uniform, mechanical):** add `require id < 2^32` to every
  creation/entity method that uses a user id as a slot key. (Exec-layer can't backstop — aliasing never
  over-pays contract balance.)
- **MEDIUM — mines `reap` horizon 1200 blocks (~2h) vs siblings' 18000 (~30h), and doesn't require
  `gh==0`.** `mines.py:410-417`. A player picks, reads public `bhash(gh)`; if losing, waits 1200 blocks
  and `reap`s to refund `gv` instead of `resolve`-ing the loss; if winning, `resolve`s. Strictly +EV free
  option defeating the 1% edge whenever a passive banker doesn't resolve within ~2h. **Fix:** gate the
  pending-resolve refund on `gh + 18000 < cursor` matching siblings.
- **LOW — reclaim/settle window overlap (~2000 blocks) lets a losing player dodge a negligent banker**
  (dice/roulette/blackjack/slots + PvP). Funds conserved (per-party refunds) — griefing not drain, and
  only if banker neglects `settle` ~30h. Tighten overlap toward true prune height.
- **LOW — pets challenge escrow self-locks if challenger releases/transfers their pet pre-accept** (`EX`
  set only at accept). Self-inflicted. **Fix:** stamp `EX` on `WA` at `challenge`.
- **LOW — battleship reveal-at-claim forfeit / PvP fixed-deadline griefing** (loser stalls to force
  refund-draw or reclaim from offline winner). Anti-cheat by design; online honest party always wins.
- **RELEASE/GOVERNANCE — games deploy `upgradable=True` (`state.py:1024`); deployer key can rewrite any
  unlocked game to drain all escrow up to holdings.** By-design for alphanet iteration, but a total SPOF
  for mainnet. **Recommend `lock`-ing (renouncing upgradability) on every game before release, or moving
  the deployer to governance/multisig.**
- **Verified PRESENT/SAFE:** BHASH-prune fund-lock fixes (2ec0923 horizon reclaim/reap correct in
  dice/roulette/coinflip/blackjack/farkle), privileged escape-hatch fixes (19dac94 holdem/hexholm
  permissionless per-seat refunds), banked solvency (tp/tc/tk accounting correct incl. the tp double-
  credit fix; cover reserved before bet), exec-layer backstop (payout > contract balance REVERTS — a
  solvency bug can brick a method but never mint/drain another contract; upgrade/lock/transfer/issue
  deployer-only), no float/wall-clock in payouts, field-wrap LATENT only (needs stake ≈2^55-62 vs supply
  ≈2^45; recommend explicit stake cap as DiD), parimutuel/markets (bet/hamster/lend/reserve conserve
  per-market, permissionless void/default timeouts, mark-settled-before-pay, randomness pinned to
  ungrindable future bhash).

### Native Rust crates (wave 2)

No remotely-triggerable panic, memory-safety violation, or signature/proof-acceptance bypass in the
crates as written. Field arithmetic verified correct (reduce128, addf, MDS overflow path).

- **MEDIUM — ML-DSA verify soundness delegated entirely to unaudited `ml-dsa 0.1.1`; adoption gate is
  positive-only.** `native/mldsa44/src/lib.rs:95-102` — since alphanet-14 this crate DEFINES signature
  acceptance for every node. `signatures.py:_interop_ok` only checks positive round-trips, so it
  structurally CANNOT catch the native backend OVER-ACCEPTING a signature the FIPS-204 reference rejects
  (non-canonical z/hint, out-of-range coeffs, malleability) — a chain-wide forgery/soundness hole that
  wouldn't show as a fork (all nodes run the same .so). **This is the same gap as the crypto-wave
  "native self-test lacks negative vectors" MEDIUM — merge them.** **Fix:** (a) run `ml-dsa` against
  ACVP KATs + reject-vector suite; (b) extend `_interop_ok` with negative vectors (flipped/truncated/
  non-canonical sigs must be rejected identically by both backends before adoption).
- **LOW — `sp_compose_ext` OOB read under misaligned `ext_pairs`** (`starkprove/src/lib.rs:1307-1326`);
  prover-side, `ext_pairs` aligned by construction so not attacker-reachable. **Fix:** assert the walk
  consumes exactly `n_logical` alphas.
- **LOW — Arena `Mutex` poisoning wedges the exec node until restart** (`starkprove` `.lock().unwrap()`
  everywhere); one transient prove panic → all subsequent proving dead. **Fix:** `unwrap_or_else(|e|
  e.into_inner())` + re-establish invariants.
- **LOW/info — verify-path batch marshalling trusts proof tuple arities** (`alghash2.py:452,467`); ctypes
  raises before the native call, caught by settle-path try/except → informational. **Fix:** validate
  `len==CAPACITY` up front.
- **Verified SAFE:** alghash2 arithmetic + verify path OOB-safe (fixed-width indexing, all shapes
  range-refused, no panic sites reachable), mldsa44 DoS-safe (null/len checks, error-code decodes never
  unwrap on attacker bytes, shim length-guards before `from_raw_parts`), prover parallelism deterministic
  (fixed subtree schedule, grind returns global-min nonce independent of thread count, no floats),
  compose/prove validate operands + guard n==0/t==0 before `%n`, native_guard staleness policy sound.

### DA / snapshot / rollback transport (wave 2)

No state-forgery or root-divergence on ingest (fresh-sync determinism classes all verified closed).

- **MEDIUM — Snapshot `chunk_count`/chunk array is outside the consensus hash → chosen source can OOM a
  bootstrapping node.** `snapshot_ops.py:316-342` `manifest_hash` covers only core fields (state_root +
  state_digest + entry_count DO pin payload bytes — no false-state injection), but NOT `chunk_count` or
  `chunks[]`. `fetch_snapshot` (`:510-565`) trusts them anyway (its "trusted because self-hash" comment
  at :552-558 is FALSE). A peer echoing the honest quorum `snapshot_hash` can be picked as source and
  serve a self-hash-valid manifest with `chunk_count≈4M` (rows all in chunk 0 so `sum(rows)==entry_count`
  passes); `chunks=[None]*cc` + `gather(*4M coroutines)` → OOM/hang on the syncing node. Reachable on
  lone-seed and normal quorum paths. **Fix:** bound `cc <= entry_count+1` and reject `rows==0` before
  allocation; better, fold a digest of the chunk list into `manifest_hash`. Fix the misleading comment.
- **LOW — `save_block` hash-consistency gate skipped when a hashed field is absent.** `block_ops.py:742-750`
  guards `block_content_hash==block_hash` behind `all(k in block for k in _hashed)`; a donor anchor/body
  omitting one `_hashed` field bypasses the content check and persists under its claimed hash. Impact
  limited (claimed hash quorum-bound) but a validity gate a peer can disable by dropping a field is a
  latent fork vector. **Fix:** missing `_hashed` key on a non-genesis block = refusal, not skip.
- **LOW/DiD — Reanchor anchor `state_root` not directly cross-checked against a block-committed root**
  (`core_loop.py:961-996`); safe today because the tail-replay state-root gate makes a tampered snapshot
  fail-SAFE (wedge not false-accept), but under a fully Sybil quorum reduces to weak subjectivity
  (documented, seed-anchored). Note in release threat model.
- **Verified SAFE:** snapshot state forgery (content pinned by state_root + state_digest re-derived
  locally, excluded rows stripped on import, finalized_height reconstructed not trusted), DA soundness
  (blake2b commitment binds index + full manifest into every leaf, reconstruct raises on inconsistent
  shards, DaStore round-trips through encode, unavailable→DEFER not reject/accept), pruning (in-block
  watermark GC with byte-exact node-local revert records, pruned bodies root-independent), sync DoS caps
  (read_capped, zstd-bomb defeated, MAX_SNAPSHOT_TOTAL), path traversal (int-coerced heights/cids, DaStore
  rejects `../`), rollback transport (MissingParent/FinalityViolation guards, atomic identity swap).

### Shielded pool & asset ledger (wave 2) — CLEAN

No CRITICAL/HIGH. All classic attacks verified closed by control-flow tracing (named fences C-1/2/3/3b,
H-1/H-4, M-10 all correctly wired):

- **LOW — Asset supply cap reachable exactly (off-by-one vs `< 2^62` RANGE window).** `state.py:1265` /
  `:223` mint uses `supply+amt > CAP → reject`, permitting total to hit exactly `ASSET_SUPPLY_CAP=1<<62`,
  while `asset_create` (`:1131`) is strict `<`. A `2^62` balance is outside the VM RANGE window
  (`zkvm.py:174`), so a `lt`/`gte` on it REVERTS — fails safe (liveness/DoS edge on a max-supply
  position, e.g. AMM can't process a cap-sized balance), no mint/conservation break. **Fix:** make mint
  reject at the boundary (`>=`) to match `asset_create`.
- **Verified CLOSED:** unbacked mint (coins enter only via L1 shield escrow driving finalized tx.amount,
  commit recomputed server-side, `public_value>0` fenced, conservation integer-exact via C-3 range gadget
  + MAX_EXIT bound, transparent path uses big-ints), double-spend/nullifier (nf bound to exact note,
  atomic check→add→append under `_mutate_lock`, append-only, `%P` collapses nf/nf+P), membership (root
  from authenticated anchor window never prover-supplied, dir∈{0,1}, depth/T pinned per H-1), supply
  conservation + all-or-nothing native+asset staging + exact refund on revert, contract-issued assets
  (issuer=CID unforgeable), revert/rollback symmetry (pool values excluded from root, replay-derived),
  L1 escrow boundary (settled-root proof + per-(addr,nonce) nullifier + cumulative escrow-release cap),
  claim-delivery (destination bound in sighash + FS transcript, front-run diverges proof).
- Privacy notes (documented intent, not bugs): transparent-pool nf is sender-linkable (field pool fixes
  via secret nsk); transparent phase is "sound but not yet private" by design.

### Network / RPC / DoS (wave 2)

Root theme: raising `MAX_TX_BODY`/pool caps to 192 MiB for inline settle proofs created an unauthenticated
DoS surface on endpoints whose real payloads are KB. Classic bugs (self-update supply-chain, traversal,
SSRF, injection, deserialization, eclipse, forum SQLi) all verified HARDENED.

- **HIGH — Global 192 MiB body cap → unauthenticated memory-amplification DoS.** `nado.py:1933`
  `web.Application(client_max_size=_MAX_INLINE_TX)` applies 192 MiB to EVERY route; `/message`,`/msg_key`
  decode the full body via `json.loads` BEFORE the real 16/32 KiB check. A 192 MiB JSON int-array
  expands to multi-GiB Python objects (net_ops.py:8-19 acknowledges the blow-up), 30/min per IP, on the
  bounded `to_thread` pool → RSS→OOM + starves block sync/status/admission. **Fix:** scope the large cap
  to `/submit_transaction` only; enforce true per-endpoint raw-byte cap pre-decode elsewhere.
- **HIGH — Linked peers bypass the submit rate limit entirely.** `nado.py:437`
  `if ip not in memserver.peers and _rate_limited(...)` → any peer IP skips the 30/min cap with NO limit;
  becoming a peer is cheap/permissionless (`/announce_peer` + status node). Combines with 192 MiB bodies
  and settle-verify. **Fix:** finite higher bucket for peers, gate exemption on body size.
- **HIGH — Unauth `/submit_transaction` forces full STARK settle-proof verify at admission.**
  `memserver.merge_transaction` → settle branch runs `verify_settlement_sparse` synchronously (~22–94 s,
  the fleet-freeze class). Gated by bonded-validator check (B_MIN=10 NADO) run BEFORE verify — the main
  thing keeping it non-critical — but bond is low/refundable, settle is fee-exempt, and distinct proofs
  miss the byte-keyed verdict memo, each forcing fresh multi-second verify holding a `to_thread` worker →
  stalls block production. **Fix:** admit on structural checks only; move proof verify to a dedicated
  `Semaphore(1-2)` queue off the HTTP/block-production pools; per-sender distinct-proof rate limit.
- **MEDIUM — `/transaction_pool` serializes the whole mempool ON the event loop, no rate limit.**
  `nado.py:169-176` `_dump_handler` runs `serialize(getter())` inline; pool budget ~196 MiB, so during
  settlement a single unauth GET JSON-encodes ~100+ MiB on the event loop → freezes all I/O/consensus/
  gossip, bandwidth-amplified. **Fix:** rate-limit + move to `to_thread` + paginate.
- **MEDIUM — `da_proxy` has no rate limit** (`nado.py:1871`), unlike siblings; holds 120 s streaming
  connections and pokes exec `da.reconstruct`. Bounded (loopback-only target, DA_RETAIN=24, exec
  MAX_INFLIGHT) but should get `_rate_limited` + lower timeout.
- **Verified HARDENED:** self-update (ff-only, pinned repo regex, refuses dirty/diverged, dark-403 when
  auto_update off, controls only WHEN not WHAT), no pickle/eval/exec/shell=True in net path, path
  traversal contained (normpath+prefix, DA/proof_da reject `../`), SSRF/eclipse (`check_ip` rejects
  loopback/RFC1918/mapped-v6/own-IP, subnet diversity cap, XFF ignored unless trusted_proxies),
  auth on /health,/log,/force_sync,/terminate, zstd-bomb defeated, forum fully parameterized SQL.

### State-root determinism / settlement (wave 1)

- **CRITICAL — Pubkey-once revert regression: the h15076 fleet-wedge bug was reintroduced at the
  alphanet-14 reroll.** ***CONFIRMED by direct code read + git history.*** `transaction_ops.py:2067`
  revert deletes the sender's established `public_key` when `transaction.get("public_key")` is truthy AND
  `kv_ops.tx_of_account(sender)` is empty. `tx_of_account` reads `_HISTORY_DBS` — EXCLUDED from snapshot
  and state root, rebuilt only by tail replay — so a snapshot-bootstrapped/pruned node sees no history
  below its checkpoint. Later txs re-carry the pubkey (settle/duty/heartbeat/register all include it),
  and the apply side establishes it only on first-carry (`:2098-2102`), so reverting a later
  key-carrying tx deletes a pubkey a full-history node KEEPS → divergent `accounts` roots (accounts is in
  the root) from identical block sequence → FATAL state-root gate → split-brain / permanent wedge. The
  fix (`942f41f1`, journal the establishment in node-local `pubkey_revert`, no history read) was reverted
  at `492bb2e1` (alphanet-14); `pubkey_revert_put`/`pop` now have ZERO call sites (dead code, both DBs
  still registered). The in-code comment at :2060-2066 claims the guard is the fix but only reasons about
  pubkey-LESS reverts — it misses the pubkey-carrying later-tx case, which is precisely the wedge. Commit
  942f41f1's own message describes the exact live scenario (alphanet-13, 18h outage). **Fix:** re-apply
  `942f41f1` — apply calls `pubkey_revert_put(txid)` when it sets the field; revert replaces the
  `tx_of_account` heuristic with `pubkey_revert_pop(txid)`. No schema change (DBs already present).
  **NOT auto-applied — consensus-path; pushing restarts prod during release. Awaiting go-ahead.**
- **LOW — DA-carried validity proofs never record the on-chain `proven` marker.** `account_ops.py:184-190`
  `proven = "proof" in data`, but DA-carried settle's `data` holds only `proof_da`, so
  `settlement_proof_put` never fires → trustless path is effectively dead even with
  `SETTLE_PROOF_TRUSTLESS=True`; every root still settles by bonded quorum. Deterministic, fails SAFE
  (quorum always correct) — functional gap, not a fork/soundness bug. Decision before release. *(Note:
  interacts with the STARK query-count finding — the trustless path being dead is currently what keeps
  that HIGH rather than CRITICAL.)*
- **LOW — `deep` settle depth-gate is node-local weak subjectivity** (`_known_tip_height`); documented
  tradeoff (doc/settle-proof-transport.md option 1). Conscious release decision.
- **Verified SOUND:** codec byte-stability (pack does NOT sort_keys; `_normalize` fixes dict order; gen-8
  sort_keys regression stays reverted), rollback inverse for execsum retention-del + div-carry (dc chain
  inside the summary = exact inverse), canonical-zero meta rows (`meta_del` at 0 avoids phantom rows),
  root exclusions (execsum/tvprev/finalized_height/pruned_below/block-by-num, read_state drops all-default
  rows + single MVCC snapshot), ordering (all root-affecting projections use `sorted(...)`, no
  insertion-order dep), settlement soundness (binds authenticated summaries not bodies, re-derives cid_io,
  verdict memo on bytes), NO float/RNG/wall-clock in any root path (integer-only balances/emission;
  `block_ts=chain_clock(height)` pure fn; `random` only for node-local ids).

### Consensus / block validation / rollback (wave 1)

- **MEDIUM (→HIGH the longer RANDAO stays off) — Epoch beacon grindable by the prior epoch's anchor
  producer.** `block_ops.py:518-553` `epoch_beacon`; `RANDAO_ENFORCED=False` (protocol.py:959) so reveals
  are optional/unpenalized. In steady state (no reveals), `beacon(E)` is a pure function of the anchor
  block hash, which the anchor producer fully controls (pad with self-txs, grind variants). Each variant
  → different producer schedule + duty committee for all 60 slots of epoch E; the anchor finalizes before
  E opens so a landed grind sticks. Bias compounds (winning future anchors is itself biased). No reorg/
  theft/fleet-disagreement (beacon stays deterministic), capping at MEDIUM. **Fix:** enforce ≥1 reveal per
  epoch for E≥2 (fail-closed), or enforce RANDAO, or fold an unpredictable-at-anchor-time input.
- **LOW — `rollback_one_block` restore of retention-pruned exec summary not byte-exact** (the h4260
  shape). `rollback.py:73-76` restores only `inert`+`calls`, dropping `rd`/`rec`/`dc` (records/derivable/
  div_carry default None) that incorporate journaled (`core_loop.py:1944`). NOT exploitable today —
  `execsum:` rows excluded from L1 root (`snapshot_ops.py:148`) and restored height sits ~16 epochs below
  any settle span. But guarantee is incidental. **Fix:** reconstruct all three from `_doc` so the inverse
  is exact regardless of future root-membership changes.
- **LOW — Nothing-at-stake equivocation costless for UNSIGNED blocks.** `block_ops.py:1065-1079` winner
  sig optional; `verify_equivocation_proof` needs two sigs. A producer who never signs authors multiple
  valid blocks per slot with zero slashing exposure. No weight advantage (fork weight content-independent)
  and finality floor bounds reorg, so not a reorg primitive — but enables costless withholding/grinding
  (feeds the beacon grind). **Fix (pre-mainnet decision):** require the winner sig for bonded-lane blocks
  so equivocation is always provable.
- **Verified SAFE:** reward/mint (equality-enforced, no overflow), fork-weight forgery (recomputed +
  equality), producer spoofing (winner re-derived, parent==tip enforced), deep reorg / FFG-finalize-fork
  (rollback refuses to cross finalized_height; `ffg_final < depth_final` always), tx replay/target binding
  (fail-closed for remote blocks), slash/equivocation proofs (signature-bound, deduped, chain-bound
  against cross-gen false-slash), reg-difficulty integer math (division-safe), block timestamp (outside
  hash, non-consensus).

### zkVM / STARK proof soundness (wave 1)

- **HIGH → CRITICAL when `SETTLE_PROOF_TRUSTLESS` flips on — Settled-root forgery: transition binding
  reads its FRI query count from the prover's bundle.** ***CONFIRMED by direct code read.***
  `execnode/stark/state_transition.py:185-186`:
  `nqi = num_queries if num_queries is not None else tr["num_queries"]` (same for `nqo`/`outer_queries`).
  The query count *is* the soundness, yet it defaults to the prover-supplied transition object when the
  caller passes `None`. Two consensus callers do:
  - KV half: `settlement_sparse.py:182-183` passes `num_queries=nq` but **not** `outer_queries` → `nqo`
    prover-controlled.
  - Records half: `transaction_ops.py:1414-1416` → `records_bind.bind_and_verify_records` (defaults
    `None,None`) → `verify_records_transition` → `verify_transition` → **both** counts prover-controlled.
  A malicious bonded settler sets `tr["outer_queries"]=1` (records: also `num_queries=1`); `verify_fold`
  only rejects `<1`, so the outer STARK proving the whole pre_root→post_root advance is checked at ONE
  spot-check (~couple bits). A valid-AIR/invalid-witness outer trace passes with non-negligible, re-rollable
  probability → binds an ARBITRARY settled root (overwrite storage, drain escrow) while every other settle
  check still passes (they bind the statement, not the proof strength). Not yet live fund theft
  (`SETTLE_PROOF_TRUSTLESS=False`, settlement_ops.py:60) — but the validation code runs today and this is
  the exact path that flag enables. **Fix (robust, safe, strictly tightening — honest provers already
  build at NUM_QUERIES per records_transition.py:84-85):** make `verify_transition` default
  `None → stark.NUM_QUERIES` for BOTH `nqi` and `nqo`, never `tr[...]`, matching every sibling verifier
  (`settlement_sparse.py:455`, `fri_verify.verify_fold`, `recursive_verify.RV.verify`). **NOT auto-applied
  — consensus-path file; pushing restarts prod during the release window. Awaiting go-ahead.**
- **LOW/DiD — `verify_transition` branches on `if "bundle" in tr`** (`state_transition.py:187`), an
  attacker-chosen key selecting the O(1) path; same hazard already flagged at `recursive_verify.py:285`.
  Select the branch from verifier-side policy, not the proof.
- **Verified SOUND:** Fiat-Shamir (challenges/indices/grind re-derived from public part only, two-phase
  transcript replayed in AIR order, challenge-field pinned, base-field backend refused), unconstrained
  witness (one-hot selectors, load-op set from `_LOAD_OPS`, inverse/range witnesses constrained, LogUp
  buses pinned to 0 both ends incl. every GF(p²) limb), proof-to-data binding (`cid_io` re-derived from
  authenticated io+calls never trusted, pre-state pinned to `sparse_pre_root`, verdict memo keys on proof
  BYTES), query soundness (~156 bits, blowup pinned=2, `len(openings)==num_queries`, coset separation
  asserted), recursion symmetry (RV rebuilds both statements, cross-checks fold covers segments' FRI
  roots), error paths (except→False, calls=0 not a wildcard).

### Crypto / signatures / origin-auth (wave 1)

- **MEDIUM — Native ML-DSA backend adopted with NO negative-signature test.** `signatures.py:123-143`
  `_interop_ok()` only checks positive direction (native-sign→pure-verify, pure-sign→native-verify,
  keygen match). It never checks the candidate REJECTS a bad sig. A native module whose `verify_internal`
  returns True unconditionally (or a build regression dropping a bounds check) passes all four asserts
  and is adopted → `verify()` returns True for EVERY signature = total origin forgery on that validator.
  Supply-chain/integrity gap (module is local `nado_pq_native`), but exactly the failure the self-test
  exists to catch. **Fix:** add negative vectors that MUST return False — byte-flipped sig, wrong message,
  wrong pubkey, random/truncated sig.
- **MEDIUM (latent) — Entire consensus signature/txid verification runs on bare `assert`.**
  `transaction_ops.py:885/1650/1905/1910`, `multisig_ops.py:86-111`. Under `python -O` / `PYTHONOPTIMIZE=1`
  every assert is stripped → `validate_origin`/`verify_multisig_origin` fall through to `return True`,
  `validate_transaction` accepts unsigned, malleable txs = universal forgery. Prod runs plain `python`
  (not triggered today), and `protocol.py:982` already uses `raise` for this exact reason on ONE
  invariant — but the whole signature spine is on asserts. **Fix:** convert to explicit
  `if not ...: raise`, or hard-fail at startup when `__debug__` is False.
- **LOW/hardening — Sender binds only 21 bytes (168 bits) of the pubkey** (`address_ops.py:84`).
  2^168 second-preimage / 2^84 birthday — infeasible, not exploitable. Flag only: becomes binding if
  `ADDRESS_BODY` is ever reduced. No action.
- **Verified SAFE:** pubkey-once (immutable once set, can't pre-seed a victim, re-bound not trusted on
  later txs), multisig (canonical sorted-unique descriptor, distinct-member enforcement, threshold,
  chain_id-committed → no cross-account replay), replay/malleability/cross-generation (`chain_id`
  committed + asserted, `validate_txid` rebinds in both mempool and block, mined-txid rejected),
  canonical encoding (sort_keys+ensure_ascii, floats/surrogates rejected, no two-body collision),
  verify() fail-closed (try/except→False, seed pinned to 32 bytes), reserved-as-sender blocked.

### Transaction / spending / economic (wave 1)

- **HIGH — Unbounded `data` on ordinary transfers evades DA blob pricing.** `ops/transaction_ops.py`
  data gate (~860-871), blob cap only at ~1060; `MAX_TX_BODY` now 192 MiB (raised for inline settle
  proofs). Size-proportional base fee was removed as non-deterministic and never replaced with a
  deterministic cap. `BLOB_MAX_BYTES`/`MAX_BLOB_BYTES_PER_BLOCK` apply ONLY to `recipient=="blob"`, so a
  normal transfer can carry ~192 MiB of `data` for a flat `MIN_TX_FEE` (1000 raw). Every node stores and
  gossips it forever; repeatable per nonce, effectively free. **Fix:** deterministic canonical-bytes cap
  (and/or per-byte fee) on `data` for EVERY recipient — reuse `blob_payload_size()`/`BLOB_MAX_BYTES` in
  the top-level gate. *Spot-check pending before fix.*
- **MEDIUM — Fee-exempt `msgkey` spam.** `msgkey` branch (~1036-1047) is fee==0 and, unlike `register`,
  has NO per-epoch/per-block uniqueness key (`reserved_uniqueness_key` omits it). Account holder floods
  unlimited fee-exempt ~2.4 KB txs. **Fix:** add `("msgkey", sender)` to `reserved_uniqueness_key` or
  charge a fee.
- **LOW — Cumulative treasury payouts unbounded per block (halt, not mint).** `SpendingLedger._escrow_release`
  (~1772-1790) omits `TREASURY_ADDRESS`; ≥5 approved proposals in one block each pass the 25% cap
  individually but collectively underflow at apply → `floor_zero` raises inside `incorporate_block` =
  halt. Governance-gated. **Fix:** track TREASURY draws in SpendingLedger like the escrows.
- **LOW — `check_balance()` dead-code chained-comparison bug** (~1720-1726); no callers; conservative if
  wired. Delete or fix to `>= 0`.
- **Verified SOLID:** double-spend/replay (within-block dedup + on-chain tx-index at-most-once +
  `validate_all_spending` cumulative caps + landing window), negative/overflow/float amounts (int-only
  `>=0` gates, `_has_float`, big-ints), supply inflation (block_reward equality-enforced + range,
  conserved splits), balance underflow (fails closed via `floor_zero` raise), fee-exempt value carry
  (all assert amount==0), settlement-oracle/escrow caps.
