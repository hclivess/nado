# Takeover resistance — why NADO can't be captured the way Nyzo was

> **Status: architecture rationale (implemented).** This documents the specific attack NADO is shaped to
> prevent — a single actor Sybil-capturing the reward-earning set and locking everyone else out — and the
> mechanisms that make it structurally impossible on the cheap path and merely expensive on the capital path.
> It ties together the two-lane design, the reward-capture bound, and the anti-Sybil economics; see also
> [reward-capture-theorem.md](reward-capture-theorem.md), [mining.md](mining.md),
> [ip-spoofing-and-sybil.md](ip-spoofing-and-sybil.md), and [node-service-reward.md](node-service-reward.md).

## 1. The failure mode (what killed Nyzo)

Nyzo's reward-earning set was the **cycle** of verifiers. You joined a queue, were voted into the cycle, and
in-cycle verifiers took turns producing blocks and splitting the reward. The fatal property was that **cycle
entry was cheap and influence was neither capped nor capital-gated.** One actor spun up hundreds of
verifiers, flooded the queue/cycle, reached a majority, and from there controlled block production and locked
legitimate verifiers out — a **Sybil takeover of the reward set**. It worked for one reason: 500 verifiers
cost that operator almost nothing, and 500 verifiers *meant* 500× the influence.

Generalize it and you get the rule NADO is built on:

> **Any system whose reward-earning weight can be increased by adding cheap, farmable units (nodes,
> identities, IPs, "unique" IPs, heartbeats) will be captured by whoever farms them, because concentrating N
> bots is always lower-friction than coordinating N real people.** The honest side always pays more friction
> for the same units, so the farmer wins.

The only escape is to anchor influence on something **farm-neutral** — a unit that costs a bot exactly what
it costs a person — or to **hard-cap** the cheap path so farming it buys a bounded slice, not the network.
NADO does both.

## 2. There is no single "cycle" to capture

NADO has **no admission-gated producer set**. Every block's producer is a deterministic, beacon-keyed draw
over open state (see [mining.md](mining.md)). Reward flows through **two lanes** with fundamentally different
entry costs, and neither can be monopolized:

- **OPEN lane** — capital-free, anyone can win, **hard-capped**.
- **BONDED lane** — won by staked coins, **farm-neutral cost**.

Because there is no cycle to vote your way into, the Nyzo "flood the queue" move has no target. What an
attacker *can* do is (a) flood the open lane, or (b) buy bonded stake. Both are bounded below.

## 3. The cheap path is hard-capped at ~30%

Anyone can mine the OPEN lane with zero coins. But the open lane is allocated a fixed slice of each epoch's
slots: `K_OPEN / EPOCH_LENGTH = 18 / 60 = 30%`. **No matter how many identities exist**, the open lane wins
at most 30% of blocks. The [reward-capture theorem](reward-capture-theorem.md) proves a free / Sybil actor
cannot exceed ~30% of total emission through it.

This is the direct Nyzo fix: **flooding the cheap path with cheap nodes buys a bounded 30% slice, not the
network.** Sybil a *million* identities and you still top out at 30% — and the
[presence dividend](presence-dividend.md) then spreads that 30% across everyone present (fidelity-weighted, a
fresh Sybil at floor weight), so a farm doesn't even get all of the 30%. On top of the cap, each open
identity carries a renewable **Proof of Sequential Work** lease ([ip-spoofing-and-sybil.md](ip-spoofing-and-sybil.md)) —
non-parallelizable time to create *and to keep alive* — which throttles mass identity creation, but the cap
is the real bound: even free identities cannot cross 30%.

## 4. The rest costs farm-neutral capital

The other ~70% of emission runs through the BONDED lane, won by **staked coins**. To take it over you must
acquire a **majority of the bonded stake** — i.e. buy or earn a large fraction of the actual coin supply.
Three things make this the opposite of Nyzo:

1. **Farm-neutral.** A coin costs a coin to bond whether you are a bot or a person. There is no Sybil
   discount — running more nodes does not make stake cheaper. This is the one anchor with no friction
   asymmetry.
