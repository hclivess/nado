"""
Epoch settlement proof (doc/zk-execution-proofs.md — Phase-2b) — the capstone that lets L1 accept a settled
zkVM state root because a PROOF says the ordered calls produce it, not because a bonded committee attested it.

AGGREGATED: the whole epoch is proven as ONE zkVM trace (vm_circuit.prove_epoch_calls) — N calls, possibly
across many contracts, concatenated into a single STARK. L1 verifies ONE proof for the epoch (~0.3 s,
independent of the call count) instead of N proofs. `prove_epoch` chains each call's storage, runs the batch
through the aggregated prover, and binds the pre/post zkVM state roots (the SAME Merkle-leaf shape
execnode/state.py commits, so the post root is exactly the state_root L1 settles for the zkVM projection).
`verify_epoch` checks the single proof and replays the epoch's authenticated I/O log to recompute the post
root — NO re-execution.

Remaining (documented, not correctness gaps): PROOF-OF-PROOF recursion (verifying a STARK inside a STARK) to
make the proof O(1) in SIZE too, and full-state settlement composing this zkVM projection with the other blob
families' own proofs (bridge/dividend/shielded). One trace already caps an epoch at vm_circuit.MAX_T rows, so
very large epochs split across a few proofs until recursion lands.
"""
from hashing import canonical_bytes, merkle_root
from execnode import runtimes, zkvm
from execnode.stark import vm_circuit, field as F


def zkvm_leaves(contracts):
    """The canonical Merkle leaves for the zkVM-storage projection — byte-identical to the `kv` leaves
    execnode/state.py commits in state_root, so a post root here equals that state_root's zkVM part."""
    out = []
    for cid in sorted(contracts):
        c = contracts[cid]
        if c.get("runtime") != "zkvm":
            continue
        slots = (c.get("storage") or {}).get("slots") or {}
        for k in sorted(slots, key=lambda s: int(s)):
            out.append(canonical_bytes(["kv", cid, "slots", str(k), slots[k]]))
    return out


def zkvm_root(contracts):
    """Merkle root over the zkVM-storage projection (the settled sub-root a proof justifies)."""
    return merkle_root(zkvm_leaves(contracts))


def _apply_payouts(bridge, cid, payouts):
    """Move a call's payouts out of the contract's escrow into recipients (mirrors state.apply_blob).
    Returns False if the contract can't cover them (the call would have reverted on-chain)."""
    total = sum(a for _t, a in payouts)
    if total > bridge.get(cid, 0):
        return False
    for to, amt in payouts:
        bridge[cid] = bridge.get(cid, 0) - amt
        if bridge[cid] == 0:
            bridge.pop(cid, None)
        bridge[to] = bridge.get(to, 0) + amt
    return True


