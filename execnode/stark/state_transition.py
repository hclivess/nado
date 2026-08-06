"""
State TRANSITION proof (state-root binding, doc/zk-recursion.md §5b piece (a)) — the batch layer.

A whole epoch touches K storage slots. This chains K in-circuit merkle-update proofs (merkle_update.py) into
one state-transition proof of pre_root → post_root: update i pins pre_root_i → post_root_i, and the roots CHAIN
(post_root_i = pre_root_{i+1}), so pre_root_0 → post_root_K is the net effect of rewriting exactly those slots.

The K proofs all share the merkle-update AIR, so they fold K→1 with recursive_verify (exactly the segment path),
and that bundle collapses to a constant-size root with recursion_authdepth — O(1) verify. `prove_transition`
returns the chained proofs (+ optionally the K→1 bundle); `verify_transition` checks the roots chain to the
public (pre_root, post_root) AND re-verifies every update — either per-proof (native, O(K)) or via the K→1
bundle. Binding the updates to the epoch's actual SSTOREs is `exec_state_bind` (piece (b)); swapping this in as
the settled root is the settlement integration (piece (c)).
"""
import os

from execnode.stark import (merkle_update as MU, field as F, backend as B, recursive_verify as RV,
                            storage_tree as ST)

# HOW MANY UPDATES SHARE ONE STARK — and why this is NOT MU.max_batch(depth).
#
# max_batch answers "what fits MAX_TRACE_ROWS", which at EXEC_TREE_DEPTH=256 is 9. MEMORY says otherwise:
# proving 9 in one trace was OOM-killed at 35.7 GB resident, and it took two of the box's other processes
# down with it. Trace length is not the binding resource.
#
# The composition allocates a size-N inverse-denominator vector PER BOUNDARY, and batching multiplies BOTH
# — boundaries grow ~K x 288 (256 of those 288 are the per-level position pins) and N grows ~K x 131072 — so
# memory is QUADRATIC in K while the size win is only logarithmic. That is the trade this constant sits on.
#
# So it is set from a MEASURED safe value, not from what the trace can hold. 1 = the pre-batching behaviour
# exactly (one proof per update), which is the only value verified at live geometry so far. Raise it only
# against a measured peak RSS on this box, with the exec node's own footprint and the owner's jobs left room.
DEFAULT_BATCH = int(os.environ.get("NADO_SETTLE_BATCH", "1"))


def _dirs(key, depth):
    return [(int(key) >> i) & 1 for i in range(depth)]


def prove_transition(pre_store, updates, num_queries=MU.stark.NUM_QUERIES, outer_queries=MU.stark.NUM_QUERIES,
                     fold=False, batch=None):
    """Prove a batch state transition. `pre_store` is a storage_tree.SparseStore at pre-state; `updates` an
    ordered [(key, new_value), ...]. Chains the roots across all of them. Returns a transition dict. Mutates
    `pre_store` to the post-state.

    SEVERAL UPDATES SHARE ONE STARK. This emitted one proof PER UPDATE, and that made the records half
    unshippable: proof size is ~10.82 MiB at EXEC_TREE_DEPTH=256 and the records half needs one update PER
    PRESENT MINER (20 and rising, because it tracks fleet size), so K x 10.82 MiB ran past the 191.94 MiB tx
    budget and kept rising on its own.

    Proof size is LOGARITHMIC in trace length — measured ~1 MiB per doubling of T, because 88% of a proof is
    FRI queries and a query costs one Merkle path. So `batch` updates in ONE trace cost ~(10.82 + log2 batch)
    MiB instead of batch x 10.82. Default is MU.max_batch(depth), the largest that fits MAX_TRACE_ROWS.

    The two alternatives were measured and rejected: the K->1 recursion bundle OOM-killed at 27.5 GB resident
    for K=2, and dropping NUM_QUERIES buys size with security bits (fri.py sizes 320 to clear 128 bits on the
    PROVABLE branch), which is not a prover-side decision.

    With `fold=True` also produces the recursive_verify K→1 bundle over the batch proofs."""
    depth = pre_store.depth
    if batch is None:
        batch = DEFAULT_BATCH
    batch = max(1, min(int(batch), MU.max_batch(depth)))
    proofs, bnds, roots, upd = [], [], [pre_store.root()], []
    for lo in range(0, len(updates), batch):
        items = []
        for key, new_value in updates[lo:lo + batch]:
            old = pre_store.get(key)
            items.append((old, new_value, pre_store.path(key), _dirs(key, depth)))
            upd.append((int(key), old % F.P, new_value % F.P))
            # APPLY AS WE GO, INSIDE the chunk: segment s+1's siblings must be the ones AFTER segment s
            # landed, exactly as K separate proofs saw them. Collecting all the paths first and then
            # applying would prove a batch against a pre-state that never existed.
            pre_store.set(key, new_value)
        proof, rts = MU.prove_updates(items, num_queries=num_queries, backend=B.RECURSION)
        if rts[0] != roots[-1]:
            raise ValueError("internal: batch pre_root breaks the chain")
        proofs.append(proof)
        bnds.append(MU._boundaries_batch(items, rts, depth))
        roots.extend(rts[1:])
    out = {"proofs": proofs, "bnds": bnds, "roots": roots, "updates": upd, "depth": depth,
           "num_queries": num_queries, "outer_queries": outer_queries, "batch": batch,
           "periodic": MU._periodic_batch(proofs[0]["T"], depth, proofs[0]["K"]) if proofs else None}
    if fold and proofs:
        out["bundle"] = RV.prove(proofs, MU._transitions(), bnds, num_queries_outer=outer_queries,
                                 periodic=out["periodic"])
    return out