2. **Per-address cap, split-neutral — capital only, no PoSW.** Bonded eligibility is purely `bonded >=
   B_MIN` (100 NADO/share); the bonded lane requires **no registration or PoSW** — that is the OPEN lane's
   cost. A single address's weight is capped at `BOND_CAP` (10,000 NADO → 100 shares), so no single identity
   dominates, but a holder above the cap **spreads real stake across addresses** to deploy all of it. That
   is **split-neutral**: every share costs the same `B_MIN` of real, farm-neutral coins whether concentrated
   or spread, so splitting buys **no Sybil discount** — total influence is ∝ real capital, which is the PoS
   security model, not an exploit.
   **Sudden-whale ramp (implemented).** A newly-bonded identity's **producer-selection** weight ramps
   linearly 0 → full over `BOND_RAMP_EPOCHS` (30), by a **stake-weighted bond age** (`mining_ops.bond_ramp_weight`,
   fed by `bond_since`): a top-up re-ramps the new stake (closing "age a cheap address then dump"), while
   auto-bond's tiny top-ups barely move it. So a whale who bonds a majority **cannot control the very next
   epoch** — it must accrue selection weight over ~30 epochs, buying the network reaction time. Crucially the
   ramp is applied **only to the producer draw**, never to `total_bonded_shares`, so **fork-choice weight and
   the FFG/settlement quorum stay ramp-free** — finality is never made tenure-dependent, and a fresh whale
   still counts its full stake toward slashing/finality the instant it bonds. This only *delays* a patient
   whale; the ultimate bound stays **cost ∝ network value + whale-cap-per-address + finality/slashing.**
   (Genesis-seeded / pre-existing stakes have an unset age = fully aged, so the bonded lane never stalls at
   chain start; tests: `tests/test_bond_ramp.py`.)
3. **Bounded even at majority.** Enforced finality (a persisted, un-reorgable finalized floor) plus
   equivocation **slashing** mean that even a stake majority cannot rewrite finalized history without
   **burning** its own bond. A takeover is expensive *and* self-damaging, not free and consequence-free.

So the capital path is the standard, well-understood cost-of-attack ∝ value-of-network, not a
run-more-nodes exploit.

## 5. The combined guarantee

Put the two together and the Nyzo outcome — "one actor takes the whole reward-earning set" — has no path:

| attacker resource | what it buys | ceiling |
|---|---|---|
| unlimited cheap identities / IPs / nodes | open-lane wins | **≤ ~30% of emission (proven), spread by the dividend** |
| unlimited cheap identities *without* stake | bonded-lane wins | **0** — bonded weight requires bonded coins |
| majority of the coin supply, bonded | bonded-lane control | expensive (∝ network value), whale-capped, and finality+slashing-bounded |

The maximum a *cheap* (Sybil/bot) attacker can ever reach is the 30% open cap. To exceed it they must stop
being cheap and start buying majority stake — at which point they are a farm-neutral, bonded, slashable
majority holder, i.e. the accepted PoS cost-of-attack, not a Nyzo-style free capture.

## 6. Why an IP / node-service reward would *reopen* the vector

This is the practical warning. A reward attached to **IP uniqueness** (or node count, or bandwidth) is
exactly a new cheap-to-farm reward-earning set — a fresh Nyzo cycle bolted onto the side. Cloud/IPv6/proxy
markets make IP diversity cheap and farm-asymmetric, so "more unique IPs → more coins" hands the pool to the
datacenter. Even the *stake-gated* service reward in [node-service-reward.md](node-service-reward.md), which
is carefully built to NOT reopen it (the pool is gated by bond and IP-diversity can only *discount*), adds
**nothing** to takeover resistance — the protection already lives in the lanes. So for the goal of
preventing a Nyzo-style capture, the correct move is **not to add an IP/service reward at all**, and to keep
reward anchored on the two farm-safe things: the 30%-capped open lane and farm-neutral bonded stake.

## 7. Residual risk + what to keep proving

The one honest residual is the PoS universal: an actor who **buys a majority of the bonded stake**. That is
not free (cost ∝ network value), not farmable (no Sybil discount), whale-capped per address, and bounded by
finality + slashing. There is no cryptographic system that removes it without a trusted identity oracle,
which NADO refuses (it is not IDENA).

To keep the central guarantee honest rather than merely asserted, the open-lane cap should carry an
**adversarial regression test**: flood the draw with thousands of Sybil open identities and assert their
combined win rate never crosses `K_OPEN / EPOCH_LENGTH`. That converts "the theorem says ≤ 30%" into "every
commit proves ≤ 30% under a Sybil flood" — a standing, machine-checked guard on exactly the Nyzo scenario.
