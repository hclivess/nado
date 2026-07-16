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
from execnode.stark import merkle_update as MU, alghash as A, field as F, backend as B, recursive_verify as RV


def _boundaries(D, old_val, new_val, pre_root, post_root):
    """The exact boundary list merkle_update.prove_update pins for a depth-D update (shape identical across all
    updates — only the values differ — so recursive_verify can fold them as one shared AIR)."""
    RPL = MU.RPL
    return [(0, MU.OS1, A.IV), (0, MU.OS0, A.DOM_NODE), (0, MU.OAB, A.DOM_NODE), (0, MU.OCARRY, old_val % F.P),
            (0, MU.NS1, A.IV), (0, MU.NS0, A.DOM_NODE), (0, MU.NAB, A.DOM_NODE), (0, MU.NCARRY, new_val % F.P),
            (D * RPL, MU.OS0, pre_root % F.P), (D * RPL, MU.NS0, post_root % F.P)]


def prove_transition(pre_store, updates, num_queries=MU.stark.NUM_QUERIES, outer_queries=MU.stark.NUM_QUERIES,
                     fold=False):
    """Prove a batch state transition. `pre_store` is a storage_tree.SparseStore at pre-state; `updates` an
    ordered [(key, new_value), ...]. Produces one RECURSION-committed merkle-update proof per update, chaining
    the roots. With `fold=True` also produces the recursive_verify K→1 bundle over them (the O(1) enabler; slow
    to prove — the recursion throughput wall). Returns a transition dict. Mutates `pre_store` to the post-state."""
    depth = pre_store.depth
    proofs, bnds, roots, upd = [], [], [pre_store.root()], []
    for key, new_value in updates:
        old = pre_store.get(key)
        sibs = pre_store.path(key)
        dirs = [(int(key) >> i) & 1 for i in range(depth)]
        proof, pre_root, post_root = MU.prove_update(old, new_value, sibs, dirs, num_queries=num_queries,
                                                     backend=B.RECURSION)
        if pre_root != roots[-1]:
            raise ValueError("internal: update pre_root breaks the chain")
        proofs.append(proof)
        bnds.append(_boundaries(depth, old, new_value, pre_root, post_root))
        roots.append(post_root)
        upd.append((int(key), old % F.P, new_value % F.P))
        pre_store.set(key, new_value)
    out = {"proofs": proofs, "bnds": bnds, "roots": roots, "updates": upd, "depth": depth,
           "num_queries": num_queries, "outer_queries": outer_queries,
           "periodic": MU._periodic(proofs[0]["T"], depth) if proofs else None}
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
            return (roots == [pre_root] and pre_root == post_root), "empty transition"
        if roots[0] != pre_root % F.P:
            return False, "transition pre_root != public pre_root"
        if roots[-1] != post_root % F.P:
            return False, "transition post_root != public post_root"
        if len(roots) != len(proofs) + 1:
            return False, "root/proof count mismatch"
        nqi = num_queries if num_queries is not None else tr["num_queries"]
        nqo = outer_queries if outer_queries is not None else tr["outer_queries"]
        if "bundle" in tr:                                   # O(1)-class: ONE recursion bundle re-verifies all K
            pubs = [RV.public_part(p) for p in proofs]
            okr, whyr = RV.verify(pubs, MU._transitions(), tr["bnds"], tr["bundle"], num_queries_outer=nqo,
                                  periodic=tr["periodic"], num_queries_inner=nqi)
            if not okr:
                return False, f"K->1 bundle failed: {whyr}"
        else:                                                # native: re-verify each update proof + its roots
            for i, (proof, bl) in enumerate(zip(proofs, tr["bnds"])):
                old_v = bl[3][2]; new_v = bl[7][2]           # OCARRY / NCARRY boundary values
                ok, why = MU.verify_update(proof, old_v, new_v, roots[i], roots[i + 1],
                                           num_queries=nqi, backend=B.RECURSION)
                if not ok:
                    return False, f"update {i} failed: {why}"
        return True, "state transition verified (roots chain + every update re-verified)"
    except Exception as e:
        return False, f"malformed transition: {e}"
