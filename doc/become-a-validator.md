# How to become a NADO validator

There is no application, no whitelist, no minimum hardware tier and no permission to ask. **Every node
produces blocks.** The only question is which lane you produce in — and one of them costs nothing.

All figures below are the live protocol constants (`protocol.py`). If this document and the code ever
disagree, the code is right and this document is a bug.

---

## The short version

| | Open lane | Bonded lane |
|---|---|---|
| **Cost to enter** | free — no coins | 10 NADO per selection share |
| **Share of block slots** | 30% | 70% |
| **What decides your weight** | presence + continuity (capital-free) | bonded capital, capped |
| **Cap** | — | 1000 NADO (100 shares) per address |
| **Risk** | none | stake is slashable; 24 h unbond timelock |
| **How to start** | open the wallet, press *Start mining* | bond coins you have already earned |

Start in the open lane. It is the fair-launch path, it needs no coins, and it is how you earn the coins
you would later bond. Most people never need the bonded lane at all.

---

## The open lane (free)

**What it is.** 30% of every epoch's block slots are reserved for identities that hold a valid *presence
lease*. Selection weight there is **capital-free**: every present identity gets a flat floor, plus a
loyalty ramp that grows over consecutive renewals. Coins buy you nothing in this lane.

**How you get in.** You register by computing a **sequential proof-of-work** — a non-parallelisable hash
chain that takes about a second, even in a phone browser. It is fee-exempt and post-quantum (it assumes
only blake2b: no trusted setup, nothing a quantum computer breaks). A GPU or ASIC cannot mint identities
in bulk, because the work is sequential by construction.

**It is a lease, not a one-time payment.** The registration is a **renewable presence lease** of about
**24 hours** (240 epochs). To stay eligible you renew with a *fresh* proof — this turns "pay once, farm
forever" into "pay continuously per identity". The miner auto-renews at ~80% of the lease, so once it is
running it keeps itself alive. There is no separate heartbeat: the renewal *is* the presence signal.

**AFK mining works.** One ~1 s proof buys a full day of eligibility whether your phone is locked or not.

### Two ways to run it

**1. Phone or browser — nothing to install**

Open **<https://get.nadochain.com>**, create a wallet, press **Start mining**. That is the whole process.

**2. A real node**

This one line is the only officially supported install:

```
curl -sSfL https://raw.githubusercontent.com/hclivess/nado/main/scripts/install.sh | sudo bash -s -- --service --user nado --pq-native
```

It installs the node as a systemd service and builds the native post-quantum verifier. To have the node
register and renew by itself, add this to its unit and restart:

```
Environment=NADO_AUTO_REGISTER=1
```

Add `--exec` to the install line if you also want the execution node (contracts, the shielded pool, the
DEX). That is optional — L1 validation does not need it.

### What actually maximises open-lane earnings

- **Stay present.** Continuity over consecutive renewals is what builds your weight. A lapse resets it.
- **Mine to ONE address.** Weight does not shard: splitting across addresses gains you nothing, and
  onboarding many addresses from one machine is rate-limited by subnet proximity.
- **Be reachable.** The node's health line should read `Ports open (mineable)`. A node nobody can reach
  still validates, but it is a worse peer.

---

## The bonded lane (optional stake)

The other **70%** of slots. A `bond` transaction moves spendable balance into a non-spendable `bonded`
column; `unbond` + `withdraw` moves it back after a timelock.

- **10 NADO buys one selection share.** (`B_MIN`)
- **1000 NADO is the cap** — 100 shares. Bonding beyond it buys **no** additional weight.
- **Split-neutral.** Weight depends on total bonded capital, so sharding across addresses gains nothing.
- **24-hour unbond timelock** before withdrawn stake becomes spendable again.
- **Slashable.** Equivocation (signing two conflicting blocks for one slot) burns stake. Running the same
  validator key on two machines at once is the usual way people do this to themselves — don't.

There is no premine and no faucet into this lane by design: you mine the open lane first, then bond what
you earned. The wallet's **auto-save** can compound a percentage of your mining rewards into savings
automatically, once per epoch.

> **Common misreading:** a share costs **10 NADO**, not 100. If you have seen 100 somewhere, it was a
> stale tooltip in the wallet (fixed 2026-08-12) — the protocol value has been 10 NADO.

---

## Which lane should someone actually pick?

- **No coins?** Open lane. It is free and it is the only way in from zero.
- **Have earned coins and want more slots?** Bond up to 1000 NADO. Past that you are locking capital for
  nothing.
- **Want maximum participation?** Do both — bonding does **not** remove you from the open lane. A staked
  validator that also holds a presence lease is eligible in both.

---

## Honest status

Betanet is **pre-mainnet**. Balances persist across upgrades and carry forward to mainnet, but consensus
is still hardening, so a genesis reroll remains possible — if that happens, balances are carried across
and it will be announced openly. Bonded stake carries slashing risk. Nothing here is investment advice.
