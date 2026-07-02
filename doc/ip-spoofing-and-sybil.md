# IP spoofing, Sybil identities, and fair distribution of the open lane

**This is a FAIR-DISTRIBUTION concern, not a chain-safety one.** Sybil identities and IP spoofing cannot
halt the chain, double-spend, or take the bonded lane — the objective consensus and the `OPEN_BPS` lane
cap prevent that. What they *can* do is let **one entity masquerade as many distinct participants and so
capture a disproportionate share of the free, zero-capital OPEN lane** — eroding the promise that the
fair launch distributes coins broadly to *real, distinct* phone miners rather than to one operator wearing
10 000 masks. This document is about that: keeping the open-lane *distribution fair*, and why IP is a weak
tool for it.

**TL;DR.** An IP address is **not** a consensus input in NADO and never can be — it is spoofable,
NAT/CGNAT-ambiguous, and different nodes see a different IP for the same peer. The per-IP registration
cap (`ops/ratelimit.allow_registration`) is therefore only **best-effort relay friction**: it raises the
cost of casually scripting thousands of identities from one box, but a motivated operator can bypass it
(VPNs, proxies, a botnet of real residential IPs, IPv6 address space). The one **hard** guarantee is
distributional and IP-independent: the OPEN lane is a fixed `OPEN_BPS` (20%) of blocks no matter how many
identities register, so Sybil can *redistribute* the free lane unfairly but can never *enlarge* it
(whitepaper §2.2). Everything else here is about narrowing that unfair-redistribution gap.

---

## 1. What an IP is (and is not) in NADO

| | |
|---|---|
| **Is** | A hint used by one relay to throttle *registration admission* at its own front door. |
| **Is not** | A consensus input. Selection weight, fork-choice, finality, and validity never read an IP. |

The only place an IP is consulted is `nado.py:_ip_registration_rejection` → `ratelimit.allow_registration`,
called when a `register` transaction is **submitted to a relay**. It is a local rate-limit, applied before
the tx enters the mempool. It is not in any signed structure, not hashed into any block, and not
replicated. Turning it off (`max_registrations_per_ip = 0` / `NADO_MAX_REG_PER_IP=0`) changes nothing
about consensus.

## 2. Why IP can never be a consensus input

If block production, selection weight, or validity depended on a peer's IP, the chain would **fork on
sight**, because:

- **Nodes see different IPs for the same identity.** Behind NAT/CGNAT/VPN, the "source IP" a peer
  presents differs per observer and per hop. There is no canonical IP for an address, so two honest nodes
  would compute different results and diverge.
- **It is trivially spoofable at the layer that matters.** For a rate-limit the source IP of a TCP
  connection is hard to forge *to complete a request*, but an attacker doesn't need to forge it — they
  simply **use many real IPs**: a $5 VPN rotates through hundreds; a residential-proxy service sells
  millions of real consumer IPs; a /64 of IPv6 is 18 quintillion addresses handed to a single home line.
- **It punishes honest users.** A CGNAT carrier puts thousands of *real, independent* phone users behind
  one IPv4 address — exactly NADO's target audience. Any IP-based *consensus* rule would disenfranchise
  them while barely inconveniencing an attacker with address space to burn.

So IP is deliberately kept **out** of consensus. This is a design invariant, not an oversight.

## 3. How Sybil / IP-spoofing skews the open-lane distribution

The concern is **fair distribution**: one operator registering many OPEN-lane identities to collect more
than one person's fair share of the free, zero-capital lane — coins that were meant to spread to *distinct*
newcomers. Walk that operator's path:

1. **Bypass the per-IP cap.** Given VPNs / proxies / IPv6 / a botnet, the per-IP crowding cost
   (`ratelimit.allow_registration`, progressive by subnet proximity: ~`max_addrs` per exact IP, ~2× per
   /24, ~4× per /16, ~8× per /8) is *friction, not a wall*. Assume the attacker defeats it.
2. **Register N identities.** Each `register` costs a **sequential PoSW** (`ops/posw.py`) instead of a
   fee — a non-parallelizable hash chain, so a GPU gives ~no edge and N identities cost N *serial
   time-lanes*, not N cheap parallel PoWs. This is the current, shipped cost (it replaced the old
   parallelizable 16-bit hashcash). Still, a datacenter with many cores can run many lanes, so assume
   the attacker registers as many as it is willing to pay serial time for.