def _run_call(contracts, bridge, abal, assets, registry, call, i, cursor, timestamp, beacons, block_hashes,
              want_rows):
    """Execute ONE call against the mutable shadows (contracts, bridge, abal, assets, registry): advance
    storage, resolve native payouts AND asset effects, and return (epoch_call, public_call, rows). `rows`
    (executed step count, only when want_rows) is what the segmenter packs against MAX_T. Raises on
    revert/bad payout/illegal asset effect — the same conditions that make the call unprovable.

    ASSETS (doc/assets.md §8): the shadow `abal`/`assets` are the prover's asset half, symmetric to the
    native `bridge`. They are prove-time only (they never enter any root) and exist so the prover never
    proves a storage transition the real chain would revert-and-refund. Crucially, the VM/AIR enforces only
    holder-side solvency; issuer-only / mintable-only / supply-cap live in stage_asset_effects_pure — the
    SAME function the live apply path calls — so authority can never drift between apply and proof."""
    from execnode.state import stage_asset_effects_pure, commit_asset_effects_pure, asset_credit_dict
    cid, method = call["cid"], call["method"]
    c = contracts.get(cid)
    if not c or c.get("runtime") != "zkvm":
        raise ValueError(f"call {i}: no zkvm contract {cid}")
    caller = call.get("caller", "epoch")
    value = int(call.get("value", 0))
    in_asset = int(call.get("asset", 0))                  # 0 == native NADO
    cf, fargs = runtimes.zkvm_statement(caller, call.get("args", []), registry)
    slots = {int(k): int(v) for k, v in (c["storage"].get("slots") or {}).items()}
    if value > 0:
        # Escrow the call value into the contract, same as the live path. Native lands in the bridge shadow;
        # an asset-denominated value lands in the asset shadow — credited BEFORE the abal-view below, so
        # ABAL and pay-out solvency see the escrowed units.
        if in_asset:
            if str(in_asset) not in assets:
                raise ValueError(f"call {i}: no such asset {in_asset}")
            asset_credit_dict(abal, in_asset, cid, value)
        else:
            bridge[cid] = bridge.get(cid, 0) + value
    # the VM sees ONLY this contract's asset balances, {int(aid) -> bal} — the shadow of holder_assets(cid)
    abal_view = {int(aid): int(row.get(cid, 0)) for aid, row in abal.items() if row.get(cid)}
    selfd = runtimes.zkvm_addr_digest(cid)
    res = zkvm.run(c["code"], method, cf, fargs, slots, value=value, cursor=cursor, timestamp=timestamp,
                   beacons=beacons, block_hashes=block_hashes, selfd=selfd, asset=in_asset, abal=abal_view,
                   witness=want_rows)
    ok, _ret, new_slots, io = res[:4]
    if not ok:
        raise ValueError(f"call {i} reverted — nothing to prove")
    rows = len(res[4]) if want_rows else 0
    # ONE reader of the log's meaning, shared with the interpreter: native payouts + asset effects, ASEL
    # pairing enforced, recipients resolved through the same registry (unresolvable -> revert).
    split = runtimes.split_io(io, registry)
    if split is None:
        raise ValueError(f"call {i}: bad io (unresolved payee / broken asset pairing)")
    payouts, effects = split
    if not _apply_payouts(bridge, cid, payouts):
        raise ValueError(f"call {i}: unaffordable payout")
    if effects:
        aok, reason, deltas, sup = stage_asset_effects_pure(abal, assets, cid, effects)
        if not aok:
            raise ValueError(f"call {i}: illegal asset effect — {reason}")
        commit_asset_effects_pure(abal, assets, deltas, sup)
    c["storage"] = {"slots": {str(k): v for k, v in sorted(new_slots.items())}}
    epoch_call = {"code": c["code"], "method": method, "caller_f": cf, "args_f": fargs,
                  "caller": caller, "args": call.get("args", []), "value": value, "cursor": cursor,
                  "timestamp": timestamp, "beacons": beacons, "block_hashes": block_hashes, "slots": slots,
                  "selfd": selfd, "asset": in_asset, "abal": abal_view}
    public_call = {"cid": cid, "method": method, "caller": caller, "args": call.get("args", []),
                   "value": value, "asset": in_asset}
    return epoch_call, public_call, rows


def prove_epoch(pre_contracts, calls, cursor, timestamp=0, beacons=None, block_hashes=None,
                pre_bridge=None, pre_abal=None, pre_assets=None,
                num_queries=vm_circuit.stark.NUM_QUERIES, backend=None, row_commit=False):
    """Prove a batch of zkVM calls as ONE aggregated epoch proof. `pre_contracts` is the pre-state
    {cid: {"code", "storage": {"slots":{...}}, "runtime":"zkvm"}}; `calls` an ordered list of
    {cid, method, caller, args, value?, asset?}. Returns a self-contained bundle: a SINGLE proof binding
    pre_root → post_root over the whole batch. Raises ValueError if the batch exceeds one trace — use
    prove_settlement for unbounded epochs (it segments automatically).

    `pre_abal`/`pre_assets` (doc/assets.md §8) are the asset half of the shadow ledger — pass the state's
    `abal`/`assets` to settle asset-touching calls. They gate the proof (so it never proves a transition the
    chain reverts) but never enter `post_root`, which binds contract STORAGE only.

    `backend` (doc/zk-recursion.md): None/blake2b is the fast native-hash proof L1 verifies directly;
    pass the alghash2 backend to produce a RECURSION-READY proof (field-native verification), the hybrid-wrap
    inner layer a fold circuit consumes. verify_epoch reads the hash from the proof, so no need to thread it."""
    import copy
    contracts = copy.deepcopy(pre_contracts)
    bridge = dict(pre_bridge or {})
    abal = {a: dict(h) for a, h in (pre_abal or {}).items()}   # nested copy: never mutate the caller's rows
    assets = copy.deepcopy(pre_assets or {})                   # supply mutates on mint/burn
    registry = {}
    pre_root = zkvm_root(contracts)
    epoch_calls, public_calls = [], []
    for i, call in enumerate(calls):
        ec, pc, _ = _run_call(contracts, bridge, abal, assets, registry, call, i, cursor, timestamp, beacons,
                              block_hashes, want_rows=False)
        epoch_calls.append(ec); public_calls.append(pc)
    proof, epoch_io, _per = vm_circuit.prove_epoch_calls(epoch_calls, num_queries=num_queries, backend=backend,
                                                         row_commit=row_commit)
    return {"cursor": cursor, "timestamp": timestamp, "pre_root": pre_root,
            "post_root": zkvm_root(contracts), "calls": public_calls,
            "io": [list(e) for e in epoch_io], "proof": proof,
            "pre_contracts": {cid: {"code": c["code"], "storage": c["storage"], "runtime": "zkvm"}
                              for cid, c in pre_contracts.items() if c.get("runtime") == "zkvm"},
            "num_queries": num_queries}