def verify_transition(tr, pre_root, post_root, num_queries=None, outer_queries=None):
    """Verify a state-transition proof against the PUBLIC (pre_root, post_root). Checks: (1) the per-update
    roots chain pre_root → post_root; (2) every merkle-update proof re-verifies against its boundaries (which
    pin roots[i] → roots[i+1]) — via the K→1 recursion bundle if present (O(1)-class), else per proof (O(K)).
    `num_queries`/`outer_queries` are the verifier's policy (None ⇒ the counts the proof was built at, pinned).
    Returns (ok, reason)."""
    try:
        roots = tr["roots"]
        proofs = tr["proofs"]
        if not proofs:
            return (len(roots) == 1 and ST._eq(roots[0], pre_root) and ST._eq(pre_root, post_root)), "empty transition"
        if not ST._eq(roots[0], pre_root):                       # roots are alghash2 CAPACITY-tuples
            return False, "transition pre_root != public pre_root"
        if not ST._eq(roots[-1], post_root):
            return False, "transition post_root != public post_root"
        # A BATCHED proof covers proof["K"] updates, so the old "one root per proof" arithmetic no longer
        # holds. Derive the per-proof span from the PROOF'S OWN declared K and require it to account for
        # every update exactly once — a proof whose K is short would otherwise leave later updates
        # unverified while the roots chain still lined up.
        batched = "K" in (proofs[0] or {})
        spans = [int(p.get("K", 1)) for p in proofs] if batched else [1] * len(proofs)
        if any(s < 1 for s in spans):
            return False, "a proof declares a non-positive update count"
        if sum(spans) != len(tr["updates"]):
            return False, (f"proofs cover {sum(spans)} updates but the transition lists "
                           f"{len(tr['updates'])}")
        if len(roots) != sum(spans) + 1:
            return False, "root/proof count mismatch"
        nqi = num_queries if num_queries is not None else tr["num_queries"]
        nqo = outer_queries if outer_queries is not None else tr["outer_queries"]
        if "bundle" in tr:                                   # O(1)-class: ONE recursion bundle re-verifies all K
            pubs = [RV.public_part(p) for p in proofs]
            okr, whyr = RV.verify(pubs, MU._transitions(), tr["bnds"], tr["bundle"], num_queries_outer=nqo,
                                  periodic=tr["periodic"], num_queries_inner=nqi)
            if not okr:
                return False, f"K->1 bundle failed: {whyr}"
        else:                                                # native: re-verify each proof + its roots
            depth = tr["depth"]
            at = 0
            for pi, (proof, span) in enumerate(zip(proofs, spans)):
                chunk = tr["updates"][at:at + span]
                if batched:
                    pub = [(old_v, new_v, _dirs(key, depth)) for (key, old_v, new_v) in chunk]
                    ok, why = MU.verify_updates(proof, pub, roots[at:at + span + 1],
                                                num_queries=nqi, backend=B.RECURSION)
                else:
                    (key, old_v, new_v) = chunk[0]
                    ok, why = MU.verify_update(proof, old_v, new_v, roots[at], roots[at + 1],
                                               _dirs(key, depth), num_queries=nqi, backend=B.RECURSION)
                if not ok:
                    return False, f"proof {pi} (updates {at}..{at + span - 1}) failed: {why}"
                at += span
        return True, "state transition verified (roots chain + every update re-verified)"
    except Exception as e:
        return False, f"malformed transition: {e}"