3. **Keep all N present by renewing each recert lease** — one fresh PoSW per identity roughly once per
   `POSW_LEASE_EPOCHS` (≈ 1 day), **not** a per-epoch heartbeat (the heartbeat tx and `PRESENCE_WINDOW`
   were removed). So upkeep, not just creation, is priced in sequential time: the farm pays
   *size × time*, continuously, to keep its masks alive.
4. **Collect open-lane blocks proportional to their share of the open registry.**

**What this does NOT buy them:** more than `OPEN_BPS = 2000` bps (**20%**) of *all* blocks. The lane split
permutes **slot indices**, not per-identity weight, so the OPEN lane is a fixed fraction of blocks *no
matter how many identities register*. Flooding the open registry only makes the attacker compete with
**honest open-lane miners for the same fixed 20%** — it dilutes the honest open-lane miners' share, but it
**cannot touch the 80% bonded lane** and cannot exceed 20% overall. And the reward per open block is a flat
base subsidy, so N identities split the same 20% pie — there is no super-linear payoff to registering more.

So the worst case of *total* IP-cap bypass is: **an operator can crowd out honest zero-capital miners
within the 20% free lane** — a *distribution* harm (fewer real newcomers get their share), bounded and
never a *safety* harm (no chain halt, no double-spend, no reach into the bonded lane). The whole question
is how close to "one share per real person" we can push the open lane, given that IP can't get us there.

## 4. What keeps the distribution fair (defense-in-depth)

1. **Structural lane cap — the hard bound.** `OPEN_BPS` (20%) caps the free lane at the *slot-permutation*
   level. A free botnet can never exceed 20% of blocks or reach the bonded lane. This is the project's
   central security parameter (whitepaper §2.2) and it is **population-independent** — it holds against an
   attacker with unlimited identities and unlimited IPs.
2. **Reward dilution — the economic bound.** Open-lane reward is split among *all* present open miners, so
   registering more identities does not increase the attacker's total take beyond the 20% pie; it only
   splits it more finely. There is no economic incentive to Sybil for profit, only to *deny* honest
   miners — a griefing motive, not a profit one.
3. **Renewable PoSW recert lease — a farm-neutral per-identity cost (creation AND upkeep).** Each identity
   pays a **sequential** proof-of-work (`ops/posw.py`) to register, and pays another to *renew* before its
   `POSW_LEASE_EPOCHS` (≈ 1 day) lease lapses. Because the PoSW is non-parallelizable, a GPU/ASIC gives ~no
   edge — the cost is real serial wall-clock time, per identity, per lease. For an honest phone that is ~1 s
   once a day; for a farm it is *size × time* of continuous serial compute. This is the shipped mechanism
   (it replaced the old parallelizable 16-bit hashcash and the removed per-epoch heartbeat). It is
   deliberately light per identity, so it is not a Sybil *wall* — but unlike the old hashcash it prices a
   fleet in a resource a farm cannot parallelize away.
4. **Progressive per-IP crowding cap — DEFENSIVE friction only.** `ratelimit.allow_registration`
   (`max_registrations_per_ip`) makes casual single-box scripting expensive and bounds a datacenter's whole
   subnet, not just one IP. It is used **purely defensively** at a relay's front door — never in consensus.
   Evadable (VPNs/proxies/IPv6), but it raises the floor for the low-effort attacker (the common case).

> **The organizing principle: a permissionless Sybil anchor must be FARM-NEUTRAL** — it must cost an
> automated bot the *same* as a real human, or the farm simply pays less per mask than the humans it
> displaces and the "fair" distribution collapses. Two costs qualify: **capital** (the bonded lane — a coin
> costs a bot and a human the same) and **sequential-work-per-lease** (the open lane — a second of serial
> time is a second for either). **IP uniqueness does NOT qualify**: IPs are far cheaper per-unit for a farm
> (bulk proxies, a whole IPv6 /64) than for a human, and they punish shared/CGNAT humans — so IP can only
> ever be defensive friction, never the anchor. See doc/takeover-resistance.md and doc/node-service-reward.md.

The fairness posture is therefore: **do not try to make Sybil impossible; make its payoff bounded (20%
lane) and unprofitable (reward dilution), price each mask in a farm-neutral cost (the sequential-PoSW
recert lease), and add cheap defensive friction (the per-IP cap) against the low-effort masquerade.** IP
is the outermost, weakest, most-evadable layer, and the design is deliberately built so that its failure
only skews *how the free lane is shared*, never anything about safety.

