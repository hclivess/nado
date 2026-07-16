"""
FOLD-LAYER io BINDING (doc/zk-recursion.md §5c, piece 2) — bind the exec proof's io to the state replay's io
WITHOUT re-checking the log, WITHOUT making the io public, and WITHOUT a shared prover transcript.

The soundness obstacle (proven earlier): a fingerprint/multiset match binds two ios only if its challenge
post-dates BOTH commitments; a one-sided public challenge lets the other side's free-witness io adapt to collide.
The DEEP evaluation primitive resolves it: commit each side's io columns, draw a random OOD point z from a
transcript that absorbs BOTH sides' roots (so z post-dates both), and prove P_a(z)=P_b(z) for each column pair.
Equality at one random z ⟹ the polynomials (hence the io) are equal (Schwartz–Zippel), in O(polylog) — no DA, no
re-execution, no combined mega-AIR.

The io columns are committed with the SAME geometry (N, offset, backend) the two proofs used, so a caller ties
each root by EQUALITY to an already-committed column (`exec_roots` = the exec AIR's committed io-table roots,
`replay_roots` = the replay's io roots). This binding proof is itself RECURSION-committable, so it folds into the
settlement bundle via recursive_verify_hetero.
"""
from execnode.stark import field as F, deep_eval as DE, fri, backend as _backend
from execnode.stark.transcript import Transcript
from execnode.stark.stark import OFF as DEFAULT_OFF


def prove_io_bind(exec_cols, replay_cols, N, offset=DEFAULT_OFF, num_queries=fri.NUM_QUERIES, backend=None):
    """`exec_cols` / `replay_cols` are equal-length lists of the two sides' io columns (same encoding + length T).
    Commit both, draw z from a transcript absorbing ALL roots (post-both), and DEEP-eval every column at z.
    Returns a bundle {roots_a, roots_b, z, evals_a, evals_b}. verify checks the roots tie to the real proofs and
    the paired evaluations are equal — i.e. the ios are the same multiset in the same order."""
    b = backend or _backend.DEFAULT
    if len(exec_cols) != len(replay_cols):
        raise ValueError("exec/replay must expose the same number of io columns")
    roots_a = [DE.commit_column(c, N, offset, b) for c in exec_cols]
    roots_b = [DE.commit_column(c, N, offset, b) for c in replay_cols]
    t = Transcript("io-bind", backend=b)
    for r in roots_a + roots_b:
        t.absorb(r)
    z = t.challenge()
    evals_a = [DE.prove_eval(c, z, N, offset, num_queries=num_queries, backend=b) for c in exec_cols]
    evals_b = [DE.prove_eval(c, z, N, offset, num_queries=num_queries, backend=b) for c in replay_cols]
    return {"roots_a": roots_a, "roots_b": roots_b, "z": z, "evals_a": evals_a, "evals_b": evals_b}


def verify_io_bind(bundle, exec_roots, replay_roots, num_queries=fri.NUM_QUERIES, backend=None):
    """Verify the io binding: (1) the bundle's committed roots equal the two proofs' actual io roots (the tie);
    (2) z is the challenge drawn from ALL those roots (post-both — the soundness crux); (3) every column's DEEP
    eval verifies against its pinned root; (4) the paired evaluations are equal ⟹ exec io == replay io. Returns
    (ok, reason)."""
    try:
        b = backend or _backend.DEFAULT
        exec_roots, replay_roots = list(exec_roots), list(replay_roots)
        if bundle["roots_a"] != exec_roots:
            return False, "exec io roots do not match the exec proof"
        if bundle["roots_b"] != replay_roots:
            return False, "replay io roots do not match the replay proof"
        if len(exec_roots) != len(replay_roots):
            return False, "io column count mismatch"
        t = Transcript("io-bind", backend=b)
        for r in exec_roots + replay_roots:
            t.absorb(r)
        z = t.challenge()
        if z != bundle["z"]:
            return False, "z was not drawn from both proofs' committed roots"
        for j in range(len(exec_roots)):
            ea, eb = bundle["evals_a"][j], bundle["evals_b"][j]
            oka, whya = DE.verify_eval(ea, z, num_queries=num_queries, backend=b, expect_P_root=exec_roots[j])
            if not oka:
                return False, f"exec io column {j} eval failed: {whya}"
            okb, whyb = DE.verify_eval(eb, z, num_queries=num_queries, backend=b, expect_P_root=replay_roots[j])
            if not okb:
                return False, f"replay io column {j} eval failed: {whyb}"
            if int(ea["v"]) % F.P != int(eb["v"]) % F.P:
                return False, f"io column {j} differs (exec io != replay io)"
        return True, "ok — exec io == replay io (bound at a random OOD point post both commitments)"
    except Exception as e:
        return False, f"malformed io-bind bundle: {e}"