def prove_settlement(pre_contracts, calls, cursor, timestamp=0, beacons=None, block_hashes=None,
                     pre_bridge=None, pre_abal=None, pre_assets=None,
                     num_queries=vm_circuit.stark.NUM_QUERIES, max_rows=None, backend=None,
                     row_commit=False):
    """Prove an epoch of ANY size by SEGMENTING it into consecutive chunks that each fit one trace, then
    chaining their state roots: segment j binds root_j → root_{j+1}, and the whole batch is proven by
    root_0 → root_K. This removes the single-trace 2^17-row cap (doc/zk-execution-proofs.md scaling
    point 1) with NO new cryptography — every segment is an ordinary, sound aggregated epoch proof.

    Returns a bundle {"segments": [epoch_bundle, ...], "pre_root", "post_root", "cursor"}. L1 verifies K
    segment proofs (still no re-execution); folding those K proofs into ONE O(1) check is the recursion
    step (point 2), tracked separately. A single-segment epoch (the common case) yields exactly one proof —
    identical cost to prove_epoch."""
    import copy
    if max_rows is None:
        max_rows = vm_circuit.MAX_T - 2
    contracts = copy.deepcopy(pre_contracts)
    bridge = dict(pre_bridge or {})
    abal = {a: dict(h) for a, h in (pre_abal or {}).items()}
    assets = copy.deepcopy(pre_assets or {})
    pre_root = zkvm_root(contracts)
    # pass 1: run every call once (chaining state) to measure its trace-row cost, packing into segments so
    # each segment's (rows + distinct program sizes + io length + headroom) stays under one trace.
    registry = {}
    boundaries, rows_acc, progs_acc, io_acc = [], 0, 0, 0
    seg_progs = set()
    start = 0
    for i, call in enumerate(calls):
        c = contracts.get(call["cid"])
        prog = c["code"][call["method"]] if c else []
        pkey = id(prog)
        # peek the row cost WITHOUT mutating committed state yet: run on scratch copies. The abal shadow is
        # NESTED, so a shallow dict() here would let the peek mutate the real holder rows.
        peek = copy.deepcopy({call["cid"]: c}) if c else {}
        peek_abal = {a: dict(h) for a, h in abal.items()}
        _ec, _pc, rows = _run_call(peek, dict(bridge), peek_abal, copy.deepcopy(assets), dict(registry),
                                   call, i, cursor, timestamp, beacons, block_hashes, want_rows=True)
        add_prog = 0 if pkey in seg_progs else len(prog)
        if i > start and rows_acc + rows + progs_acc + add_prog + io_acc + 256 > max_rows:
            boundaries.append((start, i)); start = i
            rows_acc = progs_acc = io_acc = 0; seg_progs = set()
            add_prog = len(prog)
        if rows + len(prog) + 256 > max_rows:
            raise ValueError(f"call {i} alone exceeds one trace ({rows} rows)")
        rows_acc += rows; io_acc += rows            # io is bounded by steps; a safe over-estimate
        if pkey not in seg_progs:
            seg_progs.add(pkey); progs_acc += add_prog
        # advance the REAL committed shadows so the next call (and the next segment's pre-state) chains
        _run_call(contracts, bridge, abal, assets, registry, call, i, cursor, timestamp, beacons,
                  block_hashes, want_rows=False)
    boundaries.append((start, len(calls)))
    # pass 2: prove each segment from the chained pre-state
    contracts = copy.deepcopy(pre_contracts)
    bridge2 = dict(pre_bridge or {})
    abal2 = {a: dict(h) for a, h in (pre_abal or {}).items()}
    assets2 = copy.deepcopy(pre_assets or {})
    segments = []
    for (lo, hi) in boundaries:
        seg_calls = calls[lo:hi]
        bundle = prove_epoch(contracts, seg_calls, cursor, timestamp=timestamp, beacons=beacons,
                             block_hashes=block_hashes, pre_bridge=bridge2, pre_abal=abal2, pre_assets=assets2,
                             num_queries=num_queries, backend=backend, row_commit=row_commit)
        segments.append(bundle)
        # advance contracts + bridge + asset shadows to this segment's post-state (replay < re-running)
        reg = {}
        for j, call in enumerate(seg_calls):
            _run_call(contracts, bridge2, abal2, assets2, reg, call, lo + j, cursor, timestamp, beacons,
                      block_hashes, False)
    return {"cursor": cursor, "timestamp": timestamp, "pre_root": pre_root,
            "post_root": zkvm_root(contracts), "segments": segments, "num_segments": len(segments)}


