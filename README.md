<p align="center">
  <a href="https://nadochain.com"><img src="graphics/bauhaus.png" alt="NADO" width="520" /></a>
</p>

<p align="center">
    <a href="https://discord.gg/6aEBWTvcTV"><img src="graphics/discord.png" alt="Discord" height="40" /></a>
    &emsp;
    <a href="https://twitter.com/nadochain"><img src="graphics/twitter.png" alt="Twitter/X" height="40" /></a>
</p>

# NADO

**A phone-mineable, fair-launch, post-quantum, lightweight blockchain.**

NADO is built around a **seamless, one-click experience**: every node serves a single **zero-install
browser page** — **wallet, block explorer, miner, and alias manager in one** — at its root URL, so
full interaction with the chain is one tap away from *any* device, with no app, no sync, and no
account. Under that surface, NADO lets an ordinary phone — running nothing but that browser tab — take
part in block production for **zero capital**, on a **fair launch with no premine**, secured by
**post-quantum signatures**. It replaces the Proof-of-Work hash race with a **deterministic,
beacon-keyed weighted draw**: one hash decides each block's producer, so faster hardware (ASICs, GPUs)
confers no advantage and there is nothing to grind. Coins enter circulation only as block rewards.

> **Status: testnet-stage alpha, NOT yet mainnet-launched.** The fair-mining economics and the full
> consensus-security hardening plan (objective fork-choice, enforced finality, grind-proof chain
> weight, detached winner signatures + **equivocation slashing** (block-authorship + FFG attestation),
> **enforced FFG stake-attested finality**,
> **commit-reveal RANDAO**) are now implemented; the multi-node, epoch-crossing behaviour of the last
> three is still only lightly exercised empirically (see [Security](#security)). What genuinely remains
> is a subset of **eclipse hardening** (ASN-level peer diversity, pinned multi-seed bootstrap, snapshot-
> bootstrap binding to a finalized signed checkpoint). On top of consensus, a **STARK-proven execution
> layer** (a field-native zkVM) is live and carries real dApps — ~20 on-chain games, shielded transfers,
> and end-to-end-encrypted on-chain messaging. Run it on testnet / at your own risk; do not secure value
> of consequence with it yet. The betanet **rerolls often** (fresh genesis, balances carried forward) as
> consensus changes land strictly with no backward-compat; the current chain id is `betanet-6`.

---

## Why NADO

Most "anyone-can-mine" coins fail in one of four ways: mining gets captured by specialized hardware;
the launch isn't fair (premines, insider allocations); the cryptography isn't quantum-resistant; or
a "light" client still leans on trusted infrastructure. NADO targets all four at once, and adds a
fifth goal — that **re-joining the network should never get harder as more people join**.

It is inspired by NANO, IDENA, NYZO and Vertcoin, and pushes the barrier to entry lower than any of
them: no puzzles to keep solving, no efficient rig to keep running, and no requirement to own coins.

## Key features

- **Seamless — one client, any device, one tap.** Every node serves a single browser page (`/`) that
  is at once the **wallet, block explorer, miner, and alias manager** — and, via a **Rollup tab**, a
  window onto the execution layer that browses, deploys and calls contracts. No install, no browser
  extension, no full node, no signup, no seed-phrase ceremony. **Unlike a MetaMask-style extension
  wallet** — which only *holds keys*, can't mine, and means "install the extension, back up a seed, buy
  gas, connect to a dApp" before you do anything — NADO is just a URL. Open it and you're already a full
  participant: generate a post-quantum wallet, mine, send/receive, register a human-readable **alias**,
  and browse the chain, all from one link on any phone or laptop.

- **A real execution layer, already live.** Beyond payments, NADO runs a **field-native zkVM** whose
  state is settled to L1 under **STARK proofs** (objective, stake-backed finality — L1 verifies a Merkle
  proof against a bonded-quorum-settled root, not a re-execution). On it today: **~20 provably-fair
  on-chain games** (dice, roulette, poker/hold'em, blackjack, mines, an original settlers-genre strategy
  game, an auto-battler, a deck-builder, tamagotchi-style NFT pets, and more — each with its own
  subdomain), **shielded transfers** (a private payments pool), and **end-to-end-encrypted on-chain
  messaging** (ML-KEM-768) — so you can DM any address with no off-chain server. Randomness for games is
  pinned to **future block hashes** (nobody can rig a roll); hidden information (hole cards, fog-of-war)
  uses **commit-reveal**. Games self-serve from the wallet's background signer — no per-move wallet
  round-trip.

- **Everyone mining earns — a presence dividend, not a lottery.** Winner-take-all blocks mean most miners
  see *nothing* for long stretches. NADO redistributes most of the open lane's block reward to **everyone
  present**, weighted by how steadily they show up — a steady stream instead of a rare jackpot. It accrues
  **off-chain** while you mine (so a million miners cost the chain nothing and there's no dust bloat), and
  you sweep it into your spendable balance with one **Collect** tap — claimed trust-minimised against a
  bonded-quorum-settled state root. Many people getting a little, continuously: what an open, populace-scale
  chain should actually feel like. (Design + mechanism: [doc/presence-dividend.md](doc/presence-dividend.md).)

- **Mine from your pocket — and *forever* if you keep it open.** Presence is a **device lease**: one tap on a
  real device buys 36 h of eligibility, so a **locked, asleep phone keeps mining** on its own — no relay, no
  per-epoch traffic — and the wallet shows the exact "mining while locked" countdown. Leave the page
  **open and mining never stops**: it renews the lease just before it lapses (a Ledger or Trezor renews
  without a prompt), auto-bonds your rewards
  if you want, and auto-resumes across a browser refresh — so direct mining runs **indefinitely with zero
  babysitting**. Open the link once and walk away.

> **Share the link, and the barrier to entry collapses.** Because the whole experience is one page with
> no install step, onboarding *is* sending a link. Drop it in a school group chat and whoever opens it is
> instantly mining — and each of them shares it again. No app store, no wallet setup, no gas to buy
> first: the distance between "hears about NADO" and "is mining and transacting on NADO" is a single tap.
> Lower the barrier to entry to a shared URL and let it spread — one classroom becomes the whole school.
> That is the growth thesis.
- **Phone-mineable.** Block production is one hash per slot over a public beacon, not a race — a
  phone competes on equal terms with a datacenter. Winners are credited **by address**, so a phone
  can win a block while its tab is closed and a relay assembles the block on its behalf.
- **Fair launch, no premine.** Genesis mints **zero** coins (`TREASURY_GENESIS = 0`). Every coin in
  existence was minted as a block reward. A flat base subsidy lets a brand-new, zero-coin miner earn
  spendable coins from block 1.
- **Governed, self-burning treasury.** The 10% treasury is a **keyless** reserved account — no founder
  key, no multisig — spent only by a **2/3 bonded-stake vote** in the wallet's Quorum tab, and any idle
  balance is **burned each period**. Emission holders would get anyway is forced into the ecosystem by
  their own vote, or destroyed — never hoarded (`doc/treasury.md`). Even the **maintainer's reward** is a
  votable, revocable quorum grant (guideline ~1% of treasury inflow) — **not** a hard-coded founder cut.
- **Consensus anti-Sybil registration (PoSEA).** A registration carries a hardware attestation from a real
  device — an Android phone, a Windows TPM, a Ledger or a Trezor Safe — verified by **every node** against
  vendor roots pinned in the protocol, and the device's certificate is bound to that identity: one device,
  one identity. Identity farming needs genuine hardware and a human tap per identity per lease
  (`doc/device-attestation.md`).
- **Two-lane "diligence" mining.** A free **OPEN lane** anyone can win with no coins (capped at ~30%
  of blocks, a *population-independent* Sybil ceiling) plus a **BONDED lane** won with refundable,
  whale-capped stake. Bonding is **optional** and only boosts the bonded lane — never required.
- **Post-quantum signatures.** ML-DSA-44 (NIST FIPS 204 / Dilithium) via pure-Python `dilithium-py`
  — no native build, in keeping with the lightweight goal. Cross-validated against the browser's
  `@noble/post-quantum` so a phone and a full node verify each other.
- **Lightweight & reproducible.** Consensus hashing is over canonical JSON, so a browser client
  reproduces every address, transaction id, and verification byte-for-byte. State is a single
  memory-mapped key-value store; block bodies are compact zstd-compressed blobs.
- **First-party clients.** A browser/mobile NADO Interface that is also a full wallet, and browsable
  explorer endpoints on every node.

---

## How mining works

> **Just want to start validating?** → **[How to become a NADO validator](doc/become-a-validator.md)** —
> the practical version: the free open lane needs no coins, one line installs a node, and a bonded share
> costs 10 NADO. This section is the mechanism behind it.

Time is divided into **epochs** of `EPOCH_LENGTH = 60` slots, each keyed by a per-epoch randomness
**beacon**. For each slot the protocol deterministically draws exactly one producer.

### Draw, not race

For a given slot the winner is a single computation over the public beacon:

```
draw   = int( blake2b([beacon, slot]) ) % total_weight
winner = the address whose cumulative-weight band contains `draw`
         (walking eligible addresses in canonical sorted order)
```

There is **no multi-attempt hash race and no nonce grinding** — one hash decides each slot. Faster
hashing hardware therefore confers *no advantage*, and any full node or browser client reproduces the
same winner from public chain state. Because the winner is chosen *by address*, an offline phone can
win a slot and a relay can build and broadcast the crediting block for it.

### Two lanes per epoch

Each epoch's 60 slots are split by a **beacon-keyed permutation of slot indices** into two lanes:

- **OPEN lane** — `K_OPEN = 18` slots (~30%, `OPEN_BPS = 3000`), winnable by any registered, present
  identity for **zero coins**.
- **BONDED lane** — the remaining 48 slots, won in proportion to locked, refundable stake.

The split is over *slot indices*, not per-identity weight, so there are always exactly `K_OPEN` open
slots **no matter how many identities register**. A zero-capital botnet of a million identities still
cannot win more than `OPEN_BPS` (30%) of blocks. This **population-independent structural ceiling** —
not a puzzle difficulty or an economic cost — is NADO's central Sybil defense. (Empty-lane policy is
one-directional and fail-closed: an empty open slot falls back to the bonded lane, but an empty
bonded slot is skipped, never the reverse, so the free lane can never absorb bonded slots.)

### The OPEN lane (free)

1. **Register** with a **device statement** (PoSEA — see below): the wallet asks the device's secure hardware
   for an attestation over a chain-chosen challenge, wraps it in a fee-exempt `register` transaction, and every
   node verifies the vendor certificate chain in consensus (`validate_transaction`, the block-validation path)
   — not just the relay you connect to, so a bogus registration is rejected network-wide. Registration is a
   **renewable presence lease** (`POSW_LEASE_EPOCHS` = 360 epochs, 36 h): a phone or a TPM re-attests on every
   renewal; a Ledger or Trezor is bound for life and renews with a statement-free `register` signed by the
   account key. The device certificate is **bound to the identity** for the lease, so the same device cannot
   hold a second identity meanwhile. The structural ~30 % lane cap (`OPEN_BPS`) is still the *hard* Sybil
   bound; the device rule prices identity creation in real hardware on top. The renewal is the **single
   presence signal — there is no separate heartbeat.** You're eligible iff your lease is live, so **AFK mining
   is trivial: one tap buys a full lease of eligibility, locked phone or not** — no relay, no pre-signed
   heartbeats, no per-epoch traffic. The miner auto-renews at ~80 % of the lease; kept open, it mines *forever*.

> **Why no separate per-epoch heartbeat?** An earlier design had one. But once the lease covers the whole
> 36-hour AFK window, a per-epoch heartbeat is co-terminal with the lease and carries no information the
> renewal doesn't — redundant. Collapsing to one signal is strictly simpler: the renewal **binds the device
> *and* marks presence**. The ~30 % lane cap stays the hard Sybil bound regardless.

Open-lane selection weight is **capital-free**: a flat floor (`OPEN_BASE_FLOOR = 2`) every present
identity always gets, plus a diligence ramp to `OPEN_FID_BONUS = 8` over `FIDELITY_CAP = 30` **consecutive
renewals** (overall range 2..10). Fidelity is **continuity over renewals** (`apply_register`,
revert-symmetric): a continuous renewal adds a step, a lapse halves the streak — so a rotated/churned
identity can't keep a ramp it stopped paying for. The single most effective thing you can do is **stay
present**. Mine to **one address** — a second address needs a second real device.

> **Free-lane blocks are for device-only miners (from block 6600 of betanet-7).** An identity holding one
> bonded share (10 NADO) or more is not drawn for OPEN slots — it produces in the BONDED lane instead. The rule
> is per device, so a staker cannot keep a second wallet in the free lane without a second device. The
> **presence dividend is unchanged**: every attested device is paid by fidelity, staked or not.

### The BONDED lane (optional stake)

A `bond` transaction moves spendable balance into a non-spendable `bonded` column; an `unbond`/`withdraw`
pair moves it back out after a timelock (see below). Bonded **producer** weight is per attested device, on a curve
(`mining_ops.bond_weight`, from block 11800 of betanet-7; a hard 1,000 NADO cap per device from block 4200 before that):

- **Attested only.** A bonded identity is drawn for producer slots only while it holds a live device lease
  (`bonded_producer_registry`). Unattested stake weighs **zero** in the draw — anything softer is dodged by splitting
  keys. It still votes for finality and still counts as fork weight (`total_bonded_shares` stays linear and
  attestation-free, so finality never depends on how many devices exist). If no bonded identity is attested at all,
  the draw falls back to plain stake weight so a bonded slot never stalls.
- **The curve.** Stake counts one-for-one up to a **knee** = max(1,000 NADO, 5 % of the *other* attested devices'
  stake) — a device's own stake never lifts its own knee — then flattens: weight = K·(1.5 − 0.5·K/stake), continuous
  with slope 1 at the knee, saturating at **1.5 K**. Every extra coin still counts, just less, and no single device can
  ever count for more than one and a half knees. Chosen by simulation (single whale, split whale, 40-phone farm,
  100-device lane, 10,000-device lane): a 500,000 NADO whale on a 10,000-device lane wins ~6 % of bonded blocks (12 %
  uncapped), a 3,000-phone farm gets its stake share and nothing more, and 94 % of all stake still counts.
- **Split-neutral below the knee, one device per knee above it.** Sharding capital across keys gains nothing;
  sharding it across *devices* is the only way to more weight — and a device is the one thing a farm cannot mint.
  The old per-KEY cap (removed 2026-08-25) never bound a whale because a second key restored linear weight; a cap
  per **device** is different in kind. `/mining_status` reports `my_bonded_effective` and `bond_knee`.

#### Staking pools (from block 6000 of betanet-7)

Capital without a device may **rent** one. A holder points their bonded stake at an attested identity with a
fee-exempt `delegate {to}` transaction; the pool produces with own + delegated stake under the same curve, and when it
wins a bonded block the chain **splits the reward in that same block**, pro rata by stake, minus the pool's fee
(`reward_ops._pool_split`, journaled and reverted integer-for-integer). Coins never leave the delegator's account,
`undelegate` is instant, and a delegator has no producer weight of its own (it still votes for finality with its own
stake and still earns the presence dividend if it holds a device).

- **Running a pool**: any identity with bonded stake and a device sends `pool {fee_bps 0..10000, open 0|1, min ≥
  10 NADO, max ≤ 100 M NADO, label ≤ 32 ASCII}`; another `pool` tx changes the terms, `pool {close: 1}` releases every
  delegator in that block. Up to 1,000 members per pool. A delegator cannot run a pool; a pool cannot delegate.
- **Why pools do not reopen the Sybil hole**: every unit of producing weight still sits on one real attested device,
  on the same curve. A full pool pays each delegator less per coin, so capital spreads to emptier pools by itself. What
  a pool changes is *who owns the capital* on a device — not how many devices the network sees.
- **Wallet**: the Stake card's *Staking pools* panel — your status, the picker (open attested pools, cheapest first,
  room, members), Delegate / Undelegate, *Run a pool* with fee, name, minimum, maximum, open, and *Close pool*.
  `GET /pools` lists every pool with its terms, own and pooled stake and room. The relay fleet runs the zero-fee
  pool **nadochain.com**.

> **Bonded lane + FFG finality — now active.** At the **10-NADO** entry the bonded registry is
> **populated** and blocks began producing on the bonded lane the moment `B_MIN` dropped. At the old
> 1,000-NADO entry nobody on a fair launch could grind enough to bond, so the registry sat **empty** and
> every block fell back to the zero-stake OPEN lane — no economic weight behind blocks. Now each lane
> carries distinct security: the **OPEN lane** is Sybil-capped *presence*, the **BONDED lane** is
> stake-weighted *capital* that both draws its share of producers and backs finality. A validator that
> signs **two blocks at the same height+parent** — or **two conflicting FFG attestations** for one epoch —
> is slashable via a portable proof (below), and **FFG** (Casper-style stake-attested epoch checkpoints,
> justifying at a **strict >2/3** quorum) now **enforces** finality: a justified→finalized checkpoint is
> folded into the persisted rollback floor, so a >2/3-attested checkpoint is **objectively un-reorgable**
> (remote sync can't adopt a conflicting heavier chain) — it is no longer merely observed. **Honest scope:**
> FFG does **not** speed up confirmations — confirmation finality is still the depth-based floor at
> `tip − FINALITY_DEPTH` (**~12 blocks**), and FFG (**epoch-granular**, 60 blocks) normally *trails* that
> floor. FFG is the **objective, accountable, long-range** finality layer on top of the fast **subjective**
> depth floor, never a latency reduction, and it can never stall the chain: the quorum denominator is the
> *active* bonded set (validators that attested within `INACTIVITY_WINDOW = 3` epochs), so a bonded validator
> that goes dark is **leaked from the finality quorum** (its vote lapses, its bond untouched) and a live
> attesting majority can always finalize.

> **Bonded mining is passive — no work beyond keeping the device lease.** Once you hold enough to bond (`B_MIN =
> 10 NADO`), the bonded lane is **staking**: there is nothing to compute and no node to run — the beacon draws
> you in proportion to your (curved) stake, and because winners are credited **by address**, a relay builds your
> winning block even while you're offline. The one upkeep is the device lease: a phone or TPM re-attests every
> 36 h from the open wallet, a Ledger or Trezor attests once for life and the lease renews itself. No device?
> Delegate to a pool (above). With **auto-bond** on, rewards compound straight back
> into stake, so it grows hands-free. Two honest caveats: (1) a *freshly* bonded stake ramps to full
> selection weight over `BOND_RAMP_EPOCHS` (~30 epochs) — an automatic anti-sudden-whale delay, no action
> needed — after which it earns at full rate; (2) your share is **competitive** (proportional to your slice
> of *total* bonded stake), and this lane is **rich-get-richer by design** (stake = yield, as in any
> Proof-of-Stake). The capital-*free* path — the OPEN lane + presence dividend — is the counterweight for
> anyone without coins, and it's the part that actually requires (light, phone-doable) mining.

> **Unbond is now timelocked (enforced).** `unbond` is a **release request**, not an instant refund:
> the stake **stays in the `bonded` column — still slashable** — and a maturity block
> `release_block = current + BOND_UNLOCK_DELAY (1440)` is recorded. A separate fee-exempt **`withdraw`**
> transaction moves the matured amount to spendable balance only **at/after** `release_block`. Keeping
> the stake bonded through the delay is what keeps a *caught equivocator's* stake slashable while the
> unbond is in flight. One unbond may be pending at a time.

---

## Economics

`protocol.py` is the economic source of truth. All on-chain amounts are integers in raw units, where
**1 NADO = `DENOMINATION` = 10,000,000,000 raw** (the smallest unit is 0.0000000001 NADO).

- **No premine.** Genesis mints zero coins; the chain bootstraps purely through the open mining lane.
- **Per-block reward = a FLAT base subsidy scaled by bonding** — `reward = BASE_SUBSIDY (0.1 NADO) · m(r)`.
  No fee-weighted term and **no ceiling** (the old `REWARD_CAP` is removed): fees are destroyed, so minting
  more when fees rise would only soften the deflation. Since `m(r) ≤ 1`, **0.1 NADO is the max emission per
  block** (~1,440 NADO/day at the 6 s `block_time`), and `m·BASE ≈ 0.0166` the min (perpetual tail,
  ~87,000 NADO/yr forever). Emission is per-block, so `block_time` (default 6 s) is the emission-*rate* lever.
- **Bond-elastic emission → super hard money** (`doc/bond-elastic-emission.md`). `m(r) = 0.15 + 0.85·e^(−4r)`
  (tuned), where `r` is the **bonded ratio** (bonded ÷ total supply): the more the network locks up, the less it
  mints. Combined with fee destruction this makes NADO **net-deflationary under real usage**, while the
  **perpetual tail** (`m` never reaches 0) means block production is *always* rewarded — **no hard cap, no
  security cliff** (Monero's reasoning). It self-limits: the open lane siphons `OPEN_BPS`=30 %, so bonding
  past ~70 % is real-negative and the ratio settles ~40 %. `m(r)` is a **hardcoded integer table** in
  `protocol.py` (never a runtime float — a last-ULP difference could fork consensus), read from committed
  parent state exactly like `cumulative_weight`.
- **90 / 10 split.** The producer keeps 90 %; **10 % accrues to the treasury** (`TREASURY_BPS = 1000`).
  The treasury is a **reserved, keyless `treasury` account** (no private key exists for it) that starts
  empty and fills only from this per-block cut.
- **Quorum-governed, self-burning treasury** (`doc/treasury.md`). The treasury is spent **only** by a
  **2/3 bonded-stake vote** — no founder key, no multisig; the bonded lane *is* the multisig, reusing the
  same `settlement_justified` quorum as finality. A `treasury_spend` proposal is voted with fee-bearing
  `treasury_vote`s (each approval's weight snapshotted at vote time; newly-bonded stake must age before it
  counts), capped at `TREASURY_MAX_SPEND_BPS` (25 %) of the balance per proposal, and paid by a
  `treasury_execute` once the quorum is met. Idle treasury above a floor is **burned every
  `TREASURY_SPEND_PERIOD`** (`TREASURY_BURN_BPS` = 1 %/period), so emission that holders would receive
  anyway is *forced into the ecosystem by their own vote — or destroyed*, never hoarded. Stakers propose
  and vote from the wallet's **Quorum tab**.
- **Fees are destroyed**, not paid to producers — that is what drives the elastic reward (it is a fee
  mechanic, not a "burn"; the old burn-to-bribe mechanic was removed entirely). A deterministic floor
  `MIN_TX_FEE = 1000` raw applies to ordinary transfers and `bond`; `register`, `unbond`,
  and `withdraw` are fee-exempt (they move no coins out — `unbond`/`withdraw` only retime the sender's
  own stake).
- **No free→capital faucet.** Open-lane presence can never mint bonded stake; the only path from free
  to capital is the block subsidy an open miner actually earns — itself capped at `OPEN_BPS` (30 %).

---

## Quickstart — run a node

> New validator? **[doc/become-a-validator.md](doc/become-a-validator.md)** walks the whole path end to
> end (open lane vs bonded, what each costs, what actually raises your weight).

NADO runs on Python 3.10+. The entrypoint is `nado.py`; the node serves its API and web UI on port
**9173**.

### Install

> ### This one line is the ONLY official, supported way to install or run a NADO node.
> There is no manual setup, no hand-rolled venv, no `pip install -r requirements.txt`, no `nohup`, no
> Docker image. Those paths are **unsupported** — a node installed any other way falls off the update
> path (`/update` refuses a directory that is not a git checkout), drifts out of consensus as protocol
> changes ship, and will not be helped. If you already run a node that was installed some other way, run
> this command on it: it repairs the install in place.

```bash
curl -sSfL https://raw.githubusercontent.com/hclivess/nado/main/scripts/install.sh | sudo bash -s -- --service --user nado --pq-native
```

No checkout needed — piped standalone, the script installs `git` if missing, clones the repo itself,
builds the venv, installs the node dependencies, and registers a **systemd service** that boots on start
and restarts on failure.

`--pq-native` builds the native Rust ML-DSA verify backend (it installs Rust via rustup automatically if
missing). **Strongly recommended:** signature verification is the node's main CPU cost, and a node left on
the pure-Python fallback is ~84× slower per verify — under transaction load it cannot verify full blocks
within the block interval and **falls off the tip**. The installer auto-installs both a Rust toolchain and a C
linker (`build-essential`/`gcc`) — cargo needs `cc` to link, so a truly minimal box would otherwise fail
with ``linker `cc` not found``. If the build still fails it prints the reason and the full log path and the
node runs pure-Python meanwhile. Finish it by hand after fixing the cause:

```bash
sudo apt install build-essential          # (or: sudo dnf install gcc) — only if `cc` was missing
cd <checkout>/native/mldsa44 && cargo build --release
sudo scripts/install.sh --service --user nado --pq-native   # re-run: bakes the env var into the unit
```

Confirm it took: `curl -s localhost:9173/status` should show `"pq_backend":"native:nado_pq_native"` and
`"pq_degraded":null`. Drop the flag only on a box where you cannot install a Rust toolchain.

`--user nado` runs the node as a dedicated **non-root system account** instead of root: the checkout and
chain data live at `/srv/nado-home/nado`, the units get a hardening block (`NoNewPrivileges`,
`ProtectSystem=strict`, no capabilities), and a root-owned restart bridge keeps self-update working end to
end. An existing root install is migrated in place — services stopped cleanly, directory moved, a
compatibility symlink left at the old path — and later re-runs auto-adopt the account, so nothing ever
quietly hands the node back to root. Omit the flag only if you have a reason to keep the node running as
the invoking user.

It is also the **universal upgrade / repair** command. Re-running is always safe (idempotent). If it finds
a node laid down by an **older, git-less installer** it converts that directory into a real checkout in
place and fast-forwards it to the latest code — your `private/` keys and `blocks/` / `index/` chain data
are gitignored, so nothing it does can touch them. Any node, however it was first installed, gets current
by running this again.

> **Check the path first.** If your node lives somewhere non-standard, pass `--dir /path/to/your/nado` —
> otherwise you install a *second* node and the original stays stale. (With `--user nado` the standard
> locations are found automatically: an install at `~/nado` is migrated to `/srv/nado-home/nado` and a
> symlink keeps the old path working.)

Flags: `--user <name>` runs everything as a dedicated non-root account (recommended, see above); `--exec`
also runs the execution / shielded-pool node on `:9273` (**recommended for a mining node — without it the
presence dividend is never auto-collected**, see below); `--wallet` adds the desktop-wallet deps;
`--auto-bond <pct>` auto-compounds mined rewards (see below); `--home <dir>` keeps chain data under
`<dir>/nado` instead of `~/nado`. Run `scripts/install.sh --help` for all options.

Once running, open <http://127.0.0.1:9173> for the node's web interface and JSON endpoints. To join a
network, announce your node to a peer:

```
http://127.0.0.1:9173/announce_peer?ip=<peer-ip>
```

For public reachability and rewards, forward **port 9173**. Always stop the node cleanly — `systemctl stop
nado`, or `http://127.0.0.1:9173/terminate` — never `kill -9`, which can corrupt the database. To wipe
local data and resync from scratch, stop the service and run `nado_venv/bin/python purge.py` from the
checkout: it clears the chain state (`blocks/`, `index/`, `logs/`) under your data home while keeping your
keys and peers; on the next start the node rebuilds genesis (re-seeding the public bootstrap) and resyncs
from the network.

### Operate the service

The install above already runs the node unattended — it **mines on its own**, starts on boot, restarts on
crash, and needs no open terminal. To manage it:

```bash
systemctl status nado        # health
journalctl -u nado -f        # live logs
systemctl restart nado       # pick up new code after a manual pull
systemctl stop nado          # clean shutdown (never kill -9 — it can corrupt the DB)
```

Common variants (re-run the one-liner with these appended, or `sudo scripts/install.sh` from the checkout):

```bash
--service --user nado               # run as a dedicated non-root account (recommended; migrates in place)
--service --auto-bond 25            # auto-bond 25% of mined rewards
--service --home /srv/nado-data     # chain data in /srv/nado-data/nado
--service --exec                    # execution / shielded-pool node on :9273 (also enables dividend auto-collect)
```

### Auto-bond — compound mined rewards into stake, hands-free

A miner routes a **percentage of newly-mined rewards straight into bonded stake**, auto-compounding
their weight in the bonded lane without any manual `bond` transactions. It is **on by default at
`AUTO_BOND_DEFAULT_PERCENT = 80%`** (a fresh node / browser / wallet with no saved preference joins the
bonded lane hands-free) and fully **overridable** — set `0` to keep all rewards spendable; an explicit
`0` is remembered and never reverts to the default. It is throttled to **at most one bond per epoch**,
only fires once the accrued amount clears a small dust floor (so each bond dwarfs its tiny fee), and
**never stops** (every bonded coin still adds weight — one-for-one below the device's knee, flattening above
it — so it never needlessly freezes coins). It is available in **all three clients**:

- **Node (unattended):** set `auto_bond_percent` in `private/config.json`, or the
  `NADO_AUTO_BOND_PERCENT` environment variable (which the `--service` installer wires into the unit).
  The node bonds the configured share of its own block rewards each epoch — ideal for a headless miner.
- **Browser interface:** the **Stake** tab has an "Auto-bond mining rewards" field; while the tab is
  mining it compounds that share of your rewards (persisted in the browser).

It is a **client/operator convenience and is never validated on-chain** — every auto-bond is just an
ordinary signed `bond` transaction.

### Keeping a node up to date

NADO nodes update themselves. Two mechanisms:

- **Integrated updater (`/update`).** Any node running current code exposes a harmless `/update`
  endpoint — hitting it makes the node **fast-forward-pull the official `main`** (pinned to
  `github.com/hclivess/nado`, ff-only, never an arbitrary branch), then relaunch its services. It also
  **waves the request to its peers**, **checks on its own every 15 minutes**, and — the part that makes
  fleet versioning near-real-time — **reacts to peer hints**: the moment any peer's status advertises a
  commit a node does not recognize, that node checks origin immediately. So the first node to pick up a
  push (timer or nudge) pulls the entire mesh current within seconds; a hostile peer controls only *when*
  a node glances at the canonical repo, never *what* it pulls. A node's latest applied commit is visible
  in `/status` (`running_commit`).

- **Self-healing updatability (startup check + auto-repair).** A node that *cannot* update is not merely
  stale — since consensus changes ship with no backward compatibility, it eventually **diverges and forks**.
  So at boot (and again daily) the node checks whether it could update *at all*: is `git` installed, is
  this a real checkout, does `origin` point at the official repo, and is there a **systemd unit** so an
  applied update actually restarts the process. If any of those fail it logs the defect loudly and
  **repairs itself by running its own `scripts/install.sh --service`** — the local installer that ships
  with the node, never a download. The verdict is published in `/status` as **`update_capable`**, so a
  node that will drift is visible from the outside instead of discoverable only by calling `/update`.
  An **unreachable origin is a warning, never a failure** — treating a GitHub outage as fatal would take
  the whole fleet down at once.

  > Why this exists: a fleet sweep found **21 of 25 peers reporting `running_commit: null`** — installed
  > by hand or by an old installer, so they could never self-update and could not even be version-checked.
  > Three more had current repos but stale running processes, because nothing existed to restart them.
  > Note the limit: a node already in that state **cannot receive this fix** (that is the defect). It stops
  > the fleet rotting into it again; the stranded ones still need their operator to run the one-liner once.

- **The installer one-liner** (above) is the fallback for a node too old to have `/update`, or one laid
  down by an **old git-less installer**: re-running it installs `git`, converts the directory to a real
  checkout, and fast-forwards it — keys and chain data preserved. *Old nodes with no `/update` and no
  `git` cannot be reached remotely; their operator must run this one line once to rejoin the update path.*

- **Fork resolution — one measurement, one decision.** Recovery used to be *inferred* from chain weights,
  donor behaviour and peer benching across five overlapping paths. Those mis-fired together on 2026-07-20:
  a node that was simply ~500 blocks **behind on the correct chain** read that as "forked", rolled back
  into a snapshot with no history beneath it, and looped for 40+ minutes. The inference is gone, replaced
  by a single measured number — **the highest height where our block hash equals the majority's**:

  | measurement | state | action |
  |---|---|---|
  | ancestor == our tip | `BEHIND` | ordinary forward sync — **never** a rollback |
  | ancestor ≥ finalized | `REORG` | roll back to the ancestor, then sync |
  | ancestor < finalized | `DEAD_FORK` | finality forbids the rollback → **purge chain data + resync** |
  | no majority / peers silent | `UNKNOWN` | do nothing |

  Hash equality at a height is a fact, not a heuristic, and the binary search costs ~log₂(depth) probes.
  It asks peers **directly**, so it cannot be blinded by a collapsed peer set or a wrong bench — both of
  which happened. `DEAD_FORK` is the case that previously required a human: it is now automatic, but
  deliberately hard to trigger (frozen tip for 15 min, two independent probes must agree, **any** peer
  agreeing with us vetoes it), because the remedy destroys chain-derived data. `private/` is never touched.

**Genesis rerolls.** Because consensus changes ship **strictly, with no backward compatibility**, the
betanet occasionally **rerolls to a fresh genesis** (balances carried forward from the prior chain).
This is signalled in the code by a bumped `CHAIN_GENERATION`: on the next update a current node
**automatically wipes its old chain data and boots the new genesis** — no manual step. (Keys in
`private/` are never touched.) A node that has fallen too far behind to auto-detect the reroll clears
its old state with `scripts/purge_resync.sh` and rejoins.

Two more unattended behaviors round out a hands-free headless node (both best-effort, once per epoch, never
disrupting consensus):

- **Auto-collect the presence dividend** — **on by default** (`auto_collect_dividend` / `NADO_AUTO_COLLECT`):
  sweeps your accrued dividend into a provable collection, then claims it to L1 with the fee-exempt
  `dividend_withdraw` proof once the exec root settles. Skipped unless the node is an open-lane member
  (a bonded-only node accrues none, so it never burns a wasted fee).
  > **Needs the exec node (`--exec`).** The LOCAL execution node is the accrual oracle: auto-collect reads
  > your exact accrued balance from it and only spends the fee once the accrual is worth it
  > (`AUTO_COLLECT_MIN_RAW`, 10 000x the fee) rather than sweeping blind. **An L1-only node still EARNS the
  > dividend but never collects it** — the accrual just grows. Either install with `--exec`, or open the
  > same address in the browser wallet, which claims for you. Nothing is lost by collecting late: the
  > accrual is on-chain state, not something the node holds.
- **Auto-register the open lane** — **opt-in** (`auto_register` / `NADO_AUTO_REGISTER=1`): keeps the
  presence lease alive (renews inside the lease tail), so a server can mine 24/7 unattended. A node cannot
  attest itself: bind it to a Ledger or Trezor once from the wallet's Mining page (*Attest a node you run*)
  and it renews statement-free from then on; a phone or TPM has to re-attest it every 36 h. Off by default so a headless node never silently joins — and Sybil-loads — the open
  lane. Full reference: **[doc/cli.md](doc/cli.md)**.

### Local multi-node testnet

A self-contained harness spins up N nodes on `127.0.0.x` loopback IPs, meshes them, and reports
whether they converge and produce blocks:

```bash
python scripts/testnet/run_testnet.py [num_nodes=3] [run_seconds=240]
```

It uses throwaway temp dirs and sets `NADO_TESTNET=1` per child (relaxes the SSRF guard for loopback).
**Never set `NADO_TESTNET` on a real node.**

### Ubuntu notes

For a production-style node, raise the open-file limit (`/etc/security/limits.conf`:
`root soft/hard nofile 65535`, `fs.file-max = 100000` via `sysctl`). The installer handles Python and the
venv itself; update with `/update` or by re-running the one-liner — never by hand-pulling, which leaves the
running process on the old code until you `systemctl restart nado`.

### Windows

Not a supported node platform — the installer targets Linux with systemd. To mine from Windows, open any
running node's light-miner in a browser (see [Mine from a phone](#mine-from-a-phone)); it needs no install
at all. For a full node, use a Linux VM or WSL2 and run the one-liner inside it.

---

## Proof of Secure Element Attestation (PoSEA)

NADO's Sybil resistance is **PoSEA** — Proof of Secure Element Attestation, pronounced "posee": every open-lane
identity is a genuine device whose secure element vouches for it, and one device holds one identity at a time.

A registered mining identity must prove it runs on **real hardware**. When the wallet registers (and on
every lease renewal, every 36 h) the device's secure hardware creates a hardware-bound key and returns a
WebAuthn *attestation*: a statement signed inside that hardware whose certificate chain ends at a vendor
root **pinned in protocol**. Nodes verify every signature of the chain, the validity window at the anchor
block's time and the vendor-specific extensions with a native kernel (`native/attest`), identically on
every node; roots are never fetched and change only by a protocol commit.

| you mine on | what attests | root | one identity per device |
|---|---|---|---|
| Android phone (Android 12+, locked bootloader) | TEE / StrongBox | Google hardware-attestation roots | yes — the device's attestation certificate is bound to your identity for each lease |
| Windows PC | a physical TPM 2.0 via Windows Hello | Microsoft TPM Root CA 2014 (virtual TPMs refused) | yes — the TPM's AIK certificate is bound |
| Ledger (Nano S / S Plus / X, Stax, Flex), Chrome/Edge/Brave on a computer | the device's factory-certified secp256k1 key, via Ledger's own genuineness handshake (WebHID) | Ledger issuer key | yes — the device key is bound |
| Trezor Safe 3 / 5 / 7, Chrome/Edge/Brave on a computer | the secure element's per-device certificate, via `AuthenticateDevice` (WebUSB) | Trezor root key per model | yes — the device certificate is bound (Trezor One / Model T have no secure element: refused) |
| FIDO2 security key | its batch certificate | vendor root from the FIDO metadata snapshot | **no** — batch certificates identify a model, not a unit, so keys are **refused** from block 460 |
| iPhone / iPad / Mac | — | — | Apple passkeys carry **no attestation** (iOS 16+, macOS 13+); the device cannot vouch through a web page. A native App Attest bridge (per-device keys) is the route; it needs an Apple developer account to ship. |

**One device, one identity.** From block 460 of betanet-7 a register transaction's device certificate is bound to
its sender in consensus state for one lease (36 h); the same device cannot register a second identity while that
binding lives. Device classes that carry nothing per-device are not accepted at all: what cannot be bound is not
proof of anything.

### Identity management is the only weapon against miner centralisation

Every mining rule that is written *per identity* — a work proof, a waiting time, a per-address cap, a per-IP budget,
a probation period — is linear in the number of identities, so it costs an honest miner exactly as much as it costs a
farm *per identity*, and a farm has as many identities as it wants. The attack vector is not stake and not hashpower;
it is **identity farming**, and it opens the moment an identity is something a script can mint. This has been the
holy grail of every project that tried to pay people rather than capital: NANO's representative spam, Idena's
validation ceremonies, Nyzo's cycle, NADO's own IP-based mining — each was gamed by whoever could manufacture
identities fastest, and each answered with more per-identity rules that the next farm dodged the same way. On
NADO the free lane lost ~42 % of its emission to about a thousand farmed identities before this rule.

The only things that discriminate are the ones a farm cannot copy: **capital** (which the bonded lane weighs) and a
**real identity**. NADO's identity is a physical secure element — the chip in an Android phone, a TPM, a Ledger, a
Trezor — that vouches for the wallet with a certificate its maker signed, bound to one identity at a time. That is
what lets every other rule be simple: the free lane is one device, one vote; the bonded lane is one device, one
knee; pools rent devices instead of pretending to be many. Without a real identity, identity farming is what opens
the centralisation attack; with one, the attack costs a device per identity and a hand on each device every lease.

### Why a device at all, and what the network sees

Before this rule the free mining lane was farmed: about a thousand fake identities, run by two or three people on rented servers, took roughly 40 % of all emission. Every rule that was per identity — proof of work, waiting times, per-address limits — was dodged by making more identities. The one thing a server farm cannot fake is a real device's secure chip, so a mining identity is now one real device.

It is not a passkey or a login. The wallet asks your phone or PC to create a throwaway hardware key and sign one challenge chosen by the chain. What every node verifies, offline, is the maker's certificate: "genuine Android", "genuine TPM", "genuine Ledger". No serial number, no account, no name leaves the device; the key is never used again; nothing is stored with your wallet key; no node ever contacts Google, Microsoft, Ledger or Trezor.

Holding, sending and receiving NADO need no device. Attestation is only for mining rewards. If you would rather not attest from the device you mine on, "Attest from another device" lets any phone or PC you trust vouch for the wallet.

**Free-lane blocks are for device-only miners (from block 6600 of betanet-7).** An identity holding one bonded share
(10 NADO) or more is not drawn for open-lane slots; it produces in the bonded lane. Per device, not per key, so a
staker cannot keep a second wallet in the free lane without a second device. The **presence dividend is unchanged**:
every attested device is paid by fidelity, staked or not. The dividend ramp also flattens from the same epoch,
`min(fidelity, 15)` instead of 30, so a first week is no longer almost nothing next to a thirty-day identity.

**No device? Delegate to a pool (from block 6000 of betanet-7).** Savings produce blocks only on an attested device.
A holder without one delegates their bonded stake to a pool run by someone with a device: the pool produces with own
plus delegated stake on the same per-device curve, and the chain splits every block it wins between the pool
and its delegators in that same block, pro rata, minus the pool's fee. Your coins never leave your account and you can
undelegate any time. Anyone with an attested device opens a pool from the Stake card and sets its fee, name, minimum,
maximum and whether it is open. The Sybil bound is unchanged: every unit of producing weight still sits on one real
device on the same curve; what a pool changes is who owns the capital on it. Full details: *Staking pools* above.

**Bound for life or leased — two binding modes (from block 3900 of betanet-7).** A Ledger or Trezor carries a
factory-fixed device key, so it attests **once**: the binding never expires, and the identity renews its 36-hour
presence lease with a register transaction that carries no statement at all — the account key signs it, no cable,
no prompt, the mining loop does it while the page is open. A phone or a Windows PC is **leased**: its attestation
key rotates (Android about every two weeks, a TPM per Windows account), so a binding that outlived the key would
let one phone bind a fresh identity per rotation; it re-attests on every renewal, which is the only correct form
for a rotating key. The wallet shows the mode on the identity card ("Bound for life to a Ledger — renews without a
prompt" / "Leased — re-attests every 36 h"). A hardware wallet can be **rebound to another account** without the
old account's key (lost key, sold device, wallet migration): make a statement from the new account in any block; the
binding flips in that block and the old account is evicted at once — out of the producer draw and the dividend weights
from that block (from block 5400 of betanet-7; before it a 36-hour cooldown applied instead). Whoever holds the device
wins immediately. The wallet asks "this Ledger vouches for
another account — rebind it here?" before the tap is spent. One hardware wallet per identity. A node attested with
a hardware wallet renews itself the same way; the operator attests once.

**Savings stake counts only while attested, on a curve (from block 11800 of betanet-7; a hard 1,000 NADO cap from block 4200 before that).** A device's producing weight is its stake up to a knee, at least 1,000 NADO and 5 % of the other attested devices' stake when that is more, then flattens toward one and a half knees: every extra coin still counts, just less, and no single device can ever count for more than 1.5 knees. Chosen by simulation against a single whale, a split whale, a phone farm and a large lane (`doc/device-attestation.md`). The
bonded (savings) lane draws its block producers only from identities that hold a live device lease. Unattested stake
still votes for finality and still counts as fork weight, but it produces no bonded blocks — so a whale needs one
real device per knee of full weight, and splitting keys buys nothing. A node you run: bond, then attest it from the
Mining page. With a Ledger or Trezor that is one tap for life; the node renews itself and keeps producing. If no
bonded identity is attested at all, the lane falls back to plain stake weight so the chain never stalls.

**iPhone, iPad, Mac.** Apple devices are not an accepted device class (decision 2026-09-07). Apple passkeys carry
no attestation, and Apple's App Attest — built, tested against a real iPad and then withdrawn — carries no per-device
certificate: one device, one identity would rest on app code, and a jailbroken older iPhone could farm identities
undetected. Every other class binds on something the chip itself issues. Apple users mine anyway: on a Mac, a Ledger
or Trezor in Chrome, Edge or Brave; on an iPhone or iPad, *Attest from another device* (an Android phone, a Windows PC
or a Mac with a hardware wallet vouches for the wallet).

**Windows says "Windows Hello is not using a TPM" (authenticator 9ddd1817).** Windows created the Hello key inside
virtualization-based security (VBS) instead of the TPM; a VBS key has no certificate chain. The BIOS TPM switch alone
does not move it. Check `tpm.msc` (ready, 2.0) and `msinfo32` (VBS "Running" is the cause); on a standalone PC
disable VBS and Credential Guard from an elevated PowerShell (`LsaCfgFlags = 0` under
`HKLM\SYSTEM\CurrentControlSet\Control\Lsa`, `EnableVirtualizationBasedSecurity = 0` under
`…\Control\DeviceGuard`), reboot, confirm VBS "Not enabled", remove and re-create the Hello PIN while online (Windows
fetches the TPM's AIK certificate then), and retry — the pre-flight should name 08987058. BitLocker is unrelated. The
wallet's Mining page shows this guide, and the one for every other verdict, under the device line.

**Linux, Mac, iPhone, or any wallet without a device of its own: attest from another device.** On the wallet that
needs the lease press *Attest from another device*; on an accepted device (an Android phone, a Windows TPM PC, a
Ledger or Trezor Safe) open Mining → *Attest another wallet or node*, paste that wallet's address and confirm.
The statement travels through the relay, the first wallet picks it up, wraps it in its own signed registration and
submits. The coins never leave the first wallet; the device that confirmed is the one bound, so it cannot vouch for
a second identity while that lease lives. Renew every 36 h the same way.

**Running a node?** A node cannot attest itself (no secure element, nobody to tap). On the wallet's Mining page,
*Attest a node you run*: paste the node's address, tap once, and the attestation reaches the node through the
network — it signs its own registration. Renews every 36 h, like any miner.

What that buys: a server, a VM, a desktop browser without hardware, an emulator, a software
authenticator, a virtual TPM or a rooted phone cannot produce the chain. Farming identities needs
genuine hardware and a human tap per identity per lease — non-automatable by design — and no account,
phone number or central service: the vendor roots are public constants checked by every node.

In the wallet it is not hidden: the setup step attests the device right after the key is stored, the
**Mining** page shows *Real device: attested ✓* (or exactly why not), and Settings has *Verify this
device*. The rule is live since betanet-7 (gen 25, `DEVICE_ATTEST_HEIGHT` = 1): that reroll retired the
sequential-work proof, the per-IP budgets and probation, which a device proof makes redundant, and the
dividend weight is one clean line — `min(fidelity, 15)` (30 before epoch 110), the first lease pays weight 1. Design and
verifier details: `doc/device-attestation.md`.

Enforcement by IP is gone, observation is not: every register tx a node receives leaves one line in
`<home>/identity_log.jsonl` (client IP, sender, entry/renewal, device class, AAGUID, certificate hashes;
node-local, never consensus, never served). `python3 tools/identity_audit.py` groups the last lease's
identities by IP, by device certificate and by device class, so an operator can check that the
identities are really individual instead of assuming it.

## Mine from a phone

Open the running node's light-miner in any browser:

```
http://<node-ip>:9173/static/interface.html
```

The NADO Interface (`static/interface.html` + `static/interface.js`) is also a **full wallet**: it generates or
imports a key, asks the device's secure hardware for its **attestation** (WebAuthn, WebHID for Ledger, WebUSB for
Trezor), registers/renews its device lease against the node (no heartbeats), and **keeps winning blocks even while the
phone is locked** — presence is a 36-hour lease (no per-epoch traffic), and a relay assembles the
crediting block. It can send/receive with QR payment links and `#pay` deep links,
bond/unbond, browse the chain, and runs in **16 languages** (browser-locale default) — all from a phone. It also shows
**how busy each lane is right now** — live **OPEN** and **BONDED** participant counts (from
`/mining_status` `open_registry_size` / `bonded_registry_size`) alongside your own bonded shares — so a
miner can see the field it is competing against. Crypto is **vendored** (`static/vendor/nado-crypto.js`:
blake2b + ML-DSA-44) so it works offline, and an in-page self-test asserts byte-equality of its canonical
encoding against the live repo on boot.

> The NADO Interface keeps its private key in browser `localStorage` in **plaintext** (disclosed in the
> UI). Treat it like a hot wallet.

## Clients

- **Command line (`scripts/nado_cli.py`)** — every interface operation from the terminal, signed by your local
  `keys.dat`: `info`, `send`, `register` (a node cannot attest itself — bind it from the wallet's Mining page
  instead; the CLI path only renews a hardware-bound lease), `bond`/`unbond`, `alias`,
  `propose`/`vote`/`execute` (treasury governance), `collect` (presence dividend), `bridge-deposit`. It builds
  the *same* signed transaction the browser does and POSTs it to the node's existing `/submit_transaction` —
  no new signing endpoint, no new trust surface. Full reference: **[doc/cli.md](doc/cli.md)**.
- **Browser / mobile NADO Interface (wallet)** — `static/interface.html` (see above).
- **Block explorer** — folded into the NADO Interface as an **Explore tab** (`static/interface.html` +
  `static/interface.js`): search by address / **alias** / block number / block hash / txid, browse recent
  blocks, and see live network + mining-lane stats — all reading the node's own public JSON API in the
  browser. The node serves the wallet/explorer at `/`. (The raw JSON endpoints — `/get_account`,
  `/get_block`, `/get_transaction`, `/get_supply`, `/status`, `/resolve_alias`, … with `readable=true` —
  remain available directly.)

---

## Security

NADO's security rests on the two-lane selection design plus anti-DoS/anti-Sybil hygiene. The split
between **implemented** and **planned** below is the difference between testnet-safe and mainnet-safe —
read it before running anything of value.

### Can a relay steal your keys? No — and what one *can* do

The web wallet signs every transaction **in the browser**; the relay receives signed bytes and nothing else. No key,
seed phrase or password is ever sent to a relay, and the wallet loads its code only from the page's own origin
(`get.nadochain.com` or the node you opened it from) — never from the relay it talks to. So switching relays, the
automatic failover, or a hostile node in the peer list cannot take your coins. **The one way to lose keys is to load
the wallet page itself from an untrusted site**: use `get.nadochain.com` or your own node, and bookmark it.

What a hostile relay *can* do is **answer wrongly**: a fake balance, a stale tip, or an alias that resolves to its own
address. The wallet treats every relay other than the one it was loaded from as untrusted: a failover or pinned
relay must hash the same **finalized block** (60 below the tip) as the home relay before it is used; an alias →
address answer from such a relay must **agree with the home relay** or the send is refused; and every payment
confirm shows the **exact address** being signed. Transactions carry the chain id and a target block, so a relay
cannot replay them elsewhere. Settings → Network lists the advertised relays with their measured latency.

### Security audit (all exploitable findings fixed)

A deep adversarial audit was run across **six surfaces** (fork-choice/51%/rollback/finality;
Sybil/two-lane/selection; slashing/equivocation/unbond; RANDAO/FFG/beacon; tx-validation/pubkey-once;
KV atomicity/eclipse/DoS), against a chain that was **testnet-stage alpha with no value at stake**.
Every **exploitable** finding it surfaced is now **fixed and unit-tested** — full writeup in
[`doc/security-audit.md`](doc/security-audit.md). In brief:

- **In-block duplicate reserved-tx bugs (CRITICAL/HIGH).** Uniqueness was checked only against
  *parent* state and block assembly did no dedup, so duplicates of a reserved tx in **one** block could
  drain a single unbond via repeated `withdraw`s (slash-escape / chain-halt), over-burn on a duplicate
  `slash` (which two honest reporters trigger organically), or collapse duplicate `heartbeat`/`reveal`
  rows so a reorg over-deletes the shared row → **registry/beacon desync fork**. Fixed by **per-reserved-tx
  in-block uniqueness** (`reserved_uniqueness_key` + `dedupe_reserved` in assembly + `assert_unique_reserved`
  in `verify_block`), plus cross-block `heartbeat`/`reveal`-secret guards.
- **Same-length fork-choice wedge (CRITICAL, liveness).** Two equal-weight honest tips at one height
  could wedge forever because the switch was strictly-greater-weight only. Fixed by the deterministic
  **lowest-hash tie-break**: every node now switches to the global-best tip by `(weight DESC, hash ASC)`,
  so they converge.
- **`quick_sync` validation bypass (HIGH).** Old-block sync skipped signature + spending checks. `verify_block`
  now **always** runs `validate_transactions_in_block` — the bypass is gone.
- **Unauthenticated advertised-weight DoS (HIGH).** A single Sybil peer advertising a huge
  `latest_block_weight` forced honest nodes into emergency rollbacks. Fixed by a bounded, auto-clearing
  **`rejected_tips`** exclusion so a bogus weight can't loop a node.
- Plus: **per-IP rate limits** on the heavy unauthenticated read endpoints (`/mining_status`,
  `/get_transactions_of_account`, `/get_blocks_after`/`/get_blocks_before`); an **honest-signer guard**
  (a node only ever signs a *strictly higher* height, so an honest re-signer can't be slashed for its own
  reorg); the **per-/16 subnet cap now also gates the disk-reload path**; and a dead `/get_blocks_before`
  was fixed.

The audit also **confirmed the safety core sound** with no change needed: the atomic
incorporate/rollback window, the monotonic finality floor, equivocation-proof unforgeability (and the
no-innocent-victim address binding), the detached-signature-outside-the-hash property, and pubkey-once
key→sender binding. The remaining items are documented **residuals / future hardening** (below and in
[`doc/security-audit.md`](doc/security-audit.md)), none of which is a theft or fork vector in the current
code.

### Implemented (live in production and verification paths)

- **Structural Sybil bound** — the open lane is exactly `K_OPEN` slots/epoch regardless of identity
  count, so a free botnet can never exceed 30 % of blocks. One-directional fail-closed empty-lane
  policy preserves the ceiling.
- **Fail-closed deterministic authorship** — `validate_block_producer`, called inside `verify_block`
  *before* incorporation, recomputes the two-lane winner from parent state + the epoch beacon and
  **rejects** any block whose producer isn't that winner (block integrity is by deterministic
  recomputation, optionally authenticated by the detached winner signature below).
- **Objective stake-weighted heaviest-chain fork-choice** — the canonical tip is `argmax
  cumulative_weight` among tips whose chain contains the node's finalized block, switching only on
  strictly-greater weight (lowest-hash tie-break). **Peer IPs, trust, and uptime carry exactly zero
  weight**, so a Sybil fleet of zero-bond IPs cannot reorg honest nodes. Replaces the old peer-IP
  plurality fork-choice.
- **Grind-proof `cumulative_weight` header** — committed inside the block-hash preimage as
  `parent.cumulative_weight + total_bonded_shares(as-of-parent) + 1`. It is the *total* bonded registry
  weight (not the slot winner's share), so it is **beacon-independent**: a proposer can't grind the
  beacon to inflate fork weight. Recomputed in `rebuild_block` and verified as-of-parent. The **`+1`
  height term** guarantees the weight is *strictly increasing* even when the bonded registry is empty:
  without it, a no-stake network advertises one frozen weight forever, fork-choice degenerates to the
  lowest-hash tie-break, and a stalled node whose tip hash happens to sort low considers *itself*
  canonical and never resyncs (observed live 2026-07-05; fixed at the `relaunch-3` genesis). Pure
  longest-chain while nothing is bonded, stake-dominated the moment anything is (`shares ≫ 1`).
- **Advertised-tip (weight) DoS hardening** — a peer's advertised `latest_block_weight` is only ever a
  *hint*: acting on it means fetching the blocks, which `verify_block` re-derives and enforces. A tip
  that was advertised heavier but could **not** be backed by a valid chain — the peer serves nothing,
  garbage, or forged blocks — is excluded (`rejected_tips`, bounded + auto-cleared ~30 s so a real tip
  that merely blipped is retried). The exclusion is honoured **everywhere it matters**: the emergency
  sync loop rejects the tip on *every* failure path and re-evaluates being-behind each pass, and the
  caught-up production gate skips rejected advertisements — so two forked-away or lying clients can
  cost the network ~one failed sync per 30 s, **never a production stall or an emergency-mode wedge**.
  Peer admission is additionally gated on an exact **`chain_id` match** in `/status` (a missing field
  counts as a mismatch), so nodes from a different chain/relaunch never enter the consensus pools at
  all — a foreign chain's frozen weight can't trip the caught-up gate.
- **Enforced finality floor** — a block at height H finalizes everything at/below `H - FINALITY_DEPTH`
  (`FINALITY_DEPTH = 12`); rollback **refuses** to cross the persisted, monotonic finalized height
  (raises `FinalityViolation`). The ordering `max_rollbacks (10) < FINALITY_DEPTH (12) < EPOCH_LENGTH
  (60)` means honest reorgs never hit the floor while a long-range reorg is capped below one epoch.
- **Corroborated finality + escalated re-anchor (partition-wedge recovery)** — the depth floor now advances
  **only while the peer-majority tip lies on our canonical chain** (`_depth_floor_corroborated`); a node that
  briefly loses the majority (e.g. under load) and keeps producing on its own branch no longer *self-finalizes*
  that minority fork, so partition forks stay reorgable and heal through the normal weight-based reorg (a Sybil
  can only *withhold* corroboration — delay the floor, the safe direction). And if a node is ever wedged anyway
  (its snapshot/finality floor stuck on a minority fork below the heaviest chain's snapshots), after
  `REANCHOR_ESCALATE = 3` cooldown-spaced failed re-anchors it **drops the snapshot-above-floor restriction** and
  re-anchors to the strictly-heaviest chain (every tail block still re-verified). Observed live and fixed; both
  are node-local safety/fork-choice rules (they change only when a node advances its *own* floor, never block
  validity). Unit-tested (`tests/test_wedge_recovery.py`).
- **Fail-loud epoch beacon** — `epoch_beacon` chains from the hash of the first block of the previous
  epoch (a finalized, non-parent anchor), and now **raises instead of silently substituting**
  `GENESIS_BEACON` when the anchor is missing (a missing anchor means this node is under-synced).
- **Detached winner block signature** — when the selected winner is online it attaches an *optional*
  ML-DSA signature **outside** the hash preimage (so it never affects the hash, weight, validity, or
  reward); verifiers reject a present-but-forged or wrong-signer signature. An offline winner's
  relay-built block is simply unsigned and still valid — **"win-while-offline" is preserved**.
- **Equivocation slashing (both proof types)** — slashing punishes **double-signing**, and covers two
  distinct offences under one `resolve_slash` path: **(1) block-authorship equivocation** — two valid
  winner signatures over *different* blocks at the *same* height+parent; and **(2) FFG-attestation
  equivocation** — the same validator signs **two conflicting `attest` transactions** for one
  `target_epoch` (same epoch, different `target_hash` — a finality double-vote). Either forms a portable,
  unforgeable proof (only the key-holder can sign either message). A fee-exempt `slash` transaction
  carrying the proof burns `SLASH_BOND_PENALTY` (= `B_MIN`, one bonded share) of the offender's **bonded**
  stake. Anyone may report it (the proof is the anti-spam); it is replay-guarded to **one slash per
  (offender, height)** — attestation slashes are namespaced above real block heights so the two proof
  types never collide — revert-symmetric on rollback, and the coins are **destroyed** (the deterrent is
  the loss, not a bounty). Validation requires the offender still hold the penalty so the dock never
  floors. **This punishes equivocation, not Sybil-ness** — Sybil resistance is a separate mechanism
  (open lane capped at `OPEN_BPS = 30%` + one real device per identity; bonded lane attested per device, on a curve).
- **FFG stake-attested finality (enforced)** — bonded validators emit one `attest` transaction per epoch
  for that epoch's checkpoint (its first block). A checkpoint **justifies** when attesting bonded shares
  *strictly* exceed >2/3 (`FFG_NUM/FFG_DEN = 2/3`) of the **active** quorum, and **finalizes** on
  two-consecutive-justified; on-chain `UNIQUE(validator, epoch)` prevents on-chain double-voting (and a
  cross-fork double-vote is now slashable — above). The finalized checkpoint is **folded into the
  persisted rollback floor** (`finalized_height = max(prev, tip − FINALITY_DEPTH, ffg_finalized)`), so a
  >2/3-attested checkpoint is **objectively un-reorgable** — remote sync cannot adopt a heavier
  conflicting chain. **Inactivity leak:** the quorum denominator is `active_shares` — the selection
  shares of bonded validators that attested *some* checkpoint within the last `INACTIVITY_WINDOW = 3`
  epochs — **not** all bonded stake. A validator that goes dark is leaked from the finality quorum (its
  **vote** lapses; its **bond is untouched**), so a live attesting majority always finalizes instead of
  being wedged by bonded-but-absent stake. This is what let `ffg_finalized` start advancing despite many
  bonded-but-non-attesting dust accounts. **Honest scope:** FFG is **epoch-granular** and normally
  *trails* the depth floor, so confirmation latency remains the depth floor (~12 blocks) — FFG is the
  objective/long-range finality layer on top of the fast subjective floor, never a speedup, and (being
  layered on the always-advancing floor) it can never stall the chain. Exposed at **`/status.ffg_finalized`**.
- **Commit-reveal RANDAO (voluntary participation)** — bonded validators `commit` a
  secret's hash in epoch E−2 and `reveal` it in E−1's finalized window; `epoch_beacon` mixes the
  finalized prior-epoch anchor with the revealed secrets, so **no single anchor-producer controls the
  beacon**. With zero reveals it falls back to the anchor-only value (liveness). It keeps the anchor
  (non-recursive), so the beacon stays snapshot-safe and the reveals are immutable by the time the
  beacon is needed. **Participation is voluntary** (`RANDAO_ENFORCED = False` in `protocol.py`):
  every reveal that lands strengthens the beacon, but skipping the duty costs nothing and the
  bonded-lane draw runs over the full registry. The enforcement machinery
  (`randao_eligible_bonded` — no reveal for epoch E, no production rights in E — applied identically
  at production, relay rebuild, and verification) is implemented, unit-tested, and kept behind the
  flag; it was switched off because mandatory participation forces O(validators) commit+reveal txs
  every epoch and ties rewards to tx-inclusion latency, which scales poorly. Fork weight and the
  FFG/settlement quorums stay on the *full* registry in either mode, so withholding can't move
  fork-choice or stall finality. Both the node (`maybe_randao`) and the browser interface (for
  bonded wallets, while the tab is open) still contribute automatically.
- **Pubkey-once** — the 1312-byte ML-DSA `public_key` is **excluded from the txid** and stored once in
  account state on an address's first tx, so later txs (notably every-epoch heartbeats) omit it;
  validators recover it from committed state. Store/clear is byte-identically revert-symmetric.
- **Reward recompute-and-enforce**, **registration-PoW enforcement**, **canonical in-block tx
  ordering** (txid-sorted before hashing, so honest nodes selecting the same tx set produce an
  identical block hash).
- **Anti-DoS / eclipse throttles** — per-IP sliding-window rate limits on `/submit_transaction`
  (30 req/60 s) **and** `/announce_peer` (10 req/60 s), **plus the heavy unauthenticated read endpoints**
  (`/mining_status`, `/get_transactions_of_account`, `/get_blocks_after`/`/get_blocks_before`, added in
  the audit), a **per-/16 peer-diversity cap** (at most `MAX_PEERS_PER_SUBNET = 4` peers per /16 — now
  enforced on the disk-reload path too, so one network can't fill a victim's peer view), a **progressive
  per-range IP registration cap** on OPEN-lane onboarding (crowding cost scales with subnet proximity, so
  a datacenter /24 gets one bounded budget — `max_registrations_per_ip`), a hard mempool cap (150,000),
  heartbeat-index GC, and an SSRF guard (`check_ip` rejects own-IP and all non-globally-routable
  addresses).

### Lightly exercised (implemented + unit-tested, but not yet hardened on a live multi-node net)

The equivocation slashing (both proof types), FFG finality, and commit-reveal RANDAO above are **wired
and unit-tested for correctness**, and FFG now **finalizes live** (`ffg_finalized` advances past 0 once
the active bonded set attests two consecutive checkpoints). Their **multi-node, adversarial,
epoch-crossing** behaviour is still only **lightly exercised empirically**: the core loop's ~6 s/block
cadence makes exercising a full justify→finalize under contention and a complete commit→reveal cycle
slow. Treat their cross-epoch adversarial dynamics as not-yet-battle-tested.

### Planned (designed, NOT yet implemented — do not rely on these)

- **Broader eclipse hardening** — beyond the per-/16 subnet cap and the `/announce_peer` rate-limit
  (both already live): **ASN-level** (vs /16) peer-diversity caps, pinned anchor outbound slots, a
  **multi-seed** bootstrap list (replacing the single genesis seed), and **snapshot-bootstrap binding
  to a finalized signed checkpoint**. These are post-launch items.

### Honest statement of current limits

Objective fork-choice, enforced finality, equivocation slashing (block-authorship + FFG attestation),
enforced FFG stake-attested finality, and the commit-reveal RANDAO make a zero-bond Sybil/IP reorg
ineffective, bound the disagreement window below one epoch, and layer objective finality and a
non-grindable beacon on top — a substantial
hardening over the previous peer-count fork-choice. Beyond the lightly-exercised cross-epoch behaviour
of FFG/RANDAO and the outstanding eclipse hardening above, the **documented residuals** from the audit
(see [`doc/security-audit.md`](doc/security-audit.md)) — none a theft or fork vector — are:

- **RANDAO withholder penalty: CLOSED** (2026-07-05). Reveal-for-the-epoch is now a hard eligibility
  condition for the bonded-lane draw (see above), so suppression costs the withholder its entire
  epoch of production. The residual is only the classic last-revealer bit: with `m` colluding
  withholders, up to `2^m` beacon outcomes — each priced at `m` epochs of forfeited rewards, and
  defeated whenever ≥1 honest secret is revealed after the anchor.
- **FFG slashable-stake backing: CLOSED.** FFG is no longer observational — the finalized checkpoint is
  **enforced** in the rollback floor (objectively un-reorgable), and **attestation-equivocation slashing
  is live**: a validator that signs two conflicting attestations for one epoch loses `SLASH_BOND_PENALTY`
  of bonded stake via the same `slash` path as block-authorship double-signing. On-chain double-voting is
  still blocked by the per-epoch `UNIQUE(validator, epoch)` marker; cross-fork double-voting is now
  punished rather than merely prevented.
- **The bonded producer curve is per device, not per key** — the old per-key `MAX_SHARES` (removed 2026-08-25)
  was recovered by sharding across addresses. Since block 11800 of betanet-7 weight is `bond_weight(stake, knee)` per
  *attested device*; sharding across addresses on one device gains nothing, and more weight needs more real devices.
  Fork weight and the finality quorum stay capital-proportional and attestation-free.
- **Registration / fee-exempt state growth** — `register` writes an account doc; **idle-account GC is implemented**
  (`ops/gc_ops.py`): long-lapsed empty docs and ancient recert rows are swept deterministically
  in-block at epoch boundaries (revert-safe, snapshot-root-identical on every node). Also bounded by the lane cap, per-IP rate limit, mempool cap, and the
  in-block one-register-per-sender dedup; idle-account GC is future work.
- **Fidelity is continuity over recerts** — `apply_register` adds a step for each *continuous* recert
  (gap ≤ the lease) and halves the streak on a lapse (never below 1); it ramps the open bonus over `FIDELITY_CAP` recerts.
- **Snapshot bootstrap** trusts an 80%-of-peers quorum with **no hardcoded finalized checkpoint**
  cross-check (weak-subjectivity); a pinned checkpoint is future eclipse hardening.

All mining/economic parameters are **provisional** and flagged *simulate-before-lock-in* in code. NADO
remains a **testnet-stage alpha, not open-value-mainnet-safe**. (No hardfork concern: mainnet is not
live.)

---

## Cryptography & determinism

- **Signatures** — ML-DSA-44 (FIPS 204, post-quantum) via `dilithium-py`. Keys are a **32-byte seed**
  from which the 1312-byte public key and ~2420-byte signatures are deterministically regenerated.
  Consensus only ever checks `verify(sig, pk, msg) == True`, never signature-byte equality, so hedged
  signatures interoperate across implementations. Signatures authenticate transactions/heartbeats and
  are **deliberately never** the randomness source (a malleable signature would be grindable).
- **Addresses** — `"ndo"` + 42-hex public-key prefix + a 4-hex `blake2b` checksum (49 chars). The
  keyless reserved recipients `{bond, unbond, withdraw, register, slash, attest, commit,
  reveal, alias}` are valid as a recipient/target only, never as a sender.
- **Aliases** — a human-readable name → owner address, so you can **send to a short name instead of the
  49-char `ndo…` address**. Register / transfer / unregister are on-chain ops (reserved recipient
  `alias`); an ordinary transfer whose recipient is a registered alias credits the alias's current
  owner. See [`doc/aliases.md`](doc/aliases.md); the NADO Interface's Send field accepts an alias and its
  Receive tab manages them.
- **Multisig (opt-in)** — native **M-of-N shared accounts** with no script language and no on-chain
  setup: the address **is** the policy — `make_address(blake2b(["nado-msig-v1", M, members]))`, the
  way a P2SH hash commits a script. Fund it like any address; a spend carries the descriptor in the
  signed body plus a **list of member signatures over the txid**, so co-signers sign independently in
  any order and exchange the proposal by any channel (the Interface's Multisig tab and the CLI's
  `msig-propose` / `msig-sign` / `msig-submit` implement the relay). Multisig accounts are **payment
  accounts only** — they can't bond, mine or vote, so every one-key-one-identity validator assumption
  stays intact. `ops/multisig_ops.py`.
- **Hashing & serialization** — BLAKE2b over `canonical_bytes()` (compact, sorted-key, ASCII JSON,
  float-free). Every consensus integer is a raw integer, so a browser reproduces identical bytes with
  BigInt-aware serialization. Transaction ids and blocks bind `CHAIN_ID = "betanet-1"`, blocking
  cross-chain / pre-relaunch replay.
- **Wire** — transactions submit over **HTTP POST + msgpack** (an ML-DSA-44 tx is too large for a GET
  URL); msgpack is wire/transport only and never the hashed preimage.

### Zero-knowledge proof stack

Everything below is **hash-based and post-quantum** — no elliptic curves, no pairings, **no trusted
setup** anywhere. Full component map with measured numbers and per-piece status:
[`doc/zk-components.md`](doc/zk-components.md); vocabulary: [`doc/zk-glossary.md`](doc/zk-glossary.md).

- **Arithmetic core** — the Goldilocks field (p = 2⁶⁴ − 2³² + 1) with a GF(p^d) extension for challenge
  soundness, Merkle commitments, a Fiat–Shamir transcript, and **FRI** underneath every proof. Protocol
  strength is 320 queries at blowup 2 with 18 grinding bits ≈ **146 provable bits** (Johnson).
- **alghash2** — the algebraic hash the recursion layer needs, because a STARK that verifies another
  STARK must hash *inside* a circuit and BLAKE2b is far too expensive there. Wide sponge over Goldilocks
  (WIDTH 12, RATE 8, CAPACITY 4, α = 7, 54 rounds); 256-bit capacity ⇒ 128-bit collision and 128-bit
  Grover preimage resistance.
- **A field-native execution zkVM** — the only contract runtime, with an AIR that proves "running this
  public program on this input yields this output". ~20 game contracts run on it today.
- **A shielded pool** — join-split circuits (1-in/1-out and 2-output) plus a Merkle-membership AIR for
  private transfers. This is the one subsystem where the whole loop — prove → publish to DA → carry only
  the commitment on chain → verify — **already works in production**.
- **Recursion, for O(1) verification** — a verifier-authoritative in-circuit STARK/FRI verifier, an
  in-circuit Fiat–Shamir transcript, a K→1 collapse and fold-of-folds, so an epoch's root verifies in
  constant time regardless of how much executed. Live on the consensus path since betanet-14.
- **Rust proving, no fallback** — `native/starkprove` (2 222 lines), `native/alghash2`,
  `native/starkcompose`, `native/mldsa44`. The guard **fail-stops** rather than degrading quietly,
  because a Python path shadowing a Rust one is invisible degradation, not a safety net.
- **On-device proving** — 650 lines of JS in `static/stark/` let a phone build a shielded-transfer proof
  in the browser with no install.

> **Honest status (updated 2026-08-06).** **Trustless settlement now works end to end.** Block **43153**
> on betanet-15 carries a settle with `proof=True` for `exec_cursor 42876`: a peer verified the STARK in
> **114.5 s** and returned `{"result": true}`, all four nodes agree on the block hash, it is final at
> depth 71, and `/get_settled` returns the proven root. **The exec root advanced on a validity proof
> rather than a bonded quorum.**
>
> This replaces the previous status, which said it "has never completed end to end" and that a proof
> "can only ever travel via DA" against "a ~256 KiB block". That was wrong in an instructive way: **nothing
> in consensus bounds transaction or block size.** The ~256 KiB figure was a mempool cull budget quoted
> from a comment, and the limit that actually rejected large settles was `ops/net_ops.MAX_TX_BODY` — 1 MiB,
> aiohttp's default. The proof now rides **inline in the transaction** (a 126.6 MiB block); DA is not used
> for it, which matters because only one node in this fleet runs a DA store.
>
> Six independent blockers had to fall, each individually fatal — the deepest being that **all three peers
> were missing `libgoldilocks.so`**, so with no Python fallback since betanet-14 no peer could verify a
> settle proof under any circumstances. [`doc/settle-proof-transport.md`](doc/settle-proof-transport.md)
> §6 documents all six with evidence.
>
> **Since then the proof got 13× smaller and 35× faster, and it was one producer-side default.** The
> non-recursive prover committed the trace by COLUMN, so each of the 320 FRI queries opened all 167 columns
> with its own Merkle path — 334 paths per query. Row-committing builds one tree per phase, so a query
> carries 2. Measured on production state, same span, byte-identical settled root: **140.9 s / 126.56 MiB
> / 19.6 s verify → 7.3 s / 9.73 MiB / 6.4 s verify.** Openings were 95.6% of the old proof. This needed no
> verifier change and is not a consensus change — `verify_bound_epoch` recovers the commit mode from the
> proof (`"row_roots" in proof`) and L1 passes neither knob. A separate fix removed the other 72–81% of
> prove time: the sparse state root was rebuilt from scratch on every prove *and* every verify (2.3 M
> alghash2 permutations), and memoizing its singleton folds took it from 65.1 s to 0.46 s.
>
> Blocks **46766** and **47078** then carried proofs at **9.74 MiB**, each agreed by all four nodes.
> Peers verify them: pushing a pending proof to each peer returned `{"result": true, "message": "Already
> present"}` — gossip had beaten the push and each had already *admitted* it, which runs the full
> verification. §8–§11 of the transport doc has the measurements.
>
> **What is still not done:** the landed proofs were **unfolded** (`calls=0`). A span containing a call is
> refused because the records half moves, and a span crossing a dividend epoch boundary is refused for the
> same underlying reason — counted over one day, those two are **91 of 146** refusals and are one gate, not
> two. Lifting it needs `SETTLE_PROOF_RECORDS_VALUE_CALLS`, which is implemented and inert because
> activating it requires a genesis reroll. So production settlement is still predominantly quorum-carried,
> and the fold has still never folded more than one proof.

## Storage

State lives in a single **schemaless, memory-mapped, ACID key-value store (LMDB)** — `ops/kv_ops.py`,
which **replaced the prior SQLite index**. Account/state records are schemaless msgpack documents
(no columns, no DDL), so adding a field needs no migration. A whole block's mutations (account docs,
tx index, block index, totals, heartbeats) commit in **one** write transaction, so a crash leaves a
block either fully applied or not at all, and replay is idempotent. Block bodies are `zstd(codec)`
records in append-only **segment files** under `blocks/` (`ops/segment_store.py` — ~300 files/year
instead of one per block; crc-guarded, fsynced before their LMDB locator commits, torn tails repaired
at startup), and consensus hashing stays canonical JSON — neither is touched by the index.

**Archive vs rolling nodes (opt-in history pruning).** By default a node is an **archive** node
(`config.archive = true`) that keeps every block body forever. Set `archive = false` (or `NADO_ARCHIVE=0`)
to run a **rolling/pruned** node that drops finalized block *bodies* older than `HISTORY_RETENTION_BLOCKS`
(default 100 800 ≈ 1 week) while **always** keeping state and the number↔hash indexes — so it stays a full
validator and still serves the beacon/FFG lookbacks, with bounded disk. Retention is floored internally at
`REWARD_WINDOW + FINALITY_DEPTH` so pruning can never corrupt the reward calc or a legal rollback. This
keeps phones viable under adoption; see [`doc/rolling-mode-and-da.md`](doc/rolling-mode-and-da.md).

## Private key storage

Keys are post-quantum **ML-DSA-44 (FIPS 204)**; what is stored is the 32-byte seed. Your `ndo…` address
shape is unchanged (49 chars).

- Linux: `~/nado/private/keys.dat`
- Windows: `C:\Users\<username>\nado\private`

---

## Learn more

- **Whitepaper** — [`doc/whitepaper.md`](doc/whitepaper.md): the authoritative, accuracy-reviewed
  overview of the mechanism, with a full constants table and an explicit implemented-vs-planned split.
- **Roadmap** — [`ROADMAP.md`](ROADMAP.md): where the app layer goes next. An honest gap analysis
  against the chains that actually generate app revenue (assets → AMM → launchpad → router → wallet
  swap → terminal), the on-ramp/fair-ordering/dev-surface tracks that run alongside it, and the rule
  that keeps it NADO-shaped: **the protocol takes nothing, apps declare their fees on-chain, and the
  default sink is burn.**
- **Consensus hardening plan** — [`doc/consensus-hardening-plan.md`](doc/consensus-hardening-plan.md):
  the locked, ordered design for the remaining security milestones.
- **Scheduled cleanups** — [`SCHEDULED_CLEANUPS.md`](SCHEDULED_CLEANUPS.md): activation gates and
  migration shims that are correct today and deletable at a stated chain height, each with the reason the
  *earlier* cleanup is a bug. Check it after any genesis reroll — height numbering restarts and every
  activation constant in it becomes wrong.
- **Storage design** — [`doc/storage-kv-migration.md`](doc/storage-kv-migration.md).
- **Execution-layer instructions** — [`doc/exec-instructions.md`](doc/exec-instructions.md): every blob op
  (deploy/call/upgrade/lock with `value` escrow, bridge/dividend, emit, privacy) with params + how to submit
  and read. Contracts run on a **STARK-provable zkVM** (the only runtime), authored in **zkasm**
  (`execnode/zkvmasm.py`); every call is provable (`doc/zk-execution-proofs.md`). **Settlement accepts a
  validity proof as of betanet-14** (`SETTLE_PROOF_RECURSIVE`): a settle transaction may carry a K→1
  recursion bundle and L1 verifies ONE proof for the epoch — **~0.3 s, independent of the call count** —
  replaying the authenticated I/O log to recompute the post-state root with **no re-execution**. The
  bonded-stake quorum (`settlement_justified`, the same >2/3 shape as finality) remains the path for epochs
  that ship no proof.
  **15 games ship as live zkVM contracts** — coin flip, dice, roulette,
  slots, mines, blackjack, tic-tac-toe, Connect Four, reversi, chess, farkle, parimutuel sports betting,
  battleship, tamagotchi-NFT pets, and multiplayer Texas hold'em with an on-chain 7-card hand evaluator —
  each an ordinary upgradable contract (opt-in immutability via `lock`) with no game-specific API.
- **STARK recursion — succinct, K→1, O(1) verify** — [`doc/zk-recursion.md`](doc/zk-recursion.md): the path to
  verifying an epoch of execution in constant time. **Live on the L1 consensus path since betanet-14** (`SETTLE_PROOF_RECURSIVE`), gated behind a reroll
  because a node honouring the `recursive` field skips the classic per-segment check: a
  verifier-authoritative in-circuit STARK verifier over an algebraic hash (**alghash2**); **T-independent
  ("succinct") verification** (structured periodic columns — no per-proof O(T) work); a **K→1 collapse** (one
  recursion bundle re-verifies K chained segment proofs from their public parts alone); an **in-circuit
  Fiat-Shamir transcript**; and **recursion depth** (fold-of-folds) whose root **verifies in ~0.2 s regardless
  of tree size** — the O(1)-verification goal, realized. **Honest status:** the *verify* side is O(1) and the
  mechanisms are validated at small scale. Proving is now **native** (Rust-only, no fallback); a full
  settlement prove measures **240–270 s** on production state. The settlement rule **is** wired and
  unconditional (`SETTLE_PROOF_TRUSTLESS` — the ZK feature flags were deleted), but **no proof-carrying
  settle has ever completed end to end**, so the bonded quorum still carries settlement in practice. The
  K→1 fold is built and switched on yet has **never run**: it needs contract calls to fold, and an idle
  chain has none. None of this touches L1 block validity.
- **Every ZK component in one place** — [`doc/zk-components.md`](doc/zk-components.md): the arithmetic
  core, algebraic hashes, STARK proving, the execution zkVM, the shielded pool, state-root binding,
  recursion, the four Rust crates, DA transport and the consensus constants — each marked **live /
  capability / research / removed**, with the measured numbers behind them and an explicit §14 on exactly
  where trustless settlement stops. Start at [`doc/zk-glossary.md`](doc/zk-glossary.md) if the vocabulary
  is new.
- **Previous-network snapshot** — [`doc/previous-network-snapshot.md`](doc/previous-network-snapshot.md):
  the prior NADO network's final account balances (2,801 holders), exported from its ledger index — the
  dev-fund premine excluded, in keeping with the no-premine relaunch.
- **Release notes** — [`RELEASE_NOTES.md`](RELEASE_NOTES.md).
- Project site: <https://nadochain.com> — shared block production explained live at <https://nadochain.com/production> (design: [doc/leaderless-assembly.md](doc/leaderless-assembly.md))

`protocol.py` and the `ops/` modules are the source of truth; where an older companion doc disagrees,
the code wins.

## Related repositories

- [NADO .NET SDK](https://github.com/blocksentinel/nado-dotnet-sdk)
- [NADO Media Kit](https://github.com/hclivess/nado-media-kit)
- [NADO Web Repository](https://github.com/hclivess/nado-web)

---

## For developers

### Design philosophy

New functionality should be driven by the existing routines/loops rather than instant invocation of
functions — every function should have its place in the routine responsible for it. Functions should
be small, independent, and named after the small task they perform; prefer returning values to mutating
objects passed as arguments. Use the existing compounder for multi-target loops rather than synchronous
loops.

### How NADO is structured

- **Level III** — `nado.py` runs all loops and governs API endpoints.
- **Level II** — a central memory element, `memserver.py`, holds shared state accessed by the main
  loops (`consensus_loop.py`, `core_loop.py`, `message_loop.py`, `peer_loop.py`).
- **Level I** — `*_ops.py` modules (`block_ops.py`, `account_ops.py`, `transaction_ops.py`,
  `mining_ops.py`, `kv_ops.py`, `peer_ops.py`, …) hold minimal low-level operations.

### Block production

A block is built with `construct_block()`, then produced via `produce_block()` →
`verify_block()` (with `rebuild_block()` to recompute hashes/weights for remotely received blocks) →
`incorporate_block()`. There is ONE mempool (`transaction_pool`): a submitted tx is validated and
enters it directly, and peers keep pools converged by **set reconciliation** — when advertised pool
hashes differ, a node fetches the peer's txid list (`/transaction_ids`, ~64 B/tx) and downloads only
the bodies it is actually missing (`POST /transactions_by_id`), never the whole pool.

### Contributing

Fork the repository, make your changes, and open a merge request.

## License

Copyright (C) 2022-2026 Jan Kučera (hclivess).

NADO is free software licensed under the **GNU Affero General Public License v3.0**
(see [`LICENSE`](LICENSE)). The AGPL's network clause (§13) means that anyone who
runs a modified version of NADO as a network service must make their modified source
available to its users — you may fork and build on it, but derivative networks must
stay open. This replaces the project's earlier MIT license going forward; copies
already distributed under MIT remain under their MIT grant.
