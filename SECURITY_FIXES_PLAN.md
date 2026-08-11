# NADO security — remaining-work plan (deferred + in-flight)

Companion to `SECURITY_AUDIT.md`. The 14 fixes in that doc's "applied" log are committed on `main`
(5 commits, `f95141d1`→`ab68920f`). This plan covers what is NOT yet live: the push, the game-contract
redeploy, and the items deliberately deferred because they need coordination or a real design pass.

Ordering principle: **land the committed consensus criticals first (cheapest, highest value), then the
contract redeploy, then the design-heavy items.** Nothing below should ride ahead of the push.

---

## 0. IMMEDIATE — push the committed node-side fixes (blocked on authorization)

`git push origin main` was denied by the harness safety classifier (it restarts the fleet). Everything is
committed and tested. **Action: user runs `! git push origin main`** (or authorizes it). Expect the usual
submit-500s / peer-drop blip as the fleet self-updates. No Rust sources changed → no crate rebuild.
The two CRITICALs (pubkey wedge, settle query-count forgery) go live on this push; the forgery one is
**already-exploitable today** because `SETTLE_PROOF_TRUSTLESS` is `True`, so this is the priority action.

---

## 1. Game-contract redeploy (makes fixes #13/#14 actually take effect)

The contract *source* is fixed (`_lib.open_table`, `reserve`, `mines`) but the **deployed bytecode is
unchanged** — a call still runs the old, unguarded code until each contract is upgraded in place.