## 5. Ideas to make the open-lane distribution fairer / harder to spoof (ranked)

None of these are free; each trades away some of NADO's fair-launch / phone-first / permissionless
identity. Listed strongest-first by how well they tie one share to one *real, distinct* participant, with
the cost each imposes.

1. **Proof-of-personhood / unique-human identity** (BrightID, Worldcoin-style, Idena's synchronous
   flip-test, social-graph attestation). *Strongest* Sybil resistance — caps identities at ~one per human.
   **Cost:** centralization / liveness ceremonies / privacy loss / an onboarding wall that kills "open a
   link and you're mining." Idena's flip-test is the closest fit to NADO's ethos but requires everyone to
   be online simultaneously for validation. **Verdict:** philosophically opposed to the one-tap fair
   launch; keep as an *optional* per-deployment overlay, not the base layer.
2. **Scale the registration PoW with open-registry population** (adaptive difficulty: the more identities
   present, the harder each new registration). Makes a *large* Sybil fleet cost real energy while a normal
   phone still registers cheaply when the network is small. **Cost:** reintroduces a mild hash-race at the
   registration edge (against NADO's "nothing to grind" ethos), and a determined attacker with GPUs still
   wins; hurts honest late-joiners as the network grows. **Verdict:** a plausible, self-contained lever —
   worth prototyping as an *edge* cost (registration only), never in block production.
3. **Small refundable bond to enter the OPEN lane** (a tiny stake, returned on exit). Directly prices
   identities. **Cost:** breaks the **zero-capital** promise — the whole point of the OPEN lane is that a
   coinless newcomer can mine. Even a tiny bond needs coins the newcomer doesn't have. **Verdict:**
   rejected; it collapses the OPEN lane into the BONDED lane.
4. **Proof-of-storage / proof-of-space per identity** (a per-identity resource that is costly to replicate
   N times). Sybil cost scales with a real resource without a hash-race. **Cost:** phones can't spare much
   storage; complexity; still buyable at scale. **Verdict:** poor fit for phone-first.
5. **Device / platform attestation** (Play Integrity, Apple App Attest, WebAuthn/passkey per device).
   Caps identities at ~one per genuine device. **Cost:** centralizing (Google/Apple as gatekeepers),
   excludes de-Googled / desktop / non-attested devices, and a browser-only client can't do full device
   attestation. **Verdict:** a strong *optional* filter for app builds, not for the open web client.
6. **Behavioural / network heuristics at the relay** (timing correlation, TLS/JA3 fingerprint,
   ASN-reputation, "these 10k registrations all arrived in 200ms from one ASN"). Catches the lazy botnet.
   **Cost:** best-effort, evadable, false-positives against CGNAT, and it is *relay-local* (each operator
   sets its own), so it can't be a consensus rule. **Verdict:** worth adding to `ratelimit` as opt-in
   relay policy — it is the cheapest win against the *common* low-effort attacker and changes no invariant.
7. **Lower `OPEN_BPS`.** If free-lane Sybil ever becomes a practical griefing problem, the blunt but
   *guaranteed* mitigation is to shrink the attackable surface: a smaller open lane means a Sybil flood
   captures a smaller slice of total blocks. **Cost:** directly reduces the fair-launch subsidy to honest
   zero-capital miners — it trades fairness for Sybil-resistance one-for-one. **Verdict:** the reliable
   backstop knob; it is already the security-defining parameter and is config-visible.

## 5a. The proposed refinement: attribute registrations to the relay *node's* IP

**Idea:** instead of rate-limiting by the *miner's* (spoofable, NAT-ambiguous, client-side) IP, take the
IP of the **node** a miner registers/recerts *through*, and make **every address mining via that node
share that node's IP budget**. A node's IP is more stable and observable than a phone's, and a full node
is heavier to spin up than a rotating client IP — so the thinking is that this raises the Sybil bar.

It has a real kernel, but two structural problems and one promising twist:

- **It helps a little: it shifts the unit of cost from "cheap client IP" to "a whole node."** Running N
  full nodes on N IPs is more effort than rotating N proxy IPs from one script. So the *low-effort*
  attacker is inconvenienced more than by the current per-client cap.
- **Problem 1 — it punishes the legitimate shared relay, hard.** A single popular public relay (exactly
  like the live demo node) serves *thousands of real, independent phone miners*. If they all share **one**
  node-IP budget, that relay's honest users hit the cap and are locked out — the CGNAT problem, but
  amplified: one relay is *thousands* of real people, not dozens. This directly attacks the "share a link,
  the whole school mines through my node" story. To avoid it the budget must be so generous it stops
  limiting anything.
- **Problem 2 — it does not stop the self-hosting attacker.** If the budget is per node-IP, the attacker
  simply **runs their own node(s)**. A node is just software; 1 000 cheap VPS instances (or one machine on
  a /64 of IPv6) give 1 000 node-IPs, each with a full budget. So it collapses back to the same
  IP-multiplication attack, only one heavier level up — and it is *still* not a consensus rule (a miner can
  submit the same registration to many nodes; there is no canonical "which node owns this address," and
  the block *producer* is chosen deterministically, not by the miner, so you can't bind the identity to a
  node in a way all nodes agree on).

**The promising twist — sponsorship by a *bonded* node (stake as the Sybil resource).** The genuinely new
angle hiding in this idea is not the *IP* but the *node*: make a registration be **vouched for by a bonded
node**, and put that node's **stake** at risk for the identities it sponsors (e.g. a sponsor that floods
Sybils can be slashed, or its sponsored identities are rate-limited against its bonded shares). Now the
Sybil cost is **economic and on-chain** (locked stake), not an IP heuristic — and crucially the *miner*
stays **zero-capital** (the sponsor holds the stake, not the phone). This is delegated, staked admission:
identity creation is scarce because sponsorship is scarce, while onboarding stays one-tap for the user.
Trade-offs: it centralizes onboarding onto bonded sponsors, a sponsor can still Sybil up to its own stake,
and it needs careful on-chain accounting (a `sponsor` field bound into `register`, sponsor-stake-weighted
registration budgets, and a slashing condition) — but unlike the IP schemes it is **enforceable in
consensus** and **spoof-proof**, because stake is on-chain and IP is not. This is the version worth
prototyping if free-lane Sybil ever becomes a practical problem.

