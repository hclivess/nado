"""RECORDS-HALF state transition — the missing piece of full-state settlement.

THE GAP THIS CLOSES. The settled root is `full_root_hex(kv, rec) = rnode(kv_root, rec_root)`: a KV half over
zkVM contract storage, and a RECORDS half over everything else the exec layer holds -- bridge balances,
dividend accruals, asset balances and metadata, delegated-spend allowances, withdrawals, the shielded pool
and field pool, outbox/inbox (execnode/exec_root.records_projection).

Settle-with-proof covers only the KV half. The L1 composition pins the SAME rec_hex into both the pre and
post root, so a proven span REQUIRES the records half to be unchanged (calls_commit's RECORDS-INERTNESS note,
enforced on-chain by `block_records_inert`). That allowlist is correct and load-bearing -- a span that really
did move records, proven with records FROZEN, would settle a root silently omitting those payouts, and L1's
settled pointer would diverge permanently from every honest exec node with no quorum to correct it.

But it means any epoch containing a bridge deposit, a dividend accrual, an asset transfer or a shielded
transfer CANNOT settle by proof at all. It falls back to quorum. That is the ceiling on the whole
state-proof line: "one proof settles the block" is currently true only of blocks that touch nothing but
contract storage.

THE OBSERVATION THAT MAKES THIS CHEAP. records_projection returns {position: value} -- exactly the shape the
KV half already uses. So the records half is a storage_tree.SparseStore like any other, and
state_transition.prove_transition proves its advance with no new AIR: the same per-key merkle-update chain,
the same recursion-committed proofs, the same K->1 foldability. Nothing here invents cryptography; it applies
the machinery already proven for the KV half to the half that was frozen.

WHAT IS STILL OPEN, stated plainly rather than implied: this proves that the records half ADVANCED from one
root to another over a stated update set. It does NOT yet prove that the update set is exactly what the
block's transactions imply -- the records analogue of exec_state_bind, which ties the KV updates to the
epoch's actual SSTOREs. Without that binding a prover can advance records to any state it likes, so this is
NOT yet sufficient to relax block_records_inert. Landing the binding is the next step, and until it does the
allowlist must stay exactly as strict as it is today.
"""
from execnode.stark import state_transition as SX, storage_tree as ST, field as F
from execnode import exec_root as ER


def records_store(st, depth=ER.DEPTH):
    """A SparseStore over the exec layer's records half at the given state."""
    return ST.SparseStore(depth, ER.records_projection(st))


def records_updates(pre_st, post_st, depth=ER.DEPTH):
    """The net records writes between two exec states, as [(key, new_value), ...] sorted by key.

    NET, not per-operation: settlement cares about where the half ENDED, and a key written twice inside the
    span costs one update. Sorted so the update list -- and therefore the proof -- is a pure function of the
    two states and not of iteration order, which is what makes two provers agree byte-for-byte.

    A key present in pre and absent in post is emitted as a write of 0, because that is exactly how
    SparseStore represents deletion (writing 0 deletes).
    """
    # DIFF THROUGH THE STORE, NOT THE RAW PROJECTION. SparseStore masks every key to `depth` bits
    # (key & ((1<<depth)-1)) and drops zero values. Diffing the raw projection instead lets the update list
    # and the store disagree the moment two record keys share their low `depth` bits -- the proof then
    # advances to a root nobody else computes. At the production depth (256, the full slot space) they never
    # collide, which is exactly what would have made this a latent bug rather than a visible one: it only
    # surfaces at a small depth, i.e. in tests. Building both sides through SparseStore makes the update list
    # agree with the tree by construction, at any depth.
    pre = ST.SparseStore(depth, ER.records_projection(pre_st)).values
    post = ST.SparseStore(depth, ER.records_projection(post_st)).values
    out = []
    for k in sorted(set(pre) | set(post)):
        old = int(pre.get(k, 0)) % F.P
        new = int(post.get(k, 0)) % F.P
        if old != new:
            out.append((int(k), new))
    return out


def prove_records_transition(pre_st, post_st, num_queries=None, outer_queries=None, fold=False,
                             depth=ER.DEPTH):
    """Prove the records half advanced pre_st -> post_st. Returns an ordinary transition bundle, so it folds,
    merges and verifies exactly like the KV half's."""
    store = records_store(pre_st, depth)
    updates = records_updates(pre_st, post_st, depth)
    nq = num_queries if num_queries is not None else SX.MU.stark.NUM_QUERIES
    oq = outer_queries if outer_queries is not None else nq
    tr = SX.prove_transition(store, updates, num_queries=nq, outer_queries=oq, fold=fold)
    tr["half"] = "records"
    return tr


def verify_records_transition(tr, pre_root, post_root, num_queries=None, outer_queries=None):
    """(ok, reason) — the records transition advances pre_root -> post_root."""
    try:
        if tr.get("half") != "records":
            return False, "not a records-half transition"
        return SX.verify_transition(tr, pre_root, post_root, num_queries=num_queries,
                                    outer_queries=outer_queries)
    except Exception as e:
        return False, f"malformed records transition: {type(e).__name__}: {e}"


def compose_full_root(kv_root, rec_root):
    """The settled root from both halves — the SAME composition L1 applies (exec_root.full_root_hex)."""
    return ER.full_root_hex(kv_root, rec_root)


def verify_full_transition(kv_tr, rec_tr, pre_full_hex, post_full_hex, num_queries=None,
                           outer_queries=None):
    """(ok, reason) for a FULL-state transition: both halves proven, composed with the same rnode(kv, rec)
    L1 uses, matching the claimed pre and post settled roots.

    Both halves are required even when one is empty. An absent half is not an unchanged half: a caller that
    may omit one could advance the other and leave the missing side's root to be whatever the verifier
    happens to have, which is precisely the divergence the records-inertness allowlist exists to prevent.
    An unchanged half proves an EMPTY update list, whose pre and post roots are equal -- cheap, and explicit.
    """
    try:
        kv_pre, kv_post = tuple(kv_tr["roots"][0]), tuple(kv_tr["roots"][-1])
        rec_pre, rec_post = tuple(rec_tr["roots"][0]), tuple(rec_tr["roots"][-1])
        if compose_full_root(kv_pre, rec_pre) != pre_full_hex:
            return False, "composed pre-root does not match the claimed settled pre-root"
        if compose_full_root(kv_post, rec_post) != post_full_hex:
            return False, "composed post-root does not match the claimed settled post-root"
        ok, why = SX.verify_transition(kv_tr, kv_pre, kv_post, num_queries=num_queries,
                                       outer_queries=outer_queries)
        if not ok:
            return False, f"kv half invalid: {why}"
        ok2, why2 = verify_records_transition(rec_tr, rec_pre, rec_post, num_queries=num_queries,
                                              outer_queries=outer_queries)
        if not ok2:
            return False, f"records half invalid: {why2}"
        return True, "ok"
    except Exception as e:
        return False, f"malformed full transition: {type(e).__name__}: {e}"
