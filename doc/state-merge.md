# State merging — sequential and parallel

How two state-transition proofs compose into one. This is the mechanism behind off-chain transaction bulking
with on-chain reuptake: prove work off-chain, merge it, settle once.

**Why it can work at all** — measured on `vm_circuit.prove_epoch_calls`:

| calls | T | W | prove | verify | proof |
|---|---|---|---|---|---|
| 1 | 512 | 167 | 36.0 s | **0.13 s** | 1263 KB |
| 2 | 512 | 167 | 38.6 s | **0.09 s** | 1263 KB |
| 4 | 512 | 167 | 39.6 s | **0.13 s** | 1263 KB |
| 8 | 512 | 167 | 40.2 s | **0.11 s** | 1263 KB |

Verify is **flat** and proof size **constant** while the work proven grows 8×. If verification does not grow
with the computation, arbitrarily much execution can move off-chain and settle through one proof. That is the
whole basis; everything below is about *composing* those proofs safely.

## The state model

State is a `storage_tree.SparseStore` — a sparse alghash2 Merkle tree at depth 256, keyed by
`slot_key(cid, slot)`. Missing keys read 0; writing 0 deletes.

`state_transition.prove_transition(pre_store, updates)` proves an ordered `[(key, new_value), …]` by emitting
**one `merkle_update` proof per key**, each proving `old→pre_root` and `new→post_root` over ONE shared
authentication path, and chaining them:

```
r₀ --update k₁--> r₁ --update k₂--> r₂ … --update kₙ--> rₙ
```

The bundle carries `{proofs, bnds, roots, updates, depth}`, where `roots[0]` is the pre-root, `roots[-1]` the
post-root, and `updates[i] = (key, old_value, new_value)`.

## Sequential merge — already works, by construction

Two transitions where the second starts where the first ended:

```
A: r₀ → rₐ   over keys K_A
B: rₐ → r_b  over keys K_B     (B was proven against rₐ)
```

Composition is concatenation. The chain condition `A.roots[-1] == B.roots[0]` is the entire check — no key
constraint is needed, and **K_A and K_B may overlap freely**: if both write key `k`, B simply observes A's
value as its `old`, because B was proven against A's post-root.

This is what the K→1 fold (`SETTLE_PROOF_RECURSIVE`, betanet-14) collapses: K chained segment proofs
re-verified inside ONE recursion bundle whose verification is O(1). Multi-epoch spans in
`prove_settlement_sparse` are exactly this shape.

**Limitation:** it is strictly serial. B cannot begin until A's post-root exists, so proving cannot be spread
across machines. That is what parallel merge is for.

## Parallel merge — the useful case, and why it is not free

Two provers start from the **same** pre-root and work different parts of the state:

```
A: r₀ → rₐ    over keys K_A
B: r₀ → r_b   over keys K_B
                              want:  r₀ → r_ab  applying both
```

**Naive concatenation is unsound.** Every `merkle_update` proof authenticates a path *at a specific root*.
B's proofs were produced against `r₀`. Updating any key in K_A changes every node on that key's root-path —
and all paths share the upper tree, always including the root itself. So B's authentication paths are stale at
`rₐ`, and splicing the two proof lists proves nothing about the combined state.

**Disjointness is necessary but not sufficient.** `K_A ∩ K_B = ∅` makes the *result* well defined — sparse-tree
updates to distinct keys commute, so `r_ab` is unambiguous regardless of application order — but it does not
repair B's stale paths. Disjointness gives you a target; it does not give you a proof.

### What is actually required

Three obligations, and a merge is sound only with all three:

1. **Disjointness.** `K_A ∩ K_B = ∅`, proven, not assumed. Cheapest sound form: require each update list to be
   **strictly increasing by key**, then a merge is valid iff the interleaved sequence is also strictly
   increasing. Strict inequality at every step is what rules out a shared key. Without it, two provers could
   both write `k` and the "merged" root would depend on order — i.e. it would not be a function of the inputs
   at all.
2. **Same pre-root.** `A.roots[0] == B.roots[0]`. Otherwise the two transitions describe different worlds.
3. **A re-derivation of the merged root** binding `(r₀, merged_updates, r_ab)`.

Obligation 3 is the real work, and it is what makes this a *merge circuit* rather than a bookkeeping trick.

### The shape being implemented

The expensive half — executing N calls and proving the exec AIR — parallelises cleanly, because that half
never touches the shared tree. Only the state-transition half needs care, and it operates on the update
**sets** (sorted keys and values), which are small next to an execution trace.

So: prove A and B independently on separate machines, then produce a small **merge proof** over
`(r₀, K_A ∪ K_B, r_ab)` that re-derives the combined root. Cost is proportional to `|K_A| + |K_B|`, not to
the number of calls, so it stays negligible against the execution proving it unlocks.

**Verification obligations for a merged bundle:**

- both sub-proofs verify
- `A.roots[0] == B.roots[0] == r₀`
- the merged update list is strictly increasing (⇒ disjoint)
- the merged update list is exactly the union of A's and B's, with no additions or drops
- the merge proof carries `r₀ → r_ab`

Miss any one and the merge is forgeable. The fourth in particular: a prover that may silently *drop* an update
can settle a state where someone else's write never happened.

## Status

| | status |
|---|---|
| sequential merge | **live** — `prove_settlement_sparse` multi-epoch spans, folded K→1 (`SETTLE_PROOF_RECURSIVE`) |
| parallel merge | **in progress** — `state_merge.py`, see below |
| full-state composition | **open** — settlement proves the zkVM projection only; bridge/dividend/shielded settle by their own paths |

That last row is the honest ceiling on all of this: until one proof covers the whole state transition, there
is no single object to merge. It is the same composition gap `settlement_proofs` names in its own docstring.

## Related

- `doc/zk-recursion.md` — the K→1 fold and O(1) verification
- `doc/zk-execution-proofs.md` — the epoch execution proof
- `execnode/stark/state_transition.py` — per-key update chaining
- `execnode/stark/storage_tree.py` — the sparse tree