**Verdict on the raw "share the node's IP" form:** net-negative as stated — it degrades legitimate shared
relays more than it costs a self-hosting attacker, and it is still an off-chain IP heuristic. Keep the
*node-level* intuition but move the scarce resource from **IP → bonded stake** (sponsorship) to get a real,
consensus-enforceable Sybil cost without breaking zero-capital mining.

## 5b. The permissionless, no-bother lever: cost from a real physical limit (sequential time / VDF)

> **Status: this is now the shipped mechanism.** The lever proposed in this section was adopted. NADO
> registration is a hash-based **Proof of Sequential Work** (`ops/posw.py`, verified in consensus in the
> `register` branch of `ops/transaction_ops.py`), and presence is a **renewable recert lease**
> (`POSW_LEASE_EPOCHS`, `account_ops.get_open_registry`) rather than a per-epoch heartbeat. The reasoning
> below is why; **Appendix A** explains why NADO uses a *hash-based PoSW* rather than an algebraic **VDF**
> (post-quantum). Read "VDF" throughout this section as "the sequential-time primitive", realized as PoSW.

Start from the hard result. **Permissionless Sybil resistance is impossible without *some* cost to
minting an identity** (Douceur, 2002 — the paper that named the Sybil attack): with no trusted authority,
an entity with more resources than any honest peer can always mint more identities. So the goal cannot be
"free *and* permissionless *and* Sybil-proof" — that's a trilemma, pick two. NADO keeps **permissionless**,
wants **no-bother**, and therefore must accept a *bounded* (not zero) Sybil, sourced from a cost that a
real single user barely notices but that a farm cannot dodge. The `OPEN_BPS` cap already bounds the
*damage*; the question here is what cost bounds the *count* without permission or friction.

The only resource that is permissionless, needs no identity/stake/gatekeeper, doesn't reintroduce a
grindable hash-race, **and** is anchored in a genuine physical limitation is **sequential time**, proven
with a **VDF (verifiable delay function)**:

- **The real technical limit:** a VDF is *inherently sequential* — by construction it cannot be sped up
  by adding cores, GPUs, or ASICs beyond a small constant factor (a VDF has a known-fastest algorithm;
  that is the whole point of the primitive). You **cannot parallelize wall-clock time.** So each identity
  must burn real, serial elapsed time on a real core; N present identities need N sequential lanes running
  in real time.
