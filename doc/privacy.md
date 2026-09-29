# Privacy — a post-quantum zk-STARK shielded pool

> **Status: BUILT.** The shielded-pool state machine (`execnode/shielded.py`) AND the FRI/STARK join-split
> proof are implemented and wired into `verify_transfer` — a shielded transfer verifies its **full** ZK
> proof on-chain (see the §6 build table). What remains is **rollout**, not design: the pool-tree /
> browser hash migration (BLAKE2b → alghash) and the client-side / delegated prover so a phone can produce
> proofs itself. Until then proving is done by a helper; the pool is private and sound, not transparent.

## 1. Why this design (and not Monero/Zcash-as-is)

We want the most complete privacy — hide **sender, recipient, and amount**, with a **pool-wide anonymity
set** — that is also **post-quantum**. Every elliptic-curve privacy stack fails the PQ bar:

- Monero RingCT (ring sigs + Pedersen commitments + **bulletproofs**) is all EC discrete-log. A quantum
  computer breaks it, and for confidential amounts it breaks the *binding* of the commitments **and** the
  *soundness* of bulletproofs at once → **undetectable supply inflation**. (See the ANN/discussion.)
- Zcash-Sapling's zk-SNARK (Groth16) is pairing-based → also not PQ, and needs a trusted setup.

The post-quantum, trustless answer is a **zk-STARK shielded pool** (a Zerocash-model shielded pool proven
with **FRI-based STARKs**): hash-based, so the only assumption is a collision-resistant hash — the same trust
NADO already places in BLAKE2b and its PoSW — with **no trusted setup**. Runner-up considered: MatRiCT+
(lattice RingCT), lighter to prove but a smaller (ring, not pool-wide) anonymity set; kept as a fallback if
client-side STARK proving proves too heavy for phones.

## 2. Where it lives — the execution layer, not L1

L1 stays the minimal, transparent ledger. Privacy is an **opt-in execution-layer feature**, exactly like
contracts and the bridge (doc/execution-layer.md):

- **L1** carries each shielded transaction as an ordered, opaque **`blob`** (data availability + ordering)
  and escrows/releases the *transparent* coins that enter/leave the pool (`public_value`). It never sees a
  note.
- The **execution node** replays shielded blobs from **finalized** blocks in order and maintains the pool
  (commitment tree + nullifier set). Because it tails *finalized* blocks, there are no reorgs at the exec
  cursor, so the pool needs no rollback bookkeeping.
- The **STARK verifier** for the pool is the same class of verifier planned for Phase-2b settlement — one
  verifier, two uses.

## 3. The scheme (Phase 1 — implemented)

**Notes.** A note is `(value, owner, rho)`. `owner = H(spend_secret)` identifies the recipient; `rho` is
fresh randomness. You send a shielded note to someone by committing to *their* `owner`.

- **Commitment** `cm = H("cm", value, owner, rho)` — *hiding* (fresh `rho`) and *binding* (collision-resistant
  hash). Appended to the pool's Merkle set.
- **Nullifier** `nf = H("nf", spend_secret, rho)` — deterministic, revealed once on spend to prevent
  double-spends, and in a **different hash domain** than `cm` so a revealed nullifier can't be linked to its
  commitment. Only the holder of `spend_secret` can compute it.

**Commitment tree.** An append-only fixed-depth (`SHIELD_DEPTH = 32`) Merkle tree of commitments; the root is
an **anchor**. The pool keeps the **set of all past anchors**, so a proof built against a slightly stale root
(the tree grows between proof-build and landing) is still accepted — standard Zcash anchor handling.

**Transfer = join-split.** Spend `inputs` notes, create `outputs` notes, with a signed `public_value`
(`>0` = coins **enter** the pool / shield; `<0` = **leave** / unshield; `0` = fully-private transfer) and a
`fee`. The statement proven is:

