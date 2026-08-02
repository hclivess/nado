"""PARALLEL state merge — compose two transitions proven from the SAME pre-root into one.

doc/state-merge.md has the reasoning. The short version:

`state_transition.prove_transition` chains one merkle-update proof per key, r0 -> r1 -> ... -> rn. Two
transitions where the second starts where the first ended compose by concatenation (SEQUENTIAL merge, already
what the K->1 fold collapses). Two transitions proven from the SAME pre-root do not, and the reason is worth
stating precisely because it is easy to get wrong:

    Every merkle-update proof authenticates a path AT A SPECIFIC ROOT. B's proofs were produced against r0.
    Updating any key in K_A rewrites every node on that key's root-path, and all paths share the upper tree
    -- always including the root. So B's paths are STALE at rA, and splicing the two proof lists proves
    nothing about the combined state.

Disjointness (K_A n K_B = {}) is NECESSARY but NOT SUFFICIENT. It makes the merged root well DEFINED --
sparse-tree updates to distinct keys commute, so r_ab does not depend on application order -- but it does not
repair a stale path. Disjointness gives you a target, not a proof.

So a merge must discharge three obligations, and is sound only with all three:

  1. DISJOINTNESS, proven rather than assumed. Each side's updates must be strictly increasing by key, and
     the interleaving must be strictly increasing too. Strict inequality at every step is exactly what rules
     out a shared key.
  2. SAME PRE-ROOT. Otherwise the two transitions describe different worlds.
  3. A RE-DERIVATION binding (r0, merged_updates, r_ab).

This module implements the merge-plan half: it checks (1) and (2), derives the merged update list, and
re-derives r_ab. `prove_merge` then produces the transition proof for the merged list, which discharges (3).

WHY THE ECONOMICS WORK. The expensive half -- executing N calls and proving the exec AIR -- parallelises
cleanly, because it never touches the shared tree. Only the state-transition half needs this, and it operates
on the update SETS (sorted keys and values), which are small next to an execution trace. Measured:
prove_epoch_calls verify is FLAT (0.09-0.13 s) and proof size CONSTANT (1263 KB) as calls go 1 -> 8, so the
work this unlocks scales while the settlement cost does not.
"""
from execnode.stark import state_transition as SX, storage_tree as ST, field as F


class MergeError(ValueError):
    """A merge that cannot be shown sound. Raised rather than returned so a caller cannot ignore it."""


def _updates_of(tr):
    """(key, old, new) triples of a transition, in application order."""
    return [(int(k), int(o) % F.P, int(n) % F.P) for (k, o, n) in tr["updates"]]


def check_disjoint(tr_a, tr_b):
    """(ok, reason). The two transitions may be merged in parallel: same pre-root, same depth, and their key
    sets are disjoint. Returns the reason rather than a bare False so a rejection is diagnosable."""
    if tr_a.get("depth") != tr_b.get("depth"):
        return False, f"depth mismatch: {tr_a.get('depth')} vs {tr_b.get('depth')}"
    ra, rb = tr_a.get("roots"), tr_b.get("roots")
    if not ra or not rb:
        return False, "a transition carries no root chain"
    if tuple(ra[0]) != tuple(rb[0]):
        return False, "different pre-roots — the transitions describe different states"
    ka = [k for (k, _o, _n) in _updates_of(tr_a)]
    kb = [k for (k, _o, _n) in _updates_of(tr_b)]
    # A side that writes the same key twice is legal on its own (the second update sees the first's value)
    # but cannot be merged in parallel: its second write depends on its own first, and the merged ordering
    # would have to preserve that while ALSO interleaving the other side. Refuse rather than guess.
    if len(set(ka)) != len(ka):
        return False, "left transition writes a key more than once"
    if len(set(kb)) != len(kb):
        return False, "right transition writes a key more than once"
    clash = set(ka) & set(kb)
    if clash:
        return False, f"key sets overlap ({len(clash)} key(s), e.g. {sorted(clash)[0]})"
    return True, "disjoint"


