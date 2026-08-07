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
import time

from execnode.stark import (merkle_update as MU, field as F, backend as B, recursive_verify as RV,
                            storage_tree as ST)


def _rss_gb():
    """Process RSS in GiB, or 0.0 if unavailable. /proc/self/statm field 2 is resident pages — no psutil
    dependency, and it must never be able to break a prove, hence the bare except."""
    try:
        with open("/proc/self/statm") as fh:
            return int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / (1024.0 ** 3)
    except Exception:
        return 0.0

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
# So it is set from a MEASURED safe value, not from what the trace can hold. At EXEC_TREE_DEPTH=256, all
# verified end to end (prove + verify_updates). The position pins used to dominate the composition's memory
# (a size-N vector PER BOUNDARY, and 256 of each segment's ~288 boundaries were per-level DIR pins), so
# moving them into the DIRP periodic column changed every column of this table:
#
#            BEFORE DIRP                        AFTER DIRP (26028450)
#     K   prove s   peak RSS            K   T        prove s   MiB     MiB/update   peak RSS
#     1     35.0     ~0.8 GB            2   32768      39.5    11.90     5.95        0.4 GB
#     2     57.7      2.4 GB            4   65536      75.9    13.02     3.25        0.9 GB
#     3    215.6      6.7 GB            9  131072     178.9    14.19     1.58        1.6 GB   <-- shipped
#     4    332.6      8.7 GB
#     9      OOM     35.7 GB  <-- killed two of the box's other processes
#
# K=9 IS max_batch(256) — the largest that fits MAX_TRACE_ROWS — and it is now better on EVERY axis at once
# for a real 25-update span: 3 proofs instead of 13, 42.6 MiB instead of 155, 537 s instead of ~850, at
# 1.6 GB. Fewer proofs also cuts what L1 pays: its cost is size-linear PLUS ~31 s per merkle-update proof,
# and 13 of those was ~400 s of the submit that timed out at 1204.2 s.
#
# The old "K=3/K=4 buy bytes with time" tradeoff was an artefact of the boundary memory, not of the padding.
DEFAULT_BATCH = int(os.environ.get("NADO_SETTLE_BATCH", "9"))


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
    # PER-BATCH INSTRUMENTATION. A whole transition logs NOTHING until it finishes, and the settle path only
    # prints [settle-prove] on COMPLETION — so a prove that runs past SETTLE_PROVE_TIMEOUT and is abandoned
    # (observed 2026-08-07 00:33, >2400 s against a 640 s model) leaves no evidence of WHERE the time or the
    # memory went. Both of the numbers I shipped this size on were measured in a fresh idle process and were
    # wrong live: per-proof RSS 2.4 GB vs a node at 14.6 GB, and 57.7 s per proof vs ~4x that. One line per
    # batch (~1/minute) is cheap, and it is the difference between measuring the next span and guessing at it.
    _n_batches = -(-len(updates) // batch)
    _t0 = time.monotonic()
    for bi, lo in enumerate(range(0, len(updates), batch)):
        items = []
        for key, new_value in updates[lo:lo + batch]:
            old = pre_store.get(key)
            items.append((old, new_value, pre_store.path(key), _dirs(key, depth)))
            upd.append((int(key), old % F.P, new_value % F.P))
            # APPLY AS WE GO, INSIDE the chunk: segment s+1's siblings must be the ones AFTER segment s
            # landed, exactly as K separate proofs saw them. Collecting all the paths first and then
            # applying would prove a batch against a pre-state that never existed.
            pre_store.set(key, new_value)
        _tb = time.monotonic()
        proof, rts = MU.prove_updates(items, num_queries=num_queries, backend=B.RECURSION)
        if rts[0] != roots[-1]:
            raise ValueError("internal: batch pre_root breaks the chain")
        proofs.append(proof)
        bnds.append(MU._boundaries_batch(items, rts, depth))
        roots.extend(rts[1:])
        _now = time.monotonic()
        print(f"[prove_transition] batch {bi + 1}/{_n_batches} K={len(items)} T={proof.get('T')} "
              f"{_now - _tb:.1f}s (cum {_now - _t0:.1f}s) rss={_rss_gb():.2f}GB", flush=True)
    out = {"proofs": proofs, "bnds": bnds, "roots": roots, "updates": upd, "depth": depth,
           "num_queries": num_queries, "outer_queries": outer_queries, "batch": batch,
           # NO SHARED `periodic` FOR A BATCHED TRANSITION. The batch AIR's periodic columns carry the
           # POSITIONS, which differ per batch, so one array cannot describe all of them. The fold takes
           # `periodic_list` instead — recursive_verify._per_of has supported that all along — and
           # verify_transition rebuilds the same list from the PUBLIC updates.
           "periodic": None}
    if fold and proofs:
        # THE K->1 FOLD, WIRED FOR THE BATCH AIR.
        #
        # It used to be handed MU._transitions() (the SINGLE-update AIR) and a shared `periodic`, against
        # proofs built by the BATCH AIR. That is an IndexError the moment a round constraint reads
        # per[RC_lo + j] out of an array with the wrong width, and it is why the fold looked structurally
        # incompatible with DIRP. It is not: recursive_verify.prove/verify both accept `periodic_list`, one
        # entry per proof, which is exactly what per-proof positions need.
        out["bundle"] = RV.prove(proofs, MU._transitions_batch(), bnds,
                                 num_queries_outer=outer_queries,
                                 periodic_list=_periodic_list(proofs, upd, depth, batch))
    return out


def _periodic_list(proofs, updates, depth, batch):
    """One periodic array per proof, rebuilt from the PUBLIC updates.

    The fold needs the inner AIR's periodic columns for every proof it folds, and with DIRP those columns
    carry the positions — so they differ per proof. Deriving them from `updates` (which is public and which
    the verifier also holds) rather than stashing them in the transition keeps the prover from choosing
    them: verify_transition calls this same function on its own copy."""
    out, at = [], 0
    for p in proofs:
        k = int(p.get("K", 1))
        dirs_list = [_dirs(key, depth) for (key, _o, _n) in updates[at:at + k]]
        out.append(MU._periodic_batch(int(p["T"]), depth, k, dirs_list))
        at += k
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
            # Same AIR and the same per-proof periodic the prover used — both REBUILT here from the public
            # updates, never taken from the transition, so the prover cannot choose what it is verified
            # against. (verdict-cache-must-bind-bytes and settle-verify-authenticate-intermediates were both
            # this bug class: a verifier trusting prover-supplied intermediates.)
            okr, whyr = RV.verify(pubs, MU._transitions_batch(), tr["bnds"], tr["bundle"],
                                  num_queries_outer=nqo, num_queries_inner=nqi,
                                  periodic_list=_periodic_list(proofs, tr["updates"], tr["depth"],
                                                               int(tr.get("batch") or 1)))
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