# ---- recursive aggregation of the segment proofs' FRI (doc/zk-recursion.md, doc/zk-glossary.md) ------------
# Each segment proof is an execution-AIR STARK; its cost is dominated by the FRI low-degree argument (the
# Merkle-heavy part). `prove_settlement_recursive` proves those segments with the RECURSION hash backend (so
# their FRI trees are rleaf/rnode) and FOLDS every segment's FRI proof into ONE recursion proof
# (execnode.stark.fri_verify), verified by a single verifier-authoritative check.
#
# SCOPE / SAFETY — read before wiring into the settlement seam:
#   * The fold proves ONLY that each segment's committed COMPOSITION polynomial is low-degree (a sound FRI
#     verification of K proofs in one). It does NOT yet bind those FRI roots to the segment's trace / state
#     transition — that is the STARK composition spot-check for the execution AIR, still unbuilt. So the fold
#     CANNOT by itself justify a settled state root.
#   * Therefore `verify_settlement_recursive` runs the fold ALONGSIDE the authoritative `verify_settlement`
#     (full per-segment STARK verification + the state-root chain) and requires BOTH. The sound path stays the
#     seam's source of truth; the fold is a cross-checked, non-authoritative aggregation. When the composition
#     spot-check + roots-to-state-root binding land, the per-segment STARK verification can be dropped and this
#     becomes the O(1) path. Until then this MUST NOT be registered as the sole settlement verifier.


def _stark_fri_transcript_factory(stark_proof):
    """Rebuild the transcript at the exact point the execution-AIR STARK handed it to fri.prove — from the
    proof's PUBLIC column roots + the AIR's shape (verifier-authoritative). Mirrors stark.prove's two-phase
    order: absorb the W_MAIN main-column roots, draw the 2 aux challenges (β,γ), absorb the NUM_AUX aux-column
    roots, draw the (#transitions + #boundaries) constraint α's. Returns a factory `() -> Transcript`."""
    from execnode.stark import backend as _bk
    from execnode.stark.transcript import Transcript, DOMAIN_STARK
    col_roots = stark_proof["col_roots"]
    Tlen = stark_proof["T"]
    w_main = vm_circuit.W_MAIN
    n_alpha = len(vm_circuit.transitions()) + len(vm_circuit._boundaries(Tlen))

    def make():
        t = Transcript(DOMAIN_STARK, backend=_bk.RECURSION)
        for r in col_roots[:w_main]:
            t.absorb(r)
        t.challenge(); t.challenge()                     # β, γ (aux_spec num_challenges = 2)
        for r in col_roots[w_main:]:
            t.absorb(r)
        for _ in range(n_alpha):
            t.challenge()                                # the constraint-combination α's
        return t
    return make


def prove_settlement_recursive(pre_contracts, calls, cursor, timestamp=0, beacons=None, block_hashes=None,
                               pre_bridge=None, num_queries=vm_circuit.stark.NUM_QUERIES, max_rows=None,
                               fold_outer_queries=vm_circuit.stark.NUM_QUERIES):
    """Segment the epoch (RECURSION backend) and fold every segment's FRI proof into one. Returns the settlement
    bundle plus {"fri_fold": recursion_proof, "fri_fold_public": public}."""
    from execnode.stark import backend as _bk, fri_verify
    bundle = prove_settlement(pre_contracts, calls, cursor, timestamp=timestamp, beacons=beacons,
                              block_hashes=block_hashes, pre_bridge=pre_bridge, num_queries=num_queries,
                              max_rows=max_rows, backend=_bk.RECURSION)
    fri_proofs = [seg["proof"]["fri"] for seg in bundle["segments"]]
    mk = [_stark_fri_transcript_factory(seg["proof"]) for seg in bundle["segments"]]
    fold, public = fri_verify.prove_fold(fri_proofs, num_queries_inner=num_queries,
                                         num_queries_outer=fold_outer_queries, mk_transcripts=mk)
    bundle["fri_fold"] = fold
    bundle["fri_fold_public"] = public
    return bundle