def merge_plan(tr_a, tr_b, pre_store):
    """The merged update list and the root it must produce, WITHOUT proving anything yet.

    `pre_store` must be a SparseStore at the shared pre-root; it is NOT mutated (a copy is advanced).
    Returns {updates, pre_root, post_root, keys_a, keys_b} where `updates` is [(key, new_value), ...] sorted
    strictly increasing by key -- the canonical order, so the merged root is a pure function of the two
    inputs and not of who merged them.

    Raises MergeError if the merge is not admissible.
    """
    ok, why = check_disjoint(tr_a, tr_b)
    if not ok:
        raise MergeError(why)
    depth = tr_a["depth"]
    pre_root = tuple(tr_a["roots"][0])
    if tuple(pre_store.root()) != pre_root:
        raise MergeError("pre_store is not at the transitions' shared pre-root")

    ua, ub = _updates_of(tr_a), _updates_of(tr_b)
    # Each side's `old` must match the SHARED pre-state, not some intermediate: both were proven against r0,
    # and with keys disjoint no update on one side can have changed a key the other side read.
    for (k, old, _new) in ua + ub:
        if int(pre_store.get(k)) % F.P != old:
            raise MergeError(f"update for key {k} claims old={old} but the pre-state holds "
                             f"{int(pre_store.get(k)) % F.P}")

    merged = sorted([(k, n) for (k, _o, n) in ua + ub], key=lambda t: t[0])
    for i in range(1, len(merged)):
        if merged[i][0] <= merged[i - 1][0]:      # strict: equality would be a shared key
            raise MergeError(f"merged updates are not strictly increasing at index {i}")

    # Re-derive the merged root by applying every update to a COPY of the pre-state.
    work = ST.SparseStore(depth, dict(pre_store.values))
    for k, v in merged:
        work.set(k, v)
    post_root = tuple(work.root())

    return {"updates": merged, "pre_root": pre_root, "post_root": post_root,
            "keys_a": [k for (k, _o, _n) in ua], "keys_b": [k for (k, _o, _n) in ub], "depth": depth}


def prove_merge(tr_a, tr_b, pre_store, num_queries=None, outer_queries=None, fold=False):
    """Prove the parallel merge of two same-pre-root transitions.

    Produces a TRANSITION over the merged update list, so the result is an ordinary transition bundle:
    anything that already verifies a transition verifies a merge, and merges nest. `pre_store` is advanced to
    the merged post-state, matching prove_transition's contract.

    The merged proof is what discharges obligation (3) -- it re-derives r0 -> r_ab with authentication paths
    that are valid, which is precisely what splicing the two sub-proofs could not do.
    """
    plan = merge_plan(tr_a, tr_b, pre_store)
    nq = num_queries if num_queries is not None else tr_a.get("num_queries", SX.MU.stark.NUM_QUERIES)
    oq = outer_queries if outer_queries is not None else tr_a.get("outer_queries", nq)
    tr = SX.prove_transition(pre_store, plan["updates"], num_queries=nq, outer_queries=oq, fold=fold)
    if tuple(tr["roots"][-1]) != plan["post_root"]:
        raise MergeError("internal: proved post-root does not match the re-derived merged root")
    tr["merged_from"] = {"keys_a": plan["keys_a"], "keys_b": plan["keys_b"]}
    return tr


def verify_merge(tr_merged, tr_a, tr_b, num_queries=None, outer_queries=None):
    """(ok, reason) for a merged transition against the two it claims to compose.

    Checks every obligation, INCLUDING that the merged update list is exactly the union of the two inputs.
    That last one is not bookkeeping: a prover able to silently DROP an update could settle a state in which
    someone else's write never happened, and every other check here would still pass.
    """
    try:
        ok, why = check_disjoint(tr_a, tr_b)
        if not ok:
            return False, f"inputs not mergeable: {why}"

        pre_root = tuple(tr_a["roots"][0])
        if tuple(tr_merged["roots"][0]) != pre_root:
            return False, "merged transition does not start at the shared pre-root"

        want = sorted([(k, n) for (k, _o, n) in _updates_of(tr_a) + _updates_of(tr_b)], key=lambda t: t[0])
        got = [(k, n) for (k, _o, n) in _updates_of(tr_merged)]
        if got != want:
            return False, (f"merged updates are not the union of the inputs "
                           f"({len(got)} present, {len(want)} expected)")
        for i in range(1, len(got)):
            if got[i][0] <= got[i - 1][0]:
                return False, f"merged updates are not strictly increasing at index {i}"

        ok2, why2 = SX.verify_transition(tr_merged, pre_root, tuple(tr_merged["roots"][-1]),
                                         num_queries=num_queries, outer_queries=outer_queries)
        if not ok2:
            return False, f"merged transition proof invalid: {why2}"
        return True, "ok"
    except Exception as e:                       # a malformed bundle is a rejection, never a crash
        return False, f"malformed merge: {type(e).__name__}: {e}"
