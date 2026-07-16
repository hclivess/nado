"""
IN-CIRCUIT io REPLAY (in-circuit statement rebuild, doc/zk-recursion.md §5c(i)) — the state half.

exec_state_bind binds the transition to the io NATIVELY (verifier derives net-updates, O(#io)). This does it
IN-CIRCUIT: it processes the epoch's io directly against the running sparse root — each SLOAD is a membership
proof (the read value is a member of the current root), each SSTORE a merkle-update proof (advance the root
old→new) — chaining pre_root → post_root. Every step is a RECURSION-committed proof (membership.py /
merkle_update.py), so the whole replay folds K→1 via recursive_verify → authoritative depth → O(1). No
net-update derivation, no whole-state merkle: the transition is bound to the exact io the epoch proof proved.

Cost is one proof per storage io entry (vs one per touched slot for the state_transition batch) — the direct-but-
heavier route; committing the io (io_commitment, like calls_commit) is what makes the verifier O(1) on top.
"""
from execnode.stark import (field as F, storage_tree as ST, merkle_update as MU, membership as MB,
                            exec_state_bind as ESB, backend as B, stark)
from execnode import zkvm


def prove_io_replay(pre_store, cid_io, depth, num_queries=stark.NUM_QUERIES, backend=None):
    """Replay `cid_io` (=[(cid, kind, slot, value)]) against `pre_store` IN-CIRCUIT. SLOAD → membership of the
    read value in the current root; SSTORE → merkle-update advancing the root. Returns {steps, roots, depth,
    num_queries}. `backend` (default RECURSION) makes the step proofs foldable. Mutates `pre_store` to post-state."""
    bk = backend or B.RECURSION
    roots, steps = [pre_store.root()], []
    for (cid, kind, slot, value) in cid_io:
        key = ESB.slot_key(cid, int(slot), depth)
        sibs = pre_store.path(key)
        dirs = [(key >> i) & 1 for i in range(depth)]
        cur = pre_store.get(key)
        if kind == zkvm.IO_SLOAD:
            proof, root = MB.prove_membership(int(value) % F.P, sibs, dirs, num_queries=num_queries, backend=bk)
            steps.append({"kind": "load", "value": int(value) % F.P, "proof": proof, "root": root})
            roots.append(pre_store.root())                       # read: root unchanged
        elif kind == zkvm.IO_SSTORE:
            proof, pre_root, post_root = MU.prove_update(cur, int(value) % F.P, sibs, dirs,
                                                         num_queries=num_queries, backend=bk)
            steps.append({"kind": "store", "old": cur, "new": int(value) % F.P, "proof": proof,
                          "pre_root": pre_root, "post_root": post_root})
            pre_store.set(key, int(value) % F.P)
            roots.append(pre_store.root())
        # non-storage io (PAY / BHASH / BEACON / RET) touches no state — skipped
    return {"steps": steps, "roots": roots, "depth": depth, "num_queries": num_queries}


def verify_io_replay(bundle, pre_root, post_root, num_queries=None, backend=None):
    """Verify the chained replay: every step proof verifies AND its roots chain pre_root → post_root. A SLOAD
    proof must fold its read value to the CURRENT root (so a lied read is caught); an SSTORE proof must advance
    the current root to the next. Returns (ok, reason)."""
    try:
        bk = backend or B.RECURSION
        nq = int(num_queries) if num_queries is not None else bundle["num_queries"]
        roots = bundle["roots"]
        if roots[0] != pre_root % F.P:
            return False, "replay pre_root != public pre_root"
        if roots[-1] != post_root % F.P:
            return False, "replay post_root != public post_root"
        if len(roots) != len(bundle["steps"]) + 1:
            return False, "root/step count mismatch"
        for i, step in enumerate(bundle["steps"]):
            cur, nxt = roots[i], roots[i + 1]
            if step["kind"] == "load":
                if step["root"] != cur or nxt != cur:            # read: proof folds to cur, root unchanged
                    return False, f"load step {i}: root mismatch"
                ok, why = MB.verify_membership(step["proof"], cur, lambda r: r == cur, num_queries=nq, backend=bk)
                if not ok:
                    return False, f"load step {i}: {why}"
            elif step["kind"] == "store":
                if step["pre_root"] != cur or step["post_root"] != nxt:
                    return False, f"store step {i}: root chain break"
                ok, why = MU.verify_update(step["proof"], step["old"], step["new"], cur, nxt,
                                           num_queries=nq, backend=bk)
                if not ok:
                    return False, f"store step {i}: {why}"
            else:
                return False, f"step {i}: unknown kind"
        return True, "io replay verified in-circuit (chain pre_root → post_root; every step re-verified)"
    except Exception as e:
        return False, f"malformed io replay: {e}"