def verify_settlement_recursive(bundle):
    """Verify a recursively-aggregated settlement. Requires BOTH: (1) the FRI fold verifies (all segments'
    compositions proven low-degree in ONE verifier-authoritative recursion check), AND (2) the authoritative
    `verify_settlement` passes (full per-segment STARK verification + state-root chain). Returns
    (ok, reason, post_root). Both are required because the fold does not yet bind FRI roots to the state root."""
    from execnode.stark import fri_verify
    try:
        fold, public = bundle.get("fri_fold"), bundle.get("fri_fold_public")
        if fold is None or public is None:
            return False, "missing FRI fold", None
        mk = [_stark_fri_transcript_factory(seg["proof"]) for seg in bundle["segments"]]   # verifier rebuilds
        # PIN the fold's query strength to the protocol constant — the number of FRI spot-checks IS the
        # soundness, so it is never taken on the prover's word.
        nq = vm_circuit.stark.NUM_QUERIES
        okf, whyf = fri_verify.verify_fold(fold, public, mk_transcripts=mk, expect_inner=nq, expect_outer=nq)
        if not okf:
            return False, f"FRI fold invalid: {whyf}", None
        # cross-check the fold's public roots ARE the segments' actual FRI roots (so the fold isn't over some
        # other proofs) — the roots the aggregation attests must be the ones the sound path verifies.
        seg_roots = [tuple(tuple(d) for d in seg["proof"]["fri"]["roots"]) for seg in bundle["segments"]]
        fold_roots = [tuple(tuple(d) for d in pub["roots"]) for pub in public["publics"]]
        if seg_roots != fold_roots:
            return False, "FRI fold does not cover the segments' roots", None
        return verify_settlement(bundle)               # AUTHORITATIVE: full per-segment verify + chain
    except Exception as e:
        return False, f"malformed recursive settlement bundle: {e}", None


def prove_settlement_o1(pre_contracts, calls, cursor, timestamp=0, beacons=None, block_hashes=None,
                        pre_bridge=None, num_queries=vm_circuit.stark.NUM_QUERIES, max_rows=None,
                        outer_queries=vm_circuit.stark.NUM_QUERIES, comp_points_per_proof=None):
    """The AUTHORITATIVE recursive settlement (doc/zk-recursion.md §5 step 7 applied to the money path).
    Segments the epoch with ROW-COMMITTED recursion-backend proofs and produces ONE recursion bundle
    (fold + row-mode composition) that re-verifies EVERY segment STARK — so `verify_settlement_o1` never runs
    a per-segment stark.verify. `comp_points_per_proof` bounds each composition proof's trace (K·queries spot
    checks split across chunks). Returns the settlement bundle with {"recursive": ...} attached."""
    from execnode.stark import backend as _bk, recursive_verify as RV
    bundle = prove_settlement(pre_contracts, calls, cursor, timestamp=timestamp, beacons=beacons,
                              block_hashes=block_hashes, pre_bridge=pre_bridge, num_queries=num_queries,
                              max_rows=max_rows, backend=_bk.RECURSION, row_commit=True)
    proofs, bnds, pers = [], [], []
    for seg in bundle["segments"]:
        pub_calls, epoch_io = _epoch_pub_statement(seg)
        ok, why, periodic, bl = vm_circuit.epoch_statement(seg["proof"], pub_calls, epoch_io)
        if not ok:
            raise ValueError(f"segment statement: {why}")
        proofs.append(seg["proof"]); bnds.append(bl); pers.append(periodic)
    bundle["recursive"] = RV.prove(proofs, vm_circuit.transitions(), bnds, num_queries_outer=outer_queries,
                                   periodic_list=pers, num_challenges=2, num_aux=vm_circuit.NUM_AUX,
                                   comp_points_per_proof=comp_points_per_proof)
    bundle["comp_points_per_proof"] = comp_points_per_proof
    return bundle


