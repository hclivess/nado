# v1.0.0-beta.5 — 2026-08-20 — betanet-4: the convergence reroll, every amount carried

> **CHAIN_GENERATION 22.** Nodes purge and boot betanet-4 from genesis automatically on restart.
> All balances, bonded stakes, uncollected dividends, pending withdrawals and bridge amounts carried
> forward — supply conserved exactly (Δ=0, 244 accounts). Contract ids unchanged; games redeployed
> at their existing addresses.

## Every 2026-08-20 consensus rule ships ungated, from block 0

Canonical per-block dividend accrual, committed epoch weights, quantized boundary settle
attestations. Every betanet-3 height gate is DELETED — including the h10047-16000 state-root repair
window, whose raw heights would otherwise have suspended root enforcement on THIS chain at h10047.

## Generation identity, three layers deep (what this cutover taught)

A reroll's purge marker is a hint that hand-installed layouts miss; block-0 hash checks are mute on
rolling nodes that hold no block 0 — and purged nodes were re-infected by the un-purged majority via
quorum snapshots that carry no genesis-descent proof. The durable identity is arithmetic: **height is
bound to wallclock** (production paces at BLOCK_TIME, so no chain of this genesis can be taller than
~2x elapsed since GENESIS_TIMESTAMP). Boot purges on-disk data that exceeds the bound; status
admission refuses peers advertising an impossible height; /status advertises genesis_hash and
admission refuses a mismatch. A previous generation's chain can no longer veto finality, win a
verdict, or serve a snapshot here.


# v1.0.0-beta.4 — 2026-08-15 — the faucet actually pays, and a scary number that was never real

> No consensus change. Wallet, operator tooling and the apps page. Safe to update at any time; nodes need
> no coordination for this one.

## The faucet was never going to pay anything

`reward()` is operator-only and nothing in the node calls it — the distributor `_faucet_rewards.py` is the
only caller. It had been written, 14 games were enrolled against it, and **it was scheduled nowhere**: no
crontab entry, no systemd timer, nothing in `/etc/cron.d`. Donations accumulated and every airdrop-play
leaderboard went unpaid. Verified by hand: the exec layer showed a funded faucet balance and the
distributor ran clean when invoked, so only the trigger was missing.

The deeper problem was that the schedule lived nowhere in the repo. `bet-oracle` had the same shape —
units committed, installed by hand — so a unit that exists on one machine silently stops existing.

    scripts/nado-faucet-rewards.{service,timer}   the distributor, matching the bet-oracle convention
    scripts/install-timers.sh                     installs + enables every OPERATOR timer (--list to preview)
    doc/faucet.md §2b                             the scheduling step, and why re-running is safe

