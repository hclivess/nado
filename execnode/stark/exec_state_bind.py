"""
Bind a state-transition proof to the EPOCH's writes (state-root binding, doc/zk-recursion.md §5b piece (b)).

state_transition.py proves that a set of (key, old, new) updates turns pre_root into post_root. On its own that
could be ANY set of updates; this binds them to the epoch's ACTUAL storage writes so the transition provably IS
the epoch's transition. The epoch's public io log (SLOAD/SSTORE per call — execnode/zkvm.replay_io) determines
the NET change of every touched (cid, slot): its old value (the pre-state) and its final value (last write).
`net_updates` derives exactly that ordered set; `bind_and_verify` requires the transition to prove that set and
nothing else, then verifies it. The io itself is proven correct by the epoch STARK, so binding the transition to
the io binds it to a real execution.

This is the VERIFIER-side binding (native, O(#io) — the cost of reading the calldata, which L1 pays anyway); an
in-circuit LogUp that folds the derivation into the proof (so verify is O(1)) is the succinctness step on top.
Key(cid, slot) maps a contract slot to a sparse-tree position deterministically.
"""
from execnode.stark import field as F, alghash as A
from hashing import blake2b_hash

DOM_KVPOS = 5                                    # alghash domain tag for slot positions (disjoint from 1..4)


def cid_limbs(cid):
    """A contract id as 8×32-bit field limbs — the alghash-friendly encoding of its 256-bit id. Deterministic;
    a hex cid decodes directly, anything else is blake2b-folded first so any id maps into the field cleanly."""
    try:
        n = int(str(cid), 16)
    except ValueError:
        n = int(blake2b_hash(["cid", str(cid)]), 16)
    return [(n >> (32 * i)) & 0xFFFFFFFF for i in range(8)]


def slot_key(cid, slot, depth):
    """Deterministic sparse-tree position for a contract slot, via ALGHASH so the (cid, slot) → position map is
    ARITHMETIZATION-FRIENDLY (provable in-circuit — the replay proves `key = slot_key(cid, slot)` cheaply, closing
    the fold-layer io binding). key = alghash.hashn([DOM_KVPOS, cid limbs…, slot]) truncated to `depth` bits; a
    real deployment uses depth ~ 256 so distinct (cid, slot) never share a leaf."""
    h = A.hashn([DOM_KVPOS, *cid_limbs(cid), int(slot) % F.P])
    return int(h) & ((1 << depth) - 1)


def net_updates(pre_get, cid_io, depth):
    """Derive the ordered NET updates an epoch makes to storage, from its io. `pre_get(cid, slot) -> value` is
    the pre-state read; `cid_io` is the epoch's io as [(cid, kind, slot, value), ...] in execution order
    (IO_SLOAD=1 read, IO_SSTORE=2 write, value 0 = delete). Returns [(key, old, new), ...] — one entry per
    (cid, slot) whose FINAL value differs from its pre-state, in first-touch order, with old = pre-state value,
    new = final value, key = slot_key(cid, slot, depth). SLOADs are consistency-checked against the running
    value (as replay_io does), so a lied read is caught here too."""
    order, cur, pre = [], {}, {}
    for (cid, kind, slot, value) in cid_io:
        ck = (str(cid), int(slot))
        if ck not in cur:
            pv = int(pre_get(cid, slot)) % F.P
            cur[ck] = pv; pre[ck] = pv
            order.append(ck)
        if kind == 1:                                    # IO_SLOAD — must match the running value
            if cur[ck] != int(value) % F.P:
                raise ValueError(f"io read of {ck} = {value} contradicts current {cur[ck]}")
        elif kind == 2:                                  # IO_SSTORE — 0 clears the slot
            cur[ck] = int(value) % F.P
        # other io kinds (PAY/BHASH/BEACON/RET) do not touch storage
    updates = []
    for ck in order:
        if cur[ck] != pre[ck]:                           # only slots whose NET value changed are updates
            cid, slot = ck
            updates.append((slot_key(cid, slot, depth), pre[ck], cur[ck]))
    return updates


def bind_and_verify(tr, pre_root, post_root, pre_get, cid_io, depth, num_queries=None, outer_queries=None):
    """Verify a state transition AND that its updates are EXACTLY the epoch's net writes. (1) derive the net
    updates from the (proven) io; (2) require tr.updates == that set, in order; (3) verify the transition proves
    pre_root → post_root (state_transition.verify_transition). All three ⇒ the transition is THIS epoch's, not an
    arbitrary one. Returns (ok, reason)."""
    from execnode.stark import state_transition as SX
    try:
        want = net_updates(pre_get, cid_io, depth)
        got = [(int(k), int(o) % F.P, int(n) % F.P) for (k, o, n) in tr.get("updates", [])]
        want = [(int(k), int(o) % F.P, int(n) % F.P) for (k, o, n) in want]
        if got != want:
            return False, f"transition updates do not match the epoch's net writes ({len(got)} vs {len(want)})"
        return SX.verify_transition(tr, pre_root, post_root, num_queries=num_queries, outer_queries=outer_queries)
    except Exception as e:
        return False, f"binding failed: {e}"
