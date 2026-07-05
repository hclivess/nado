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
> weight, detached winner signatures + **equivocation slashing**, **FFG-lite stake-attested finality**,
> **commit-reveal RANDAO**) are now implemented; the multi-node, epoch-crossing behaviour of the last
> three is still only lightly exercised empirically (see [Security](#security)). What genuinely remains
> is a subset of **eclipse hardening** (ASN-level peer diversity, pinned multi-seed bootstrap, snapshot-
> bootstrap binding to a finalized signed checkpoint). Run it on testnet / at your own risk; do not
> secure value of consequence with it yet. Chain id: `nado-relaunch-1`.

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
  is at once the **wallet, block explorer, miner, and alias manager** — and, by design, where you'll
  **interact with contracts** too. No install, no browser extension, no full node, no signup, no
  seed-phrase ceremony. **Unlike a MetaMask-style extension wallet** — which only *holds keys*, can't
  mine, and means "install the extension, back up a seed, buy gas, connect to a dApp" before you do
  anything — NADO is just a URL. Open it and you're already a full participant: generate a post-quantum
  wallet, mine, send/receive, register a human-readable **alias**, and browse the chain, all from one
  link on any phone or laptop.

- **Everyone mining earns — a presence dividend, not a lottery.** Winner-take-all blocks mean most miners
  see *nothing* for long stretches. NADO redistributes most of the open lane's block reward to **everyone
  present**, weighted by how steadily they show up — a steady stream instead of a rare jackpot. It accrues
  **off-chain** while you mine (so a million miners cost the chain nothing and there's no dust bloat), and
  you sweep it into your spendable balance with one **Collect** tap — claimed trust-minimised against a
  bonded-quorum-settled state root. Many people getting a little, continuously: what an open, populace-scale
  chain should actually feel like. (Design + mechanism: [doc/presence-dividend.md](doc/presence-dividend.md).)

- **Mine from your pocket — and *forever* if you keep it open.** Presence is a **PoSW lease**: one ~1 s
  proof buys ~a day of eligibility, so a **locked, asleep phone keeps mining** on its own — no relay, no
  per-epoch traffic — and the wallet shows the exact "mining while locked" countdown. Leave the page
  **open and mining never stops**: it auto-renews the proof just before it lapses, auto-bonds your rewards
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
- **Consensus anti-Sybil registration.** Registration is a non-parallelizable **sequential PoSW** whose
  difficulty **scales with recent registration volume** (enforced in validation off the finalized anchor
  epoch), so an identity flood gets progressively more expensive while a normal network stays at 1×
  (`doc/registration-difficulty.md`).
- **Two-lane "diligence" mining.** A free **OPEN lane** anyone can win with no coins (capped at ~30%
  of blocks, a *population-independent* Sybil ceiling) plus a **BONDED lane** won with refundable,
  whale-capped stake. Bonding is **optional** and only boosts the bonded lane — never required.
- **Post-quantum signatures.** ML-DSA-44 (NIST FIPS 204 / Dilithium) via pure-Python `dilithium-py`
  — no native build, in keeping with the lightweight goal. Cross-validated against the browser's
  `@noble/post-quantum` so a phone and a full node verify each other.
- **Lightweight & reproducible.** Consensus hashing is over canonical JSON, so a browser client
  reproduces every address, transaction id, and verification byte-for-byte. State is a single
  memory-mapped key-value store; block bodies are compact zstd-compressed blobs.
- **First-party clients.** A browser/mobile NADO Interface that is also a full wallet, a PySide6 desktop
  wallet, and browsable explorer endpoints on every node.

---

## How mining works

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

1. **Register** by computing a **sequential Proof-of-Work (PoSW)** — a *non-parallelizable* hash chain
   (`POSW_T` steps, ~1 s in-browser, fee-exempt, **post-quantum**: it assumes only blake2b — no trusted
   setup, no elliptic curve, nothing Shor-breakable). Unlike the old parallelizable hashcash, a GPU/ASIC
   can't mint identities in bulk, and the proof is **validated by every node in consensus**
   (`validate_transaction`, the block-validation path) — not just the relay you connect to, so a bogus
   registration is rejected network-wide. Registration is a **renewable presence lease**
   (`POSW_LEASE_EPOCHS`, ~1 day): to stay in the open lane you renew with a *fresh* PoSW, turning
   "pay once, farm forever" into "pay continuously per identity." The structural ~30 % lane cap is still
   the *hard* Sybil bound; the PoSW lease prices identity creation **and upkeep** in real sequential time
   on top. The recert is the **single presence signal — there is no separate heartbeat.** You're eligible
   iff you have a recert within `POSW_LEASE_EPOCHS`, so **AFK mining is trivial: one ~1 s PoSW buys a full
   lease of eligibility, locked phone or not** — no relay, no pre-signed heartbeats, no per-epoch traffic.
   The miner auto-renews at ~80 % of the lease; kept open, it mines *forever*.

> **Why no separate per-epoch heartbeat?** An earlier design had one. But once the lease covers the whole
> ~1-day AFK window (and can be pre-signed), a per-epoch heartbeat is co-terminal with the lease and carries
> no information the recert doesn't — redundant. Collapsing to one signal is strictly simpler: the recert
> **prices the identity *and* marks presence**. The ~30 % lane cap stays the hard Sybil bound regardless.

Open-lane selection weight is **capital-free**: a flat floor (`OPEN_BASE_FLOOR = 2`) every present
identity always gets, plus a diligence ramp to `OPEN_FID_BONUS = 8` over `FIDELITY_CAP = 30` **consecutive
recerts** (overall range 2..10). Fidelity is **continuity over recerts** (`apply_register`,
revert-symmetric): a continuous recert adds a step, a lapse resets the streak — so a rotated/churned
identity can't keep a ramp it stopped paying for. The single most effective thing you can do is **stay
present**. Mine to **one address** — splitting across addresses gains nothing, and onboarding many
addresses from one machine is throttled (below).

> **Progressive IP-diversity onboarding cap.** Registering (onboarding) new OPEN-lane addresses is
> rate-limited per source IP *by subnet proximity*: a new address's "crowding cost" is full for a
> same-exact-IP peer and halves for each broader shared prefix (same /24 = ½, /16 = ¼, /8 = ⅛),
> unrelated networks cost nothing (IPv4 /32·/24·/16·/8; IPv6 /128·/64·/48·/32). So a datacenter /24
> gets one bounded shared budget while distinct networks aren't penalised — stopping "one box scripts
> 10 000 miners" at the entry point. This is **relay admission control, not consensus** (an IP can't be
> a consensus input without forking); the *hard* Sybil bound is still the structural ~30 % lane cap.
> Budget is `max_registrations_per_ip` (default 64/hr, `NADO_MAX_REG_PER_IP`, `0` = off).

### The BONDED lane (optional stake)

A `bond` transaction moves spendable balance into a non-spendable `bonded` column; an `unbond`/`withdraw`
pair moves it back out after a timelock (see below). Bonded selection weight is
`min(bonded, BOND_CAP) // B_MIN`, capped at `MAX_SHARES = 100`:

- **Split-neutral** — weight depends only on total bonded capital, so sharding across many addresses
  gains nothing.
- **Whale-capped** — a single identity tops out at `BOND_CAP = 10,000 NADO` (`B_MIN = 100 NADO` per
  share), so no whale can monopolise the lane. The bond is **refundable** — you keep your coins.

> **Bonded mining is passive — no work, no need to be online.** Once you hold enough to bond (`B_MIN =
> 100 NADO`), you can stop *actively* mining: the bonded lane is **staking**, not proof-of-work. There is
> **no PoW/PoSW to compute, no periodic recert, and no requirement to keep the app or a node open** — the
> beacon draws you in proportion to your stake, and because winners are credited **by address**, a relay
> builds your winning block even while you're offline. With **auto-bond** on, rewards compound straight back
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
  block** (~144 NADO/day at 60 s), and `m·BASE ≈ 0.0166` the min (perpetual tail, ~8,700 NADO/yr forever).
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

NADO runs on Python 3.10+. The entrypoint is `nado.py`; the node serves its API and web UI on port
**9173**.

### One-command install (recommended)

`scripts/install.sh` creates a venv, installs the node dependencies (skipping the desktop-wallet-only
`PySide6` so a server install stays lean), and prints how to run. Re-running is safe (idempotent).

```bash
git clone https://github.com/hclivess/nado
cd nado
scripts/install.sh                 # venv + node deps
nado_venv/bin/python nado.py       # run it
```

Flags: `--wallet` also installs the desktop-wallet deps; `--service` (as root) installs a systemd
service for **unattended** running; `--auto-bond <pct>` auto-compounds mined rewards (see below);
`--home <dir>` keeps chain data under `<dir>/nado` instead of `~/nado` (recommended when the repo
itself is checked out at `~/nado`). Run `scripts/install.sh --help` for all options.

### Manual setup

```bash
git clone https://github.com/hclivess/nado
cd nado
python3.10 -m venv nado_venv
source nado_venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt   # PySide6 (last line) is wallet-only; the node doesn't need it
python nado.py
```

Once running, open <http://127.0.0.1:9173> for the node's web interface and JSON endpoints. To join a
network, announce your node to a peer:

```
http://127.0.0.1:9173/announce_peer?ip=<peer-ip>
```

For public reachability and rewards, forward **port 9173**. Close the node cleanly with **CTRL+C** or
`http://127.0.0.1:9173/terminate` (never the window's **X**, to avoid database corruption). To wipe
local data and resync from scratch, stop the node and run `python purge.py` — it clears the chain
state (`blocks/`, `index/`, `logs/`) under your data home while keeping your keys and peers; on the
next start the node rebuilds genesis (re-seeding the public bootstrap) and resyncs from the network.

### Run unattended (mine 24/7, no terminal)

For a node that **mines on its own** — starts on boot, restarts on crash, needs no open terminal —
install the systemd service (Linux):

```bash
sudo scripts/install.sh --service                 # boots on start, restarts on failure
sudo scripts/install.sh --service --auto-bond 25  # ...and auto-bonds 25% of mined rewards
sudo scripts/install.sh --service --home /srv/nado-data   # chain data in /srv/nado-data/nado
```

```bash
systemctl status nado        # health
journalctl -u nado -f        # live logs
systemctl stop nado          # clean shutdown (never kill -9 — it can corrupt the DB)
```

Without systemd, run it detached with `nohup`:

```bash
cd nado && nohup nado_venv/bin/python nado.py > nado.out 2>&1 &
```

### Auto-bond — compound mined rewards into stake, hands-free

A miner routes a **percentage of newly-mined rewards straight into bonded stake**, auto-compounding
their weight in the bonded lane without any manual `bond` transactions. It is **on by default at
`AUTO_BOND_DEFAULT_PERCENT = 80%`** (a fresh node / browser / wallet with no saved preference joins the
bonded lane hands-free) and fully **overridable** — set `0` to keep all rewards spendable; an explicit
`0` is remembered and never reverts to the default. It is throttled to **at most one bond per epoch**,
only fires once the accrued amount clears a small dust floor (so each bond dwarfs its tiny fee), and
**stops automatically at `BOND_CAP`** (10,000 NADO — bonding past it buys no extra selection weight, so
it never needlessly freezes coins). It is available in **all three clients**:

- **Node (unattended):** set `auto_bond_percent` in `private/config.dat`, or the
  `NADO_AUTO_BOND_PERCENT` environment variable (which the `--service` installer wires into the unit).
  The node bonds the configured share of its own block rewards each epoch — ideal for a headless miner.
- **Browser interface:** the **Stake** tab has an "Auto-bond mining rewards" field; while the tab is
  mining it compounds that share of your rewards (persisted in the browser).
- **Desktop wallet:** the **Mining** tab has an "Auto-bond mining rewards" control (persisted in
  `~/.nado_wallet/wallet.json`).

It is a **client/operator convenience and is never validated on-chain** — every auto-bond is just an
ordinary signed `bond` transaction.

Two more unattended behaviors round out a hands-free headless node (both best-effort, once per epoch, never
disrupting consensus):

- **Auto-collect the presence dividend** — **on by default** (`auto_collect_dividend` / `NADO_AUTO_COLLECT`):
  sweeps your accrued dividend into a provable collection. Skipped unless the node is an open-lane member
  (a bonded-only node accrues none, so it never burns a wasted fee).
- **Auto-register the open lane** — **opt-in** (`auto_register` / `NADO_AUTO_REGISTER=1`): keeps the PoSW
  presence lease alive (registers when absent, renews inside the lease tail), so a server can mine the free
  lane 24/7 unattended. Off by default so a headless node never silently joins — and Sybil-loads — the open
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
`root soft/hard nofile 65535`, `fs.file-max = 100000` via `sysctl`), run inside `screen`, and use the
`deadsnakes` PPA for `python3.10-venv`. Update an existing install with `git reset --hard origin/main
&& git pull origin main`.

### Windows

Install [Python](https://www.python.org/downloads/), `python -m pip install -r requirements.txt`, then
`python nado.py`. Run the console as Administrator and close with **CTRL+C** or `/terminate`.

---

## Mine from a phone

Open the running node's light-miner in any browser:

```
http://<node-ip>:9173/static/interface.html
```

The NADO Interface (`static/interface.html` + `static/interface.js`) is also a **full wallet**: it generates or
imports a key, computes the sequential registration **PoSW** in pure JS (byte-identical to the node's
verifier), registers/renews its PoSW lease against the node (no heartbeats), and **keeps winning blocks even while the
phone is locked** — presence is a ~1-day PoSW lease (no per-epoch traffic), and a relay assembles the
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
  `keys.dat`: `info`, `send`, `register` (computes the sequential PoSW), `bond`/`unbond`, `alias`,
  `propose`/`vote`/`execute` (treasury governance), `collect` (presence dividend), `bridge-deposit`. It builds
  the *same* signed transaction the browser does and POSTs it to the node's existing `/submit_transaction` —
  no new signing endpoint, no new trust surface. Full reference: **[doc/cli.md](doc/cli.md)**.
- **Browser / mobile NADO Interface (wallet)** — `static/interface.html` (see above).
- **Desktop wallet** — `python3.10 pyside_wallet.py` (PySide6): overview, send, bond/unbond, register
  & mine, expected-time-to-mine, an **auto-bond** control (compound a % of mined rewards into stake),
  and a live selection-lane visualization. PySide6 is wallet-only; the node itself does not need it.
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
  `parent.cumulative_weight + total_bonded_shares(as-of-parent)`. It is the *total* bonded registry
  weight (not the slot winner's share), so it is **beacon-independent**: a proposer can't grind the
  beacon to inflate fork weight. Recomputed in `rebuild_block` and verified as-of-parent.
- **Enforced finality floor** — a block at height H finalizes everything at/below `H - FINALITY_DEPTH`
  (`FINALITY_DEPTH = 30`); rollback **refuses** to cross the persisted, monotonic finalized height
  (raises `FinalityViolation`). The ordering `max_rollbacks (10) < FINALITY_DEPTH (30) < EPOCH_LENGTH
  (60)` means honest reorgs never hit the floor while a long-range reorg is capped below one epoch.
- **Fail-loud epoch beacon** — `epoch_beacon` chains from the hash of the first block of the previous
  epoch (a finalized, non-parent anchor), and now **raises instead of silently substituting**
  `GENESIS_BEACON` when the anchor is missing (a missing anchor means this node is under-synced).
- **Detached winner block signature** — when the selected winner is online it attaches an *optional*
  ML-DSA signature **outside** the hash preimage (so it never affects the hash, weight, validity, or
  reward); verifiers reject a present-but-forged or wrong-signer signature. An offline winner's
  relay-built block is simply unsigned and still valid — **"win-while-offline" is preserved**.
- **Equivocation slashing** — two valid winner signatures over *different* blocks at the *same*
  height+parent form a portable proof that an identity double-authored a slot. A fee-exempt `slash`
  transaction carrying that proof burns `SLASH_BOND_PENALTY` (= `B_MIN`, one bonded share) of the
  offender's **bonded** stake. Anyone may report it (the unforgeable proof is the anti-spam); it is
  replay-guarded to **one slash per (offender, height)**, revert-symmetric on rollback, and the coins
  are **destroyed** (the deterrent is the loss, not a bounty). Validation requires the offender still
  hold the penalty so the dock never floors.
- **FFG-lite stake-attested finality** — bonded validators emit one `attest` transaction per epoch for
  that epoch's checkpoint (its first block). A checkpoint **justifies** at *strictly* >2/3 of total
  bonded shares (`FFG_NUM/FFG_DEN = 2/3`) and **finalizes** on two-consecutive-justified; on-chain
  `UNIQUE(validator, epoch)` prevents double-voting. This is exposed as **`/status.ffg_finalized`**.
  It is an **additive, observable, accountable** finality signal layered *on top of* the depth-based
  floor — it does **not** replace the time-based `finalized_height` (which stays the deeper rollback
  bound and guarantees liveness), so FFG can never stall the chain.
- **Commit-reveal RANDAO** — bonded validators `commit` a secret's hash in epoch E−2 and `reveal` it
  in E−1's finalized window; `epoch_beacon` now mixes the finalized prior-epoch anchor with the
  revealed secrets, so **no single anchor-producer controls the beacon**. With zero reveals it falls
  back to the anchor-only value (liveness). It keeps the anchor (non-recursive), so the beacon stays
  snapshot-safe and the reveals are immutable by the time the beacon is needed.
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

The equivocation slashing, FFG-lite finality, and commit-reveal RANDAO above are **wired and
unit-tested for correctness**, but their **multi-node, epoch-crossing** behaviour has only been
**lightly exercised empirically**: the core loop's ~10 s/block cadence makes crossing the 120+ blocks
needed to observe a full justify→finalize and a complete commit→reveal cycle slow. They engage as the
chain crosses epochs; treat their cross-epoch dynamics as not-yet-battle-tested.

### Planned (designed, NOT yet implemented — do not rely on these)

- **Broader eclipse hardening** — beyond the per-/16 subnet cap and the `/announce_peer` rate-limit
  (both already live): **ASN-level** (vs /16) peer-diversity caps, pinned anchor outbound slots, a
  **multi-seed** bootstrap list (replacing the single genesis seed), and **snapshot-bootstrap binding
  to a finalized signed checkpoint**. These are post-launch items.

### Honest statement of current limits

Objective fork-choice, enforced finality, equivocation slashing, FFG-lite stake-attested finality, and
the commit-reveal RANDAO make a zero-bond Sybil/IP reorg ineffective, bound the disagreement window
below one epoch, and layer accountable finality and a non-grindable beacon on top — a substantial
hardening over the previous peer-count fork-choice. Beyond the lightly-exercised cross-epoch behaviour
of FFG/RANDAO and the outstanding eclipse hardening above, the **documented residuals** from the audit
(see [`doc/security-audit.md`](doc/security-audit.md)) — none a theft or fork vector — are:

- **No RANDAO withholder penalty.** A producer suppressing its own reveals has up to `2^m` grinding
  combinations; defeated whenever ≥1 honest secret is revealed after the anchor. A withholder fidelity
  dock + minimum-reveal rule is future work.
- **FFG "slashable-stake backing" is aspirational** — there is **no attestation-equivocation slashing**
  yet (only block-authorship equivocation is slashable). On-chain double-voting is blocked by the
  per-epoch `UNIQUE(validator, epoch)` marker, but cross-fork attestation equivocation is unpunished;
  FFG remains an observational signal.
- **The bonded `MAX_SHARES` cap is per-identity, not aggregate** — sharding capital above `BOND_CAP`
  across addresses recovers full proportional weight. The bonded lane is **capital-proportional by
  design**; the cap only limits single-address variance, not aggregate stake.
- **Registration / fee-exempt state growth** — `register` writes a permanent account doc; `GC_IDLE_EPOCHS`
  is defined but **not yet wired**. Bounded today by the lane cap, per-IP rate limit, mempool cap, and the
  in-block one-register-per-sender dedup; idle-account GC is future work.
- **Fidelity is continuity over recerts** — `apply_register` adds a step for each *continuous* recert
  (gap ≤ the lease) and resets the streak on a lapse; it ramps the open bonus over `FIDELITY_CAP` recerts.
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
- **Hashing & serialization** — BLAKE2b over `canonical_bytes()` (compact, sorted-key, ASCII JSON,
  float-free). Every consensus integer is a raw integer, so a browser reproduces identical bytes with
  BigInt-aware serialization. Transaction ids and blocks bind `CHAIN_ID = "nado-relaunch-1"`, blocking
  cross-chain / pre-relaunch replay.
- **Wire** — transactions submit over **HTTP POST + msgpack** (an ML-DSA-44 tx is too large for a GET
  URL); msgpack is wire/transport only and never the hashed preimage.

## Storage

State lives in a single **schemaless, memory-mapped, ACID key-value store (LMDB)** — `ops/kv_ops.py`,
which **replaced the prior SQLite index**. Account/state records are schemaless msgpack documents
(no columns, no DDL), so adding a field needs no migration. A whole block's mutations (account docs,
tx index, block index, totals, heartbeats) commit in **one** write transaction, so a crash leaves a
block either fully applied or not at all, and replay is idempotent. Block bodies stay as `zstd(msgpack)`
files under `blocks/`, and consensus hashing stays canonical JSON — neither is touched by the index.

**Archive vs rolling nodes (opt-in history pruning).** By default a node is an **archive** node
(`config.archive = true`) that keeps every block body forever. Set `archive = false` (or `NADO_ARCHIVE=0`)
to run a **rolling/pruned** node that drops finalized block *bodies* older than `HISTORY_RETENTION_BLOCKS`
(default 10 000 ≈ 1 week) while **always** keeping state and the number↔hash indexes — so it stays a full
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
- **Consensus hardening plan** — [`doc/consensus-hardening-plan.md`](doc/consensus-hardening-plan.md):
  the locked, ordered design for the remaining security milestones.
- **Storage design** — [`doc/storage-kv-migration.md`](doc/storage-kv-migration.md).
- **Release notes** — [`RELEASE_NOTES.md`](RELEASE_NOTES.md).
- Project site: <https://nadochain.com>

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
`incorporate_block()`. The mempool has three levels: `user_tx_buffer` (direct user submissions) →
`tx_buffer` (merged with other nodes' pools for the next block) → `transaction_pool` (merged in before
block production).

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