def verify_settlement_o1(bundle, num_queries=None, outer_queries=None):
    """Verify an authoritative recursive settlement: the segment STATEMENTS (pre-root, io replay → post-root,
    chain) natively — cheap, no cryptography — and ONE recursion bundle in place of the K per-segment STARK
    verifications. The recursion bundle's soundness: the fold proves every segment's composition FRI is
    low-degree AND the row-mode composition half proves the Merkle-authenticated trace rows recompute the AIR
    composition to the (in-circuit-validated) FRI layer-0 values, at Fiat-Shamir positions the verifier
    derives itself — i.e. it re-establishes exactly what stark.verify establishes, per segment, in one check.
    `num_queries`/`outer_queries` are the VERIFIER'S policy (None = the protocol constant — never read from
    the bundle). Returns (ok, reason, post_root)."""
    from execnode.stark import recursive_verify as RV
    try:
        rb = bundle.get("recursive")
        if rb is None:
            return False, "missing recursion bundle", None
        nqi = int(num_queries) if num_queries is not None else vm_circuit.stark.NUM_QUERIES
        nqo = int(outer_queries) if outer_queries is not None else vm_circuit.stark.NUM_QUERIES
        # 1) segment statements + io replay + state-root chain (no per-segment proof checks)
        ok, why, post = verify_settlement(bundle, check_proofs=False)
        if not ok:
            return False, why, None
        # 2) rebuild every segment's public statement and verify the ONE recursion bundle against it
        pubs, bnds, pers = [], [], []
        for seg in bundle["segments"]:
            pub_calls, epoch_io = _epoch_pub_statement(seg)
            ok2, why2, periodic, bl = vm_circuit.epoch_statement(seg["proof"], pub_calls, epoch_io)
            if not ok2:
                return False, f"segment statement: {why2}", None
            pubs.append(RV.public_part(seg["proof"])); bnds.append(bl); pers.append(periodic)
        cpp = bundle.get("comp_points_per_proof")
        if cpp is not None and (not isinstance(cpp, int) or cpp < 1):
            return False, "bad comp chunk size", None
        okr, whyr = RV.verify(pubs, vm_circuit.transitions(), bnds, rb, num_queries_outer=nqo,
                              periodic_list=pers, num_challenges=2, num_aux=vm_circuit.NUM_AUX,
                              comp_points_per_proof=cpp, num_queries_inner=nqi)
        if not okr:
            return False, f"recursive verification failed: {whyr}", None
        return True, "ok (authoritative recursive)", post
    except Exception as e:
        return False, f"malformed recursive settlement bundle: {e}", None


def verify_settlement(bundle, num_queries=None, check_proofs=True):
    """Verify a segmented settlement: each segment is a valid epoch bundle AND they chain
    (pre_root_0 = bundle.pre_root, post_root_j = pre_root_{j+1}, post_root_K = bundle.post_root).
    Returns (ok, reason, post_root) — the chain is what proves the whole (unbounded) epoch with no
    re-execution and no trust in any single segment's boundary. `num_queries` is the VERIFIER'S policy
    (None = the protocol constant); `check_proofs=False` runs only the statement/replay/chain checks — for
    the recursive path, whose ONE bundle replaces the per-segment STARK verifications."""
    try:
        segs = bundle.get("segments")
        if not isinstance(segs, list) or not segs:
            return False, "no segments", None
        expect_pre = bundle["pre_root"]
        post = None
        for j, seg in enumerate(segs):
            if seg["pre_root"] != expect_pre:
                return False, f"segment {j} pre_root breaks the chain", None
            ok, why, post = verify_epoch(seg, num_queries=num_queries, check_proof=check_proofs)
            if not ok:
                return False, f"segment {j}: {why}", None
            if post != seg["post_root"]:
                return False, f"segment {j} post_root mismatch", None
            expect_pre = post
        if post != bundle["post_root"]:
            return False, "final post_root mismatch", None
        return True, "ok", post
    except Exception as e:
        return False, f"malformed settlement bundle: {e}", None


