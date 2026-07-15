"""
Recursion DEPTH — fold-of-folds (doc/zk-recursion.md §5b). The K→1 collapse of recursive_verify still leaves a
verifier O(K) cheap work and a bundle that grows with K. DEPTH removes it: a fold proof (fri_verify.prove_fold
with out_backend=RECURSION) is itself an rleaf/rnode-committed STARK, so its OWN embedded FRI is exactly the
shape prove_fold folds — a fold can be folded. `fold_tree` fans N inner FRI proofs in by F at each level, so
after ⌈log_F(N)⌉ levels ONE ROOT fold proof attests every inner proof's low-degree, and the verifier checks
that single fixed-size object (plus the O(log N) hashing to rebuild each level's public statement).

Verifier-authoritative at every level: each node's public statement is the level-below fold proofs' PUBLIC
parts ({roots, N, offset, blowup, final, pow}), and the Fiat-Shamir transcript that embeds each fold proof's
FRI is rebuilt from that proof's own committed column roots + AIR shape (the standard nado-stark single-phase
replay: absorb col_roots, draw #transitions + #boundaries challenges). A prover controls only witness; the tree
structure and every schedule are verifier-derived.

Scope: this is the LOW-DEGREE depth — it proves, in one root, that all N inner FRI proofs (and transitively all
intermediate fold proofs) are low-degree. Making each level AUTHORITATIVE for a state root additionally folds
the composition half (recursive_verify) at each level; same mechanism, more plumbing (§5b). The low-degree tree
is the recursion-DEPTH primitive: a recursion proof verifying recursion proofs.

MEASURED (pure Python, this box): the VERIFY side is O(1) — a fold-of-folds ROOT verifies in ~0.2 s regardless
of how many proofs sit beneath it (that is the whole point). The PROVE side is throughput-bound: each level
folds the level-below fold proofs' embedded FRI, and a fold proof's FRI (blowup·pad ≈ N=4096–8192, ~11–12
layers) makes the next level's recursion trace large (a level-1 fold measured at N=131072, ~19 min), outgrowing
the native NTT cap into Python big-int NTTs — the same wall the W=106 settlement bundle hits. The Rust prover is
the prerequisite to make DEEP trees fast to PRODUCE; verification is already constant. tests/test_recursion_depth.py
validates the enabler + foldability fast and the full fold-of-folds step under NADO_HEAVY=1.
"""
from execnode.stark import fri_verify, backend as B
from execnode.stark.transcript import Transcript


def _fold_proof_fs(fold_proof, b=B.RECURSION):
    """The transcript factory that positions a fold proof's transcript exactly where its embedded FRI began.
    A fold proof is an ordinary single-phase STARK, so: absorb its committed column roots, then draw
    (#fold-AIR transitions + #its boundaries) constraint challenges. Both counts are read from the proof
    itself — the fixed fold-AIR transition count and the proof's stored boundary list — so the factory is
    generic over any fold proof, at any tree level."""
    nt = len(fri_verify._transitions())
    nb = len(fold_proof["boundaries"])
    col_roots = fold_proof["col_roots"]

    def mk():
        t = Transcript("nado-stark", backend=b)
        for r in col_roots:
            t.absorb(r)
        for _ in range(nt + nb):
            t.challenge()
        return t
    return mk


