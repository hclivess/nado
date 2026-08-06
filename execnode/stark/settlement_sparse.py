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
                            vm_circuit, calls_commit as CC, stark, backend as _bk)
from execnode import settlement_proofs as SP, zkvm

DEFAULT_DEPTH = 256                      # sparse-tree depth = full 128-bit-secure slot space (2^256 positions):
                                         # distinct (cid, slot) never collide, so the scheme is production-final
                                         # (no future reroll for depth). Tests pass their own small depth.


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
    """Serialize a sparse root (alghash2 CAPACITY-tuple) to the on-chain 64-hex form (storage_tree.digest_hex)."""
    return ST.digest_hex(root)


def root_from_hex(h):
    """Inverse of root_hex (storage_tree.digest_from_hex)."""
    return ST.digest_from_hex(h)


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
                      pre_bridge=None, pre_abal=None, pre_assets=None,
                      num_queries=vm_circuit.stark.NUM_QUERIES, depth=DEFAULT_DEPTH,
                      backend=None, row_commit=False):
    """Prove an epoch AND its sparse state transition. Returns a bound bundle = the ordinary epoch bundle (exec
    proof + io) plus {sparse_pre_root, sparse_post_root, transition, cid_io, depth}, where the transition proves
    the epoch's net writes advance sparse_pre_root → sparse_post_root. `pre_abal`/`pre_assets` (doc/assets.md
    §8) are the asset shadow — pass the state's to settle asset-touching calls; they gate the proof but never
    enter the sparse root (which projects contract STORAGE only)."""
    # PER-STAGE TIMING. A settle prove exceeded its own 1200s bound on production state (25 contracts)
    # while an empty-state fixture took 110s, and "the prove is slow" is not an actionable statement — it
    # does not say WHICH stage to port to Rust. prove_epoch reaches the arena for its two stark.prove calls
    # but does its own Merkle commits; prove_transition chains K in-circuit merkle-updates and is pure
    # Python. This says which one to attack, in production, without a profiler.
    import time as _t
    _stage = {}
    _t0 = _t.time()
    bundle = SP.prove_epoch(pre_contracts, calls, cursor, timestamp=timestamp, beacons=beacons,
                            block_hashes=block_hashes, pre_bridge=pre_bridge, pre_abal=pre_abal,
                            pre_assets=pre_assets, num_queries=num_queries,
                            backend=backend, row_commit=row_commit)
    _stage["prove_epoch"] = _t.time() - _t0
    _t1 = _t.time()
    cid_io = _cid_io(bundle)
    pre_store = ST.SparseStore(depth, sparse_projection(pre_contracts, depth))
    sparse_pre = pre_store.root()
    pre_get = lambda cid, slot: ((pre_contracts.get(cid) or {}).get("storage") or {}).get("slots", {}).get(str(int(slot)), 0)
    net = ESB.net_updates(pre_get, cid_io, depth)
    _stage["sparse_projection"] = _t.time() - _t1
    _t2 = _t.time()
    tr = SX.prove_transition(pre_store, [(k, n) for (k, _o, n) in net], num_queries=num_queries)
    _stage["prove_transition"] = _t.time() - _t2
    try:
        print("[settle-prove] cursor=%s calls=%d net_updates=%d | %s | total %.1fs" % (
            cursor, len(calls or []), len(net),
            " ".join("%s=%.1fs" % (k, v) for k, v in _stage.items()), _t.time() - _t0), flush=True)
    except Exception:
        pass
    bundle.update(sparse_pre_root=sparse_pre, sparse_post_root=pre_store.root(),
                  transition=tr, cid_io=cid_io, depth=depth,
                  calls_commitment=CC.calls_commitment(bundle["calls"], cursor, timestamp))
    return bundle


