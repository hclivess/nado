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
| **What decides your weight** | presence + continuity (capital-free) | bonded capital, capped — *and* ramped by the same continuity streak |
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

## How the presence lease actually works (and why it renews late)

**Registration is a lease, not a flag.** A `register` transaction records a *recert* at the current
epoch. You are eligible in the open lane **iff your most recent recert is within `POSW_LEASE_EPOCHS`**.

    epoch          = 60 blocks x 6 s = 6 minutes
    lease          = 240 epochs      = 24 hours

Nothing expires you actively — eligibility is simply "was your last recert within the last 240 epochs?"

**Both miners renew near the end of the lease, on purpose:**

| Who | Renews when | Margin left |
|---|---|---|
| Browser wallet | once `epoch - reg_epoch >= 192` (80% of the lease) | ~4.8 hours |
| Node (`NADO_AUTO_REGISTER=1`) | once `epoch >= reg_epoch + 230` (last 10 epochs) | ~1 hour |

**Why not renew early?** Renewing *resets the clock* — a recert at 50% of the lease buys the same 24 h a
recert at 80% does, so renewing early just pays the sequential proof more often for nothing. And why not
renew at the very last epoch? Because a renewal has to be computed, submitted, gossiped and mined; the
margin is there so a brief outage, a slow block or a missed slot cannot silently drop you out of the lane.

**A renewal is not free and not instant.** It computes a fresh sequential proof (~1 s), and it is an
ordinary transaction that has to land. This is the whole anti-Sybil design: identity costs sequential
real time *continuously*, not once.

---

## Shares — the thing that actually decides how often you win

"Shares" are **selection weight**: the protocol draws one producer per slot, and your chance is your
weight over the lane's total. The two lanes compute weight completely differently.

### Open-lane weight (capital-free)

    open_weight = OPEN_BASE_FLOOR + min(fidelity, FIDELITY_CAP) * OPEN_FID_BONUS // FIDELITY_CAP
                = 2 + min(fidelity, 30) * 8 // 30          ->  ranges 2 .. 10

Coins are irrelevant here. What moves it is **fidelity**, the continuity streak:

- every recert that is **continuous** (gap since the previous one <= 240 epochs, i.e. you renewed before
  the lease lapsed) adds `FIDELITY_GAIN = 1`;
- **a lapse resets fidelity to 1** — not to zero, but the whole ramp is lost;
- it saturates at `FIDELITY_CAP = 30`.

Since a renewal happens about once a day, going from a fresh identity (weight 2) to maximum (weight 10)
takes roughly **30 days of unbroken presence**. That 5x is the entire reward for staying present, and it
is why churned or rotated identities never catch up with a node that simply stays up.

### Bonded-lane shares (capital, capped — and ALSO ramped)

    shares = min(bonded, BOND_CAP) // B_MIN            = min(bonded, 1000 NADO) // 10 NADO   -> 0 .. 100
    if fidelity < FIDELITY_CAP:
        shares = shares * fidelity // FIDELITY_CAP     # the anti-whale time ramp

- **10 NADO = 1 share**, and **1000 NADO (100 shares) is the ceiling** — bonding past it buys nothing.
- **Split-neutral:** weight depends on total bonded capital, so spreading it over many addresses gains
  nothing.
- **The fidelity ramp applies here too**, and this surprises people: capital alone does not buy weight on
  day one. An address that bonds 1000 NADO with fidelity 1 gets `100 * 1 // 30 = 3` shares, not 100. Full
  weight arrives only after the same ~30 continuous recerts. **A whale cannot buy its proportional share
  instantly — it has to also be present, for a month.**

### Putting it together

The two lanes are separate draws (30% of slots open, 70% bonded) and **bonding does not remove you from
the open lane**. A node that registers, stays present, and bonds earned coins is eligible in both, with
both weights ramping on the same continuity clock. Staying online is not merely good practice here — it
is the only input that raises weight in *either* lane.

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
