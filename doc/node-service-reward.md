# Node service reward — paying real infrastructure, without a farmable IP loop

> **Status: design proposal (not implemented).** Captures the "reward public-IP operators, consensus-routed
> and non-custodial" idea from the reward-redistribution discussion, with the Sybil anchor moved OFF IP
> uniqueness (farmable) and ONTO bonded stake + *provable* service. IP/ASN diversity survives only as a
> defensive *discount*, never as a way to mint more. Locks nothing until we agree the parameters.

## 1. The goal (and the trap)

We want to reward the operators who actually keep NADO usable: nodes on **public, reachable IPs** that
**serve data** (recent block bodies, DA blobs, snapshots) so phones can sync, mine, and transact. Ideally
the reward is **consensus-routed and non-custodial** — an operator receives what the rules assign, and
cannot skim or redirect it.

The trap is anchoring that reward to **IP uniqueness**, and the deepest reason is not that IPs are cheap
(they are — cloud spans hundreds of /16s, residential-proxy pools cover every prefix, a single IPv6 /32 holds
2⁹⁶ addresses across 2⁶⁴ /64s). The deepest reason is a **friction asymmetry**:

> **Concentrating N bots is always lower-friction than coordinating N real people.** One operator scripts a
> thousand nodes — spread across prefixes or packed behind one IP — in an afternoon; a thousand humans never
> assemble that cleanly. So *any* metric that a bot can satisfy as well as a person (an IP, a "unique" IP, a
> device, a heartbeat) structurally **favors the farmer and disadvantages real users** — the honest side
> always pays more friction to produce the same units. (CGNAT is just one symptom: many real phone users
> *share* one public IP, so they even look *smaller* than the farm. But the core problem is the asymmetry,
> not CGNAT.)

The only anchors that escape this are ones where **the attacker has no friction advantage over an honest
user** — where a unit costs the *same* to a bot and a human. **Bonded capital is exactly that**: a coin costs
one coin to lock whether you are a person or a script; you can't "run a bot" to make stake cheaper. That is
why NADO anchors Sybil resistance on stake, and why this design does too. See
[ip-spoofing-and-sybil.md](ip-spoofing-and-sybil.md).

So the invariant we must keep is NADO's founding one: **you cannot raise your reward share by acquiring more
of anything a bot can farm more cheaply than a person can.** Stake is farm-neutral; IPs are not.

## 2. Two hard walls

1. **Scarcity anchor = bonded stake, not IP.** The service pool is split only among **bonded** nodes,
   weighted by `min(bond, cap)`. More IPs without more bond earns nothing; the whale cap bounds the top.
   This is the *same* Sybil economics as the bonded mining lane.
2. **The service role is SEPARATE from phone mining.** Phones keep earning through the OPEN lane + the
   presence dividend ([presence-dividend.md](presence-dividend.md)) — none of that touches IPs. The service
   reward is an **opt-in role for infrastructure operators** (relays/archives), so rewarding public IPs here
   does not re-price phone fairness. A phone behind CGNAT is unaffected: it was never competing for the
   service pool.

## 3. What "provable service" means (the core mechanism)

We cannot put "this node is up and serving" directly into consensus — availability is a live, off-chain,
network property. So we do what NADO already does for finality and settlement: **let a beacon-selected,
bonded committee attest it, and settle by quorum.** The novelty is that each attestation is backed by a
*verifiable challenge-response*, and a *wrongful* failure is a publishable fraud proof.

### 3.1 Opt in
A bonded validator becomes a **service node** with a signed `service_register` tx declaring its public
endpoint `{ip, port, class}` (`class` = `rolling` | `archive` | `da`). Key-bound (the tx is signed), so the
endpoint is cryptographically tied to the node's address. Requires bond ≥ `SERVICE_MIN_BOND`.

### 3.2 Unpredictable challengers (you can't pick who tests you)
Each epoch `E`, for each service node `N`, the **beacon deterministically selects** a committee of
`K_CHAL` bonded validators to challenge `N` — the same grind-resistant machinery that selects block
producers (`epoch_beacon` + a keyed draw over the bonded set). Neither `N` nor an attacker can choose `N`'s
challengers, and the assignment is identical on every node.

### 3.3 The challenge (verifiable, not a vibe)
Each challenger `C`, off-chain:
1. Derives a **deterministic target** from `H(beacon_E ‖ N ‖ C)` — e.g. "block body at height
   `h = target mod retention_window`" for a `rolling` node, a specific DA blob for a `da` node, or a
   snapshot chunk for `archive`. Consensus already knows the correct **hash** of that object (block index /
   blob commitment / snapshot manifest), so the answer is checkable.
2. Connects to `N`'s declared endpoint, requests the object, and asks `N` to sign `nonce ‖ object_hash`.
3. **Verifies**: returned bytes hash to the consensus-known hash **and** `N`'s signature is valid **and** the
   response arrived within `SERVICE_LATENCY_MS`. Pass or fail.

Because the object's hash is fixed by consensus, `C` cannot be fooled by garbage, and `N` cannot pre-compute
without actually holding the data. The signature proves the *reachable* node controls `N`'s key (closes the
"claim someone else's IP" hole).

### 3.4 Attest + settle by quorum
`C` posts a fee-exempt `service_attest` tx `{epoch E, node N, verdict}` (mirrors the FFG `attest` duty; one
per `(C, N, E)`). At epoch close, consensus tallies: `N` is **in service for E** iff a **quorum**
(`SETTLE_NUM/SETTLE_DEN = 2/3`, reused) of its assigned committee attested PASS. Faking a PASS therefore
requires controlling ≥ a random ⅔ of a committee — i.e. a large fraction of *total bonded stake*, the same
honest-majority assumption that already secures finality/settlement.

