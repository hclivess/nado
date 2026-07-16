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
from execnode.stark import (field as F, storage_tree as ST, merkle_update as MU, exec_state_bind as ESB,
                            backend as B, stark, recursive_verify as RV)
from execnode import zkvm


def prove_io_replay(pre_store, cid_io, depth, num_queries=stark.NUM_QUERIES, backend=None, fold=False,
                    outer_queries=stark.NUM_QUERIES):
    """Replay `cid_io` (=[(cid, kind, slot, value)]) against `pre_store` IN-CIRCUIT. Every storage step is a
    POSITION-PINNED merkle-update at slot_key(cid, slot): a SLOAD is a no-op update (old = new = the read value)
    that proves that value sits at that slot in the current root; an SSTORE advances the root old → new. The
    pinned position + value bind the step to the exact (slot, value) the io claims. Returns {steps, roots, depth,
    num_queries}. `backend` (default RECURSION) makes the step proofs foldable. Mutates `pre_store` to post-state."""
    bk = backend or B.RECURSION
    roots, steps = [pre_store.root()], []
    for (cid, kind, slot, value) in cid_io:
        if kind not in (zkvm.IO_SLOAD, zkvm.IO_SSTORE):
            continue                                             # PAY / BHASH / BEACON / RET touch no state
        key = ESB.slot_key(cid, int(slot), depth)
        sibs = pre_store.path(key)
        dirs = [(key >> i) & 1 for i in range(depth)]
        cur = pre_store.get(key)
        v = int(value) % F.P
        if kind == zkvm.IO_SLOAD:
            proof, pre_r, post_r = MU.prove_update(v, v, sibs, dirs, num_queries=num_queries, backend=bk)
            steps.append({"kind": "load", "key": key, "old": v, "new": v, "dirs": dirs, "proof": proof,
                          "pre_root": pre_r, "post_root": post_r})
            roots.append(pre_store.root())                       # read: value==cur ⇒ root unchanged
        else:                                                    # SSTORE
            proof, pre_r, post_r = MU.prove_update(cur, v, sibs, dirs, num_queries=num_queries, backend=bk)
            steps.append({"kind": "store", "key": key, "old": cur, "new": v, "dirs": dirs, "proof": proof,
                          "pre_root": pre_r, "post_root": post_r})
            pre_store.set(key, v)
            roots.append(pre_store.root())
    out = {"steps": steps, "roots": roots, "depth": depth, "num_queries": num_queries}
    if fold and steps:
        # every step is the SAME merkle-update AIR, so the K step proofs fold K->1 via recursive_verify -> the
        # whole replay is re-verified by ONE bundle (the state-binding crypto becomes O(1)).
        proofs = [s["proof"] for s in steps]
        bnds = [MU._boundaries(s["old"], s["new"], s["pre_root"], s["post_root"], s["dirs"], depth) for s in steps]
        per = MU._periodic(proofs[0]["T"], depth)
        out["fold_bnds"] = bnds
        out["fold_periodic"] = per
        out["outer_queries"] = outer_queries
        out["fold_bundle"] = RV.prove(proofs, MU._transitions(), bnds, num_queries_outer=outer_queries, periodic=per)
    return out


def verify_io_replay(bundle, pre_root, post_root, num_queries=None, backend=None):
    """Verify the chained replay: every step is a position-pinned merkle-update that verifies AND whose roots
    chain pre_root → post_root. A SLOAD (old = new) leaves the root unchanged and proves the value at its slot; a
    SSTORE advances it. A wrong value/position (the pinned boundaries) or a broken chain is caught. Returns
    (ok, reason)."""
    try:
        bk = backend or B.RECURSION
        nq = int(num_queries) if num_queries is not None else bundle["num_queries"]
        roots = bundle["roots"]
        if roots[0] != pre_root % F.P:
            return False, "replay pre_root != public pre_root"
        if roots[-1] != post_root % F.P:
            return False, "replay post_root != public post_root"
        steps = bundle["steps"]
        depth = bundle["depth"]
        if len(roots) != len(steps) + 1:
            return False, "root/step count mismatch"
        # chain check + verifier-rebuilt per-step boundaries (nothing constraint-shaped taken from the proof)
        bnds = []
        for i, step in enumerate(steps):
            cur, nxt = roots[i], roots[i + 1]
            if step["kind"] == "load" and nxt != cur:
                return False, f"load step {i}: a read must not change the root"
            if step["pre_root"] != cur or step["post_root"] != nxt:
                return False, f"step {i}: root chain break"
            bnds.append(MU._boundaries(step["old"], step["new"], cur, nxt, step["dirs"], depth))
        if "fold_bundle" in bundle:                              # O(1) crypto: ONE recursion bundle re-verifies all K
            pubs = [RV.public_part(s["proof"]) for s in steps]
            per = MU._periodic(steps[0]["proof"]["T"], depth)
            okr, whyr = RV.verify(pubs, MU._transitions(), bnds, bundle["fold_bundle"],
                                  num_queries_outer=bundle["outer_queries"], periodic=per, num_queries_inner=nq)
            if not okr:
                return False, f"folded replay failed: {whyr}"
        else:
            for i, step in enumerate(steps):
                ok, why = MU.verify_update(step["proof"], step["old"], step["new"], roots[i], roots[i + 1],
                                           step["dirs"], num_queries=nq, backend=bk)
                if not ok:
                    return False, f"step {i}: {why}"
        return True, "io replay verified in-circuit (chain pre_root → post_root; every step re-verified)"
    except Exception as e:
        return False, f"malformed io replay: {e}"