def public_statement(bundle):
    """The O(1)-SHAPED public statement of a bound epoch — three field elements: (calls_commitment,
    sparse_pre_root, sparse_post_root). A verifier checks calls_commitment against the on-chain calldata's
    running commitment (O(1)) and the two roots against the settled chain — no per-call data in the statement."""
    return (bundle["calls_commitment"], bundle["sparse_pre_root"], bundle["sparse_post_root"])


def verify_bound_epoch(bundle, num_queries=None, check_exec_proof=True):
    """Verify a bound epoch WITHOUT replaying the io or re-merkleizing the whole state: (1) the exec proof —
    the io is a valid execution of the public calls; (2) bind_and_verify — the transition's updates are exactly
    the epoch's net writes AND advance sparse_pre_root → sparse_post_root. Returns (ok, reason, sparse_post_root).

    `check_exec_proof=False` skips ONLY step (1) — the recursive settlement path (verify_settlement_sparse with a
    `recursive` bundle) re-verifies every segment's exec proof inside ONE recursion bundle instead of K
    per-segment stark.verify calls, exactly as settlement_proofs.verify_settlement_o1 does. Everything else
    (calls_commitment, the pre-state pin, the state-transition binding) still runs per segment."""
    try:
        nq = int(num_queries) if num_queries is not None else vm_circuit.stark.NUM_QUERIES
        pub_calls, epoch_io = SP._epoch_pub_statement(bundle)
        if check_exec_proof:
            row_commit = "row_roots" in bundle["proof"]
            # The backend is resolved from the PROOF here, deliberately. prove_bound_epoch takes it as a
            # parameter (default blake2b; only prove_settlement_sparse asks for RECURSION), so a bundle can
            # legitimately carry any of them — pinning one would force the wrong HASH and desync the
            # transcript. That is safe because the challenge FIELD is no longer backend-dependent: every
            # backend is GF(p^2), so verify_epoch_calls' guard has nothing weaker to be steered into. If a
            # base-field backend is ever reintroduced, that guard refuses a proof-declared one and this call
            # must start passing the backend it actually expects.
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
        # SOUND-READ BINDING: pre_get below reads the epoch's initial storage values from the prover-supplied
        # pre_contracts. The state transition re-authenticates every WRITTEN slot's old value against
        # sparse_pre_root, but a slot the epoch only READS (never writes) would otherwise take its value on the
        # prover's word — letting a forged read drive the execution while sparse_pre_root stays pinned to the
        # settled tip. Pin the WHOLE pre-state: sparse_pre_root MUST be the root of pre_contracts' projection, so
        # every slot — read-only included — is the committed one. (This native path's O(state) cost; it already
        # carries the full pre_contracts. The succinct io-replay path binds each read via in-circuit membership.)
        want_pre = tuple(int(x) % F.P for x in bundle["sparse_pre_root"])
        if tuple(int(x) % F.P for x in sparse_root(bundle["pre_contracts"], depth)) != want_pre:
            return False, "pre_contracts do not match sparse_pre_root (unbound storage reads)", None
        pre_get = lambda cid, slot: ((bundle["pre_contracts"].get(cid) or {}).get("storage") or {}).get("slots", {}).get(str(int(slot)), 0)
        # BIND cid_io TO THE EXEC PROOF (critical soundness): net_updates/bind_and_verify below drive the settled
        # post-root ENTIRELY from cid_io, but the exec proof (or, in the fold path, RV.verify) authenticates only
        # bundle["io"] + bundle["calls"] — NOT bundle["cid_io"]. Re-derive cid_io from that authenticated io+calls
        # and NEVER trust the prover's bundle["cid_io"] field: otherwise a bonded settler could append a
        # fabricated (cid, IO_SSTORE, slot, value) absent from io, prove a transition over it, and settle an
        # ARBITRARY forged root (overwrite any contract's storage, drain escrow). _cid_io is a pure function of
        # the authenticated (io, calls), so this is transparent for honest bundles and closes the forgery.
        cid_io = _cid_io(bundle)
        okb, whyb = ESB.bind_and_verify(bundle["transition"], bundle["sparse_pre_root"], bundle["sparse_post_root"],
                                        pre_get, cid_io, depth, num_queries=nq)
        if not okb:
            return False, f"state transition binding failed: {whyb}", None
        return True, "ok (sparse-root bound, no replay)", bundle["sparse_post_root"]
    except Exception as e:
        return False, f"malformed bound epoch: {e}", None