### 3.5 Fraud proof for a wrongful FAIL (optimistic dispute)
A false PASS needs quorum collusion (expensive). A false **FAIL** is cheaper to attempt but **provable**:
`N` keeps `C`'s signed challenge and its own signed, correct response. If wrongly failed, `N` publishes the
pair as a `service_fraud` proof; consensus verifies (valid challenge → correct object+signature) and
**slashes** the lying challenger's bond (extends the equivocation-slash path). So a challenger that fails an
honest node loses stake — FAILs become truthful under rational play.

## 4. The payout (non-custodial, stake-gated, diversity-discounted)

Add a small **service cut** to the block reward split (alongside treasury / open-tip / dividend):

```
service = R · SERVICE_BPS / 10000            # a fixed slice of each block, accrued to a SERVICE_POOL
```

Each epoch the pool is divided among the **in-service** nodes, weight:

```
w_N = min(bond_N, SERVICE_BOND_CAP)  ×  diversity_factor(N)
```

- **`min(bond, cap)`** — the stake gate + whale cap. This is what makes IPs un-farmable: the pool is fixed
  and only bonded nodes share it, so spinning up more IPs *redistributes*, it never *mints*.
- **`diversity_factor(N) ∈ (0, 1]`** — computed deterministically from the declared IPs of the in-service
  set: discounted by how many other in-service nodes share `N`'s /24, /16, and ASN (ASN via a table pinned
  in consensus, or pure prefix bits to avoid an external dependency). A rack of 50 nodes in one /24 is
  diversity-crushed toward the weight of ~one; genuinely distributed operators keep full weight. Crucially
  this factor can only **lower** a share of the fixed pool — it can never increase total emission, so it is
  the *defensive* use of IP diversity (like Bitcoin addrman / Tor path selection), not a mint.

Credit is applied by the block-reward code directly to each node's address (like the treasury cut) —
**no operator ever routes anyone's coins**, so there is nothing to skim. That delivers the "consensus
assigns, node can't keep it" property you wanted, correctly.

## 5. Why each attack fails

| attack | why it fails |
|---|---|
| **Rent 10⁶ IPs / IPv6 /32** | Pool is gated by **bond**; extra IPs without extra bond earn 0. Diversity only redistributes a *fixed* pool among bonded nodes. |
| **CGNAT / phone under-count** | Phones don't run service nodes; they earn via the open lane + dividend, untouched. Service reward is a separate infra role. |
| **Fake "I served" (false PASS)** | Needs a random ⅔ of a beacon-chosen committee — i.e. ⅔ of total bonded stake. Same bound as finality. |
| **Grief an honest node (false FAIL)** | Node publishes the signed challenge+response fraud proof → lying challenger is **slashed**. |
| **Claim someone else's IP** | Challenge requires a signature from the node's key at that endpoint; you can't sign for a key you don't hold. |
| **Serve nothing, precompute answers** | Target is unpredictable (beacon-keyed) and its correct hash is fixed by consensus; you must actually hold the data. |

The whole thing inherits NADO's existing trust model (grind-resistant beacon + 2/3 bonded-honest) and its
existing primitives (attestations, quorum, slashing, reward split) — no new cryptographic assumption.

## 6. Parameters (draft — all tunable)

| constant | draft | meaning |
|---|---|---|
| `SERVICE_BPS` | `500` (5%) | block-reward slice to the service pool (comes out of producer share, not treasury/dividend) |
| `SERVICE_MIN_BOND` | `B_MIN × 100` | minimum bond to register as a service node (spam floor) |
| `SERVICE_BOND_CAP` | = mining bond cap | whale cap on service weight |
| `K_CHAL` | `16` | challengers assigned per node per epoch |
| service quorum | `2/3` (reuse `SETTLE_*`) | PASS fraction of the committee to be "in service" |
| `SERVICE_LATENCY_MS` | `3000` | max challenge round-trip to count as served |
| diversity buckets | `/24, /16, ASN` | prefixes the diversity discount is computed over |

## 7. Open questions

- **Challenge bandwidth.** `K_CHAL` challengers × all service nodes × each epoch is real traffic. Sample a
  *subset* of nodes per epoch (rotating) rather than all, if it's too heavy — the reward just averages over
  epochs.
- **ASN table in consensus.** An IP→ASN map is external data that drifts. Options: (a) pin a versioned table
  by hash and update via governance; (b) skip ASN, use pure prefix bits only (weaker but dependency-free).
  Prefer (b) for launch.
- **Latency is subjective across the globe.** A single `SERVICE_LATENCY_MS` disadvantages far peers. Could
  make the bound relative to the challenger↔node RTT baseline, or just keep it generous.
- **Interaction with rolling mode.** A `rolling` node can only be challenged on data inside its retention
  window; the target derivation must respect each class's actual served range.
- **Does this over-reward capital?** It is stake-gated by design, so yes it favors the already-bonded. Keep
  `SERVICE_BPS` modest so the open lane + dividend (the capital-free paths) stay the headline for phones.

## 8. What this is NOT

It is **not** "proof of IP," "proof of bandwidth as consensus weight," or anything where IP count drives
emission. It is a **stake-gated, quorum-attested, fraud-proof service bounty**, with IP/ASN diversity used
only to *discount* concentrated operators inside the already-capped pool. That keeps NADO's founding
invariant intact while still paying the people who run the network's real infrastructure.