- **Permissionless + no-bother:** no sponsor, no KYC, no IP, no stake. For the honest user it is a few
  seconds of background computation to register (and a slow periodic re-proof to stay present) — one lane,
  effortless. It is *not* a race (fixed delay, no advantage to buying faster hardware), which is exactly
  why it fits NADO's anti-ASIC, "nothing to grind" ethos where hashcash PoW does not.
- **Why it's better than the old registration hashcash:** the previous 16-bit registration PoW was
  *parallelizable* — a GPU minted thousands of identities at once. Replacing it with the **sequential
  PoSW** (now shipped) removed that parallel advantage entirely: a GPU gives ~no edge, so registrations are
  throttled to real serial-time-per-core. Same one-time friction for the honest phone, a much steeper slope
  for a farm — and the *renewal* re-charges that cost every lease, so upkeep is priced too, not just entry.
- **How it makes distribution fairer:** it prices each free-lane mask in *real, proportional, ongoing
  sequential compute* rather than in near-free IPs. A farm that wants K× the shares must run K× the real
  time-lanes, continuously — so the open-lane distribution tracks real device-time, which is about as close
  to "one share per real participating device" as a permissionless, frictionless system can get.

**Honest ceiling (the real limitation cuts both ways):** a VDF ties Sybil to *sequential-compute lanes*,
and a datacenter can still buy cores — so this is a *cost floor that scales linearly*, not a hard cap.
And "continuous proof" is in tension with "no-bother" (a constant VDF drains a phone battery), so it must
be tuned to the cheap end: a short one-time VDF at registration plus a **slow, infrequent** re-proof to
maintain presence — enough to make a large farm pay real, visible, linear time-cost, not so much that a
phone notices. It does not make Sybil impossible; permissionlessly, *nothing* can. Combined with the 20%
structural cap and reward dilution, it turns "10 000 free masks" into "10 000 real time-lanes running
continuously for a slice of a fixed, diluted 20% pie" — rate-limited and unprofitable, with zero
permission and near-zero honest-user friction. **A memory-hard VDF** raises the floor further by also
pricing in RAM (a real device limit that is costlier to scale than cores).

## 6. What NADO actually does

**Do:** keep IP entirely out of consensus; keep the per-IP cap as opt-in, generous, best-effort relay
friction (progressive by subnet); rely on the **structural `OPEN_BPS` cap** for the hard bound and on
**reward dilution** for the economic bound.

