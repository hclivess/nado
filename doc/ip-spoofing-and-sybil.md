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
2. **Register N identities.** Each `register` costs a small one-time proof-of-work (16-bit) instead of a
   fee, so N identities cost N small PoWs — cheap at scale on a GPU. Assume the attacker registers as many
   as they like.
3. **Heartbeat all N each epoch** to stay present.
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
3. **One-time registration PoW — a small per-identity cost.** Each identity pays a 16-bit PoW once. It is
   deliberately light (phones must afford it), so it is a speed bump, not a Sybil wall.
4. **Progressive per-IP crowding cap — best-effort friction.** `ratelimit.allow_registration` makes casual
   single-box scripting expensive and bounds a datacenter's whole subnet, not just one IP. Evadable, but
   it raises the floor for the low-effort attacker (the common case).

The fairness posture is therefore: **do not try to make Sybil impossible; make its payoff bounded (20%
lane) and unprofitable (reward dilution), and add cheap friction (PoW + IP cap) against the low-effort
masquerade.** IP is the outermost, weakest, most-evadable layer, and the design is deliberately built so
that its failure only skews *how the free lane is shared*, never anything about safety.

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
IP of the **node** a miner registers/heartbeats *through*, and make **every address mining via that node
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

## 6. What NADO actually does, and the recommendation

**Do:** keep IP entirely out of consensus; keep the per-IP cap as opt-in, generous, best-effort relay
friction (progressive by subnet); rely on the **structural `OPEN_BPS` cap** for the hard bound and on
**reward dilution** for the economic bound.

**Recommended next step (cheap, invariant-preserving):** add **relay-side behavioural heuristics** (#6)
as optional `ratelimit` policy — this is the highest-leverage improvement against the realistic
low-effort attacker without touching consensus or the fair launch. Prototype **population-scaled
registration PoW** (#2) as a second, self-contained edge cost if free-lane crowding is observed in the
wild. If a *consensus-enforceable, spoof-proof* Sybil cost is ever needed, the right direction is
**bonded-node sponsorship** (§5a) — move the scarce resource from IP to on-chain stake while keeping the
miner zero-capital — **not** any IP-based rule.

**Do not:** add any IP-, bond-, or attestation-based rule to *block production, selection weight, or
validity*. Those would either fork the chain (IP) or destroy the zero-capital, one-tap, permissionless
fair launch that is the entire point of the project. The honest framing to users and reviewers is: **IP
is friction, not a Sybil defense; the Sybil defense is the 20% lane cap, and it holds even if every IP
control is bypassed.**

See also: whitepaper §2.2 (structural Sybil bound), `doc/mining.md` (two-lane selection),
`ops/ratelimit.py` (the progressive per-IP cap), `doc/scaling-analysis.md`.