> For each input: its `cm` is in the tree at anchor `root` (Merkle membership) and its `nf` is correctly
> derived from the note; each output `cm` is correctly derived; and **value is conserved**:
> `Σ inputs + public_value = Σ outputs + fee`.

**The verifier seam.** `verify_transfer(public, proof, root_is_known)` takes only the **public inputs**
(`root`, `nullifiers`, `out_commitments`, `public_value`, `fee`) plus a `proof`:

- **Phase 1 (now):** `proof` is the **transparent witness** (note openings + Merkle paths); the verifier
  re-checks membership + nullifier derivation + value conservation *in the clear*. → **Sound** (no
  double-spend, no forged value, no forged membership) but **not private** (witness visible).
- **Phase 2 (next):** `proof` is a **zk-STARK** of the exact same statement; the verifier checks it against
  `public` alone, hiding the witness. → **Sound and private.** `apply_transfer` and the whole state machine
  are unchanged.

The Phase-1 tests (`tests/test_shielded.py`) assert the *soundness* properties, which remain the acceptance
criteria for the Phase-2 STARK: hiding/binding commitments, unlinkable nullifiers, membership, value
conservation, double-spend rejection, forged-membership/mismatched-nullifier rejection, unshield-with-change,
unknown-anchor rejection, and fee conservation.

## 4. Phase 2 — the STARK (the remaining work)

The heart of the project. Turning the transparent re-check into a zero-knowledge proof of the same statement:

1. **Arithmetization.** Express the join-split statement as an AIR (algebraic intermediate representation)
   over a prime field: `SHIELD_DEPTH` hash-compression steps for the Merkle path, the commitment and
   nullifier hash evaluations, and the value-conservation constraint.
2. **Hash choice (a real decision).** Phase 1 uses BLAKE2b at the pool level. BLAKE2b is *expensive to
   arithmetize*, so the Phase-2 **circuit** will use a STARK-friendly hash (Poseidon/Rescue-Prime over the
   chosen field) for the in-circuit commitment/nullifier/tree. This means the pool's hash is a Phase-2
   parameter: either (a) switch the pool to the STARK-friendly hash up front, or (b) prove a BLAKE2b circuit
   (much heavier). Decision pending a proving benchmark — leaning (a).
3. **Proving system.** A FRI-based STARK (transparent, PQ). Options: port/wrap an audited prover (Winterfell,
   Plonky3, Stwo) or a minimal in-house FRI. Verifier must be deterministic and cheap enough for a commodity
   exec node.
4. **Field.** A STARK-friendly field with good 2-adicity (e.g. Mersenne-31 / BabyBear / Goldilocks), matched
   to the chosen hash.
5. **Client proving on phones — the real hurdle.** STARK proof generation is seconds-to-minutes and heavy for
   a phone. Strategy: (a) a WASM prover for occasional shielded sends; (b) a **blind/delegated prover** service
   for weak devices; (c) transparent shield/unshield stays cheap — only fully-private *transfers* need the
   heavy proof. If this stays impractical, fall back to MatRiCT+ (lattice, lighter proving).
6. **Authorisation (DONE).** Each input's owner is an ML-DSA-44 (PQ) key; a spend carries an ML-DSA
   signature over `transfer_sighash` (binds all public parts of the transfer). Knowing a note's opening
   (value, pubkey, rho) is NOT enough to spend — only the private key can sign. Verified in verify_transfer,
   so it holds in the transparent phase AND becomes an in-circuit constraint in the STARK phase.

## 5. L1 integration (to wire once Phase 1 is frozen)

- Reserved tx types (blobs, decoded only by the exec node): `shield` (escrow `public_value` on L1, add the
  note), `shielded_transfer` (private, `public_value = 0`), `unshield` (release `public_value` from escrow via
  a proof against the settled pool root — mirrors the bridge/dividend withdrawal path).
- A `SHIELD_ESCROW` keyless account holds all shielded coins on L1 (supply stays accounted).
- Unshield settles against the bonded-quorum-settled exec state root, like the bridge and the dividend.

