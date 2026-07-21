# Runtime upgrades — decentralized, atomic, verifiable (mainnet design)

> **Status: DRAFT / design target for mature mainnet.** Not for alphanet, which keeps the simple
> fast-iterating model below. This note answers one question: on mainnet, how does the chain's own logic
> (balances, staking, issuance, consensus rules) change over time **without a central party deciding, without
> a coordinated-fork scramble, and without silent divergence** — and how that reconciles with NADO's
> no-admin, provable-execution thesis. It builds on the bonded-stake quorum already defined in
> [treasury.md](treasury.md) / [governance.md](governance.md), and on the exec-layer upgrade primitives in
> [assets.md](assets.md) / [zk-execution-proofs.md](zk-execution-proofs.md).

## 0. The problem, stated honestly

Today the runtime is native Python and upgrades happen through `ops/self_update.py`: each node fetches
`origin/main` of **one pinned repo (`github.com/hclivess/nado`)**, fast-forwards, and restarts. On alphanet,
consensus changes go live immediately with no activation ceremony. That is fine for a fast-moving alpha. It
is **not** acceptable for a mature mainnet, on two independent axes:

1. **It is centralized.** Whoever controls that repo controls what code every node runs. "Fast-forward only,
   pinned to the official remote" bounds *tampering in transit*, but the operator is still the sole author of
   what the fleet executes. On mainnet that is a single point of control over monetary policy, staking, and
   consensus. Unacceptable — this is the property this document exists to remove.
2. **It diverges silently.** Nodes update at different times (or not at all — some nodes cannot even update:
   they report `not a git checkout` and run stale consensus). A change that alters a committed root then
   fractures the network during the rollout window. Observed live: a fleet that fragmented into peers on
   distinct chains, and a node running code 34 minutes older than its own fix while reporting healthy.

Any mainnet upgrade path must fix **both**: no central author, and no silent partial rollout.

## 1. The reference model, and where it actually draws the line

Polkadot/Substrate is the canonical "forkless upgrade" design: the **runtime** — the state-transition
function (balances, staking, issuance, fees) — is a WASM blob in on-chain storage, replaced by a governance
vote, and every node executes the new blob from the enacting block. No node-software coordination.

Two precisions that matter for NADO:

- **Even there, consensus is NOT in the upgradeable blob.** Block production and finality (BABE/GRANDPA),
  networking, and the WASM executor live in the native **client** ("the shell"). You cannot forkless-upgrade
  the thing that decides which block is next — every node must already agree on it to process the upgrade at
  all. So the honest scope is "the STF is a governance-enacted blob," never "the entire runtime including
  consensus."
- **The runtime is RE-EXECUTED, not proven.** Substrate nodes run the WASM and trust their own execution.
  NADO's differentiator is the opposite: **proven** execution. Copying a re-executed blob would spend the
  hardest engineering NADO has and gain none of its edge.

## 2. Design goals for NADO mainnet

An upgrade mechanism is acceptable only if it is **all** of:

1. **Decentralized** — the *authority* is the bonded-stake quorum, not an operator key or a pinned repo. No
   one party can change what runs.
2. **Atomic** — a change enacts at a specific block height, identically on every node, with no staggered
   window.
3. **Fail-loud** — a node that does not have the enacted logic **halts** (refuses to produce/finalize) rather
   than silently producing a divergent chain. Loud beats forked.
4. **Verifiable** — anyone can confirm that what is running is exactly what governance enacted, by content
   hash, from source (reproducible builds). NADO's north star extends this to *proven* execution.
5. **Bounded** — governance can improve the runtime but must **not** be able to rug holders. Certain
   invariants (the supply schedule, the no-admin asset ledger, the finality floor) are either out of scope or
   gated behind a supermajority + long timelock, so "upgradeable" never degrades into "governance mints your
   coins by simple majority."

Goal 5 is the reconciliation with NADO's ethos. The asset layer's whole promise is *no privileged path*
(renounce is permanent, fixed supply is chain-enforced). A runtime that governance can rewrite wholesale is
the opposite of that. The resolution is **scoped** upgradeability: mutable where iteration is healthy,
immutable (or supermajority-timelocked) where trust must be absolute.

## 3. Options

