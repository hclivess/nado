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


def _run_call(contracts, bridge, registry, call, i, cursor, timestamp, beacons, block_hashes, want_rows):
    """Execute ONE call against the mutable (contracts, bridge, registry): advance storage, resolve payouts,
    and return (epoch_call, public_call, rows). `rows` (the executed step count = trace rows this call adds,
    computed only when want_rows) is what the segmenter packs against MAX_T. Raises on revert/bad payout —
    the same conditions that make the call unprovable."""
    cid, method = call["cid"], call["method"]
    c = contracts.get(cid)
    if not c or c.get("runtime") != "zkvm":
        raise ValueError(f"call {i}: no zkvm contract {cid}")
    caller = call.get("caller", "epoch")
    value = int(call.get("value", 0))
    cf, fargs = runtimes.zkvm_statement(caller, call.get("args", []), registry)
    slots = {int(k): int(v) for k, v in (c["storage"].get("slots") or {}).items()}
    if value > 0:
        bridge[cid] = bridge.get(cid, 0) + value
    res = zkvm.run(c["code"], method, cf, fargs, slots, value=value, cursor=cursor, timestamp=timestamp,
                   beacons=beacons, block_hashes=block_hashes, witness=want_rows)
    ok, _ret, new_slots, io = res[:4]
    if not ok:
        raise ValueError(f"call {i} reverted — nothing to prove")
    rows = len(res[4]) if want_rows else 0
    payouts = [(registry[str(to)], amt) for k, to, amt in io if k == zkvm.IO_PAY and amt > 0
               and str(to) in registry]
    if sum(1 for k, to, amt in io if k == zkvm.IO_PAY and amt > 0) != len(payouts) \
            or not _apply_payouts(bridge, cid, payouts):
        raise ValueError(f"call {i}: unresolved or unaffordable payout")
    c["storage"] = {"slots": {str(k): v for k, v in sorted(new_slots.items())}}
    epoch_call = {"code": c["code"], "method": method, "caller_f": cf, "args_f": fargs,
                  "caller": caller, "args": call.get("args", []), "value": value, "cursor": cursor,
                  "timestamp": timestamp, "beacons": beacons, "block_hashes": block_hashes, "slots": slots}
    public_call = {"cid": cid, "method": method, "caller": caller, "args": call.get("args", []),
                   "value": value}
    return epoch_call, public_call, rows


def prove_epoch(pre_contracts, calls, cursor, timestamp=0, beacons=None, block_hashes=None,
                pre_bridge=None, num_queries=vm_circuit.stark.NUM_QUERIES, backend=None):
    """Prove a batch of zkVM calls as ONE aggregated epoch proof. `pre_contracts` is the pre-state
    {cid: {"code", "storage": {"slots":{...}}, "runtime":"zkvm"}}; `calls` an ordered list of
    {cid, method, caller, args, value?}. Returns a self-contained bundle: a SINGLE proof binding
    pre_root → post_root over the whole batch. Raises ValueError if the batch exceeds one trace — use
    prove_settlement for unbounded epochs (it segments automatically).

    `backend` (doc/zk-recursion.md): None/blake2b is the fast native-hash proof L1 verifies directly;
    pass the alghash2 backend to produce a RECURSION-READY proof (field-native verification), the hybrid-wrap
    inner layer a fold circuit consumes. verify_epoch reads the hash from the proof, so no need to thread it."""
    import copy
    contracts = copy.deepcopy(pre_contracts)
    bridge = dict(pre_bridge or {})
    registry = {}
    pre_root = zkvm_root(contracts)
    epoch_calls, public_calls = [], []
    for i, call in enumerate(calls):
        ec, pc, _ = _run_call(contracts, bridge, registry, call, i, cursor, timestamp, beacons,
                              block_hashes, want_rows=False)
        epoch_calls.append(ec); public_calls.append(pc)
    proof, epoch_io, _per = vm_circuit.prove_epoch_calls(epoch_calls, num_queries=num_queries, backend=backend)
    return {"cursor": cursor, "timestamp": timestamp, "pre_root": pre_root,
            "post_root": zkvm_root(contracts), "calls": public_calls,
            "io": [list(e) for e in epoch_io], "proof": proof,
            "pre_contracts": {cid: {"code": c["code"], "storage": c["storage"], "runtime": "zkvm"}
                              for cid, c in pre_contracts.items() if c.get("runtime") == "zkvm"},
            "num_queries": num_queries}


