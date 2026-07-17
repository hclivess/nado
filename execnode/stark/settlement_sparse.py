"""
SPARSE-ROOT settlement (state-root binding, doc/zk-recursion.md §5b piece (c)) — the integration that ties the
pieces together. It replaces the flat blake2b zkvm_root (which forced verify_epoch to re-merkleize the WHOLE
state + REPLAY the io, O(state)) with a sparse alghash storage root the recursion can bind, verified via a
bound state-transition proof (no replay, no whole-state merkle):

  prove_bound_epoch:  exec proof (io valid, vm_circuit) + a state-transition proof (state_transition) whose
                      updates are the epoch's net writes (exec_state_bind) and which advances sparse pre_root
                      → post_root over the touched slots only.
  verify_bound_epoch: verify the exec proof + bind_and_verify the transition — O(#io) + the (foldable) proof,
                      instead of O(state). Returns post_root.
  verify_withdrawal:  bridge/dividend/unshield exits prove their record is a member of the settled SPARSE root
                      (storage_tree membership) — the same root, so one settled root serves execution + exits.

Wiring this in as THE consensus settled root (settle tx state_root, ops/transaction_ops exit proofs, state.py's
projection) is the deploy step that rides the reroll (a new state-root scheme = a genesis change; forking cleared).
"""
from execnode.stark import (field as F, storage_tree as ST, state_transition as SX, exec_state_bind as ESB,
                            vm_circuit, calls_commit as CC)
from execnode import settlement_proofs as SP, zkvm

DEFAULT_DEPTH = 24                       # sparse-tree depth: 2^24 slot positions (raise toward 2^256 in prod)


def sparse_projection(contracts, depth=DEFAULT_DEPTH):
    """{slot_key(cid, slot): value} over every zkVM-runtime contract's storage — the sparse analogue of
    settlement_proofs.zkvm_leaves. Deterministic (sorted), integers only."""
    out = {}
    for cid in sorted(contracts):
        c = contracts[cid]
        if c.get("runtime") != "zkvm":
            continue
        for k, v in ((c.get("storage") or {}).get("slots") or {}).items():
            out[ESB.slot_key(cid, int(k), depth)] = int(v) % F.P
    return out


def sparse_root(contracts, depth=DEFAULT_DEPTH):
    """The settled SPARSE storage root (alghash2 CAPACITY-tuple, ~128-bit) — the binding-friendly, forgery-
    resistant replacement for zkvm_root."""
    return ST.SparseStore(depth, sparse_projection(contracts, depth)).root()


def root_hex(root):
    """Serialize a sparse root (alghash2 CAPACITY-tuple) to 64 hex chars — 16 per lane (each lane < p < 2^64), so
    it fits the on-chain state_root format (64-hex) while carrying the full 256-bit / 128-bit-secure digest."""
    return "".join(format(int(x) % F.P, "016x") for x in root)


def root_from_hex(h):
    """Inverse of root_hex — parse a 64-hex settled state_root back to the CAPACITY-tuple."""
    if not (isinstance(h, str) and len(h) == 16 * ST.DIGEST):
        raise ValueError("bad sparse root hex length")
    return tuple(int(h[i * 16:(i + 1) * 16], 16) for i in range(ST.DIGEST))


def sparse_root_hex(contracts, depth=DEFAULT_DEPTH):
    """The settled sparse root as 64-hex — what a settle tx / state_root carries on-chain."""
    return root_hex(sparse_root(contracts, depth))


def _cid_io(bundle):
    """The epoch's io tagged with the CID it belongs to: split the global io by IO_RET (one segment per call)
    and pair each with its call's cid — [(cid, kind, slot, value), ...] in execution order."""
    out, seg_idx = [], 0
    calls = bundle["calls"]
    for e in bundle["io"]:
        kind, a, b = int(e[0]), int(e[1]), int(e[2])
        if seg_idx < len(calls):
            out.append((calls[seg_idx]["cid"], kind, a, b))
        if kind == zkvm.IO_RET:
            seg_idx += 1
    return out


