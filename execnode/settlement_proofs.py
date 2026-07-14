"""
Epoch settlement proof (doc/zk-execution-proofs.md — Phase-2b) — the capstone that lets L1 accept a settled
zkVM state root because a PROOF says the ordered calls produce it, not because a bonded committee attested it.

The insight that makes this small: each call already carries a validity proof (execnode/stark/vm_circuit)
that binds (code, caller, args, context) to an AUTHENTICATED public I/O log. So proving a whole epoch's
STATE TRANSITION does NOT need a second giant in-circuit memory argument — it is the composition:

    verify every call's proof   →   replay its (now-trusted) log to advance storage   →   chain the roots

`prove_epoch` runs the calls in order, producing one per-call proof each and the pre/post zkVM state roots
(the SAME Merkle-leaf shape execnode/state.py commits, so the post root is exactly the state_root L1 settles
for the zkVM projection). `verify_epoch` checks it with NO re-execution: verify each proof, replay each log,
recompute the post root. What is NOT yet built (and is the honest remaining item) is SUCCINCT AGGREGATION —
folding the N per-call proofs into one O(1) proof via STARK recursion, so L1 verifies a single proof instead
of N. At NADO's volume N is tiny and L1 verifying N sub-second proofs is fine; recursion is the scale hedge.

Scope: this proves the zkVM-contract-storage projection of the state transition (the programmable part). The
other blob ops (bridge/dividend/shielded) already have their own L1-checkable proofs or arithmetic; a
full-state validity proof composes this with those and is future work, noted in the doc.
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


def prove_epoch(pre_contracts, calls, cursor, timestamp=0, beacons=None, block_hashes=None,
                pre_bridge=None, num_queries=vm_circuit.stark.NUM_QUERIES):
    """Prove a batch of zkVM calls as one epoch state transition. `pre_contracts` is the pre-state
    {cid: {"code", "storage": {"slots":{...}}, "runtime":"zkvm"}}; `calls` an ordered list of
    {cid, method, caller, args, value?}. Returns a self-contained bundle proving pre_root → post_root."""
    import copy
    contracts = copy.deepcopy(pre_contracts)
    bridge = dict(pre_bridge or {})
    registry = {}
    pre_root = zkvm_root(contracts)
    proven = []
    for i, call in enumerate(calls):
        cid, method = call["cid"], call["method"]
        c = contracts.get(cid)
        if not c or c.get("runtime") != "zkvm":
            raise ValueError(f"call {i}: no zkvm contract {cid}")
        caller = call.get("caller", "epoch")
        value = int(call.get("value", 0))
        cf, fargs = runtimes.zkvm_statement(caller, call.get("args", []), registry)
        slots = {int(k): int(v) for k, v in (c["storage"].get("slots") or {}).items()}
        if value > 0:
            bridge[cid] = bridge.get(cid, 0) + value        # escrow the call value into the contract
        proof, io, ret, _new = vm_circuit.prove_call(c["code"], method, cf, fargs, slots, value=value,
                                                     cursor=cursor, timestamp=timestamp, beacons=beacons,
                                                     block_hashes=block_hashes, num_queries=num_queries)
        # advance the committed storage by REPLAYING the proven log (no re-execution)
        ok, _ret, new_slots, payouts, _chain = zkvm.replay_io(io, slots)
        if not ok:
            raise ValueError(f"call {i}: proven log failed to replay")
        addr_payouts = [(registry[str(to)], amt) for to, amt in payouts if str(to) in registry]
        if len(addr_payouts) != len(payouts) or not _apply_payouts(bridge, cid, addr_payouts):
            raise ValueError(f"call {i}: unresolved or unaffordable payout")
        c["storage"] = {"slots": {str(k): v for k, v in sorted(new_slots.items())}}
        proven.append({"cid": cid, "method": method, "caller": caller, "args": call.get("args", []),
                       "value": value, "io": [list(e) for e in io], "proof": proof, "ret": str(ret)})
    return {"cursor": cursor, "timestamp": timestamp, "pre_root": pre_root,
            "post_root": zkvm_root(contracts), "calls": proven,
            "pre_contracts": {cid: {"code": c["code"], "storage": c["storage"], "runtime": "zkvm"}
                              for cid, c in pre_contracts.items() if c.get("runtime") == "zkvm"},
            "num_queries": num_queries}


def verify_epoch(bundle):
    """Verify an epoch bundle with NO contract re-execution. Returns (ok, reason, post_root). Checks: the
    pre-state hashes to pre_root; every call proof verifies for its stated (code, caller, args, context);
    replaying each proven log advances storage; the final storage hashes to post_root. A verifier trusts
    post_root as the settled zkVM root exactly when this returns ok."""
    try:
        import copy
        pre = bundle["pre_contracts"]
        if zkvm_root(pre) != bundle["pre_root"]:
            return False, "pre-state does not match pre_root", None
        contracts = copy.deepcopy(pre)
        cursor, ts = int(bundle["cursor"]), int(bundle.get("timestamp", 0))
        nq = int(bundle.get("num_queries", vm_circuit.stark.NUM_QUERIES))
        for i, call in enumerate(bundle["calls"]):
            cid = call["cid"]
            c = contracts.get(cid)
            if not c or c.get("runtime") != "zkvm":
                return False, f"call {i}: unknown contract", None
            cf, fargs = runtimes.zkvm_statement(call.get("caller", "epoch"), call.get("args", []), {})
            io = [tuple(int(x) for x in e) for e in call["io"]]
            ok, why = vm_circuit.verify_call(call["proof"], c["code"], call["method"], cf, fargs, io,
                                             value=int(call.get("value", 0)), cursor=cursor, timestamp=ts,
                                             num_queries=nq)
            if not ok:
                return False, f"call {i} proof invalid: {why}", None
            slots = {int(k): int(v) for k, v in (c["storage"].get("slots") or {}).items()}
            ok2, _ret, new_slots, _pay, _chain = zkvm.replay_io(io, slots)
            if not ok2:
                return False, f"call {i}: log replay failed", None
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
