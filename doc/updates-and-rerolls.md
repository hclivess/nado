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
settled state, as in the alphanet-6 reroll) plus the bumped `CHAIN_GENERATION`. Every node stamps the
generation its on-disk data was built under (`~/nado/chain_generation`); a post-update boot that sees
the code's generation ahead of its stamp **wipes all chain-derived data** — blocks, index, peers,
snapshots, exec state + DA; **never `private/`** (keys, config) — and regenesis/resyncs fresh. The exec
node performs the same check for its own files, so a stale execution layer can never replay a new chain.

Combined with the updater, **one `/update` wave fully deploys a reroll**: pull → restart → purge →
fresh chain. No manual steps on any operator's box.

## Abandoning a fork WITHOUT a reroll (per-node reset)

When only *some* nodes sit on a dead fork (e.g. they ran old rules while the network moved on), the
network doesn't reroll — those nodes individually abandon their fork:

    sudo scripts/purge_resync.sh        # stop services, wipe chain-derived data, restart

The reborn node re-syncs from its peers; where strict rules refuse an old-rules historical range, it
joins above it via the **snapshot bootstrap** (a donor's finalized checkpoint, verified against the
quorum-settled root) and tail-syncs from there. This is the lightweight alternative to a generation
bump: the canonical chain keeps running, only the stranded nodes reset.