def prove_bound_epoch(pre_contracts, calls, cursor, timestamp=0, beacons=None, block_hashes=None,
                      pre_bridge=None, num_queries=vm_circuit.stark.NUM_QUERIES, depth=DEFAULT_DEPTH,
                      backend=None, row_commit=False):
    """Prove an epoch AND its sparse state transition. Returns a bound bundle = the ordinary epoch bundle (exec
    proof + io) plus {sparse_pre_root, sparse_post_root, transition, cid_io, depth}, where the transition proves
    the epoch's net writes advance sparse_pre_root → sparse_post_root."""
    bundle = SP.prove_epoch(pre_contracts, calls, cursor, timestamp=timestamp, beacons=beacons,
                            block_hashes=block_hashes, pre_bridge=pre_bridge, num_queries=num_queries,
                            backend=backend, row_commit=row_commit)
    cid_io = _cid_io(bundle)
    pre_store = ST.SparseStore(depth, sparse_projection(pre_contracts, depth))
    sparse_pre = pre_store.root()
    pre_get = lambda cid, slot: ((pre_contracts.get(cid) or {}).get("storage") or {}).get("slots", {}).get(str(int(slot)), 0)
    net = ESB.net_updates(pre_get, cid_io, depth)
    tr = SX.prove_transition(pre_store, [(k, n) for (k, _o, n) in net], num_queries=num_queries)
    bundle.update(sparse_pre_root=sparse_pre, sparse_post_root=pre_store.root(),
                  transition=tr, cid_io=cid_io, depth=depth,
                  calls_commitment=CC.calls_commitment(bundle["calls"], cursor, timestamp))
    return bundle


def public_statement(bundle):
    """The O(1)-SHAPED public statement of a bound epoch — three field elements: (calls_commitment,
    sparse_pre_root, sparse_post_root). A verifier checks calls_commitment against the on-chain calldata's
    running commitment (O(1)) and the two roots against the settled chain — no per-call data in the statement."""
    return (bundle["calls_commitment"], bundle["sparse_pre_root"], bundle["sparse_post_root"])


def verify_bound_epoch(bundle, num_queries=None):
    """Verify a bound epoch WITHOUT replaying the io or re-merkleizing the whole state: (1) the exec proof —
    the io is a valid execution of the public calls; (2) bind_and_verify — the transition's updates are exactly
    the epoch's net writes AND advance sparse_pre_root → sparse_post_root. Returns (ok, reason, sparse_post_root)."""
    try:
        nq = int(num_queries) if num_queries is not None else vm_circuit.stark.NUM_QUERIES
        pub_calls, epoch_io = SP._epoch_pub_statement(bundle)
        row_commit = "row_roots" in bundle["proof"]
        ok, why = vm_circuit.verify_epoch_calls(bundle["proof"], pub_calls, epoch_io, num_queries=nq,
                                                row_commit=row_commit)
        if not ok:
            return False, f"epoch proof invalid: {why}", None
        # the O(1)-shaped public input: the epoch's calls collapse to one commitment (checked against the
        # calldata's running commitment on-chain). Here we confirm the bundle's commitment matches its calls.
        if "calls_commitment" in bundle:
            want = CC.calls_commitment(bundle["calls"], int(bundle["cursor"]), int(bundle.get("timestamp", 0)))
            if bundle["calls_commitment"] != want:
                return False, "calls_commitment does not match the epoch's calls", None
        depth = bundle["depth"]
        pre_get = lambda cid, slot: ((bundle["pre_contracts"].get(cid) or {}).get("storage") or {}).get("slots", {}).get(str(int(slot)), 0)
        okb, whyb = ESB.bind_and_verify(bundle["transition"], bundle["sparse_pre_root"], bundle["sparse_post_root"],
                                        pre_get, bundle["cid_io"], depth, num_queries=nq)
        if not okb:
            return False, f"state transition binding failed: {whyb}", None
        return True, "ok (sparse-root bound, no replay)", bundle["sparse_post_root"]
    except Exception as e:
        return False, f"malformed bound epoch: {e}", None


def prove_bound_epoch_replay(pre_contracts, calls, cursor, timestamp=0, beacons=None, block_hashes=None,
                             pre_bridge=None, num_queries=vm_circuit.stark.NUM_QUERIES, depth=DEFAULT_DEPTH,
                             backend=None, row_commit=False):
    """Like prove_bound_epoch, but the state binding is the fully IN-CIRCUIT io replay (io_replay) — the state
    half of the in-circuit statement rebuild — and the public statement is the O(1)-shaped
    (calls_commitment, io_commitment, sparse_pre_root, sparse_post_root). One proof per storage io entry
    (heavier to prove than the net-update transition; all foldable)."""
    from execnode.stark import io_replay as IR, calls_commit as CC
    bundle = SP.prove_epoch(pre_contracts, calls, cursor, timestamp=timestamp, beacons=beacons,
                            block_hashes=block_hashes, pre_bridge=pre_bridge, num_queries=num_queries,
                            backend=backend, row_commit=row_commit)
    cid_io = _cid_io(bundle)
    pre_store = ST.SparseStore(depth, sparse_projection(pre_contracts, depth))
    sparse_pre = pre_store.root()
    replay = IR.prove_io_replay(pre_store, cid_io, depth, num_queries=num_queries)   # mutates pre_store
    bundle.update(sparse_pre_root=sparse_pre, sparse_post_root=pre_store.root(), replay=replay, cid_io=cid_io,
                  depth=depth, calls_commitment=CC.calls_commitment(bundle["calls"], cursor, timestamp),
                  io_commitment=CC.io_commitment(cid_io))
    return bundle