def _epoch_pub_statement(bundle):
    """(pub_calls, epoch_io) — an epoch bundle's public statement, reconstructed from the bundle's pre-state +
    public calls (the same reconstruction verify_epoch runs before checking the proof)."""
    import copy
    contracts = copy.deepcopy(bundle["pre_contracts"])
    cursor, ts = int(bundle["cursor"]), int(bundle.get("timestamp", 0))
    epoch_io = [tuple(int(x) for x in e) for e in bundle["io"]]
    pub_calls = []
    for call in bundle["calls"]:
        c = contracts.get(call["cid"])
        if not c or c.get("runtime") != "zkvm":
            raise ValueError("unknown contract")
        # `selfd` is DERIVED from the cid, never carried in the bundle: the verifier recomputes the callee's
        # own digest from public data, so a prover cannot choose what ACTX_SELF reads.
        pub_calls.append({"code": c["code"], "method": call["method"], "caller": call.get("caller", "epoch"),
                          "args": call.get("args", []), "value": int(call.get("value", 0)),
                          "cursor": cursor, "timestamp": ts, "asset": int(call.get("asset", 0)),
                          "selfd": runtimes.zkvm_addr_digest(call["cid"])})
    return pub_calls, epoch_io


def verify_epoch(bundle, num_queries=None, check_proof=True):
    """Verify an aggregated epoch bundle with NO contract re-execution. Returns (ok, reason, post_root):
    the pre-state must hash to pre_root; the SINGLE proof must verify for the ordered public calls +
    global I/O log; replaying that log advances each contract's storage to a state hashing to post_root.

    `num_queries` is the VERIFIER'S policy — None means the protocol constant (fri.NUM_QUERIES). It is NEVER
    read from the bundle: the query count IS the proof's soundness, so a prover must not choose it. Callers
    with a deliberate non-default policy (tests) pass it explicitly. `check_proof=False` skips only the STARK
    verification (the recursive settlement path re-verifies it inside ONE recursion bundle instead)."""
    try:
        import copy
        pre = bundle["pre_contracts"]
        if zkvm_root(pre) != bundle["pre_root"]:
            return False, "pre-state does not match pre_root", None
        nq = int(num_queries) if num_queries is not None else vm_circuit.stark.NUM_QUERIES
        pub_calls, epoch_io = _epoch_pub_statement(bundle)
        # 1) the single aggregated proof must verify for the whole ordered batch
        if check_proof:
            row_commit = "row_roots" in bundle["proof"]
            ok, why = vm_circuit.verify_epoch_calls(bundle["proof"], pub_calls, epoch_io, num_queries=nq,
                                                    row_commit=row_commit)
            if not ok:
                return False, f"epoch proof invalid: {why}", None
        # 2) split the global log back per call (by RET markers) and replay to recompute the post root
        contracts = copy.deepcopy(pre)
        segs, cur = [], []
        for e in epoch_io:
            cur.append(e)
            if e[0] == zkvm.IO_RET:
                segs.append(cur); cur = []
        if len(segs) != len(bundle["calls"]):
            return False, "io log call count mismatch", None
        for call, seg in zip(bundle["calls"], segs):
            c = contracts[call["cid"]]
            slots = {int(k): int(v) for k, v in (c["storage"].get("slots") or {}).items()}
            # with_assets=True so an asset-carrying log replays instead of failing closed. The storage
            # advance (new_slots) is identical either way — the asset `effects` (6th element) are ignored
            # here exactly as native `_pay` is, because the asset LEDGER is not part of this proof's root
            # (post_root binds contract storage; balances live in the records half it does not bind).
            ok2, _ret, new_slots, _pay, _chain, _effects = zkvm.replay_io(seg, slots, with_assets=True)
            if not ok2:
                return False, "log replay failed", None
            c["storage"] = {"slots": {str(k): v for k, v in sorted(new_slots.items())}}
        post = zkvm_root(contracts)
        if post != bundle["post_root"]:
            return False, "post-state does not match post_root", None
        return True, "ok", post
    except Exception as e:
        return False, f"malformed epoch bundle: {e}", None


# ---- settlement-seam integration ------------------------------------------------------------------
# There is NO node-local verifier callback any more. Settlement-proof authority lives ON-CHAIN: a
# `settle`-with-proof transaction carries a bundle produced by prove_settlement_o1 (below); every node
# verifies it deterministically at block-validation (ops.transaction_ops, the `settle` branch, calls
# verify_settlement_o1 at the protocol query strength) and records kv_ops.settlement_proven(ns, cursor,
# root). ops.settlement_ops.settlement_justified reads that committed marker — so a validity-proven root is
# justified identically on every node, with no _EPOCH_PROOFS cache to diverge and fork the chain.