def prove_settlement(pre_contracts, calls, cursor, timestamp=0, beacons=None, block_hashes=None,
                     pre_bridge=None, num_queries=vm_circuit.stark.NUM_QUERIES, max_rows=None, backend=None):
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
        # peek the row cost WITHOUT mutating committed state yet: run on a scratch copy
        peek = copy.deepcopy({call["cid"]: c}) if c else {}
        _ec, _pc, rows = _run_call(peek, dict(bridge), dict(registry), call, i, cursor, timestamp,
                                   beacons, block_hashes, want_rows=True)
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
        # advance the REAL committed state so the next call (and the next segment's pre-state) chains
        _run_call(contracts, bridge, registry, call, i, cursor, timestamp, beacons, block_hashes,
                  want_rows=False)
    boundaries.append((start, len(calls)))
    # pass 2: prove each segment from the chained pre-state
    contracts = copy.deepcopy(pre_contracts)
    bridge2 = dict(pre_bridge or {})
    segments = []
    for (lo, hi) in boundaries:
        seg_calls = calls[lo:hi]
        bundle = prove_epoch(contracts, seg_calls, cursor, timestamp=timestamp, beacons=beacons,
                             block_hashes=block_hashes, pre_bridge=bridge2, num_queries=num_queries,
                             backend=backend)
        segments.append(bundle)
        # advance contracts + bridge to this segment's post-state (replay is cheaper than re-running)
        reg = {}
        for j, call in enumerate(seg_calls):
            _run_call(contracts, bridge2, reg, call, lo + j, cursor, timestamp, beacons, block_hashes, False)
    return {"cursor": cursor, "timestamp": timestamp, "pre_root": pre_root,
            "post_root": zkvm_root(contracts), "segments": segments, "num_segments": len(segments)}


def verify_settlement(bundle):
    """Verify a segmented settlement: each segment is a valid epoch bundle AND they chain
    (pre_root_0 = bundle.pre_root, post_root_j = pre_root_{j+1}, post_root_K = bundle.post_root).
    Returns (ok, reason, post_root) — the chain is what proves the whole (unbounded) epoch with no
    re-execution and no trust in any single segment's boundary."""
    try:
        segs = bundle.get("segments")
        if not isinstance(segs, list) or not segs:
            return False, "no segments", None
        expect_pre = bundle["pre_root"]
        post = None
        for j, seg in enumerate(segs):
            if seg["pre_root"] != expect_pre:
                return False, f"segment {j} pre_root breaks the chain", None
            ok, why, post = verify_epoch(seg)
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


def verify_epoch(bundle):
    """Verify an aggregated epoch bundle with NO contract re-execution. Returns (ok, reason, post_root):
    the pre-state must hash to pre_root; the SINGLE proof must verify for the ordered public calls +
    global I/O log; replaying that log advances each contract's storage to a state hashing to post_root."""
    try:
        import copy
        pre = bundle["pre_contracts"]
        if zkvm_root(pre) != bundle["pre_root"]:
            return False, "pre-state does not match pre_root", None
        cursor, ts = int(bundle["cursor"]), int(bundle.get("timestamp", 0))
        nq = int(bundle.get("num_queries", vm_circuit.stark.NUM_QUERIES))
        contracts = copy.deepcopy(pre)
        epoch_io = [tuple(int(x) for x in e) for e in bundle["io"]]
        # 1) the single aggregated proof must verify for the whole ordered batch
        pub_calls = []
        for call in bundle["calls"]:
            c = contracts.get(call["cid"])
            if not c or c.get("runtime") != "zkvm":
                return False, "unknown contract", None
            pub_calls.append({"code": c["code"], "method": call["method"], "caller": call.get("caller", "epoch"),
                              "args": call.get("args", []), "value": int(call.get("value", 0)),
                              "cursor": cursor, "timestamp": ts})
        ok, why = vm_circuit.verify_epoch_calls(bundle["proof"], pub_calls, epoch_io, num_queries=nq)
        if not ok:
            return False, f"epoch proof invalid: {why}", None
        # 2) split the global log back per call (by RET markers) and replay to recompute the post root
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
            ok2, _ret, new_slots, _pay, _chain = zkvm.replay_io(seg, slots)
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
_EPOCH_PROOFS = {}          # (ns, cursor) -> verified post_root  (populated as bundles arrive + verify)


def register_epoch_proof(ns, bundle):
    """Verify an epoch bundle and, if valid, record its (ns, cursor)->post_root so the installed settlement
    verifier can justify that root. Returns (ok, reason). This is what an exec node calls when it receives a
    settlement proof for its namespace (the transport — a blob op or a gossip endpoint — is separate)."""
    ok, why, post_root = verify_epoch(bundle)
    if ok:
        _EPOCH_PROOFS[(ns, int(bundle["cursor"]))] = post_root
    return ok, why


def settlement_verifier(zkvm_root_of_state):
    """Build the fn(ns, cursor, state_root)->bool to hand to ops.settlement_ops.set_settlement_verifier.
    `zkvm_root_of_state(ns, cursor)` returns the zkVM sub-root L1 expects at that (ns, cursor) — the proof
    justifies the settled root iff a verified epoch bundle's post_root matches it. (Full-state settlement
    composes this with proofs for the other op families; see the module docstring.)"""
    def _verify(ns, cursor, state_root):
        want = _EPOCH_PROOFS.get((ns, int(cursor)))
        return want is not None and want == zkvm_root_of_state(ns, int(cursor))
    return _verify
