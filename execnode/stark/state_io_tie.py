"""
STATE-side io tie (doc/zk-recursion.md §5c piece 3) — tie the BOUND io columns to the state transition.

bound_epoch_o1 binds the exec's committed io to the replay's io columns (ctr, kind, slot, value). io_replay
advances pre_root→post_root by a position-pinned merkle-update per storage entry, at key = slot_key(cid, slot).
The last leg proves those two agree WITHOUT the verifier recomputing slot_key per entry: for each storage io
entry, `slot_key_air` proves key = slot_key(cid, slot) (the position, in-circuit), and the merkle-update's pinned
DIRs are that key's bits — so the update provably lands at the slot the bound io names, with the bound value.

One slot_key derivation proof + one merkle-update proof per storage entry; both are RECURSION-committed, so the
whole set folds K→1 (recursive_verify / hetero) → O(1). This module proves + verifies the position tie; the
value/kind of each step are already the io_replay step boundaries (new = value, kind), bound to the io columns by
io_bind. Together: exec ⟶ io_bind ⟶ io columns ⟶ (slot_key_air positions + io_replay updates) ⟶ post_root.
"""
from execnode.stark import (field as F, slot_key_air as SK, exec_state_bind as ESB, backend as B, stark)
from execnode import zkvm


def prove_positions(cid_io, depth, num_queries=stark.NUM_QUERIES, backend=None):
    """For every STORAGE io entry prove key = slot_key(cid, slot) via the in-circuit sponge. Returns a list of
    {cid, slot, kind, value, key, digest, proof} in io order (the same order io_replay processes)."""
    b = backend or B.RECURSION
    out = []
    for (cid, kind, slot, value) in cid_io:
        if kind not in (zkvm.IO_SLOAD, zkvm.IO_SSTORE):
            continue
        proof, digest = SK.prove(cid, int(slot), num_queries=num_queries, backend=b)
        key = int(digest) & ((1 << depth) - 1)
        out.append({"cid": cid, "slot": int(slot), "kind": kind, "value": int(value) % F.P,
                    "key": key, "digest": int(digest), "proof": proof})
    return out


def verify_positions(positions, replay_steps, depth, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify the position tie: (1) each entry's slot_key derivation proof holds for its PUBLIC (cid, slot) and
    yields `digest`; (2) key = digest truncated to `depth` bits; (3) that key is exactly the position the matching
    io_replay step landed at (step['key']) — so the bound io's slot IS the tree position updated. Returns
    (ok, reason). The (cid, slot) are public here (calldata order); the O(1) form binds them to the io columns via
    io_bind and folds the K derivation/update proofs into one bundle."""
    try:
        b = backend or B.RECURSION
        if len(positions) != len(replay_steps):
            return False, "position/step count mismatch"
        for i, (pos, step) in enumerate(zip(positions, replay_steps)):
            okd, whyd = SK.verify(pos["proof"], pos["cid"], pos["slot"], pos["digest"],
                                  num_queries=num_queries, backend=b)
            if not okd:
                return False, f"entry {i}: slot_key derivation failed: {whyd}"
            key = int(pos["digest"]) & ((1 << depth) - 1)
            if key != pos["key"]:
                return False, f"entry {i}: key != truncated digest"
            if int(step["key"]) != key:
                return False, f"entry {i}: replay step position != proven slot_key(cid, slot)"
            # cross-check the derivation is really for this (cid, slot): recompute the native slot_key
            if key != ESB.slot_key(pos["cid"], pos["slot"], depth):
                return False, f"entry {i}: proven key != native slot_key (statement mismatch)"
            # tie the VALUE and KIND too: the step must apply exactly this io entry's (kind, value)
            want_kind = "load" if pos["kind"] == zkvm.IO_SLOAD else "store"
            if step.get("kind") != want_kind:
                return False, f"entry {i}: replay step kind != io kind"
            if int(step["new"]) % F.P != pos["value"]:
                return False, f"entry {i}: replay step value != io value"
        return True, "state positions+values tied to (cid, slot, value) in-circuit (every step applies its io entry)"
    except Exception as e:
        return False, f"malformed position tie: {e}"
