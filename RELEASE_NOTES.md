# 2026-08-13 (later the same day) — new miners could not join, and auto-bond compounded the wrong coins

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