def _chunks(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def fold_tree(inner_fri_proofs, inner_mks=None, fan_in=2, num_queries_inner=None, num_queries_outer=64):
    """Fold N inner FRI proofs into ONE root fold proof through a fan-in-`fan_in` tree. `inner_mks[i]` rebuilds
    inner proof i's FRI-start transcript (None ⇒ standalone fresh 'fri' transcripts, e.g. plain fri.prove
    proofs). Every level's fold proof is committed under backend.RECURSION so the NEXT level can fold it.
    Returns {"root", "levels"} — `levels[L]` is a list of {"proof","public","mk_next","children"} nodes, and
    `root` is levels[-1][0]. `children` are the indices (in the level below) this node folded, so verify can
    walk the tree."""
    if not inner_fri_proofs:
        raise ValueError("fold_tree needs at least one inner proof")
    if inner_mks is None:
        inner_mks = [None] * len(inner_fri_proofs)
    if num_queries_inner is None:
        num_queries_inner = len(inner_fri_proofs[0]["queries"])

    # level 0 is virtual: the raw inner FRI proofs + their transcript factories + their inner query count.
    cur = [{"fri": p, "mk": mk, "nqi": num_queries_inner}
           for p, mk in zip(inner_fri_proofs, inner_mks)]
    levels = []
    while len(cur) > 1:
        nxt, nodes = [], []
        base = 0
        for group in _chunks(cur, fan_in):
            fris = [g["fri"] for g in group]
            mks = [g["mk"] for g in group]
            nqi = group[0]["nqi"]
            if any(g["nqi"] != nqi for g in group):
                raise ValueError("a fold group mixes inner query counts")
            proof, public = fri_verify.prove_fold(
                fris, num_queries_inner=nqi, num_queries_outer=num_queries_outer,
                mk_transcripts=mks, out_backend=B.RECURSION)
            mk_next = _fold_proof_fs(proof, B.RECURSION)
            nodes.append({"proof": proof, "public": public, "mk_next": mk_next,
                          "children": list(range(base, base + len(group)))})
            # this fold proof's OWN embedded FRI (proven at num_queries_outer) is the next level's input
            nxt.append({"fri": proof["fri"], "mk": mk_next, "nqi": num_queries_outer})
            base += len(group)
        levels.append(nodes)
        cur = nxt
    if not levels:
        raise ValueError("fold_tree needs at least two inner proofs to have depth (use prove_fold for one)")
    return {"root": levels[-1][0], "levels": levels, "fan_in": fan_in,
            "num_queries_inner": num_queries_inner, "num_queries_outer": num_queries_outer,
            "_inner_mks": list(inner_mks)}


def verify_tree(tree, inner_fri_proofs, expect_inner=None, expect_outer=None):
    """SOUND verification of a fold tree. `inner_fri_proofs` is the level-0 leaf set the caller wants attested
    (the same list fold_tree was built from). Verifies EVERY node (fold proof) against its own public statement
    via verify_fold, at the caller's query-strength policy (defaults to the protocol constant), and cross-checks
    that each level actually folds the level below — a parent's declared inner roots must be exactly the FRI
    roots of the children it names (level 0 → the given inner proofs; higher levels → the child fold proofs'
    embedded FRI). All passing ⇒ every given inner FRI proof, and every intermediate fold, is low-degree,
    established by one root proof + O(log N) native checks. Returns (ok, reason)."""
    try:
        nqo = expect_outer if expect_outer is not None else fri_verify.NUM_QUERIES
        levels = tree["levels"]
        for L, nodes in enumerate(levels):
            # inner strength for THIS level: level 0 folds the raw inner proofs (expect_inner policy);
            # every higher level folds fold proofs proven at nqo, so their inner count is nqo.
            level_nqi = (expect_inner if expect_inner is not None else fri_verify.NUM_QUERIES) if L == 0 else nqo
            for node in nodes:
                mks = _child_mks(tree, L, node, inner_fri_proofs)
                ok, why = fri_verify.verify_fold(node["proof"], node["public"], mk_transcripts=mks,
                                                 expect_inner=level_nqi, expect_outer=nqo,
                                                 out_backend=B.RECURSION)
                if not ok:
                    return False, f"level {L} fold failed: {why}"
                # STRUCTURE: the parent's declared inner roots must be the children's actual FRI roots.
                declared = [tuple(tuple(d) for d in pub["roots"]) for pub in node["public"]["publics"]]
                actual = [tuple(tuple(d) for d in _child_fri(tree, L, ci, inner_fri_proofs)["roots"])
                          for ci in node["children"]]
                if declared != actual:
                    return False, f"level {L} node does not fold the children it names"
        return True, "authoritatively low-degree (fold tree: every level re-verified + structure cross-checked)"
    except Exception as e:
        return False, f"malformed fold tree: {e}"


def _child_fri(tree, level, child_index, inner_fri_proofs):
    """The FRI proof of `node`'s child `child_index`: at level 0 the children are the external inner proofs;
    at level >= 1 they are the fold proofs of the level below (their embedded FRI)."""
    if level == 0:
        return inner_fri_proofs[child_index]
    return tree["levels"][level - 1][child_index]["proof"]["fri"]


def _child_mks(tree, level, node, inner_fri_proofs):
    """Transcript factories for `node`'s inner proofs. Level >= 1: the children are fold proofs, so their
    factory is `mk_next`, rebuilt from the child proof's own committed roots + fold-AIR shape (nothing the
    prover supplied). Level 0: the children are the external inner proofs, whose factories the caller threaded
    into fold_tree (None for standalone plain fri.prove proofs; a STARK-embedded FRI factory otherwise)."""
    if level >= 1:
        return [tree["levels"][level - 1][ci]["mk_next"] for ci in node["children"]]
    inner_mks = tree.get("_inner_mks") or []
    return [inner_mks[ci] if ci < len(inner_mks) else None for ci in node["children"]]