def prove_bound_epoch_replay(pre_contracts, calls, cursor, timestamp=0, beacons=None, block_hashes=None,
                             pre_bridge=None, pre_abal=None, pre_assets=None,
                             num_queries=vm_circuit.stark.NUM_QUERIES, depth=DEFAULT_DEPTH,
                             backend=None, row_commit=False):
    """Like prove_bound_epoch, but the state binding is the fully IN-CIRCUIT io replay (io_replay) — the state
    half of the in-circuit statement rebuild — and the public statement is the O(1)-shaped
    (calls_commitment, io_commitment, sparse_pre_root, sparse_post_root). One proof per storage io entry
    (heavier to prove than the net-update transition; all foldable). `pre_abal`/`pre_assets` settle asset
    calls (doc/assets.md §8); they gate the proof and never enter the sparse root."""
    from execnode.stark import io_replay as IR, calls_commit as CC
    bundle = SP.prove_epoch(pre_contracts, calls, cursor, timestamp=timestamp, beacons=beacons,
                            block_hashes=block_hashes, pre_bridge=pre_bridge, pre_abal=pre_abal,
                            pre_assets=pre_assets, num_queries=num_queries,
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
        # Resolved from the proof, same reasoning as verify_bound_epoch above.
        ok, why = vm_circuit.verify_epoch_calls(bundle["proof"], pub_calls, epoch_io, num_queries=nq,
                                                row_commit=row_commit)
        if not ok:
            return False, f"epoch proof invalid: {why}", None
        cursor, ts = int(bundle["cursor"]), int(bundle.get("timestamp", 0))
        if bundle["calls_commitment"] != CC.calls_commitment(bundle["calls"], cursor, ts):
            return False, "calls_commitment mismatch", None
        # cid_io must be the exec-proof-authenticated io+calls, NOT the prover's field (see verify_bound_epoch):
        # otherwise io_commitment/storage_io below bind the replay to a forged log, not the proven execution.
        cid_io = _cid_io(bundle)
        if bundle["io_commitment"] != CC.io_commitment(cid_io):
            return False, "io_commitment mismatch", None
        # bind the replay to the exec's io: each replay storage step must match the storage io entry's KIND,
        # POSITION (slot_key) and VALUE, in order — so the replay is exactly this epoch's (slot, value) writes.
        depth = bundle["depth"]
        storage_io = [(c, k, s, v) for (c, k, s, v) in cid_io if k in (zkvm.IO_SLOAD, zkvm.IO_SSTORE)]
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


def prove_settlement_sparse(pre_contracts, calls, cursor, rec_hex, timestamp=0, beacons=None,
                            block_hashes=None, pre_bridge=None, num_queries=vm_circuit.stark.NUM_QUERIES,
                            depth=DEFAULT_DEPTH, backend=None, row_commit=None,
                            recursive=False, fold=True, max_rows=None, outer_queries=None,
                            comp_points_per_proof=None):
    """Assemble the settle-with-proof payload the L1 branch verifies: bound epoch(s) over the KV half plus
    the (unchanged) records half `rec_hex` — {cursor, kv_pre, kv_post, rec, segments}. Multi-epoch spans
    chain more segments (each bound epoch's post == the next's pre).

    `recursive=True` is the K→1 money path: segment the span into ONE bound epoch PER BLOCK (block-aligned, as
    L1's DA binding requires — each segment.cursor is its block height and covers contiguous whole blocks),
    proven ROW-COMMITTED with the RECURSION backend, then (if `fold`) fold their K exec proofs into ONE recursion
    bundle attached as `recursive`. verify_settlement_sparse verifies that single bundle in place of K
    per-segment stark.verify calls. The sparse state-transition binding stays per segment (the lighter,
    separately-foldable half). Folding is a VERIFICATION-STRATEGY change only: kv_pre/kv_post — the settled root
    — are byte-identical to the non-recursive proof of the same span. (A block whose calls exceed one trace is
    unsupported — the DA binding folds per block — and raises, so the exec node falls back to quorum.)"""
    # DEFAULT TO AN ARENA-COVERED BACKEND. stark.prove only reaches the native arena when
    # _b.name in ("recursion", "alghash2"); backend=None resolves to _backend.DEFAULT, which is BLAKE2B,
    # which the arena does NOT implement — so the whole settle prove silently ran in pure Python. Measured
    # on the live node 2026-08-04: 12+ MINUTES for one prove, ~75% of a core, RSS to 1.8 GB, no .so mapped,
    # and L1 starved into "Forked above the finality floor — re-anchoring".
    #
    # ...AND ROW-COMMIT IT. The default used to be ALGHASH2 in COLUMN mode, and that single choice is where
    # the settle proof's ~120 MiB came from. In column mode every one of the NUM_QUERIES=320 FRI queries
    # opens EVERY column with its own authentication path — W=167 columns x 2 (cur+nxt) = 334 paths per
    # query. row_commit commits ONE recursion-Merkle tree over LDE ROWS per phase, so a query carries 2
    # paths instead of 334. MEASURED on production state (25 contracts, 9,016 slots), empty span, full
    # prove_settlement_sparse -> verify_settlement_sparse round trip:
    #
    #   ALGHASH2 column (the old default) : prove 140.9s   126.56 MiB   verify 19.6s   -> (True, 'ok')
    #   RECURSION row    (this default)   : prove   7.3s     9.73 MiB   verify  6.4s   -> (True, 'ok')
    #
    # 13x smaller, 19x faster to prove, 3x faster to verify — and kv_pre/kv_post are BYTE-IDENTICAL between
    # the two forms (63350d91c923b70d… both ways), which is the only thing consensus sees. The openings were
    # 95.6% of the old proof (118.97 of 124.43 MiB), so this is essentially all of the size.
    #
    # WHY IT NEEDS NO VERIFIER CHANGE. Both knobs are recovered FROM THE PROOF, not from the caller:
    # verify_bound_epoch does `row_commit = "row_roots" in bundle["proof"]` (see the two call sites above),
    # and vm_circuit honours proof["backend"]. L1 calls verify_settlement_sparse(proof, depth=…) and passes
    # NEITHER (ops/transaction_ops.py:1251), so an old-format and a new-format proof are interchangeable on
    # the wire — which is also why this is a PRODUCER-side choice and not a consensus rule.
    #
    # row_commit REQUIRES the RECURSION backend (stark.py:377) — they move together, so `row_commit=None`
    # means "match the backend" rather than a bare False that would silently give up the win.
    # The recursive path already proved this way (line ~330); only the non-recursive path was left behind.
    # NB: `_bk` is imported inside the recursive branch below, which makes it a function-local for the whole
    # body and shadows the module-level import — so resolve the backend module explicitly here.
    from execnode.stark import backend as _bk_default
    backend = backend or _bk_default.RECURSION
    if row_commit is None:
        row_commit = getattr(backend, "name", "") == "recursion"
    if not recursive:
        bundle = prove_bound_epoch(pre_contracts, calls, cursor, timestamp=timestamp, beacons=beacons,
                                   block_hashes=block_hashes, pre_bridge=pre_bridge, num_queries=num_queries,
                                   depth=depth, backend=backend, row_commit=row_commit)
        return {"cursor": int(cursor), "rec": rec_hex,
                "kv_pre": ST.digest_hex(tuple(int(x) % F.P for x in bundle["sparse_pre_root"])),
                "kv_post": ST.digest_hex(tuple(int(x) % F.P for x in bundle["sparse_post_root"])),
                "segments": [bundle]}
    # --- recursive: ONE bound-epoch segment PER BLOCK, then fold the K exec proofs into one recursion bundle ---
    # Block-aligned by construction: L1's verify_calls_bound_to_summaries folds per-block summary leaves and
    # requires each segment.cursor to be its last block height, covering contiguous whole blocks. block_calls
    # stamps cursor=height per call, so we group the span's calls by block and prove one bound epoch per block
    # (prove_bound_epoch already sparse-binds it). The last segment's cursor extends to the span end so trailing
    # empty blocks (which fold to an unchanged commitment) are still covered.
    import copy
    from execnode.stark import backend as _bk, recursive_verify as RV
    from execnode.settlement_proofs import _run_call
    oq = int(outer_queries) if outer_queries is not None else int(num_queries)
    present, grouped = [], {}
    for c in calls:
        h = int(c.get("cursor", cursor))
        if not present or present[-1] != h:
            present.append(h)
        grouped.setdefault(h, []).append(c)
    if not present:
        raise ValueError("recursive settlement over an empty call span")
    contracts = copy.deepcopy(pre_contracts)
    bridge = dict(pre_bridge or {})
    segments, exec_proofs, bnds, pers = [], [], [], []
    for idx, h in enumerate(present):
        blk_calls = grouped[h]
        seg_cursor = int(cursor) if idx == len(present) - 1 else h     # last segment covers trailing empty blocks
        seg = prove_bound_epoch(contracts, blk_calls, cursor=seg_cursor, timestamp=timestamp, beacons=beacons,
                                block_hashes=block_hashes, pre_bridge=bridge, num_queries=num_queries,
                                depth=depth, backend=_bk.RECURSION, row_commit=True)
        segments.append(seg)
        reg = {}                                          # advance contracts (+bridge) to this block's post-state
        for j, call in enumerate(blk_calls):              # (records-frozen span ⇒ empty asset shadow is inert)
            _run_call(contracts, bridge, {}, {}, reg, call, j, h, timestamp, beacons, block_hashes, False)
        pub_calls, epoch_io = SP._epoch_pub_statement(seg)
        # These segments are proven with RECURSION, which now draws from GF(p^2) — so the statement must be
        # rebuilt under the EXTENSION layout (each logical aux column is a base-column PAIR, W 131 -> 149).
        # Defaulting to base here read the geometry as base-width and rejected an honest proof as "bad trace
        # geometry"; ask the one authority rather than assume.
        ok, why, periodic, bl = vm_circuit.epoch_statement(
            seg["proof"], pub_calls, epoch_io, ext=stark.ext_challenges_active(_bk.RECURSION))
        if not ok:
            raise ValueError(f"segment statement: {why}")
        exec_proofs.append(seg["proof"]); bnds.append(bl); pers.append(periodic)
    out = {"cursor": int(cursor), "rec": rec_hex,
           "kv_pre": ST.digest_hex(tuple(int(x) % F.P for x in segments[0]["sparse_pre_root"])),
           "kv_post": ST.digest_hex(tuple(int(x) % F.P for x in segments[-1]["sparse_post_root"])),
           "segments": segments}
    # K->1 NEEDS K > 1. The bundle REPLACES the K per-segment exec-proof verifications with one bundle
    # verification (verify_settlement_sparse's docstring), so with a SINGLE segment it replaces one
    # stark.verify with one bundle verify — no win — while costing a full extra STARK prove and its bytes
    # on the wire. It is not a size optimisation either: `segments` are kept and `recursive` is ADDED.
    #
    # This is not hypothetical. Measured 2026-08-06: EVERY settle on this chain emits "1 segment(s)" (14 of
    # 14 that day), so the fold has only ever folded ONE proof. It is what made a folded prove take
    # prove_transition=782-884 s against prove_epoch=8.9 s, and what pushed the first successful folded
    # prove past SETTLE_PROVE_TIMEOUT (it finished at 1156.9 s and was abandoned 43 s later).
    #
    # Skipping the fold is always SAFE: a proof without `recursive` simply takes the classic per-segment
    # verification path, which every verifier still implements (verify_settlement_sparse's `fold_exec`
    # branch is conditional on the field being present). So this is a PROVER-side choice, not a consensus
    # rule, and it needs no agreement from peers.
    if fold and len(exec_proofs) > 1:                    # attach the K→1 recursion bundle (the heavy step)
        # Which field the fold's inner proofs live in — asked, never assumed. The RECURSION backend is no
        # longer pinned to the base field (a backend that picks its own field picks its own security level),
        # so this is the single authority and BOTH halves of the fold must read it.
        _fx = stark.ext_challenges_active(_bk.RECURSION)
        out["recursive"] = RV.prove(exec_proofs, vm_circuit.transitions(ext=_fx), bnds, num_queries_outer=oq,
                                    periodic_list=pers, num_challenges=2,
                                    num_aux=(vm_circuit.NUM_AUX_EXT if _fx else vm_circuit.NUM_AUX),
                                    comp_points_per_proof=comp_points_per_proof)
        out["comp_points_per_proof"] = comp_points_per_proof
    return out


def verify_settlement_sparse(proof, num_queries=None, depth=None, outer_queries=None, allow_recursive=True):
    """Verify a chained SPARSE settlement over the KV half of the settled root: `proof["segments"]` is an
    ordered list of bound epochs (verify_bound_epoch — exec proof + bound state transition, no replay), each
    advancing the KV sparse root, with segment j's post == segment j+1's pre. `depth` is the CALLER's protocol
    constant (protocol.EXEC_TREE_DEPTH on L1) and is pinned against every segment — a proof built at a toy
    depth is rejected outright. Returns (ok, reason, kv_pre_hex, kv_post_hex); composing those halves with the
    records half against the committed settled tip is the L1 settle branch's job (ops/transaction_ops).

    K→1: when `proof["recursive"]` is present (and allow_recursive), the K per-segment exec-proof verifications
    are REPLACED by ONE recursion bundle (recursive_verify.verify — fold + row-mode composition) that
    authoritatively re-verifies every segment's exec proof at once; the sparse transition binding + calls
    commitment + pre-state pin + kv chain still run per segment. The inner AND outer query strength is pinned to
    the protocol constant (num_queries/outer_queries None ⇒ protocol) — never read from the bundle — so a
    reduced-strength recursion bundle can never justify a settlement. This is the sound O(1) money path; a proof
    WITHOUT a `recursive` bundle still verifies the classic K-segment way, so the two forms are interchangeable."""
    try:
        segs = proof.get("segments")
        if not isinstance(segs, list) or not segs:
            return False, "no segments", None, None
        # ACTIVATION GATE (consensus): honour a `recursive` bundle ONLY when the protocol flag is on — which
        # flips at a reroll, so the whole fleet agrees. While OFF, the field is IGNORED and every node verifies
        # segments the classic K-way, so folded- and unfolded-code nodes accept IDENTICALLY (a node must never
        # drop the per-segment exec check that an unupgraded peer still enforces — deep-audit finding 2026-07-27).
        from protocol import SETTLE_PROOF_RECURSIVE
        rb = proof.get("recursive") if (allow_recursive and SETTLE_PROOF_RECURSIVE) else None
        fold_exec = rb is not None
        expect, kv_pre_hex = None, None
        for j, seg in enumerate(segs):
            if depth is not None and int(seg.get("depth", -1)) != int(depth):
                return False, f"segment {j} depth != protocol tree depth", None, None
            ok, why, post = verify_bound_epoch(seg, num_queries=num_queries, check_exec_proof=not fold_exec)
            if not ok:
                return False, f"segment {j}: {why}", None, None
            pre = tuple(int(x) % F.P for x in seg["sparse_pre_root"])
            post = tuple(int(x) % F.P for x in post)
            if j == 0:
                kv_pre_hex = ST.digest_hex(pre)
            elif pre != expect:
                return False, f"segment {j} breaks the kv chain", None, None
            expect = post
        if fold_exec:
            from execnode.stark import recursive_verify as RV
            nqi = int(num_queries) if num_queries is not None else vm_circuit.stark.NUM_QUERIES
            nqo = int(outer_queries) if outer_queries is not None else vm_circuit.stark.NUM_QUERIES
            pubs, bnds, pers = [], [], []
            for seg in segs:
                pub_calls, epoch_io = SP._epoch_pub_statement(seg)
                # Extension layout, same reason as the prove side above.
                ok2, why2, periodic, bl = vm_circuit.epoch_statement(
                    seg["proof"], pub_calls, epoch_io, ext=stark.ext_challenges_active(_bk.RECURSION))
                if not ok2:
                    return False, f"segment statement: {why2}", None, None
                pubs.append(RV.public_part(seg["proof"])); bnds.append(bl); pers.append(periodic)
            cpp = proof.get("comp_points_per_proof")
            if cpp is not None and (not isinstance(cpp, int) or cpp < 1):
                return False, "bad comp chunk size", None, None
            # THE SAME AIR THE PROVER USED. This read `transitions()` and `NUM_AUX` — the BASE layout —
            # while the prove side above builds `transitions(ext=_fx)` with NUM_AUX_EXT. Under an extension
            # challenge field that is a different circuit and a different trace width, so every honest folded
            # proof was rejected, and the enclosing `except Exception` reported it as "malformed sparse
            # settlement": a wiring bug wearing a corruption error's clothes. Ask the authority, once, and use
            # the answer for both halves.
            _fx = stark.ext_challenges_active(_bk.RECURSION)
            okr, whyr = RV.verify(pubs, vm_circuit.transitions(ext=_fx), bnds, rb, num_queries_outer=nqo,
                                  periodic_list=pers, num_challenges=2,
                                  num_aux=(vm_circuit.NUM_AUX_EXT if _fx else vm_circuit.NUM_AUX),
                                  comp_points_per_proof=cpp, num_queries_inner=nqi)
            if not okr:
                return False, f"recursive verification failed: {whyr}", None, None
        return True, "ok", kv_pre_hex, ST.digest_hex(expect)
    except Exception as e:
        return False, f"malformed sparse settlement: {e}", None, None


def chain_reads(proof):
    """Every BHASH/BEACON chain-randomness read a settlement bundle claims, as an ordered list of
    (kind, key, value) with kind in {zkvm.IO_BHASH, zkvm.IO_BEACON}, key = height/epoch, value = the
    field element the proof asserts the VM read.

    verify_settlement_sparse only proves the computation is CONSISTENT with these io values; it can NOT
    prove they equal the REAL finalized chain randomness (a malicious prover is free to put any value in
    the io log). The L1 settle branch MUST cross-check each of these against its own authoritative chain
    (block hash at `key` / beacon of epoch `key`) — exactly what the interactive verifier does at
    execnode.py's /exec/verify_state. Without that check a settle-with-proof tx can settle a state built on
    attacker-chosen dice/wheel outcomes."""
    out = []
    for seg in (proof.get("segments") or []):
        for e in seg.get("io", []):
            kind, a, b = int(e[0]), int(e[1]), int(e[2])
            if kind in (zkvm.IO_BHASH, zkvm.IO_BEACON):
                out.append((kind, a, b))
    return out


def verify_withdrawal(settled_root, cid, slot, value, siblings, depth=DEFAULT_DEPTH):
    """A bridge/dividend/unshield exit proves its record (a specific contract slot = value) is a member of the
    settled SPARSE root — storage_tree membership, the sparse replacement for hashing.verify_merkle_proof
    against the flat blake2b root. `siblings` is the authentication path for slot_key(cid, slot)."""
    return ST.verify_read(settled_root, ESB.slot_key(cid, int(slot), depth), int(value) % F.P, siblings)