**Hazard (do NOT use `redeploy.py`):** `redeploy.py::target_cids()` computes `cid = H(deployer,
build(), "a5")` from the *current* (now-fixed) `build()`, so it would fresh-deploy at NEW addresses and
orphan every existing game's escrow/pot. Preserving user funds requires `deploy_game.py --upgrade
<existing_cid>`, which keeps the cid and swaps only code+abi (deployer-only op). Deployer key confirmed on
this box: `ebd27698…`.

**Procedure:**
1. Compute each affected game's CURRENT (deployed) cid from the PRE-FIX code:
   `git show <parent-of-38ea76ae>:execnode/games/<mod>.py` → `H(deployer, old_build(), "a5")`, and confirm
   it appears in the live `/exec/contracts` set (port 9273). Affected: the 7 banked games that route
   creation through `_lib.open_table` — **coinflip, dice, roulette, slots, mines, blackjack, farkle** —
   plus **reserve**. (`mines` also carries the reap-horizon change.)
2. Canary: `HOME=/root python scripts/deploy_game.py reserve --upgrade <reserve_cid>` first (lowest
   traffic), wait for it to land (`/exec/contracts` shows the new code hash), smoke-test an `open` with an
   `id >= 2^32` → must now revert.
3. Roll the remaining 7 one at a time, verifying each lands before the next (per the existing
   `deploy_wave` land-check pattern), so a bad assemble bricks nothing silently.
4. Bundle the LOW contract fixes from §4 into the SAME redeploy wave (one code swap per contract, not two).

**Sequencing:** fine to do independently of the push (upgrades submit over HTTP to the running node; the
guard is pure contract asm, no node dependency). Recommend AFTER the push so the whole fleet validates the
upgrade txs on the fixed node code.

---

## 2. Grindable epoch beacon (MEDIUM → HIGH the longer RANDAO stays off)

**Problem.** With `RANDAO_ENFORCED=False`, in the steady state (no reveals) `beacon(E)` is a pure function
of the anchor block hash, which the anchor producer fully controls (pad self-txs, grind variants) → biases
the whole next epoch's producer schedule + duty committee; bias compounds. Not a theft/reorg vector
(beacon stays deterministic fleet-wide), so MEDIUM — but it erodes as stake concentrates.

**Why it is deferred, not flipped.** Naively setting `RANDAO_ENFORCED=True` makes a block **rejected** if
its epoch has no reveal — if the reveal machinery isn't reliably producing, that **halts the chain**. This
is a liveness landmine, not a one-line flip.

**Plan (staged, each stage observable before the next):**
1. **Harden reveal production first.** Audit the commit/reveal path (`ops/mining_ops.py` compute_beacon,
   the RANDAO #7 commits/reveals DBs). Make every bonded validator auto-commit at epoch E-2 and auto-reveal
   at E-1 as part of the mining loop, idempotently, with a persisted commit so a restart doesn't miss a
   round. Ship this WITH `RANDAO_ENFORCED` still False.
2. **Observe.** Over ~10 epochs confirm `reveals_for_epoch(E)` is non-empty for every E on every node
   (add a `/status` counter). This is the gate: do not proceed until reveals land reliably.
3. **Enforce with a fail-SAFE, not fail-STOP.** Turn on enforcement as "require ≥1 reveal for E≥2, else
   fall back to the anchor-only beacon" — so a missed-reveal epoch DEGRADES to today's behavior instead of
   halting. Keep the anchor as one input, XOR-folded with the reveals, so a single honest reveal already
   removes the anchor producer's sole control.
4. **Consensus-change discipline.** Beacon derivation feeds `select_producer`/`duty_committee`, so the
   change must be simultaneous fleet-wide (the push achieves that — all nodes restart together) and must
   be deterministic (integer/hash only). Ride it on one push; no per-height gate (alphanet has none).

**Testing:** a determinism harness that replays epochs E..E+3 and asserts identical beacons across a
full-history node and a snapshot-synced node; a grind test asserting the anchor producer can no longer
move the schedule once one reveal is present. **Risk if rushed:** chain halt. Do NOT enforce before §2.

---

## 3. Off-hot-path settle-proof verification (HIGH-3)

**Problem.** `/submit_transaction`'s settle branch runs `verify_settlement_sparse` (~22–94 s) synchronously
on the shared `to_thread` pool at mempool ADMISSION. A bonded validator can submit many distinct-proof
settles, each missing the byte-keyed verdict memo, each holding a worker → starves block production. Now
partially mitigated by the new 6/min large-submit rate limit, but the structural fix remains.

**Plan.**
1. **Admit on structural checks only.** At submit time, validate the settle tx's SHAPE (fields, sizes,
   `exec_cursor <= tip`, `proof_da` safety, bond>=B_MIN) but do NOT run the STARK verify. Consensus does
   not depend on the admission-time verify — the authoritative verify happens at block validation
   (`incorporate_block`), which is unavoidable and already present.
2. **Dedicated verify lane.** Move proof verification to a bounded `asyncio.Semaphore(1–2)` worker pool
   SEPARATE from the request `to_thread` pool and the block-production path, feeding the existing
   byte-keyed `_SETTLE_VERIFY_MEMO` so a later block-validation verify is a cache hit.
3. **Guard block assembly.** Ensure the block builder does not include a settle tx whose proof has not yet
   verified (treat unverified as not-yet-includable), so admission-without-verify cannot poison a produced
   block. The builder already re-validates; confirm it re-runs the settle verify and drops on failure.
4. **Per-sender distinct-proof rate limit** independent of the peer exemption (complements the 6/min body
   limit already shipped).

**Risk:** must not create a path where an unverified settle reaches a block. Mitigated by keeping the
block-validation verify authoritative (unchanged) and gating inclusion on the verdict. Medium effort;
needs a focused test that a flood of distinct-proof settles no longer stalls production.

---

## 4. LOW items — bundle by surface

**Consensus / node (ride the next node push):**
- **`save_block` hashed-field skip → refuse** (`block_ops.py:742-750`): treat a missing `_hashed` key on a
  non-genesis block as a refusal, not a skip. *Care:* confirm legitimate anchor/backfill blocks always
  carry all `_hashed` fields (they should — they're reconstructed) before tightening, else sync breaks.
  Add a sync test first.
- **Treasury per-block cumulative cap** (`transaction_ops` SpendingLedger): track `TREASURY_ADDRESS` draws
  like the other escrows so N approved proposals in one block can't underflow at apply (halt-class, not
  mint). Low-risk, self-contained.
- **DA-carried `proven` marker** (`account_ops.py:184-190`): `proven = "proof" in data` misses DA-carried
  settles (they carry only `proof_da`), so the trustless verdict is never recorded and settlement falls
  back to quorum even though the flag is on. *Care:* the marker must be set ONLY when the proof actually
  verified at block validation — thread the verify result through to reflect, and DO NOT mark proven past
  the depth gate. Design carefully; fails SAFE today (quorum is correct), so no rush.

**Contract (bundle into the §1 redeploy wave — one code swap per contract):**
- **pets: stamp `EX` on the challenger's pet at `challenge`** (not only `accept`) so a pre-accept
  release/transfer can't strand the challenger's own escrow.
- **Per-bet / PvP id guards:** extend `require id < 2^32` to the bet/join/creation methods of the board
  games and any per-bet entity keyed by a user id (the §1 fix covered the banker-bankroll `open_table` path
  and `reserve`; confirm tictactoe/connect4/reversi/pool/hexholm creation + all bet paths). *Note:* verify
  each per-contract rather than trust the earlier auditor's list (it wrongly flagged tictactoe, which
  already guards).
- **reclaim/settle horizon overlap** (dice/roulette/blackjack/slots): tighten the ~2000-block overlap
  toward the true prune height (griefing-only, DiD).
- **Explicit stake cap** as field-wrap defense-in-depth (mines already caps at 2^50); latent only.

**Governance (operational, not code):**
- **Renounce upgradability (`lock`) on every game after the redeploy**, or move the deployer to
  multisig/governance — otherwise the deployer key remains a single point of total failure that can
  rewrite any unlocked game to drain escrow. Do this LAST (after §1 + the §4 contract bundle land), since
  `lock` is irreversible.

---

## 5. Suggested sequence

1. **Push** the committed node fixes (§0) — unblocks the two live CRITICALs. *(user action)*
2. **Redeploy** the 8 game contracts in place (§1) + fold in the §4 contract bundle. Canary reserve first.
3. **Ship** the §4 consensus/node LOW items on the next node push (treasury cap, DA proven marker, and
   `save_block` after its sync test).
4. **RANDAO** hardening (§2 stage 1) ships; observe reveals (§2 stage 2) for ~10 epochs.
5. **Enforce** RANDAO fail-safe (§2 stage 3) + **settle-verify lane** (§3) on a subsequent push.
6. **Lock** the game contracts (§4 governance) once everything above is stable.

Steps 1–2 close the last of the CRITICAL/HIGH surface. 3–6 are hardening and can proceed at a normal
cadence, not under release pressure.