### A. On-chain governance-enacted runtime blob (full Substrate model)
The STF becomes a blob (WASM, or NADO's own zkVM bytecode) in state; the quorum enacts a new blob at a
height. **Pros:** maximal forkless-ness, fully decentralized authority. **Cons:** a ground-up rewrite of the
core into a sandboxed VM; the widest governance-capture surface (all of balances/staking/issuance mutable);
and — if WASM — it buys re-execution, not proof. **Verdict: the end state, not the next step.** Right
direction, wrong first move.

### B. Activation-gated, governance-enacted native upgrades  *(recommended near-term)*
Keep the runtime as native code — **no rewrite** — but move the *authority over which version is canonical*
off the operator's git and onto the chain:

1. A release is built reproducibly and its **artifact is content-hashed**. The hash (not a git ref) is what
   gets proposed.
2. A **bonded-stake quorum** proposal — the same machinery as `treasury_execute` — enacts `runtime_hash H`
   at **activation height `A`** (with `A` far enough out to clear a mandatory **timelock**).
3. Every node, from block `A`, checks that the code it is running hashes to `H`. If not, it **halts
   production and finality** (fail-loud) instead of building a fork. It keeps *following* the chain read-only
   so it can be fixed, but it never *authors* divergence.
4. Distribution is unchanged in mechanism (nodes still fetch the artifact) but no longer *authoritative*: a
   node will only *activate* code whose hash the quorum enacted, from **any** source. The pinned repo becomes
   a convenience mirror, not the root of trust.

**This meets all five goals without a rewrite:** authority is the stake quorum (decentralized); activation
is height-gated (atomic); a stale node halts (fail-loud); the enacted hash is reproducible from source
(verifiable); and the scope rules of §4 bound it. It directly fixes both failures in §0 — the operator is no
longer the author, and there is no silent partial rollout because non-enacted code cannot produce.

### C. Provable runtime (the north star)
Move the STF into the **provable zkVM** so a light client verifies a *proof* of the state transition instead
of re-executing anything — the direction the frontier (SP1, RISC Zero, based/zk rollups) is heading, and
where NADO's existing proof investment compounds. NADO already proves *contract* execution; "prove the whole
runtime" is the hard, valuable generalization. Reachable incrementally on top of (B): as runtime modules are
expressed in the provable VM, their upgrades become both governance-enacted *and* proof-verified.

## 4. Scope — what may be upgraded, and what may not

| Class | Example | Upgrade rule |
|---|---|---|
| **App / exec layer** | games, Reserve vault, future AMM/launchpad | already forkless — deployer `upgrade`, or `lock` for immutability (assets.md). No core governance needed. |
| **Runtime modules** | fee schedule, staking params, non-monetary consensus tuning | bonded-stake quorum + timelock (§3B). |
| **Monetary & trust invariants** | total-supply schedule, the no-admin asset ledger, the finality floor, slashing bounds | **immutable**, OR a distinct **supermajority + long timelock** track — never a simple-majority runtime bump. This is what keeps "upgradeable" from meaning "rug-able." |

The split is the point: iterate freely where it is safe, and make the guarantees holders price in
**un-legislatable by ordinary governance**.

## 5. Anti-centralization safeguards (the load-bearing part)

- **No operator key, no repo-as-authority.** The bonded-stake quorum is the sole enactor. `self_update`'s
  pin to one GitHub remote is downgraded from *root of trust* to *one mirror among many*; nodes trust the
  enacted **hash**, not the source.
- **Reproducible builds.** The enacted artifact must be byte-reproducible from public source so anyone can
  independently confirm the running hash — the same "compute it yourself, don't trust an assertion" discipline
  the deterministic contract `cid`s already use. An upgrade nobody can reproduce is not verifiable and must
  not enact.
- **Timelock.** Mandatory delay between enactment and activation, so holders can exit and node operators can
  stage the artifact before it goes live. No same-block surprise upgrades.
- **Fail-loud, never fail-open.** A node without the enacted hash halts authoring. This is the inverse of
  today's silent divergence and is the single most important safety property.
- **Genesis-generation reroll stays the escape hatch** for anything the in-band path cannot express (a change
  to the enactment machinery itself), but as a rare, announced, last resort — not the normal channel.

## 6. Recommendation

Strive toward the **goal** — decentralized, atomic, verifiable, coordination-free upgrades — but reach it in
stages, not by importing a governance-mutable WASM runtime wholesale:

1. **Now (mainnet-blocking):** ship **(B)** — decouple "which runtime is canonical" from the operator's git
   by making a stake-quorum-enacted, timelocked, content-hashed activation gate the authority, with stale
   nodes failing loud. This removes the centralization in §0.1 and the silent divergence in §0.2 without a
   rewrite.
2. **Keep** forkless upgrades at the app/exec layer (already shipped) and the **scope split** of §4 so the
   trust invariants stay immutable.
3. **Aim** the long arc at **(C)**, the provable runtime — the version of "runtime on-chain" that is uniquely
   NADO's, because it is verified rather than merely re-executed.

The short answer to "should we strive for the Substrate model": strive for its *decentralization and atomic
enactment*, not its *re-executed mutable-everything blob*. Governance decides **which** verified runtime is
canonical; it does not get to quietly rewrite money.

## 7. Open decisions for the owner

- **Quorum + timelock parameters** for the runtime track vs. the invariant track (supermajority %, delay).
- **Which modules** are "runtime" (upgradeable) vs. "invariant" (immutable) — the §4 table is a starting cut.
- **Reproducible-build toolchain** — pinning the exact build so the enacted hash is independently reproducible.
- **Halt-vs-degrade** policy for a stale node: refuse to author only, or also stop serving reads? (Draft: author-halt, read-follow.)
- **Whether/when** to begin expressing runtime modules in the provable VM (path to §3C).
