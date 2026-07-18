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
    timestamp) — the leaf the calls-commitment chains. Deterministic; a verifier recomputes it from the call.
    cursor/timestamp come from the CALL dict when present (per-call execution context, the DA-binding form),
    else from the passed epoch-wide defaults (the legacy single-context form). Identical bytes on every layer:
    blake2b over a canonical list, so Python (L1/exec) and the Rust prover agree."""
    cur = int(call.get("cursor", cursor))
    ts = int(call.get("timestamp", timestamp))
    payload = ["call", str(call.get("cid", "")), str(call.get("method", "")),
               str(call.get("caller", "epoch")), [int(a) for a in call.get("args", [])],
               int(call.get("value", 0)), cur, ts]
    return int(blake2b_hash(payload), 16) % F.P


def block_calls(block, ns="default"):
    """The ORDERED execution calls a namespace's `blob` txs in `block` carry (op == 'call') — the DETERMINISTIC
    bridge that lets L1 (the settlement VERIFIER) and the exec node (the PROVER) build the IDENTICAL calls list
    from the same on-chain block, so a settle-with-proof's calls_commitment can be BOUND to the real DA calldata
    (a prover cannot substitute fabricated calls). Fields exactly as apply_blob reads them: cid = data.contract,
    method = data.method, args = data.args, value = data.value; caller = the blob tx's L1 sender; and the
    execution context cursor = block number, timestamp = block timestamp. ALL op=='call' blobs are included —
    even ones that will skip/revert in the VM — so the commitment binds the RAW on-chain calldata; the proof's
    state transition treats a skip/revert as a no-op (matching live apply). Deploys/other ops are excluded
    (they don't move the kv half a bound-epoch proof settles)."""
    h = int(block.get("block_number", 0))
    ts = int(block.get("block_timestamp", 0))
    calls = []
    for tx in block.get("block_transactions", []):
        if tx.get("recipient") != "blob":
            continue
        d = tx.get("data")
        if not isinstance(d, dict) or d.get("op") != "call":
            continue
        if d.get("ns", "default") != ns:
            continue
        calls.append({"cid": d.get("contract"), "method": d.get("method"), "caller": tx.get("sender"),
                      "args": d.get("args", []), "value": int(d.get("value", 0) or 0),
                      "cursor": h, "timestamp": ts})
    return calls


def da_calls_commitment(blocks, ns="default"):
    """The calls-commitment L1 EXPECTS for a settlement over `blocks` (ascending) in namespace `ns`: fold the
    per-call leaves of every block's blob calls, in block-then-tx order, from IV. A settle-with-proof over that
    span is bound to the DA iff its calls_commitment equals this — computed on-chain, independent of the prover."""
    node = alghash.IV
    for blk in blocks:
        for call in block_calls(blk, ns):
            node = alghash.merkle_node(node, call_leaf(call))
    return node


def verify_calls_bound_to_da(proof, ns, prev_cursor, cursor, get_block):
    """DA-BINDING GATE (settle-with-proof): every segment's calls_commitment must equal L1's OWN
    da_calls_commitment over the on-chain blob calldata it claims to settle, so a prover cannot substitute a
    fabricated call sequence for the real one. The segments partition the settled span (prev_cursor, cursor] by
    their end cursor (exec_cursor == L1 height in production, so a segment ending at C settles L1 blocks
    (prev, C]). `get_block(h)` returns the L1 block dict at height h or falsy. Returns (ok, reason)."""
    segs = proof.get("segments") or []
    if not segs:
        return False, "no segments to bind"
    lo = int(prev_cursor)
    for j, seg in enumerate(segs):
        cc = seg.get("calls_commitment")
        if cc is None:
            return False, f"segment {j} carries no calls_commitment (unbound to the DA calldata)"
        seg_end = int(seg.get("cursor", cursor))
        if not (lo < seg_end <= int(cursor)):
            return False, f"segment {j} cursor {seg_end} is outside the settled span ({lo}, {cursor}]"
        blocks = []
        for h in range(lo + 1, seg_end + 1):
            blk = get_block(h)
            if not blk:
                return False, f"block {h} in the settled span is unavailable — cannot bind calls to DA"
            blocks.append(blk)
        if int(cc) % F.P != da_calls_commitment(blocks, ns) % F.P:
            return False, f"segment {j} calls_commitment does not match the on-chain DA calldata (fabricated calls)"
        lo = seg_end
    if lo != int(cursor):
        return False, f"segments do not cover the whole settled span (reached {lo}, expected {cursor})"
    return True, "calls bound to DA"


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