**Shipped direction (permissionless, no-bother, invariant-preserving):** the *parallelizable* 16-bit
registration hashcash was **replaced with a sequential PoSW / proof-of-time** (§5b, Appendix A), and
presence is a **renewable recert lease** (`POSW_LEASE_EPOCHS`) rather than a heartbeat. It is the only lever
that is permissionless, needs no stake/identity/IP/sponsor, keeps NADO's "nothing to grind" anti-ASIC ethos
(a fixed delay, not a race), stays near-zero-bother for a real phone, and yet prices each extra free-lane
mask in a **real physical limit — serial wall-clock time that cannot be parallelized away.** It is tuned to
the cheap end (~1 s one-time reg proof + a ~daily presence re-proof). As a free, still-optional add-on, the
**relay-side behavioural heuristics** (#6) against the lazy botnet remain worthwhile — best-effort,
off-chain, changes no invariant.

**Rejected:** anything that adds *permission or bother* — bonded-node **sponsorship** (§5a, needs a
sponsor), personhood ceremonies (#1), bonds (#3), or device attestation (#5); and any **IP-, bond-, or
attestation-based rule inside consensus** (selection weight / validity / block production), which would
either fork the chain (IP) or destroy the zero-capital, one-tap, permissionless fair launch. The honest
framing stays: IP is friction, not a defense; the *distribution* is bounded by the 20% lane cap and priced
— permissionlessly — by real sequential time.

**Do not:** add any IP-, bond-, or attestation-based rule to *block production, selection weight, or
validity*. Those would either fork the chain (IP) or destroy the zero-capital, one-tap, permissionless
fair launch that is the entire point of the project. The honest framing to users and reviewers is: **IP
is friction, not a Sybil defense; the Sybil defense is the 20% lane cap, and it holds even if every IP
control is bypassed.**

See also: whitepaper §2.2 (structural Sybil bound), `doc/reward-capture-theorem.md` (the population-
independent 20% bound, proved), `doc/takeover-resistance.md` (farm-neutral anchors + the bonded producer
ramp), `doc/node-service-reward.md` (why the Sybil anchor must be farm-neutral), `doc/mining.md` (two-lane
selection + the PoSW recert lease), `ops/posw.py` (the sequential-work primitive), `ops/ratelimit.py` (the
defensive per-IP cap), `tests/test_open_cap_adversarial.py` (the 20% cap, machine-checked),
`doc/scaling-analysis.md`.

---

## Appendix A — VDFs vs elliptic-curve crypto, and why NADO uses a *hash-based* Proof of Sequential Work

A VDF *looks* like elliptic-curve crypto (both are "hard math in an algebraic group"), but the resemblance
is superficial and the differences are exactly the ones that decide this design.

| | Elliptic-curve crypto (ECDSA/ECDH) | Algebraic VDF (repeated squaring) |
|---|---|---|
| Group | curve points, **known prime order** | integers mod `N` / class group, **unknown order** (the trick) |
| Hard thing | discrete log — *infeasible, period* | `x^(2^T)` — feasible, but **only slowly, step by step** |
| Flavor | one-way ("you can't") | a **speed limit** ("you can't rush"); parallelism doesn't help |
| Secret ingredient | order is public | order must be secret from everyone (else a shortcut exists) |

They are near mirror-images on the property that defines each: ECC needs *known* order + *infeasibility*;
the VDF needs *unknown* order + *forced slowness*.

**The decision-maker is quantum.** NADO deliberately does not use elliptic curves for signatures — it uses
**ML-DSA (lattice, post-quantum)** — because **Shor's algorithm breaks ECC**. The catch: the classic
**algebraic VDF has the *same* quantum weakness** — Shor factors the RSA modulus (or a quantum algorithm
computes the class-group order), the attacker learns the group order, reduces `2^T mod order`, and the
"T sequential steps" collapse to instant. So an RSA/class-group VDF is **not post-quantum** and would
reintroduce exactly the kind of primitive NADO threw out. (It is lower-stakes than a signature — breaking
it only lets a quantum attacker mint free-lane masks faster, still bounded by the 20% cap — but it is
avoidable.)

**So NADO should not use an algebraic VDF. It should use a hash-based Proof of Sequential Work (PoSW):**

- **Post-quantum:** assumes only that a hash (blake2b) is decent — the *same* assumption the chain already
  makes everywhere. No unknown-order group, **no trusted setup**, no curve, no factoring.
- **Sequential:** a hash chain `h₀ → H(h₀) → H(H(h₀)) → …` is inherently serial — each step needs the
  previous, so GPUs/ASICs give only a bounded constant speedup, not the exponential edge of hashcash.
- **Cheap to verify (and to reject garbage):** the prover snapshots the chain at checkpoints
  `cₘ = h_{m·S}`, Merkle-commits them (root `R`), and opens **only** a few segments chosen by
  Fiat-Shamir from `H(R)`. The verifier recomputes just those `k·S` steps + Merkle openings — `O(k·S)`,
  not `O(T)` — and a bogus proof fails on the first opened segment. Skipping work leaves inconsistent
  segments that the random openings catch with overwhelming probability (with segment 0 always opened to
  bind `c₀ = H(challenge)`).

Binding the challenge to `H(address ‖ recent_block_hash)` makes proofs **un-precomputable** (you don't
know the future block hash) and **non-reusable** (a different address ⇒ a different required chain), so
each mask must pay its own fresh, un-fakeable slice of real sequential time.

**Status — the parallelizable registration hashcash has been replaced (SHIPPED):**
1. **`ops/posw.py`** — the sequential-work primitive + `tests/test_posw.py` *(done; now wired into
   consensus)*.
2. `POSW_T / POSW_S / POSW_K` (+ `POSW_ANCHOR_OFFSET`) are **`protocol.py` consensus constants**,
   calibrated so an honest phone spends ~1 s once at registration. `POSW_LEASE_EPOCHS` (≈ 1 day) sets the
   recert-lease length.
3. Browser prover in `static/` (byte-for-byte with Python; cross-checked by `tests/posw_xlang.mjs`) —
   *pending* as part of the S4b light-miner.
4. **Done:** the `register` branch of `ops/transaction_ops.py` verifies the PoSW
   (`posw.verify(posw.challenge_bytes(sender, anchor), …)`) where `anchor` is the finalized block
   `target_block − POSW_ANCHOR_OFFSET`. Presence is the **renewable recert lease**: a fresh recert keeps an
   identity in `account_ops.get_open_registry` for `POSW_LEASE_EPOCHS` — the "slow, infrequent presence
   re-proof" is live, and there is no separate heartbeat.
