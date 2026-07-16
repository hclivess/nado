"""
CALLS COMMITMENT (state-root binding / O(1) settlement, doc/zk-recursion.md §5b) — the O(1) public input for an
epoch's calls.

verify_bound_epoch still reads the epoch's K calls (O(K)) to rebuild the public statement. To make settlement's
public input O(1), the K calls collapse to ONE field element: c_0 = IV; c_i = merkle_node(c_{i-1}, leaf(call_i));
commitment = c_K, over the ORDERED calls. That is exactly membership.py's leaf→root fold with the call leaves as
the (all-left) siblings, so the commitment is PROVABLE + FOLDABLE (membership.prove_membership) — the in-circuit
proof that a call sequence chains to the commitment composes into the settlement recursion. A verifier then holds
only (calls_commitment, sparse_pre_root, sparse_post_root) — three field elements — and checks calls_commitment
against the on-chain calldata's running commitment (O(1)) instead of processing every call.

alghash merkle_node so it folds in the recursion layer. Binding the commitment to the exec proof's calls (so the
proof is FOR the committed calls) + proving the statement rebuild in-circuit is the remaining succinctness step.
"""
from execnode.stark import field as F, alghash, membership
from hashing import blake2b_hash


def call_leaf(call, cursor=0, timestamp=0):
    """A field element committing to ONE call's PUBLIC fields (cid, method, caller, args, value, cursor,
    timestamp) — the leaf the calls-commitment chains. Deterministic; a verifier recomputes it from the call."""
    payload = ["call", str(call.get("cid", "")), str(call.get("method", "")),
               str(call.get("caller", "epoch")), [int(a) for a in call.get("args", [])],
               int(call.get("value", 0)), int(cursor), int(timestamp)]
    return int(blake2b_hash(payload), 16) % F.P


def leaves(calls, cursor=0, timestamp=0):
    return [call_leaf(c, cursor, timestamp) for c in calls]


def io_leaf(cid, kind, slot, value):
    """A field element committing to one io entry (cid, kind, slot, value) — the leaf the io-commitment chains."""
    return int(blake2b_hash(["io", str(cid), int(kind), int(slot), int(value)]), 16) % F.P


def io_commitment(cid_io):
    """The epoch's ordered io as ONE field element (the O(1) io public input). Domain-separated from the calls
    commitment by starting the chain at merkle_node(IV, IV) and using io-prefixed leaves, so the two chains
    never collide. Provable + foldable the same way (a membership fold over the io leaves)."""
    node = alghash.merkle_node(alghash.IV, alghash.IV)          # io-domain start (distinct from the calls IV)
    for (cid, kind, slot, value) in cid_io:
        node = alghash.merkle_node(node, io_leaf(cid, kind, slot, value))
    return node


def calls_commitment(calls, cursor=0, timestamp=0):
    """The epoch's ordered calls as ONE field element: fold IV through merkle_node(node, leaf_i). Equal to
    membership.merkle_root_from_path(IV, leaves, [0]*K), hence provable + foldable via prove_calls_commitment."""
    node = alghash.IV
    for lf in leaves(calls, cursor, timestamp):
        node = alghash.merkle_node(node, lf)
    return node


def prove_calls_commitment(calls, cursor=0, timestamp=0, num_queries=membership.stark.NUM_QUERIES, backend=None):
    """IN-CIRCUIT proof that `calls` chain to their commitment — a membership fold of IV through the call leaves
    (all left, dirs=0). `backend=backend.RECURSION` makes it foldable into the settlement recursion. Returns
    (proof, commitment). (The leaves are private witness; binding them to the exec proof's calls is the
    succinctness integration.)"""
    ls = leaves(calls, cursor, timestamp)
    if not ls:
        return None, alghash.IV
    proof, root = membership.prove_membership(alghash.IV, ls, [0] * len(ls), num_queries=num_queries,
                                              backend=backend)
    return proof, root


def verify_calls_commitment(proof, commitment, k, num_queries=membership.stark.NUM_QUERIES, backend=None):
    """Verify an in-circuit calls-commitment proof folds to `commitment` over exactly `k` calls (depth = k)."""
    if proof is None:
        return (k == 0 and commitment == alghash.IV), "empty"
    if proof.get("D") != k:
        return False, "commitment depth != call count"
    return membership.verify_membership(proof, commitment, lambda r: r == commitment % F.P, backend=backend,
                                        num_queries=num_queries)
