"""
O(1)-shaped BOUND EPOCH (doc/zk-recursion.md §5c) — assemble the fully-succinct settlement binding.

The verifier does NO O(#io) work on the io log: it checks the exec proof with committed periodic tables
(verify_epoch_o1, O(#calls)) and binds the exec's COMMITTED io to the state replay's io columns with the DEEP
out-of-domain binding (io_bind, O(polylog)) — the io is never made public and never re-derived. The replay's io
columns are the same io-table encoding the exec commits (PL_CTR/KIND/A/B/ACT), padded to the exec trace length so
their commitments tie by root equality.

prove_bound_epoch_o1: prove the epoch with COMMIT_PERIODIC, expose the io-table roots, build + bind the replay's
io columns. verify_bound_epoch_o1: verify_epoch_o1 (exec) + verify_io_bind (exec io == replay io). The replay's
io columns then drive the state transition (io_replay + slot_key_air for positions) — that leg is added on top.
"""
from execnode.stark import (vm_circuit as VC, io_bind as IB, deep_eval as DE, field as F, backend as B, stark)

IO_COLS = [VC.PL_CTR, VC.PL_KIND, VC.PL_A, VC.PL_B, VC.PL_ACT]     # the io-table periodic columns


def _exec_io_columns(calls, epoch_io=None, proof=None):
    """The exec io-table column VALUES (build_periodic) for a normalized call list — the columns a replay must
    match. Returns (io_values, T, N or None)."""
    ncalls = [VC._norm_call(c) for c in calls]
    trace, T, blocks, progs, ep_io, _pc = VC.build_epoch_trace(ncalls)
    periodic = VC.build_periodic(blocks, progs, ep_io, T)
    return [periodic[c] for c in IO_COLS], T


def _io_roots_from_proof(proof):
    """The committed io-table roots inside a COMMIT_PERIODIC exec proof (per_roots align with sorted COMMIT_PERIODIC)."""
    order = VC.COMMIT_PERIODIC
    return [proof["per_roots"][order.index(c)] for c in IO_COLS]


def replay_io_columns(cid_io, T):
    """The replay's io-table columns (ctr, kind, a=slot, b=value, act) built from the epoch's io in execution
    order and padded to T — the SAME encoding the exec commits, so io_bind ties them by root equality. `cid_io`
    is [(cid, kind, a, b), …] (cid is bound separately by calls_commitment; the io VALUES are what's bound here)."""
    ctr, kind, a, bb, act = ([0] * T for _ in range(5))
    for i, e in enumerate(cid_io):
        if i >= T:
            raise ValueError("io does not fit the trace")
        _cid, k, s, v = e
        ctr[i] = i; kind[i] = int(k) % F.P; a[i] = int(s) % F.P; bb[i] = int(v) % F.P; act[i] = 1
    return [ctr, kind, a, bb, act]


def prove_bound_epoch_o1(calls, cid_io, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove the epoch with committed periodic tables and bind the exec's committed io to the replay's io columns.
    `cid_io` = the epoch's io as [(cid, kind, a, b)] in execution order (from the caller's segmentation). Returns
    {proof, io_roots, replay_roots, bind, T, N}. (Uses the DEFAULT backend so the committed-column roots match
    io_bind's commit_column — the tie.)"""
    b = backend or B.DEFAULT
    proof, epoch_io, _per = VC.prove_epoch_calls(calls, num_queries=num_queries, commit_periodic=VC.COMMIT_PERIODIC,
                                                 backend=None if b is B.DEFAULT else backend)
    N, T = proof["N"], proof["T"]
    exec_io_vals, _T = _exec_io_columns(calls)
    io_roots = _io_roots_from_proof(proof)
    replay_vals = replay_io_columns(cid_io, T)
    bind = IB.prove_io_bind(exec_io_vals, replay_vals, N, offset=stark.OFF, num_queries=num_queries, backend=b)
    replay_roots = [DE.commit_column(v, N, offset=stark.OFF, backend=b) for v in replay_vals]
    return {"proof": proof, "io_roots": io_roots, "replay_roots": replay_roots, "bind": bind, "T": T, "N": N}


def verify_bound_epoch_o1(bundle, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify the O(1)-shaped bound epoch: (1) the exec proof with committed tables (verify_epoch_o1, O(#calls) —
    per_roots taken from the proof/statement, NO io-log rebuild); (2) io_bind — the exec's committed io equals the
    replay's io columns (O(polylog), no public io). Returns (ok, reason). The exec's io-table roots the binding
    pins are exactly the committed columns verify_epoch_o1 opens, so the two checks share one committed io."""
    try:
        b = backend or B.DEFAULT
        proof = bundle["proof"]
        oke, whye = VC.verify_epoch_o1(proof, proof["per_roots"], num_queries=num_queries)
        if not oke:
            return False, f"exec proof (O(1) shape) failed: {whye}"
        # the binding must pin exactly the exec proof's committed io-table roots
        if bundle["io_roots"] != _io_roots_from_proof(proof):
            return False, "io_roots do not match the exec proof's committed io"
        okb, whyb = IB.verify_io_bind(bundle["bind"], bundle["io_roots"], bundle["replay_roots"],
                                      num_queries=num_queries, backend=b)
        if not okb:
            return False, f"exec↔replay io binding failed: {whyb}"
        return True, "ok — exec verified O(#calls) + committed io bound to the replay's io (O(polylog), no public log)"
    except Exception as e:
        return False, f"malformed bound epoch: {e}"
