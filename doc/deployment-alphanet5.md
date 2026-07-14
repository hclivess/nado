# alphanet-5 deployment — the multi-part cutover (zkVM-only, provable contracts, games)

This is the operational runbook for the 2026-07-14 cutover that shipped the ZK-execution-proof stack
(issue #85). It is a **multi-part deployment**: (A) a code release, (B) a destructive L1 chain reboot with
balance carry-forward, (C) an exec-layer restart on the new runtime, and (D) per-game contract deploys +
frontend wiring. Each part is independently verifiable; do them in order. The pieces are deliberately
decoupled so downtime is one window, not the whole migration.

Cross-refs: `doc/zk-execution-proofs.md` (the proof stack), `execnode/README.md` (exec node),
`tools/alphanet5_carryforward.py` (carry-forward), `execnode/games/` (ports + `deploy.py`).

---

## Part A — the code release (reversible, no chain impact)

The zkVM stack + stackvm deletion is a normal code change, tagged **v1.0.0-alpha.9**. It makes the
field-native zkVM the only runtime (`runtimes.DEFAULT_RUNTIME = "zkvm"`), deletes `execnode/vm.py` and the
stackvm contracts/tests, and adds the execution AIR, epoch aggregation, and the settlement proof. Merged and
tested before touching the chain — so Part A can sit on `main` while the chain still runs the old build in
memory. **Do not restart `nado-exec` after this merge until Part C** (it imports the now-deleted `vm.py` only
via the old in-memory process; a restart picks up the new code, which is only coherent post-reboot).

## Part B — the L1 reboot to alphanet-5 (DESTRUCTIVE — carries balances forward)

Wiping the chain is irreversible. **Back up first**, then carry every coin forward, then wipe + reboot.

1. **Back up the live state** (restorable if aborted):
   ```bash
   BK=/root/nado-alphanet4-backup-$(date +%Y%m%d-%H%M%S); mkdir -p "$BK"
   cp -a blocks index exec_state.json private exec_da message_pool.dat peers.dat "$BK/"
   ```
2. **Quiesce** so the state is final: `systemctl stop nado-exec nado forum`.
3. **Build `genesis_alloc.dat` from the FINAL state** (the committed one is always stale — regenerate at
   cutover):
   ```bash
   HOME=/root python3 tools/alphanet5_carryforward.py --write
   ```
   This tool is the accounting core. Under the owner's cutover rules it: carries every L1 balance + bonded
   stake verbatim; **folds** each holder's exec-side bridge balance, uncollected dividends, and pending
   dividend-withdrawals into their L1 balance; **refunds contract game-pots to players** (banked games via
   the `tp`/`tk`/`ga`/`gs` invariant — banker keeps the bankroll, open bettors get their stake; PvP via
   `pt`/`st`/`p1`/`p2`; an operator-run pool with no clean per-player ledger refunds to its deployer); and
   **debits the folded totals from the `bridge`/`dividend` escrow reserved accounts** so total supply is
   conserved EXACTLY. It prints a conservation check and refuses to write on Δ≠0. It writes both
   `private/genesis_alloc.dat` and the git-tracked `genesis_data/genesis_alloc.dat` — **commit the latter**
   so every joining node builds the identical genesis (block-0 account seeding does not change the genesis
   hash, but it MUST be byte-identical across nodes or state forks).
4. **Bump the chain id + timestamp** in `protocol.py`: `CHAIN_ID = "alphanet-5"`, a fresh recent
   `GENESIS_TIMESTAMP`. Commit.
5. **Wipe the old chain + exec state** (keeps `private/` keys + `genesis_alloc.dat`, keeps `peers/`):
   ```bash
   HOME=/root python3 purge.py -y          # blocks/ index/ logs/
   rm -f exec_state.json exec_state.json~tmp exec_state.json.*; rm -rf exec_da
   ```
6. **Start L1**: `systemctl start nado`. On boot it rebuilds genesis as alphanet-5 and seeds the carried
   balances. **Verify:** `curl localhost:9173/status` shows `chain_id: alphanet-5`; `/get_supply`
   `total_supply` equals the carry-forward tool's total; a spot-check of `/get_account?address=…` matches the
   alloc (allowing for a few blocks of emission once producing).

> **Finality after a reboot needs the validator set back.** The bootstrap node alone rarely holds >2/3 of
> bonded stake, so FFG finality resumes only once the other carried-forward validators update their code and
> rejoin alphanet-5 (they re-genesis from the shared `genesis_data/genesis_alloc.dat`). The chain produces +
> depth-finalizes meanwhile, and the FFG inactivity leak recovers the quorum over epochs if some never return.

## Part C — restart the exec node on the zkVM runtime

`systemctl start nado-exec forum`. The exec node comes up on the new code with a fresh, empty state and tails
alphanet-5 from genesis. **Verify:** `curl localhost:9273/exec/runtimes` → `{"runtimes":["zkvm"],…}`;
`/exec/root` shows `contracts: 0` and a `cursor` that advances as finalized blocks arrive.

## Part D — deploy the games + wire the frontends (repeat per game)

Games return only as zkVM ports (`execnode/games/<name>.py`). Each is a self-contained deploy:

1. **Deploy the contract** (signed by a funded wallet's `keys.dat` via `HOME`):
   ```bash
   HOME=/root python3 -m execnode.games.deploy coinflip           # prints the deterministic cid
   HOME=/root python3 -m execnode.games.deploy dice --upgrade <cid>   # replace an already-live contract's code
   ```
   The deploy blob carries `runtime:"zkvm"`, the zstd-compressed code, and the `abi` (including its `_view`
   schema). It lands in a block; the exec node applies it once that block **finalizes**. Confirm:
   `curl 'localhost:9273/exec/contract?cid=<cid>'` returns the method list.
2. **Wire the frontend** — usually just the `cid`:
   - Update `const CID = "…"` in `static/<name>.js` to the printed cid.
   - Beacon games (BLOCKHASH/BEACON): swap the client-side result preview to `chainResultAlg(...)`, which
     byte-matches the contract's in-VM alghash + LO32 window (import it from `nadodapp.js`).
   - Everything else (reads via `dapp.storage()` / `_m(sto, "map")`) is **unchanged**: the exec node's
     `ExecState.decode_view` presents the contract's flat slots as the old named maps, driven by the
     contract's `abi._view` schema (map→field, index cnt+list, `board` cells, address-digest resolution).
3. **The static bundle re-versions itself** (`nado.py` stamps `?v=<newest .js mtime>`), so an edited
   `static/*.js` is served fresh — no cache bust needed.

### Deploying a NEW game port (the porting checklist)

- Write `execnode/games/<name>.py`: the contract in zkVM asm over the composite-integer `slot` model
  (`slot rd F rk` → `slot = F*2^32 + key`); an enumerable index (a count slot + a list field); and an
  `abi._view` so the frontend reads it unchanged. Many-arg methods **pack** their args (a bitmask + bounded
  in-VM loops — the 8-register arg limit is not raised; see roulette's coverage mask). Financial division uses
  the widened DIVMOD (48-bit quotient). PvP board games put each cell index in its own field
  (`BD_BASE+cell`, keyed by gameId) and declare a `board` view.
- **Test end-to-end** before deploying: add the game to `tests/test_games_e2e.py` — deploy on a fresh
  `ExecState`, play a full game via `apply_blob`, assert escrow/payout/`decode_view`, and prove one method.
- Deploy (Part D.1) and wire (Part D.2).

## Live on alphanet-5

| game | cid | notes |
|---|---|---|
| coinflip | `426b97a4b22f439cdb0bc0e4d24e6433` | BLOCKHASH 2-player flip |
| dice | `b37251eb6b8bbeedd3a69cad7d6611a1` | banked roll-under (99/target) |
| roulette | `0ccfa996d30b5228e702a38a29b965fe` | banked; 37-number coverage as a packed bitmask |
| tictactoe | `d7744c41300ef02b6cc944f0cf1ccdae` | PvP board |
| connect4 | `67349828b38443eda30de51dea8a3d67` | PvP board (7×6, column-drop) |

Remaining ports (reversi, chess, farkle, bet, slots, mines, blackjack, poker, holdem, pets, battleship) follow
the same checklist; the mega-contracts need a feasibility pass against the single-call trace bound
(`vm_circuit.MAX_T = 8192` rows) before porting.

## Rollback

Parts A/D are reversible (revert commits / redeploy). Part B is not, except by restoring the Part-B.1 backup:
stop services, restore `blocks index exec_state.json` from the backup dir, revert the `protocol.py` chain-id
bump, restart. Only viable before the network has meaningfully advanced on alphanet-5.