## 7. Scaling (design notes, referenced from the code)

The Phase-1 machinery is correctness-first; these are the documented upgrades for populace scale:
- **Incremental Merkle tree.** The pool root is cached and recomputed O(n) only on append; replace with a
  frontier/incremental tree for O(depth)-per-append root + path (the module flags the seam).
- **Bounded anchors.** The anchor set is capped to `ANCHOR_WINDOW = 128` recent roots (not every historical
  root), so it never grows without limit — clients prove against a fresh root.
- **Compact state-root binding.** The exec `state_root` commits each pool (transparent AND
  field-native) with just TWO leaves (root + nullifier digest), so it is O(1) in pool size; pending
  *unshield* exits add a leaf each and are **GC'd automatically** once their finalized L1 claim
  burns the nullifier (`ExecState.drop_claimed`).
- **Nullifier accumulator.** The nullifier digest is an O(n) hash today; swap in an incremental accumulator
  (or a sparse-Merkle nullifier tree) at large scale.
- **STARK verification is off the phone** — on the execution node — so proof *verification* cost never
  touches L1 or a mining phone.

## 6. What's built vs pending

| piece | status |
|---|---|
| note commitment / nullifier / owner scheme | ✅ implemented + tested |
| fixed-depth Merkle commitment tree + anchors | ✅ |
| pool state machine (shield / transfer / unshield), double-spend + value conservation | ✅ |
| verifier seam (`verify_transfer`), transparent Phase-1 verifier | ✅ |
| soundness test suite (10 cases) | ✅ |
| STARK engine — Goldilocks field + Merkle + FRI + AIR/STARK | ✅ (tests/test_stark_fri.py, test_stark.py) |
| STARK-friendly hash (Poseidon-lite sponge) | ✅ (execnode/stark/alghash.py) |
| join-split hash gadget arithmetised + proven in ZK (commitment/nullifier/tree-node) | ✅ (tests/test_stark_joinsplit.py) |
| Phase-2 seam wired into verify_transfer | ✅ (verifies the FULL join-split proof) |
| FULL join-split circuit (owner+commit+membership+nullifier+output+conservation) in one ZK proof | ✅ (tests/test_stark_joinsplit_circuit.py) |
| migrate the POOL TREE + browser client from BLAKE2b to the field hash (alghash) | ⏳ rollout |
| **Zero-knowledge join-split (Z1, inside SHIELD_WIDE_HEIGHT): randomizer columns + random rows + salted leaves; the old proof showed nsk in every opening** | ✅ coded, live at the reroll (`stark.prove(zk=)`, joinsplit3) |
| **WIDE pool (SHIELD_WIDE_HEIGHT, next generation): commitments / owner ids / nullifiers / tree nodes are alghash2 digests (256-bit, ~128-bit collision) and the proof is joinsplit3** — the 64-bit alghash pool's ~2^32 collision let ~2^33 sponge evaluations open one leaf two ways (review 2026-09-23, Z3) | ✅ coded, live at the reroll (execnode/shielded_wide.py, execnode/stark/{znote,joinsplit3}.py, static/alghash2.js, static/stark/joinsplit3.js; tests/test_shielded_wide.py, tests/joinsplit3_js_crosscheck.sh) |
| **The wide spend key is FOUR lanes (256 bits) and comes from its own domain (`shield-nsk-v2`)** — one lane made every public owner id a 2^64 (less, multi-target) key search, and reusing the v1 key meant every legacy proof had published the wide key (review 2026-09-24) | ✅ coded, live at the reroll (znote.nsk_lanes, joinsplit3 NSK..NSK+3, alghash2.js nskLanes, interface.js shieldNskWide) |
| **A wide unshield binds its exit address, public value AND fee into the transcript** — the circuit binds only fee − value, so a published unshield could be rewritten into a burned fee and front-run (review 2026-09-24, reproduced on the legacy circuit) | ✅ coded, live at the reroll (joinsplit3.bind_aux / joinsplit3.js bindAux) |
| **The wide pool is depth 48 (2^48 notes) from block 1** (ZK_HARDEN_HEIGHT, inlined at gen 28) — depth 12 held 4,096 notes, fillable for ~0.0004 NADO; a spend always appends two leaves, so a full tree locked every note in it while deposits kept landing and were lost (zk audit 2026-09-26, reproduced). joinsplit3's trace is T = 4096 for every depth 20..48, so 48 costs what 20 does. The depth is the POOL's: the exec state deepens it at the first block ≥ the gate (same leaves, the depth-48 root, the anchor window rebuilt at 48 so no depth-12 root survives), the snapshot carries it and `_restore` refuses one that disagrees with its cursor, the verifier pins D to the depth in force (never the proof's), and `/exec/field_leaves` reports the depth the wallet builds at (no depth = an old exec node = 12). The tree is an incremental frontier (O(depth) per append) whose depth-12 roots, paths and anchor windows are byte-identical to the old code; the exec root needs no depth record because the depth-48 root over the same leaves is a different digest | ✅ coded, dormant (ZK_HARDEN_HEIGHT = 2^62 until the fleet runs it) (execnode/shielded_wide.py, state.wide_enter, stark/joinsplit_transfer.py, static/alghash2.js treeDepth; tests/test_wide_pool_depth.py, tests/joinsplit3_js_crosscheck.sh at 12 and 48) |
| **Privacy pause (PRIVACY_PAUSE_HEIGHT = 226400): private_call, legacy field-pool transfers and stark bundles on shielded_transfer are refused; legacy field deposits closed at L1** — value-creating flaws on those paths; none carried value | ✅ LIVE on gen 25; block 1 at the reroll (the wide pool replaces the legacy one) |
| **Receiving a banknote no longer tells the relay which note** — the wallet fetches every leaf and searches locally instead of `/exec/field_shielded?cm=` | ✅ live (wallet) |
| Note randomness `rho` stays ONE field element (64 bits): a guessed (value, owner) is confirmed by a 2^64 search per note. Widening it costs a second permutation per commitment | accepted, documented |
| Notes (value, rho, cm) sit in the browser's localStorage in plaintext; the spend key does not (it is re-derived) | accepted, documented |
| client-side / delegated STARK prover (the phone-proving hurdle) | ⏳ rollout |

| client (WASM) / delegated proving | ⏳ Phase 2 |
| L1 shield-escrow + unshield settled-root exit | ✅ (tests/test_shield_l1.py) |
| exec-node pool: shield/transfer/unshield + compact state_root + unshield proof | ✅ (tests/test_shielded_exec.py) |
| **DA-backed transfers — proof rides the DA layer, the L1 blob carries only its commitment** | ✅ (tests/test_da_shielded_transfer.py) |

### Multi-validator settlement of the pool (the DA-backed transfer path)

A shielded-transfer STARK proof is ~1-4 MB — far past the 64 KiB per-tx blob cap — so it can't ride L1
directly. Previously a field transfer reached the exec node only via `POST /exec/apply_field_transfer`, so
different exec nodes held divergent pool state and the bonded quorum could never settle a root covering the
pool (a **single-operator** shielded pool: a *provable* operator that can't steal/forge but can censor/stall).

It's now **L1-ordered + DA-available**, so the whole quorum can reconstruct + settle the pool:

- The prover publishes the proof to the **DA layer** (`ops/da_store.py`: Reed-Solomon k-of-n + an index-bound
  PQ Merkle commitment; every `(shard, proof)` self-verifies, so shards spread across DA nodes and any k
  reconstruct trustlessly). Served over `/da/publish · /da/meta · /da/shard · /da/get · /da/accept`.
- The wallet submits an L1 **`blob`** carrying only `{op: field_transfer, proof_da: <commitment>}` (a few
  hundred bytes). This fixes the transfer's **ORDER** and (via the commitment) its exact content.
- Each exec node **pre-resolves** every field-transfer proof from DA *before* mutating state
  (`da_fetch`), all-or-nothing per block: an unavailable proof **stalls the block in L1 order** rather than
  half-applying it. Every honest node fetches the identical bundle by commitment → applies the identical
  transfer → identical committed root. Phones never touch any of this — it is a full/exec/DA-node concern.
- DA is a **rolling window**: once a transfer is settled + snapshotted, its proof is `prune()`-able.

**Known limitation (exec-layer liveness, not a safety break) — availability-halt griefing.** Because L1
treats a blob as opaque, it can't check that the proof behind a `field_transfer` blob's `proof_da` commitment
was ever published to DA. If an attacker submits such a blob and never publishes the proof, every exec node's
pre-resolve `stall`s at that height (the cursor can't advance past an unresolved proof, all-or-nothing per
block), halting the execution layer for the cost of one blob fee. This is **safe** — no fork, no state
divergence, L1 itself is unaffected, and it **recovers** the instant the proof becomes available — but it is a
real griefing DoS on the exec layer. A local "skip after N blocks" rule is NOT a fix: availability isn't a
deterministic predicate (it depends on what each node can fetch), so skipping would diverge state. The sound
mainnet fixes make availability an **on-chain deterministic fact** before a blob is consumable: (a) a
**proof-of-publication** the blob must carry (threshold receipts from a bonded DA set attesting they hold ≥k
shards), rejected at L1 inclusion if missing; or (b) a **deterministic expiry** keyed to an on-chain
availability attestation quorum (the skip decision reads the same settled record on every node). Tracked as
the DA layer's blocking item for a non-alpha launch.

**The bounded wait (audit 2026-09-25, `EXEC_DA_DEADLINE_HEIGHT`, live from block 29000 on gen 27 and from block 1 since gen 28, where the gate was deleted — the operator chose the bounded wait over the free freeze).**
The freeze was reproduced (`tests/test_exec_never_stalls_on_unheld_proof.py`): one blob, 1,000 retries, cursor
frozen, the honest deposit in the same block never credited — and the rolling DA window (`DA_RETAIN`, a count over
an open `/da/publish`) could evict an honest proof into the same state for any node that had not fetched it yet.
From the gate, a DA-carried op whose proof is still unavailable once L1 finality reaches its block +
`EXEC_DA_WAIT_BLOCKS` (90) is **refused** (never dispatched; nothing moves, nothing is credited) and the rest of the
block applies; before that the block stalls exactly as above. The paragraph above still holds, and this is not the
sound fix it describes: the *moment* the node stops waiting is agreed (heights only), but the verdict at that moment
is "held or not", which is not. What it buys: the free attack (a proof nobody holds) is refused identically on every
node, every honest proof — published before its blob is submitted and pulled by every live exec node's provisional
tail seconds after inclusion — applies identically, and the exec layer lags at most ~90 blocks under attack instead of
stopping. What it costs: a proof first released to *some* exec nodes inside the last poll before the deadline can split
the exec roots (the root pool logs `EXEC ROOT OUT OF MAJORITY`), and a node replaying a block after its proof has left
every store refuses what the fleet applied. Two local guards narrow that: a proof resolved for an on-chain op is
**pinned** in the DA store for ~7 days of blocks (a flood of publishes can no longer evict it), and a node retries a
missing proof for a local grace before it refuses. Turning the gate on is an operator decision on that trade.
| ML-DSA spend authorisation (a leaked note opening can't move funds) | ✅ (tests/test_shielded.py t7) |

The honest summary: the **pool is real, sound, and frozen behind a verifier seam**; the **zero-knowledge**
comes online when the STARK verifier replaces the transparent one — that is the next phase, and it is a large
one, but nothing above it has to change when it lands.