def verify_bound_epoch_replay(bundle, num_queries=None):
    """Verify a replay-bound epoch: (1) exec proof — the io is a valid execution of the calls; (2) the storage
    steps of the io replay correspond to the epoch's storage io (binds the replay to the exec's io); (3) the
    io replay chains sparse_pre_root → sparse_post_root IN-CIRCUIT (foldable → O(1) crypto); (4) the O(1)-shaped
    commitments match. Returns (ok, reason, sparse_post_root). NOTE: (1),(2),(4) are still native O(#io) — moving
    them in-circuit against the commitments (bind the exec AIR's io/calls to them) is the last O(1) step."""
    from execnode.stark import io_replay as IR, calls_commit as CC
    try:
        nq = int(num_queries) if num_queries is not None else vm_circuit.stark.NUM_QUERIES
        pub_calls, epoch_io = SP._epoch_pub_statement(bundle)
        row_commit = "row_roots" in bundle["proof"]
        ok, why = vm_circuit.verify_epoch_calls(bundle["proof"], pub_calls, epoch_io, num_queries=nq,
                                                row_commit=row_commit)
        if not ok:
            return False, f"epoch proof invalid: {why}", None
        cursor, ts = int(bundle["cursor"]), int(bundle.get("timestamp", 0))
        if bundle["calls_commitment"] != CC.calls_commitment(bundle["calls"], cursor, ts):
            return False, "calls_commitment mismatch", None
        if bundle["io_commitment"] != CC.io_commitment(bundle["cid_io"]):
            return False, "io_commitment mismatch", None
        # bind the replay to the exec's io: each replay storage step must match the storage io entry's KIND,
        # POSITION (slot_key) and VALUE, in order — so the replay is exactly this epoch's (slot, value) writes.
        depth = bundle["depth"]
        storage_io = [(c, k, s, v) for (c, k, s, v) in bundle["cid_io"] if k in (zkvm.IO_SLOAD, zkvm.IO_SSTORE)]
        steps = bundle["replay"]["steps"]
        if len(steps) != len(storage_io):
            return False, "replay step count != storage io count", None
        for step, (cid, kind, slot, value) in zip(steps, storage_io):
            want_kind = "load" if kind == zkvm.IO_SLOAD else "store"
            if step["kind"] != want_kind:
                return False, "replay step kind != io", None
            if step["key"] != ESB.slot_key(cid, int(slot), depth):
                return False, "replay step position != io slot", None
            if step["new"] != int(value) % F.P:                  # new == the io value (load: the read; store: the write)
                return False, "replay step value != io", None
        okr, whyr = IR.verify_io_replay(bundle["replay"], bundle["sparse_pre_root"], bundle["sparse_post_root"],
                                        num_queries=nq)
        if not okr:
            return False, f"io replay failed: {whyr}", None
        return True, "ok (sparse-root bound via in-circuit io replay)", bundle["sparse_post_root"]
    except Exception as e:
        return False, f"malformed replay-bound epoch: {e}", None


def public_statement_o1(bundle):
    """The O(1)-shaped public statement of a replay-bound epoch: (calls_commitment, io_commitment,
    sparse_pre_root, sparse_post_root) — four field elements, independent of the epoch size."""
    return (bundle["calls_commitment"], bundle["io_commitment"], bundle["sparse_pre_root"], bundle["sparse_post_root"])


def verify_withdrawal(settled_root, cid, slot, value, siblings, depth=DEFAULT_DEPTH):
    """A bridge/dividend/unshield exit proves its record (a specific contract slot = value) is a member of the
    settled SPARSE root — storage_tree membership, the sparse replacement for hashing.verify_merkle_proof
    against the flat blake2b root. `siblings` is the authentication path for slot_key(cid, slot)."""
    return ST.verify_read(settled_root, ESB.slot_key(cid, int(slot), depth), int(value) % F.P, siblings)
