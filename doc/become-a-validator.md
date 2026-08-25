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
| **What decides your weight** | presence + continuity (capital-free) | bonded capital, capped; new stake ramps over ~3 h by bond age |
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

It installs the node as a systemd service and builds the native post-quantum verifier. **It registers and
renews its open-lane lease by itself** — nothing to configure. (This used to need
`Environment=NADO_AUTO_REGISTER=1` and it no longer does. Two nodes on our own fleet ran for the whole life
of a chain earning exactly zero because that line was missing; a node that mines nothing until you set an
environment variable is a misconfiguration that looks like it is working.) Opt out with
`Environment=NADO_AUTO_REGISTER=0`.

Add `--exec` if you also want the execution node (contracts, the shielded pool, the DEX). L1 validation
does not need it — but **without it the node never auto-collects your presence dividend** (see *Getting
paid* below), so for a mining node it is closer to recommended than optional. This is not a small
difference: on betanet-2 the two mining nodes without an exec node had **25.54 NADO each sitting
uncollected**, while the one with it had 0.03 because it sweeps continuously.

---

## Getting paid — block rewards vs the dividend (and what collects automatically)

Two different things arrive, and only one of them is automatic everywhere.

**Block rewards** land in your balance the moment you produce a block. Nothing to claim.

**The presence dividend** does not. Most of every open-lane block streams into a dividend pool that
accrues to you *off-chain*, on the execution layer, weighted by the same `open_shares()` fidelity weight.
Turning that accrual into spendable NADO is two steps, both of which the software can do for you:

1. `collect_dividend` — sweeps your accrual into a provable withdrawal (costs `MIN_TX_FEE`);
2. `dividend_withdraw` — a **fee-exempt** Merkle proof against the settled exec root that actually moves
   the coins to L1. It can only run once the exec root has **settled**, so expect a delay.

| Where you mine | Collects automatically? |
|---|---|
| Browser wallet (phone/desktop) | **Yes** — it claims pending dividends and sweeps for you. |
| Node **with** the exec node (`--exec`) | **Yes** — on by default (`NADO_AUTO_COLLECT`), once per epoch. |
| Node **without** the exec node | **No.** Nothing collects; the accrual keeps growing unclaimed. |

**That last row is the trap.** The node's auto-collect uses its **local exec node as the accrual oracle** —
it reads your exact accrued balance and only spends the fee once the accrual is worth it
(`AUTO_COLLECT_MIN_RAW` = 0.001 NADO, 10 000x the fee). With no local exec node it deliberately does
nothing rather than burn fees sweeping blind. So an L1-only node **still earns the dividend, but never
claims it**.

If you run a headless node and want the dividend collected hands-free, install with `--exec`. Otherwise
you can always open the same address in the browser wallet and let it claim — the accrual is on-chain
state, not something the node holds locally, so nothing is lost by collecting late.

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
| Node (auto-register, on by default) | once `epoch >= reg_epoch + 230` (last 10 epochs) | ~1 hour |

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

**Fidelity counts RECERTS, not days.** This document previously said reaching maximum weight "takes
roughly 30 days of unbroken presence". That describes what the *default miners* do, not what the protocol
requires. The only spacing rule is **one recert per epoch** — and an epoch is 6 minutes — so 30 recerts
can be spread over 30 days or packed into **3 hours**. Registration is also fee-exempt, so the only cost
is the sequential proof-of-work, whose difficulty rises with recent registration *volume across the
network* (`ops/reg_difficulty.py`), not with how often you personally recert.

Two practical consequences:

- **If your fidelity jumped by more than 1 in a day, nothing is wrong** — your wallet recerted more than
  once. Each recert is +1.
- **Two identities present for the same wall-clock time can have very different weight** (2 vs 10, a 5x
  spread) purely from recert frequency. Weight 10 pays 5x the dividend share of weight 2.

That is worth knowing when comparing your rewards against someone else's.

**Fidelity is paid twice.** The same weight also sets your slice of the **presence dividend** — most of
every open-lane block streams into a dividend pool that is split by exactly this `open_shares()` weight
(`ops/dividend_ops.py`). For a small miner that is usually the larger of the two effects: you are paid
for presence even in blocks you did not win. The dividend recomputes fidelity *as of the paid epoch*
(`fidelity_at_epoch`, reconstructed from your recert history) and that reconstruction must stay
byte-identical to the live ramp — a fraud proof that miscomputed it would false-slash an honest settler.

**Where fidelity does NOT apply:** bonded selection shares (see below), fork-choice weight, and the
settlement/FFG quorum. It is a presence signal for the free lane and the dividend, never a consensus
weight for finality.

### Bonded-lane shares (capital, capped — ramped by BOND AGE, not fidelity)

    shares = bonded // B_MIN                    = bonded // 10 NADO   (linear, no per-identity cap since 2026-08-25)

- **10 NADO = 1 share**, **1000 NADO (100 shares) is the ceiling** — bonding past it buys nothing.
- **Split-neutral:** weight depends on total bonded capital, so spreading it across addresses gains
  nothing.
- **Fidelity does NOT apply here.** The bonded registry is built with `fidelity: None`, which switches
  the fidelity ramp off (`ops/account_ops._compute_bonded_registry`). Fresh stake instead ramps on its
  own clock:

        producer_weight = shares * min(tenure, BOND_RAMP_EPOCHS) // BOND_RAMP_EPOCHS
        tenure = current_epoch - bond_since        (BOND_RAMP_EPOCHS = 30 epochs = ~3 hours)

  So newly bonded stake reaches full producer weight over **~3 hours**, not a month — enough that a
  sudden whale cannot control the very next epoch.
- **That ramp applies to the producer draw ONLY.** It is deliberately excluded from `total_bonded_shares`,
  so fork-choice weight and the FFG/settlement quorum stay ramp-free — finality is never made
  tenure-dependent (`doc/takeover-resistance.md`).

### Reading the wallet's lane panel

The wallet shows two lines that look symmetric and are not. A real example:

    Open lane        115 miners ·  18/60 slots
    Savings lane       8 miners ·  33 shares

| What you see | What it is |
|---|---|
| `115 miners` | `open_registry_size` — identities holding a **valid presence lease right now**. It falls when leases lapse, not when people stop watching. |
| `18/60 slots` | `K_OPEN / EPOCH_LENGTH` — the open lane's **fixed allocation**: 18 of every 60 slots in an epoch, i.e. the 30% split. |
| `8 miners` | `bonded_registry_size` — addresses holding bonded stake. |
| `33 shares` | `total_bonded_shares` — total selection shares across all of them. At `B_MIN` = 10 NADO/share that is ~330 NADO bonded chain-wide. |

**`18/60` is not "18 of 60 slots used".** It is a constant. It does not move with activity, it is not a
progress bar, and a full epoch always awards all 60 slots. It is telling you the lane split: 18 open,
42 bonded, every epoch, forever.

**The two lines have completely different competition.** In that example 115 present identities compete
for 18 slots per epoch, while 8 bonded addresses compete for 42. That is not unfair — it is the design
working as intended. The open lane is the free, Sybil-resistant, many-participant lane, so a single open
miner wins rarely; the bonded lane is capital-gated, so few addresses share more slots. It is also why
**block wins are the wrong thing for a small open miner to watch**: the presence dividend pays you by
fidelity weight in blocks you did not win, and for most people it is the larger number (see *Getting paid*).

Two useful sanity checks: `33 shares` across `8 miners` averages ~4 shares (~40 NADO) each, so nobody is
near the 100-share cap; and if `115 miners` drops sharply, that is leases expiring — usually miners who
stopped renewing, not a network fault.

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
