# Updates, chain generations, and rerolls

How NADO nodes stay current, and what happens when consensus makes a clean break. Companion to
`ops/self_update.py`, `ops/data_ops.py` (chain-generation machinery) and `config.get_protocol()`.

## The integrated auto-updater

Every node keeps itself on `origin/main` of the official repo (github.com/hclivess/nado — any other
remote or branch refuses):

- **`GET /update`** — anyone may call it. The caller only chooses *when*; the code always comes from the
  repo the operator already trusts. Fast-forward only; a dirty or diverged checkout refuses; a current
  node answers `up_to_date` and does nothing (spam costs one rate-limited fetch). On a real update the
  node rebuilds native crates if needed, forwards the ping to its linked peers (**the update wave** — one
  call updates the reachable fleet; current peers don't re-forward, so the wave dies out), then restarts
  its services detached.
- **Daily self-check** — 10 minutes after boot, then every 24 h.
- **`nado_cli.py update`** — triggers a wave from the terminal.
- Opt out with `"auto_update": false` in `private/config.json`. This also **disables the `/update` and
  `/update_peer` endpoints** (they answer 403), so an opted-out node can neither be update-triggered
  remotely nor used as a proxy to trigger other peers. Read per-request — no restart needed to flip it.
- `"auto_heal": false` additionally disables the boot-time **installer self-repair**: a node diagnosed
  as un-updatable (`ops/self_update.ensure_updatable` — no git checkout, no systemd unit, …) then only
  logs the defect and advertises it in `/status`, instead of running the local `scripts/install.sh`.
- `/status` advertises `running_commit`, `latest_main` and `update_available`, so a lagging node is
  visible at a glance.
- **Config is never rewritten by an update.** The `config_version` migration mechanism still stamps the
  version, but its rewrite steps are disabled by operator decision (2026-08-17, `dd085b9f`): on disk, a
  value the installer wrote is indistinguishable from a value the operator chose, so "flip the old
  default" is a guess about intent — and when the v1 step guessed wrong it silently converted archive
  nodes to rolling. Re-enabling any rewrite is a deliberate act that belongs in release notes.
- **The wave is also how consensus-behaviour changes deploy.** The two-floor finality change
  ([finality.md](finality.md)) shipped with no height gate: its only new persistent key is outside the
  consensus root, so a mixed fleet commits identical roots mid-rollout, and the wave (plus
  `/update_peer` for stragglers and the peer-hint cascade from status gossip) converged all eight nodes
  within minutes. That pattern only works when the change is root-neutral — anything that moves the
  root still needs a generation reroll, exactly as below.

## No backward compatibility — the consensus policy

Consensus code carries **no compatibility of any kind**: no grandfather windows, no height-gated
leniency, no fork schedules. Every rule is enforced strictly at every height. When a change breaks
validation of the existing chain, that chain is simply no longer this protocol's chain, and the remedy
is operational, not code-level:

1. **Protocol bump** — `config.get_protocol()` is the handshake number (from CODE, never from a config
   file). Peers reporting a lower number are shed at the door instead of fought block-by-block. Bump it
   with every breaking consensus change.
2. **Chain generation bump (full genesis reroll)** — see below.

## Chain generations (genesis rerolls)

`protocol.CHAIN_GENERATION` counts **genesis lineages** — nothing to do with the 60-slot consensus
epochs. Each generation is one genesis; the counter bumps only when the chain rerolls.

A reroll ships as **one commit**: the new genesis (typically with balances frozen forward from a chosen
settled state, as in the betanet-6 reroll) plus the bumped `CHAIN_GENERATION`. Every node stamps the
generation its on-disk data was built under (`~/nado/chain_generation`); a post-update boot that sees
the code's generation ahead of its stamp **wipes all chain-derived data** — blocks, index, peers,
snapshots, exec state + DA; **never `private/`** (keys, config) — and regenesis/resyncs fresh. The exec
node performs the same check for its own files, so a stale execution layer can never replay a new chain.

Combined with the updater, **one `/update` wave fully deploys a reroll**: pull → restart → purge →
fresh chain. No manual steps on any operator's box.

### Pre-reroll checklist — what a "balances carry forward" promise actually has to cover

Betanet's promise is that **balances persist and carry to mainnet**. The purge above deletes *exec state*
as well as blocks, and several kinds of user value live **only** in exec state. Building the genesis alloc
from L1 account balances alone silently destroys them. Verified on betanet-2, 2026-08-13:

| Value | Where it lives | What a naive alloc does |
|---|---|---|
| L1 account balances | `accounts` sub-DB | carried — this is the easy part |
| **Bridged coins** | L1 escrow holds the COINS (`bridge` account, keyless); **exec state holds who owns them** | coins land in a keyless account nobody can spend; the real owners get nothing |
| **Faucet donations** | same shape — `faucet` is a keyless reserved account | same |
| **Accrued dividends** | exec-side, unclaimed until `collect_dividend` + `dividend_withdraw` | lost |
| **Contract-held stakes** | contract storage (open games, bets, LP positions) | lost |
| **Asset balances** | exec `abal` | lost |

Measured at the time of writing so the scale is known rather than guessed: L1 `bridge` escrow held
**1.43017 NADO** against an exec-side ledger of **1.192822 NADO across 4 holders**; contract storage was
**8 412 slots**, of which **99.3% sat in one contract** (`386cc6bd021c`, the bet book), with only 3 of 27
contracts holding any state at all. Small today — but the mechanism does not get safer as it grows, and
the numbers are only small because nobody is using contracts yet.

**So, before rerolling:**

1. **Sweep or re-allocate every exec-side claim**, not just L1 balances — bridge, faucet, accrued
   dividends, asset balances. Either credit each holder directly in the alloc, or land real
   `bridge_withdraw`/`collect_dividend` transactions *before* the reroll so the value is on L1 when the
   snapshot is taken. Do not carry the keyless escrow account itself; carry its beneficiaries.
2. **Decide explicitly about contract-held positions.** They cannot be carried (the contracts are
   redeployed empty). Either drain them first, or announce that open positions are void — but do not
   discover it afterwards.
3. **Redeploy all contracts in the SAME session as the reroll** — but note what that does and does not
   involve. A reroll wipes every contract, and until they are redeployed each call reverts against
   nothing, silently. What it does **not** require is rewiring the website: **contract ids are
   deterministic**. `ExecState.contract_id` is `H(deployer, code, nonce)` and the deploy nonce is PINNED
   (`execnode/games/deploy.py --nonce`, default `a5`), so the same deployer key + unchanged code
   reproduces byte-identical cids across a genesis reroll. Every hardcoded cid in `static/*.js` stays
   valid.

   `python3 -m execnode.games.redeploy` is idempotent on exactly that basis: it computes every target cid
   offline, deploys only what is missing, then rewires and restamps. `--check` reports without touching
   anything — verified on betanet-2, 26/26 up to date, every frontend + reward-table cid resolving.

   Two things that DO move a cid, and therefore break the wiring: changing the contract's **code**, or
   deploying from a **different key**. Both are ordinary reasons to redeploy; neither is caused by the
   reroll itself.

   Contracts are deployed **upgradable** (`upgradable: True` on all 27 live today, one deployer), so a
   code change afterwards goes through `deploy.py --upgrade <cid>` and keeps the cid and its storage —
   never a fresh deploy, which would strand the address.
4. **Re-check every height/epoch-gated constant** — see [`SCHEDULED_CLEANUPS.md`](../SCHEDULED_CLEANUPS.md).
   Epoch numbering restarts, so an activation constant that was 2 days out lands weeks into the new chain
   and silently leaves the old behaviour live until then. In particular
   `FIDELITY_MIN_GAP_ACTIVATION_EPOCH` must be made **unconditional** on any reroll — a fresh chain has no
   pre-activation history to preserve, and leaving it gated would reopen the fidelity-farming exploit for
   the first days of the new chain, which is exactly when an early weight advantage compounds most.
5. **Check the carried balances are not exploit-inflated.** Cheap aggregate test for the fidelity case:
   `mining_status` gives `total_open_weight / open_registry_size`. 2.0 means everyone is at fidelity 1;
   10.0 means everyone is maxed. Betanet-2 measured **2.27**, i.e. no meaningful farming, so its balances
   were safe to carry. Do the equivalent check for whatever the current known exploit is — carrying
   balances makes an exploit's proceeds permanent.

## Abandoning a fork WITHOUT a reroll (per-node reset)

When only *some* nodes sit on a dead fork (e.g. they ran old rules while the network moved on), the
network doesn't reroll — those nodes individually abandon their fork:

    sudo scripts/purge_resync.sh        # stop services, wipe chain-derived data, restart

The reborn node re-syncs from its peers; where strict rules refuse an old-rules historical range, it
joins above it via the **snapshot bootstrap** (a donor's finalized checkpoint, verified against the
quorum-settled root) and tail-syncs from there. This is the lightweight alternative to a generation
bump: the canonical chain keeps running, only the stranded nodes reset.