Deliberately separate from `install.sh`: these act **as the operator** — they spend from operator-owned
banks and sign with the operator key — so a normal node must not run them. Daily at 00:20 UTC, after the
boundary the boards are keyed on (they rank *yesterday's* verified play), `Persistent=true` so a box that
was down still pays that day, randomised so operators don't collide in a block. Re-running is safe by
construction: the contract marks `(game, day, rank)` and reverts a repeat, underfunded payouts revert, and
the per-game budget is capped in the script.

**Autogame was paid prizes it never advertised.** The "🪂 airdrop play" badge is set by hand per tile while
payouts come from a separate list — two hand-maintained lists that must agree, with nothing checking them:
14 enrolled, 13 badged. Autogame had a working Daily Gauntlet, a replay oracle and rules shared with it, so
the free play was real and would have been paid — but its tile advertised only the staked march, with no
badge and no mention of free play at all. `tests/test_faucet_badges.py` now pins both directions: every
paid game must advertise, and nothing may claim airdrop play without being enrolled (a badge promising
prizes that never arrive is the worse failure). Verified it catches the real bug rather than merely passing.

## "It says 25913 blocks to register"

A user was, reasonably, alarmed. The registration banner computes the remaining distance as
`targetBlock - state.latest`, guarded by `state.latest != null` — but `0 != null` is TRUE, so whenever the
relay reported a low or zero tip (several nodes were resyncing that day) the subtraction returned the
**absolute target height** and the wallet presented it as blocks remaining.

The bound was there to be used: the tx is built as `tip + poswTargetMarginFor(...)`, so the distance can
never legitimately exceed `POSW_TARGET_MARGIN`. Anything larger is not a long wait — it is our view of the
tip being wrong. A number is now shown only when it is credible; otherwise the banner says it is syncing
with the relay instead of inventing a figure.

The same report noted that part was not translated, and it was not — both progress strings were inline
English template literals. That turned out to be one instance of a class: `tools/check_i18n.py` flags keys
referenced by `interface.js` but absent from the English base, which render their raw fallback in **every**
language, and it was failing with 33 of them. This fixes the registration/mining path and everything added
on 2026-08-14/15 — 10 keys × 16 languages. 23 remain (`quorum.autoYes*`, `shield.*`), all pre-existing;
left rather than bulk-translated blind, since they deserve the same care.

Also: three Czech strings used **`epochová`**, an adjective Czech does not form from *epocha* — and the
real one, `epochální`, is a false friend meaning "momentous". Replaced with the genitive (`úkol epochy`,
`atestace epochy`), and a doubled "epoch" dropped from the duty message.

## Also

- **Apps tab in the wallet**, linking to `nadochain.com/apps` (the canonical URL — `/apps.html` 301s to
  it), styled like the existing Web tab, translated in all 16 languages.
- **`config.py` wrote a stale auto-bond default.** It baked the literal `80` while
  `protocol.AUTO_BOND_DEFAULT_PERCENT` had been raised to `99`, so a **fresh install** compounded at a
  different rate than a config that merely lacked the key — two nodes installed a week apart behaving
  differently with no way to tell from the outside which you had. It now writes the constant.

## Validation

Full suite: **264 passed, 30 failed, zero regressions** — the failure set is byte-identical to the
v1.0.0-beta.3 run, and every one of those 30 was already reproduced at v1.0.0-beta.2 (settle/STARK
proving, games, and browser e2e that need a display). All 14 constants the wallet mirrors from protocol.py
verified equal, served asset stamps match their files, and the fleet is 8/8 in lockstep with
`disagree=0`.

## Not in this release

A faucet change making the operator key rotatable on-chain was written and then **reverted** — the
mechanism that matters (`state.transfer_contract`, which moves contract ownership with cid and storage
preserved) already existed, and modifying a funded contract was not worth the risk for what it added.
Nothing was ever deployed; the built code matches the on-chain contract exactly.

---

# v1.0.0-beta.3 — 2026-08-14 — a fleet fork of my own making, and the guards that close the class

> **CONSENSUS.** Two changes bind: the number<->hash index is now bounded by protocol rule, and the
> index-prune watermarks are excluded from the L1 state root. A bounded repair window
> `[10047, 16000)` let the fleet cross the damage without a reroll; it has already expired and full
> enforcement is back on. No reroll, no lost balances, no lost history.

## The incident: a disk-retention counter reached consensus

The index-retention work below wrote two watermarks into the `meta` sub-DB —
`index_pruned_below_num` / `index_pruned_below_hash` — recording how far a node had pruned **its own
disk**. `meta` feeds `l1_state_root()`, which is committed into every block header, and the new keys
were never added to `ROOT_EXCLUDED_META_KEYS`. So a node's storage policy became consensus state.

The split was clean and both sides were right. The index prune first fires when finality crosses
`INDEX_RETENTION_HASH = 10 000`, so at block **10047** every ROLLING node wrote the watermark and its
committed root moved, while every ARCHIVE node — which never prunes, so never wrote the row — computed
the old root and correctly refused to extend. The fleet fragmented across three heights.

**Diagnosed by replay, not by inspection.** Restoring the wedged node's OWN checkpoint at 10000 and
replaying its OWN bodies forward reproduced `c55b376f31ee1296` — so its state was never corrupt; it was
the honest result of applying the blocks. On that same state:

    root with the watermark EXCLUDED : c55b376f31ee1296
    root with the watermark INCLUDED : 00f00a01e387ccf3   <- the root committed in block 10047

Bit-for-bit. That is what turned a guess into a diagnosis.

**Recovery without a reroll.** The roots already committed over the affected span encode one node's disk
state, so they are unverifiable *by construction* — an archive node never held the value at all.
Enforcing them wedges every honest node permanently. So the equality comparison, and only the
comparison, was suspended across `[10047, 16000)` and re-armed at a height every node agreed on;
hash chain, producer signature, cumulative weight, tx validity and per-tx state transitions stayed
enforced throughout. The fleet crossed 16000 with an archive node and five rolling nodes computing
identical roots, zero divergence.

## The tests that should have caught it, and why they did not

Both failures were the same shape: a test that asserts a **literal** instead of a **property** cannot
fail until someone has already performed the act it was meant to enforce.

- `test_seed_divergence` asserted `ROOT_EXCLUDED_META_KEYS == frozenset((...))`. It could only go red
  after the missing key had been added. Now containment plus a behavioural check — a node that has
  pruned must compute the same root as one that has not, and the root must not move as pruning
  progresses — plus the converse, that a block-derived row still DOES move it.
- **New:** `tests/test_no_local_state_in_root.py` reads `kv_ops.py`, extracts the meta keys written
  inside `prune_*`/`gc_*` functions, and requires each to be excluded. A future prune that stashes a
  watermark fails the day it is written, not the day finality crosses its threshold in production.
- **New:** `tests/test_rollback_symmetry.py` asserts rollback is the exact inverse of apply against the
  REAL `incorporate_block`/`rollback_one_block`. The existing round-trip check hand-copied both
  sequences ("mirrors ...") and so tested a replica that stayed symmetric while production drifted.

## Storage: rolling by default, and the last unbounded store bounded

- **Rolling mode is the default.** An archive node keeps every body forever — measured at 133 MB/day,
  **~47.6 GB/year**. Fine for the one box hosting an explorer, unreasonable for volunteer VPSes; and a
  node that fills its disk stops UPDATING, then forks. Rolling keeps state and the number<->hash
  indexes, dropping only bodies older than the retention window, over a hard consensus floor config
  cannot lower. Four independent decision sites now move together, pinned by test.
- **`config_version`.** A changed default reached new installs and nothing else, because
  `create_config` writes every default at install time and is create-only — the installer's value is
  indistinguishable on disk from an operator's choice. Observed directly: flipping `archive` moved
  exactly the ONE node whose config predated the key. One-time migration, narrow (only keys still
  holding the old default), and a deliberate `"archive": true` set afterwards survives.
- **The number<->hash index is bounded by protocol rule** (`doc/index-pruning.md`). At 144 B/block it
  was ~7 GiB/decade and the dominant term once bodies and tx history are pruned. It could not be a node
  setting — every carried row feeds `state_digest`, so differing depths split `snapshot_hash`. The
  window is keyed on the checkpoint height C every node already agrees on: `[C-N, C]`, with
  `N_num = 50 000` (~2.1x the deepest consumer) and `N_hash = 10 000` (~222x `FINALITY_DEPTH`, since its
  only reader is a tip-local dedupe guard). Enforced on IMPORT as well as export, so a donor shipping
  out-of-window rows has them dropped rather than trusted. Measured e2e on a 60 000-block chain:
  **50% of the transferred payload dropped**, joiner still resolving the 24 000-deep lookback.

## Archive nodes stop lying about what they hold

- **A fresh archive node refuses snapshot bootstrap.** It backfills 265 bodies behind its anchor and
  nothing older, ever — so `archive: true` used to yield a node that syncs fast, looks healthy, holds
  nothing before its snapshot, and advertises "archive" to peers who read that as "can serve history".
  Refused, naming every route to a real archive.
- **Wedge recovery is NOT refused** — that node is on a fork it cannot leave by rollback, so declining
  leaves it wedged forever serving nothing. It now logs the exact range lost and tells the operator to
  re-seed.
- **`earliest_block_height` in `/status`** — the body horizon. `node_type` answers "do I prune?";
  callers were reading it as "can you serve history?".

## Registration

- **Renewals stopped re-broadcasting.** Reported as "renewal is especially difficult today", and it was:
  552 registers from 37 senders, ~27 attempts each, every one rejected "sender already recerted this
  epoch" — the first landed and the rest were noise. `maybeRenewLease` guarded on a flag cleared when
  the SUBMIT returned, not when the tx LANDED, and its only other signal (`acc.reg_epoch`) is on-chain
  state that cannot move until mined. Widening `POSW_TARGET_MARGIN` 30 -> 90 took that window from 3 to
  9 minutes and the retries scaled with it.
- **The target margin is sized to the work owed**, not the worst case: a base renewal now lands in
  ~13 blocks (78 s) instead of 90 (540 s), while an expensive entry proof on a slow phone still gets the
  full window.

## Validation

2000-transaction stress test after recovery: **2000/2000 accepted, 2000/2000 mined**, all 147 recipients
credited, peak 44 txs in a block, 2.55 tx/s sustained, mempool building a backlog and draining it — and
**zero state divergence across the whole run** with all nodes in lockstep. The submit rate limiter
(30/min per IP per node), not the chain, was the ingestion ceiling.

Test suite: **263 passed, 30 failed, ZERO regressions** — every failure reproduces at v1.0.0-beta.2 and
predates this release (settle/STARK proving, games, and browser e2e that need a display). The one apparent
regression, `pool_ui_e2e.mjs`, was a 180 s timeout on a box that was mining and had just absorbed the
stress test; it passes in 480 s, and `pool.html` does not load any file this release touched.

A second, unrelated fork appeared during validation: `202.91.32.228` — the node that had been stuck at
height 63 with a frozen core loop all day — diverged alone at h17313 on a HEAVIER chain. Two safety
mechanisms did their job with no operator action: the state-root gate **refused the heavier chain** rather
than following weight into invalid state, and the dead-fork probe flipped to `stranded`, purged, resynced
and rejoined. Cause not established — it predates none of the fixes here, sits 1300 blocks past the repair
window, and the node destroyed its own evidence while healing. Recorded as unexplained rather than
attributed to a guess.

---

# v1.0.0-beta.2 — 2026-08-13 — new miners could not join, and auto-bond compounded the wrong coins

> **CONSENSUS FLAG DAY.** `POSW_ANCHOR_OFFSET` moves 30 -> 150 and a new `POSW_TARGET_MARGIN = 90` sizes the
> proving budget. `validate_transaction` re-derives a registration's PoSW anchor from its own `max_block`, so
> a node on the old offset computes a different challenge and rejects every honest registration. No compat
> path, no height gate: update the whole fleet. No reroll — chain state is untouched.

**New miners could not register, and the error said nothing useful.** A `register` lands at *exactly*
`max_block`, and its anchor (`max_block − POSW_ANCHOR_OFFSET`) must already exist when proving starts — so a
client targeting `tip+M` can only pick `M ≤ offset`, and `M` blocks was its entire proving budget. That
budget (30 blocks, 180 s) was never a function of the *work* the difficulty demands, and the two had drifted
far apart: an entry registration owes `POSW_ENTRY_MULT × rate` = up to 512 × `POSW_T` = 512M sequential
hashes. Benchmarked against the hasher the miner actually ships:

    WASM blake2b (what the browser uses)     3.17M hashes/sec
    pure-JS fallback (WASM unavailable)      0.07M hashes/sec      <- 45x cliff

    entry at the 96x that was live (96M)     desktop  30s | mid phone 121s | slow phone 303s   [window 180s]

The phone finished a **perfectly valid proof for a block the chain had already passed**, the submit was
refused, and the wallet reported *"the relay rejected the registration"*. Offset 150 / margin 90 gives a
540 s budget and makes the anchor `tip−60` — 60 blocks deep at prove time, which is finally past
`FINALITY_DEPTH` as the constant's own comment had always claimed. **The anti-Sybil cost does not change by
a single hash.** The 512× worst case still does not fit on a slow phone; that case only occurs when the rate
multiplier is pinned at its 16× cap by a sustained registration flood, which is when throttling entry is the
point.

**Auto-bond compounded coins it was never asked to touch.** It measured "newly-mined earnings" as the rise
in spendable *balance*, which is not the same thing — it swept up transfers, faucet payouts, bridge
deposits, and, worst, a **matured `withdraw`**: the coins the operator had just deliberately taken *out* of
savings went straight back in behind another 24 h timelock, at 99% on a node. Leaving the bonded lane was
silently self-reversing, once per unbond, forever. Both the node (`core_loop.maybe_auto_bond`) and the
wallet (`autoBond`) now baseline on `produced` — the consensus counter of what the address actually mined,
which moves only on a won slot. A clamped bond consumes only the slice of the gain it covered, so the
remainder stays claimable instead of being written off.

**Also:**

- `/posw_difficulty` answered for a landing block nobody uses (`tip+6`, the CLI's margin) while every browser
  miner targets `tip+margin` — two anchors that straddle an epoch boundary for 24 of every 60 heights.
  `posw.verify` is EXACT-T, so whenever the rate multiplier differed across that boundary an honest
  registration was rejected. Latent while the multiplier sat at 3×; live the moment it stepped to 2×, which
  it did that afternoon (24/360 heights in the window then disagreed). Callers pass their own `max_block`,
  and `required_t` now comes from `required_posw_t()` itself rather than a second copy of the formula.
- `nado_cli register` called that endpoint **bare**, so it never saw the entry multiplier and under-worked
  every first CLI registration by 32×. `mint_multiplier()` — which returned the rate multiplier alone and was
  the obvious-looking thing to reach for — is deleted rather than left as a trap.
- **`nado_cli withdraw`** exists. `unbond` only records a request; the only code that ever finished the exit
  was the browser wallet's `refreshUnbond()`, so a headless operator who unbonded had no way to claim the
  coins back at all.
- The wallet now says when WASM is unavailable (that path cannot finish a registration in any window), and
  `poswRate()`'s flat 700,000 guess — wrong by 4.5× one way and 10× the other — is seeded from the backend
  that will actually run.
- Explorer: an account read the `registered` flag alone and announced *"yes (OPEN-lane miner)"* at an address
  that was also the largest bonded producer on the chain; lanes are not exclusive. Fidelity was shown out of
  1000 when `FIDELITY_CAP` is 30, telling a fully-ramped miner it was at 3%.

## A dead RANDAO reveal killed the whole epoch duty, forever

Reported from a live session, once a minute: `Epoch duty rejected: … No matching commit for this reveal`.
A bonded validator's FFG attest (epoch X), RANDAO commit (X+2) and reveal (X+1) ride in **one** `duty` tx,
so a reveal the chain can never accept fails the whole transaction and takes the attest and the next
commit — both perfectly valid — with it. The validator silently stops attesting for FFG and stops
committing for future epochs, and retries forever, because the rejection never matched the "nothing left
to post" pattern.

The rejection is permanent, which is what `_randaoDead` was declared for ("a resubmit can never succeed")
— and nothing ever added to it. A commit for epoch E must be posted in E−2 while its reveal lands in E−1's
finalized window, so by the time a reveal is refused for a missing commit that window shut an epoch
earlier. Now: mark it dead, drop the reveal section, resubmit at once so the attest and commit still land.

## A node that cannot update itself now says so

Four nodes stopped updating and stayed stuck for a day while answering `/status` with
`update_capable: true, update_blocking: [], update_remote_reachable: true`. Nothing in the diagnosis
looked at the host, and `update_available` is derived from the last *successful* fetch — which on a node
whose every fetch fails can never learn that origin moved.

`git fetch` was dying with `fatal: unpack-objects failed`. I reproduced that exactly (60 MiB loopback
ext4, fetching as the unprivileged service account) — and then the new telemetry **disproved it as the
cause here**: `89.143.197.28` reported 1424 GiB free and was still failing. git prints that line whenever
the `unpack-objects` child dies for *any* reason, so the message cannot separate ENOSPC from inode
exhaustion from an OOM-kill. All three are now measured, with the last fetch error, and surfaced in
`/status` (`update_free_disk_mb`, `update_warnings`) — the warning band fires with ~1 GiB of headroom,
days ahead, where `blocking` only fires once the node is already stranded.

`check_and_update` also repacks and retries once on a space-shaped failure, and both fetch call sites pass
`-c transfer.unpackLimit=1` so an incoming pack stays a pack (measured: 2030 loose objects = 35.1 MiB vs
17112 packed = 22.6 MiB). **Measured limit, stated in the code:** `git gc` writes the new pack before
dropping the old objects, so it needs free space of roughly the pack size — on a 13 MiB `.git` it failed
at 6 MiB free, at 4, at 2 and at 0. The retry rescues loose-object bloat, not a full disk. Only the early
warning catches that.

## Also

- **`nado_cli withdraw`** exists. `unbond` only records a request; the only code that ever finished the
  exit was the browser wallet, so a headless operator who unbonded could not claim their coins back.
- **`execJSON()`** — every shielded-pool call reached the exec node as a bare `(await fetch(…)).json()`.
  `nado-exec` restarts independently of the relay, and on an HTML error page that surfaced to the user as
  `Unexpected token '<', "<!DOCTYPE "… is not valid JSON`. `rpcJSON` had handled this for the relay all
  along; the exec node had no equivalent.
- **Three dead code paths the suite was already reporting.** `memserver.py` used `os.environ` without
  importing `os`, inside a bare `except` — it raised on every boot and silently pinned
  `tx_history_retention_blocks` to 0, so that setting has never worked on any node. `self_update.py`
  called `_restart_services()`, which has never existed, so the stale-checkout self-heal reported an error
  instead of restarting — and hid it, because `_stale_acted` is set on the line above the failing call.
  `mint_multiplier()` returned the rate multiplier alone, so anything minting from it under-worked an
  entry registration by 32×; deleted rather than left as a trap.
- **Two tests were hiding bugs rather than catching them.** `test_stale_checkout_restart` patched
  `SU._restart_services` — assigning a name the module lacks *created* it, so the test was green over a
  production `NameError`. `test_auto_bond`'s fixture credited balance without touching `produced`, i.e. it
  could not tell a mining reward from a receive — precisely the confusion behind the auto-bond bug.

---

# betanet-3 — 2026-08-13 (carry-forward reroll: dividends folded, fidelity farming closed)

> **Chain reboot with balances carried.** `CHAIN_GENERATION 21`, `CHAIN_ID betanet-3`. Every holder's
> **balance + bonded stake carries forward**, and so does everything that previously lived only in exec
> state and would have been destroyed by the purge. Built with `tools/alphanet6_carryforward.py`, which
> refuses to write unless supply conserves exactly:
>
>     L1 accounts total (balance+bonded)      11 157 250 452 256 raw
>       folded user bridge                        11 898 223 615   -> users, -bridge escrow
>       refunded contract pots                        30 000 000   -> players/operator
>       folded dividends (uncollected)         1 651 471 200 086   -> users, -dividend pool
>       folded dividend withdrawals (pending)    144 275 085 788   -> users, -dividend pool
>       folded bridge withdrawals (pending)        2 373 497 180   -> users, -bridge escrow
>     carried total after folds               11 157 250 452 256 raw   CONSERVATION OK (delta 0)
>     139 accounts
>
> **181 NADO of dividends and bridged coins** that were unspendable-until-claimed are now plain balances at
> genesis — better than before, since a folded dividend needs no `collect_dividend` + `dividend_withdraw`
> against a settled root. **Contract ids are unchanged**: `H(deployer, code, nonce)` with a pinned nonce, so
> every hardcoded cid in the wallet still resolves after `execnode.games.redeploy`.
>
> **Known residue: 0.70074001 NADO** stays in the keyless `dividend` account. It is accrual the L1 pool
> received that no exec-side claim attributes to anyone (`div_carry`), and it does not shrink by chasing the
> tip — measured 0.38 at a 94-block exec lag and 0.70 at 41. It is left rather than assigned to a guessed
> owner. That is 0.06% of supply, and it is disclosed rather than quietly dropped.

## Why now — two economic defects, both found by measuring rather than reading

**The auto-register lease guard read a field that does not exist.** `core_loop.maybe_auto_register` gated
renewal on `acc.get("reg_epoch", -1)`, but `reg_epoch` is an enrichment the HTTP handler adds — the stored
document has no such key, so the value was always `-1`, the guard never fired, and every auto-registering
node recerted **once per epoch instead of once per ~24 h lease**. Fidelity is +1 per recert, so the three
node operators reached fidelity **366-379 on a 1.6-day chain** while browser miners sat at 1: open weight 10
against 2, i.e. **5x the producer selection and 5x the dividend share**. That is the reward gap users
reported, and it was ours, not an attacker's.

**Fidelity itself was farmable.** The ramp is per recert and the only spacing rule was "one register per
epoch" — six minutes — so `FIDELITY_CAP = 30` was reachable in **three hours**, not thirty days, on a
fee-exempt transaction. `FIDELITY_MIN_GAP_EPOCHS = 192` now gates the ramp: a closer recert still renews the
lease, it simply earns nothing. Both honest cadences (browser renews at 192, node at 230) are unaffected.

## Also in this release

- **Identity creation now costs more than renewal** (`POSW_ENTRY_MULT = 32`). The 64-per-IP registration cap
  cannot be consensus — a transaction carries no IP and arrives by gossip, so nodes would disagree — so the
  cost moved to something consensus can check: a register from an address with no valid lease pays 32x the
  sequential PoSW; renewals are unchanged. Against the measured honest weight, taking half the open lane goes
  from ~2 core-minutes/day to ~71 core-minutes one-time.
- **Nodes auto-vote on whitelisted treasury proposals.** Quorum is counted in bonded shares, and 108 of 117
  miners hold none — the wallet's auto-vote could never reach quorum by itself, which is why the treasury
  accumulated 109 NADO with zero payouts. The default allow-list is the reserved keyless `faucet`; an empty
  list approves nothing.
- **The settle prover starts warm.** `storage_tree` persists its singleton-fold cache, so a restarted exec
  node's first settle prove drops from 58.9 s to ~10 s (root() 50.30 s -> 0.64 s across a restart, root
  bit-identical). No consensus change.
- **Daily stats survive upgrades.** Chain-stamping was discarding *unstamped* history, so a routine update
  wiped every node's accumulated trend data; an absent stamp is now adopted rather than dropped.
- Docs: `doc/updates-and-rerolls.md` gains a pre-reroll checklist (what a "balances carry" promise must
  actually cover), `SCHEDULED_CLEANUPS.md` tracks code that becomes deletable at a stated height, and
  `doc/fri-parameters.md` records that the FRI blowup lever stays rejected — on proof size, not prove cost,
  after both prior rejections turned out to have measured the Python prover.

---

# Betanet reboot — 2026-07-14 (betanet-5: zkVM-only, provable contracts, games returning)

> **Chain reboot.** Deleting the legacy stack VM (v1.0.0-alpha.9) made the field-native **zkVM the only
> contract runtime**, so betanet-4 was rebooted to **betanet-5** with a fresh genesis. Every holder's
> **balance + bonded stake carried forward** (`tools/betanet5_carryforward.py`): exec-side user balances +
> uncollected dividends folded into L1 balances, contract game-pots refunded to their players, and the folds
> debited from the escrow reserved accounts so total supply is conserved EXACTLY (Δ=0). Nodes rebuild the
> identical genesis from the shared `genesis_data/genesis_alloc.dat`. Bonded validators must update + rejoin
> for full FFG finality (the chain produces + depth-finalizes meanwhile).

Games are being re-shipped as zkVM ports (`execnode/games/`) — the old stackvm game JSONs are gone. Each
port: the contract in zkVM assembly over a composite-integer `slot` model, an `abi._view` schema so the exec
node presents its flat slots as the named maps the frontend already reads (so only the `cid` changes), and
`chainResultAlg` for a client-side beacon preview that byte-matches the contract's in-VM alghash. **Live so
far:** coinflip, dice, roulette, tictactoe. Two techniques the ports drove: **arg-packing** (a many-arg game
like roulette packs its 37-number coverage into one bitmask + bounded in-VM loops — the 8-register arg limit
is a feature, not raised) and a **widened DIVMOD** (48-bit quotient) for financial payout division.

See `doc/zk-execution-proofs.md` and `execnode/README.md`.

---

