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

THE BINDING IS WIDE FROM BLOCK 1 (audit 2026-09-24/25 HIGH, "settle calldata binding is ONE field element"; gen
27's ZK_HARDEN_HEIGHT, 1 from gen 28 and deleted). Everything above describes the NARROW form, which survives only
for height 0 (wide_binding): a leaf is blake2b % P (64 bits) and the chain is width-2 / capacity-1 alghash, whose
digest is ONE Goldilocks element. A second call sequence with the same commitment therefore costs a birthday
search over 64 bits — ~2^32 hash evaluations, minutes on one core — at EITHER level: two call payloads whose
leaves collide (the cheapest: blake2b, no algebra), or two chains whose final alghash nodes collide. The
settler submits the calldata itself, so it controls both sides of the collision: it lands call A on L1, every
exec node executes A, and it proves call B, whose commitment equals A's; L1 then settles B's storage transition
as the namespace's root. From height 1:
  * a leaf is the full 256-bit blake2b digest of the same payload (domain-tagged "wide"), consumed as FOUR
    field elements (its little-endian 64-bit words, each % P) — ~2^128 collision;
  * the chain is the alghash2 sponge (width 12, capacity 4 = 256 bits, the recursion-layer hash) over
    [DOM_CALLS_WIDE, node(4), leaf(4)] from a 4-element IV — a 4-element (~256-bit) commitment, ~2^128 collision;
  * the regime of a commitment is keyed on the SEGMENT's end cursor (an L1 height, agreed data), never on
    anything a prover writes into a call, and a segment that straddles block 0 and block 1 is refused (it falls
    back to the bonded quorum), so a span never mixes widths.
The binding is a NATIVE check on both sides (settlement_sparse recomputes it from the bundle's calls, L1 folds
the persisted summary leaves); no AIR and no Rust kernel commits to it, so the widening touches no circuit and
no native crate. prove_calls_commitment below is the narrow in-circuit demonstrator only.
"""
from execnode.stark import field as F, alghash, alghash2, membership
from hashing import blake2b_hash


# --- WIDE BINDING (from height 1; see the module docstring) -----------------------------------------------
WIDE = alghash2.DIGEST                       # 4 field elements (256 bits)
# Nothing-up-my-sleeve domain tag + chain start for the wide chain, derived like alghash2's own constants
# (blake2b of labels) so they collide with no DOM_* small tag and no other chain's IV. Plain blake2b, not
# alghash2.hashn: this module is imported by incorporate_block (block_summary), which must never need the
# native sponge just to import — only a wide FOLD (settle validation) touches alghash2.
DOM_CALLS_WIDE = int(blake2b_hash(["alghash2", "dom", "calls-wide"]), 16) % F.P
IV_WIDE = tuple(int(blake2b_hash(["alghash2", "calls-wide-iv", i]), 16) % F.P for i in range(WIDE))


def wide_binding(height):
    """True iff the calls binding at L1 height `height` is the wide (4-element) form. A pure function of the
    height. `>= 1` is the deleted gate's value (ZK_HARDEN_HEIGHT, 1 from gen 28), kept because height 0 reaches
    it: a call or event with no cursor defaults to 0 (call_leaf, event_leaf), calls_commitment defaults
    cursor=0, and da_calls_commitment over no blocks answers narrow — each answers exactly what it did."""
    return int(height) >= 1


def _leaf_value(payload, wide):
    """A leaf's stored value. Narrow: blake2b % P (ONE field element — the audited ~2^32 collision, kept
    byte-identical for height 0). Wide: the WHOLE 256-bit blake2b digest as one int (the codec stores ints of
    any width), which the wide fold consumes as four field elements (_leaf_limbs). The "wide" tag keeps a wide
    leaf from ever equalling the narrow digest of the same payload."""
    if not wide:
        return int(blake2b_hash(payload), 16) % F.P
    return int(blake2b_hash(["wide", payload]), 16)


def _leaf_limbs(lf):
    """A wide leaf (256-bit int) as WIDE field elements: its little-endian 64-bit words, each reduced % P.
    Distinct digests alias only if every word pair is equal or differs by exactly P — negligible."""
    x = int(lf)
    if isinstance(lf, bool) or x < 0 or x >> 256:
        raise ValueError("wide calls leaf out of range")
    return [((x >> (64 * i)) & 0xFFFFFFFFFFFFFFFF) % F.P for i in range(WIDE)]


def chain_start(wide):
    """The IV a calls chain folds from: alghash.IV (one element) narrow, IV_WIDE (a 4-list) wide."""
    return list(IV_WIDE) if wide else alghash.IV


def _wide_step(node, lf):
    """One wide chain step: alghash2.hashn([DOM_CALLS_WIDE, node(4), leaf(4)]) -> a 4-list."""
    return [int(x) for x in alghash2.hashn([DOM_CALLS_WIDE, *node, *_leaf_limbs(lf)])]


def wide_commitment(cc):
    """`cc` as a canonical wide commitment (a list of WIDE ints in [0, P)), or None if it is not one. The
    comparison every wide gate uses: exact, typed, no mod-P leniency and no bool/str coercion — an honest
    commitment is always canonical, so anything else is refused."""
    if not isinstance(cc, (list, tuple)) or len(cc) != WIDE:
        return None
    if not all(isinstance(x, int) and not isinstance(x, bool) and 0 <= x < F.P for x in cc):
        return None
    return list(cc)


def call_leaf(call, cursor=0, timestamp=0, wide=None):
    """A field element committing to ONE call's PUBLIC fields (cid, method, caller, args, value, cursor,
    timestamp) — the leaf the calls-commitment chains. Deterministic; a verifier recomputes it from the call.
    cursor/timestamp come from the CALL dict when present (per-call execution context, the DA-binding form),
    else from the passed epoch-wide defaults (the legacy single-context form). Identical bytes on every layer:
    blake2b over a canonical list, so Python (L1/exec) and the Rust prover agree.

    `wide` (None = keyed on this call's own cursor, the L1 height block_calls stamps): the leaf form — see
    _leaf_value. calls_commitment passes it explicitly, keyed on the SEGMENT cursor, so a prover cannot pick a
    call's width by writing its cursor."""
    cur = int(call.get("cursor", cursor))
    ts = int(call.get("timestamp", timestamp))
    # `asset` is the call's ACTX_ASSET context — a PUBLIC input the VM reads and the exec proof runs over, but
    # it was absent from this leaf, so the DA binding could not detect an asset substitution. A value==0 asset
    # call is records-inert (proof-settleable), and a contract that branches on ACTX_ASSET would prove a
    # different storage transition under a swapped asset with the DA commitment still matching. Bind it in the
    # SAME canonical int form the exec statement uses (_epoch_pub_statement: int(call.asset); 0 == native).
    payload = ["call", str(call.get("cid", "")), str(call.get("method", "")),
               str(call.get("caller", "epoch")), [_arg_field(a) for a in call.get("args", [])],
               int(call.get("value", 0)), cur, ts, _asset_field(call.get("asset", 0))]
    # INVARIANT (audit 2026-09-24/25 HIGH, one-element calldata binding): from height 1 this leaf is the
    # full 256-bit digest. Never reduce a wide leaf % P or truncate it — a 64-bit leaf is a ~2^32 birthday
    # search for a second calldata with the same binding.
    return _leaf_value(payload, wide_binding(cur) if wide is None else bool(wide))


EVENT_OPS = ("deploy", "upgrade", "lock", "transfer_contract")   # == exec_state_bind.EVENT_OPS (no import: L1 path)


def event_leaf(ev, wide=None):
    """A field element committing to ONE code event's public fields (EXEC_ROOT_V2_HEIGHT, S1): the op, the
    sender, the target cid (or the deploy's fixed name and nonce), the CODE COMMITMENT of the decoded code the
    exec layer will apply (not the codez bytes — two encodings of one code are one code), the runtime, the
    lock flag or the transferee, and the block. Chained with call_leaf in tx order, so a settle proof's
    calls_commitment binds the code changes of its span as tightly as its calls. Domain-separated from
    call_leaf by the leading tag. Never raises: block_summary derives a whole block at once (see _arg_field)."""
    from execnode.stark import exec_state_bind as ESB
    code = ev.get("code")
    cc = ESB.code_commitment(code) if isinstance(code, dict) else 0
    rt = ev.get("runtime")
    payload = ["event", str(ev.get("op", "")), str(ev.get("caller", "")), str(ev.get("cid") or ""),
               str(ev.get("at") or ""), str(ev.get("nonce") or ""), int(cc),
               "" if rt is None else str(rt), 1 if ev.get("upgradable", True) else 0, str(ev.get("to") or ""),
               int(ev.get("cursor", 0)), int(ev.get("timestamp", 0))]
    # INVARIANT (audit 2026-09-24/25 HIGH): wide from height 1, exactly as call_leaf — an event leaf
    # rides the same chain, so a 64-bit event leaf would reopen the same collision.
    return _leaf_value(payload, wide_binding(int(ev.get("cursor", 0))) if wide is None else bool(wide))


def entry_leaf(entry, cursor=0, timestamp=0, wide=None):
    """call_leaf or event_leaf, by the entry's op — the one dispatch every chain of leaves goes through."""
    return (event_leaf(entry, wide) if entry.get("op") in EVENT_OPS
            else call_leaf(entry, cursor, timestamp, wide))


def _asset_field(a):
    """A call's `asset` context as the canonical int the exec statement commits (int(call.asset); 0 == native
    NADO). Asset ids are decimal-string alghash2 digests, so int() is exact; an unparseable value maps to 0 —
    it could not have named a real asset (the VM reads asset % P and a non-asset call reverts), and this
    function, like _safe_int, must never be the reason a block has no summary."""
    if isinstance(a, bool):
        return 0
    try:
        return int(a or 0)
    except (TypeError, ValueError):
        return 0


def _arg_field(a):
    """One call arg in the SAME field form the VM boundary gives it (runtimes.zkvm_statement): ints pass
    through, strings are digested.

    A bare int() here crashed on every legal string arg — and because block_summary derives the leaves for a
    whole block at once, ONE call carrying a string killed the summary for every call in that block. It was
    live: the bet oracle posts fixture names ("AS Roma vs Fiorentina\n…") as args, and the node logged
    `exec summary for block N failed: invalid literal for int()` on block after block, silently leaving
    those heights with no settle-with-proof binding at all.

    Anything that is neither an int nor a string cannot reach the VM (zkvm_statement rejects it), so it
    cannot appear in a call that executes; digesting its repr keeps the leaf total rather than throwing,
    since this function must never be the reason a block has no summary."""
    from execnode import runtimes
    if isinstance(a, bool) or not isinstance(a, (int, str)):
        return runtimes.zkvm_addr_digest(repr(a))
    return a if isinstance(a, int) else runtimes.zkvm_addr_digest(a)


def _safe_int(v):
    """A call's `value` as a non-negative int, or 0 for anything else. block_summary derives a WHOLE block's
    leaves at once, so a bare int() on a poison `value:"abc"` used to kill the summary for every call in the
    block (audit 2026-07). L1 admission now rejects such a blob; this keeps the summary total for any block
    already in history. Deterministic — every node coerces identically, and a non-int value reverts on apply
    anyway, so the leaf's exact number is immaterial."""
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def block_calls(block, ns="default"):
    """The ORDERED execution calls a namespace's `blob` txs in `block` carry (op == 'call') — the DETERMINISTIC
    bridge that lets L1 (the settlement VERIFIER) and the exec node (the PROVER) build the IDENTICAL calls list
    from the same on-chain block, so a settle-with-proof's calls_commitment can be BOUND to the real DA calldata
    (a prover cannot substitute fabricated calls). Fields exactly as apply_blob reads them: cid = data.contract,
    method = data.method, args = data.args, value = data.value; caller = the blob tx's L1 sender; and the
    execution context cursor = block number, timestamp = block timestamp. ALL op=='call' blobs are included —
    even ones that will skip/revert in the VM — so the commitment binds the RAW on-chain calldata; the proof's
    state transition treats a skip/revert as a no-op (matching live apply). Deploys/other ops were excluded
    before EXEC_ROOT_V2_HEIGHT ("they don't move the kv half" — they did: the code and meta leaves); from the
    gate the four code events ride the list too (see below)."""
    h = int(block.get("block_number", 0))
    # DETERMINISM (consensus): block_timestamp is DELIBERATELY excluded from the block-hash preimage
    # (ops/block_ops.construct_block hashes it as None) so honest clock skew cannot fork the chain — a block
    # may legitimately carry a different timestamp on different nodes, within BLOCK_TIMESTAMP_DRIFT. Feeding
    # it into call_leaf therefore made the DA binding NON-DETERMINISTIC: measured live, the same block
    # 665ed0ae60ae51 carried ts differing by 1 s across two nodes and produced completely different call
    # leaves, which desynchronised every execsum row and split snapshot identity fleet-wide. The binding must
    # commit only COMMITTED data. `cursor` (the block number) already pins exactly which block a call came
    # from, so the timestamp contributed no binding strength — it was purely an uncommitted input. Pin it to
    # 0. The leaf FORMULA is unchanged (same eight fields), so any reimplementation only has to adopt the
    # same rule. The exec VM's TIME opcode was the SECOND leak of the same uncommitted input; it now reads
    # protocol.chain_clock(height) instead (execnode sets state.block_ts from it), so neither the DA binding
    # nor contract execution can see a wall clock.
    ts = 0
    # EXEC_ROOT_V2_HEIGHT (rides a reroll), two changes to what this list carries:
    #   * the timestamp is protocol.chain_clock(h) — the SAME pure function of the height the chain hands the
    #     VM as block_ts, so a call reading TIME proves the transition the chain applied. 0 here meant the
    #     prover ran every TIME-reading call under a clock the chain never showed it, on every span. Still
    #     committed data: it depends on nothing but h;
    #   * the block's CODE EVENTS (deploy / upgrade / lock / transfer_contract) ride the list in tx order
    #     between the calls, so a settle proof binds — and its transition carries — every code change of its
    #     span (S1). Their public fields are exactly what exec_state_bind.apply_event judges.
    # Below the gate the list is calls only with ts=0, exactly as before: the leaves persist in the exec
    # summaries, which feed the L1 state root.
    from execnode.stark.exec_state_bind import root_v2
    v2 = root_v2(h)
    if v2:
        from protocol import chain_clock
        ts = int(chain_clock(h))
    calls = []
    for tx in block.get("block_transactions", []):
        if tx.get("recipient") != "blob":
            continue
        d = tx.get("data")
        if not isinstance(d, dict):
            continue
        if d.get("ns", "default") != ns:
            continue
        op = d.get("op")
        if op == "call":
            calls.append({"cid": d.get("contract"), "method": d.get("method"), "caller": tx.get("sender"),
                          "args": d.get("args", []), "value": _safe_int(d.get("value")),
                          "asset": _asset_field(d.get("asset")), "cursor": h, "timestamp": ts})
        elif v2 and op in EVENT_OPS:
            calls.append(_event_entry(d, tx, op, h, ts))
    return calls


def _event_entry(d, tx, op, h, ts):
    """One code event as block_calls carries it: the public fields the chain's admission reads, coerced to
    the shapes exec_state_bind.apply_event judges (a non-string cid or transferee becomes "", which it
    refuses exactly as the chain refuses the original). The code is DECODED here — the same bytes the exec
    layer applies — and None when undecodable, which apply_event refuses as the chain does."""
    ev = {"op": op, "caller": tx.get("sender"), "cursor": h, "timestamp": ts}
    if op in ("deploy", "upgrade"):
        from execnode.code_codec import decode_code
        try:
            code = decode_code(d)
        except Exception:
            code = None
        ev["code"] = code if isinstance(code, dict) else None
    if op == "deploy":
        at = d.get("at")
        ev["at"] = at if isinstance(at, str) else None
        ev["nonce"] = d.get("nonce", tx.get("txid"))
        ev["runtime"] = d.get("runtime", "zkvm")
        ev["upgradable"] = d.get("upgradable", True) not in (False, 0, "false", "0", "no")   # F10's rule
        return ev
    cid = d.get("contract")
    ev["cid"] = cid if isinstance(cid, str) else ""
    if op == "upgrade":
        ev["runtime"] = d.get("runtime")                    # None: keep the contract's (the v2 rule)
    elif op == "transfer_contract":
        to = d.get("to")
        ev["to"] = to if isinstance(to, str) else ""
    return ev


# --- RECORDS-INERTNESS (settle-with-proof binding, doc/rollups-and-settlement.md §6) ----------------
#
# A settle-with-proof covers only the KV half of the exec root; the composition in the L1 settle branch
# pins the SAME rec_hex into both the pre and post root, i.e. it REQUIRES the RECORDS half to be unchanged
# across the proven span. Nothing used to check that it SHOULD be. A span that really did move records
# (a value>0 call, a bridge deposit, an emit, a shield) can still be proven with records FROZEN, settling a
# root that silently omits those payouts — after which L1's settled pointer diverges permanently from what
# every honest exec node computes, with no quorum to correct it (the proof path needs none).
#
# `block_records_inert` is the on-chain predicate that closes it. It is deliberately an ALLOWLIST: a block
# is inert only if every transaction in it is something we have positively established cannot move RECORDS.
# A new blob op or reserved recipient added later is therefore NON-inert by default -> the proof path
# refuses the span -> it falls back to the bonded quorum. The denylist shape (enumerate what moves records)
# is what rotted here twice: it fails OPEN when someone adds a tenth record type.
#
# Deliberately CONSERVATIVE in two ways, both erring toward rejection:
#   * an exec-relevant L1 tx makes the block non-inert for EVERY namespace, not just the one it targets;
#   * a non-safe blob op does the same, regardless of which namespace the blob names.
# Both may refuse a span that was actually provable. Neither can ever accept one that was not.

# L1 reserved recipients whose APPLY moves exec-layer RECORDS (execnode/execnode.py block tail:
# credit_deposit / apply_shield / apply_field_shield / apply_xmsg / drop_claimed / drop_consumed_outbox).
_RECORDS_MOVING_RECIPIENTS = frozenset({
    "bridge", "bridge_withdraw", "dividend", "dividend_withdraw",
    "shield", "unshield", "xmsg", "faucet", "treasury_execute",
})

# Blob ops that touch the KV half ONLY (execnode/state.py apply_blob). `call` is conditional on value==0 —
# a value>0 call escrows sender->cid across two T_BRIDGE_BAL record positions BEFORE the VM even runs.
# NOT here, because each moves RECORDS: emit (outbox), bridge_withdraw, collect_dividend, field_transfer,
# shielded_transfer.
_RECORDS_SAFE_BLOB_OPS = frozenset({"deploy", "lock", "upgrade", "transfer_contract", "call"})


def block_records_inert(block):
    """True iff NOTHING in `block` can move the exec layer's RECORDS half — the on-chain precondition for a
    records-frozen settle-with-proof to be honest. Allowlist: every tx must be positively known-safe.

    Namespace-independent by design (see the conservatism note above): the caller asks "is this block inert
    for the whole exec layer", so one namespace's bridge deposit blocks a proof in another. That costs some
    provable spans and buys the property that a records-moving tx can never be silently skipped.

    Does NOT cover the presence-dividend accrual, which fires on an EPOCH boundary with no transaction at
    all (execnode/execnode.py tail_loop). That is span-level, not block-level, and the settle branch asserts
    it separately by refusing a span that crosses an epoch boundary."""
    for tx in block.get("block_transactions", []) or []:
        recipient = tx.get("recipient")
        if recipient in _RECORDS_MOVING_RECIPIENTS:
            return False
        if recipient != "blob":
            continue                                  # ordinary transfer / bond / register / … : no exec state
        d = tx.get("data")
        if not isinstance(d, dict):
            return False                              # undecodable blob — cannot establish safety, so refuse
        op = d.get("op")
        if op not in _RECORDS_SAFE_BLOB_OPS:
            return False
        if op == "call" and _safe_int(d.get("value")) != 0:
            return False                              # value escrow moves two bridge-balance records
    return True


def block_summary(block):
    """(inert, {ns: [call_leaf, ...]}) for one block — everything the settle-with-proof binding needs from a
    block BODY, derived ONCE at incorporate time so the consensus path never re-reads a prunable body.
    Namespaces are discovered from the block's own call blobs, so a namespace with no calls simply has no
    entry (and folds to an unchanged chain)."""
    calls_by_ns = {}
    for tx in block.get("block_transactions", []) or []:
        if tx.get("recipient") != "blob":
            continue
        d = tx.get("data")
        if not isinstance(d, dict) or d.get("op") not in _summary_ops(block):
            continue
        _ns = d.get("ns", "default")
        if not isinstance(_ns, str):
            continue                                   # unhashable ns -> not a real namespace; skip (admission rejects it too)
        calls_by_ns.setdefault(_ns, [])
    for ns in list(calls_by_ns):
        # Width keyed on each entry's own cursor, which block_calls stamps as THIS block's height — so every
        # block from 1 persists 256-bit leaves (audit 2026-09-24/25 HIGH; the settle gate folds them wide).
        # Genesis carries no transactions, so it persists no leaves of either width.
        calls_by_ns[ns] = [entry_leaf(c) for c in block_calls(block, ns)]
    return block_records_inert(block), calls_by_ns


def _summary_ops(block):
    """The blob ops a block's summary discovers namespaces from: calls, plus the code events from
    EXEC_ROOT_V2_HEIGHT (block_calls carries them from the same height)."""
    from execnode.stark.exec_state_bind import root_v2
    return ("call",) + (EVENT_OPS if root_v2(int(block.get("block_number", 0))) else ())


def fold_leaves(node, leaves):
    """Extend a calls-commitment chain by `leaves` in order — the same fold da_calls_commitment does, but
    over PERSISTED leaves instead of freshly-parsed block bodies. The chain's width is the NODE's shape: an
    int is the narrow alghash chain (unchanged), a WIDE-list is the wide alghash2 chain (chain_start)."""
    if isinstance(node, (list, tuple)):
        # INVARIANT (audit 2026-09-24/25 HIGH): a wide chain stays wide — 4 elements per node, 4 per leaf.
        node = list(node)
        for lf in leaves:
            node = _wide_step(node, lf)
        return node
    for lf in leaves:
        node = alghash.merkle_node(node, int(lf))
    return node


def span_width(lo, hi):
    """(ok, wide) for a segment covering L1 blocks (lo, hi]: the binding width is keyed on the segment's END
    height; a segment whose blocks straddle the widening (block 0 narrow, block 1 wide: lo < 0 < hi) is
    (False, None) — its summaries would mix leaf widths, so it is refused and that span settles by the bonded
    quorum instead. Kept exact for every (lo, hi): the L1 settle path never passes lo < 0 (a proof extends a
    real settlement), but this is a pure helper and its answers did not move."""
    wide = wide_binding(hi)
    if wide and not wide_binding(int(lo) + 1):
        return False, None
    return True, wide


def da_calls_commitment(blocks, ns="default", wide=None):
    """The calls-commitment L1 EXPECTS for a settlement over `blocks` (ascending) in namespace `ns`: fold the
    per-call leaves of every block's blob calls, in block-then-tx order, from IV. A settle-with-proof over that
    span is bound to the DA iff its calls_commitment equals this — computed on-chain, independent of the prover.
    `wide` (None = keyed on the last block's height, as the gates key a segment on its end): the width."""
    if wide is None:
        wide = bool(blocks) and wide_binding(int(blocks[-1].get("block_number", 0)))
    node = chain_start(wide)
    for blk in blocks:
        node = fold_leaves(node, [entry_leaf(call, wide=wide) for call in block_calls(blk, ns)])
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
        okw, wide = span_width(lo, seg_end)
        if not okw:
            return False, f"segment {j} ({lo}, {seg_end}] straddles the calls-binding widening (block 0 -> 1)"
        if wide:
            # INVARIANT (audit 2026-09-24/25 HIGH): all four elements are compared, exactly — never element 0.
            if wide_commitment(cc) != da_calls_commitment(blocks, ns, wide=True):
                return False, f"segment {j} calls_commitment does not match the on-chain DA calldata (fabricated calls)"
        elif int(cc) % F.P != da_calls_commitment(blocks, ns, wide=False) % F.P:
            return False, f"segment {j} calls_commitment does not match the on-chain DA calldata (fabricated calls)"
        lo = seg_end
    if lo != int(cursor):
        return False, f"segments do not cover the whole settled span (reached {lo}, expected {cursor})"
    return True, "calls bound to DA"


def verify_calls_bound_to_summaries(proof, ns, prev_cursor, cursor, get_summary, max_span,
                                    records_out=None):
    """PRUNE-SAFE DA-BINDING GATE — the replacement for verify_calls_bound_to_da on the consensus path.

    Identical statement (every segment's calls_commitment must equal L1's OWN fold over the real on-chain
    calldata it claims to settle), but sourced from the per-block exec summaries persisted at incorporate
    time (kv_ops.exec_summary_get) instead of from block BODIES. Bodies are prunable and are wiped wholesale
    by a snapshot re-anchor, so reading them made this check fork the fleet; summaries live in the KV store,
    which pruning never touches.

    Also enforces the RECORDS-frozen precondition the settle composition silently assumes: every block in
    the span must be records-inert, else a span that really moved records could be settled with records
    frozen, permanently diverging L1's settled pointer from every honest exec node's state.

    A MISSING summary is a hard refusal, never 'no calls' — otherwise a node that lacks the summary would
    bind the span to an empty call list and accept a fabricated one. Returns (ok, reason)."""
    segs = proof.get("segments") or []
    if not segs:
        return False, "no segments to bind"
    lo, hi = int(prev_cursor), int(cursor)
    if hi <= lo:
        return False, f"settled span ({lo}, {hi}] is empty"
    if hi - lo > int(max_span):
        return False, f"settled span ({lo}, {hi}] exceeds the {int(max_span)}-block proof cap"
    for j, seg in enumerate(segs):
        cc = seg.get("calls_commitment")
        if cc is None:
            return False, f"segment {j} carries no calls_commitment (unbound to the DA calldata)"
        seg_end = int(seg.get("cursor", hi))
        if not (lo < seg_end <= hi):
            return False, f"segment {j} cursor {seg_end} is outside the settled span ({lo}, {hi}]"
        # THE WIDTH IS THE SEGMENT'S (audit 2026-09-24/25 HIGH, one-element calldata binding): from height 1
        # the persisted leaves are 256-bit and the chain is the 4-element alghash2 fold. On the settle path lo
        # is a real settlement's cursor (>= 0), so seg_end >= 1 and every segment is wide; the narrow branch
        # below answers only a segment ending at 0, exactly as it always did.
        okw, wide = span_width(lo, seg_end)
        if not okw:
            return False, f"segment {j} ({lo}, {seg_end}] straddles the calls-binding widening (block 0 -> 1)"
        node = chain_start(wide)
        for h in range(lo + 1, seg_end + 1):
            summary = get_summary(h)
            if summary is None:
                return False, f"no exec summary for block {h} — cannot bind calls to DA"
            if not int(summary.get("inert", 0)):
                # RECORDS-BOUND SETTLEMENT (SETTLE_PROOF_RECORDS). `records_out` is not None exactly when
                # the caller intends to PROVE the records half rather than freeze it, so a non-inert block
                # is admissible — but only if this node committed effects it can actually derive.
                #
                # `rd` must be present AND 1. Its absence is NOT treated as permission: a summary written
                # before the feature (or by a node with the flag off) simply lacks the field, and reading
                # that as "nothing to bind" would let a span settle while silently omitting every payout in
                # it. Explicit 0 means the block moved records this node cannot re-derive (a shield, an
                # xmsg, a value>0 call whose escrow depends on the VM's verdict); both cases fall back to
                # the bonded quorum, which is always correct, just slower.
                if records_out is None:
                    return False, f"block {h} moved exec RECORDS; a records-frozen proof cannot settle it"
                if int(summary.get("rd", 0)) != 1:
                    return False, (f"block {h} moved exec RECORDS this node cannot derive "
                                   f"(no committed effects) — quorum only")
                records_out.extend(summary.get("rec") or [])
            elif records_out is not None and (summary.get("rec") or []):
                # INERT BY THE TX SCAN, YET IT MOVED RECORDS — the presence-dividend accrual.
                #
                # `inert` is computed by block_summary() from the block's TRANSACTIONS, before core_loop's
                # accrual hook runs; the hook then appends the accrual to the summary's `rec` and never
                # revisits `inert`. So a boundary block with no records-moving transaction is stored as
                # inert=1 WITH a full set of effects in `rec`, and the branch above — which only reads
                # `rec` for non-inert blocks — skipped it and derived nothing.
                #
                # That is exactly what refused the first records-bearing proof ever built. Span 3600->3664
                # crosses block 3660, which accrues epoch 60 to 25 miners:
                #     settle-with-proof carries a RECORDS half: 16d9366b… -> 4b77b159… (25 update(s))
                #     REFUSED … "Settle proof moves the records half but the span committed no records
                #     effects"
                # The prover derived 25 effects and L1 derived 0, so the empty-effect trap in
                # transaction_ops (rec_post must equal rec_hex when nothing is committed) fired correctly on
                # a set that was wrong. The header of this module already said the tx scan "does NOT cover
                # the presence-dividend accrual"; the collector simply never accounted for that.
                #
                # FIXED HERE, NOT BY MARKING THE BLOCK NON-INERT. `inert` lives in the `meta` sub-DB which
                # FEEDS THE L1 STATE ROOT: changing what is written there would move the root on upgraded
                # nodes only and fork the fleet (exec_summary_put's docstring, and the h4260 corruption).
                # This is a VERIFIER-side derivation change — no meta write, no root change.
                #
                # The records-FROZEN path (records_out is None) is untouched and still refuses such a span:
                # transaction_ops keeps its epoch-boundary assert for any proof that is not records-bound,
                # which is precisely the case this block would otherwise slip past.
                if int(summary.get("rd", 0)) != 1:
                    return False, (f"block {h} accrued exec RECORDS this node cannot derive "
                                   f"(no committed effects) — quorum only")
                records_out.extend(summary.get("rec") or [])
            if wide:
                try:
                    node = fold_leaves(node, (summary.get("calls") or {}).get(ns, []))
                except (TypeError, ValueError):
                    return False, f"exec summary for block {h} does not carry wide calls leaves"
            else:
                node = fold_leaves(node, (summary.get("calls") or {}).get(ns, []))
        if wide:
            # INVARIANT (audit 2026-09-24/25 HIGH): all four elements, exactly — a check on element 0 alone (or
            # any `% P` of one element) is the ~2^32 collision this widening closed.
            if wide_commitment(cc) != node:
                return False, f"segment {j} calls_commitment does not match the on-chain DA calldata (fabricated calls)"
        elif int(cc) % F.P != node % F.P:
            return False, f"segment {j} calls_commitment does not match the on-chain DA calldata (fabricated calls)"
        lo = seg_end
    if lo != hi:
        return False, f"segments do not cover the whole settled span (reached {lo}, expected {hi})"
    return True, "calls bound to DA"


def leaves(calls, cursor=0, timestamp=0, wide=None):
    return [entry_leaf(c, cursor, timestamp, wide) for c in calls]


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
    membership.merkle_root_from_path(IV, leaves, [0]*K), hence provable + foldable via prove_calls_commitment.

    FROM HEIGHT 1 (keyed on `cursor`, the segment's end — the same key L1's span_width uses) it is the
    WIDE commitment instead: a list of 4 field elements, the alghash2 fold of 256-bit leaves from IV_WIDE. The
    width is the segment's, never a call's own cursor field, so a prover cannot narrow one leaf by rewriting it."""
    wide = wide_binding(cursor)
    if wide:
        # INVARIANT (audit 2026-09-24/25 HIGH, one-element calldata binding): the prover's commitment and L1's
        # fold (verify_calls_bound_to_summaries) must be the SAME wide function — change both or neither.
        return fold_leaves(chain_start(True), leaves(calls, cursor, timestamp, wide=True))
    node = alghash.IV
    for lf in leaves(calls, cursor, timestamp, wide=False):
        node = alghash.merkle_node(node, lf)
    return node


def commitment_matches(got, want):
    """The bundle-side check that a carried calls_commitment is the one recomputed from its calls. Narrow: the
    exact `!=` the verifiers always used (cursor 0). Wide: a canonical 4-element list, all four
    equal (wide_commitment)."""
    if isinstance(want, (list, tuple)):
        return wide_commitment(got) == list(want)
    return not (got != want)


def prove_calls_commitment(calls, cursor=0, timestamp=0, num_queries=membership.stark.NUM_QUERIES, backend=None):
    """IN-CIRCUIT proof that `calls` chain to their commitment — a membership fold of IV through the call leaves
    (all left, dirs=0). `backend=backend.RECURSION` makes it foldable into the settlement recursion. Returns
    (proof, commitment). (The leaves are private witness; binding them to the exec proof's calls is the
    succinctness integration.)

    NARROW ONLY: this proves the width-1 alghash chain (membership's AIR), which is NOT the settle binding from
    height 1 (calls_commitment is wide there). No production path calls it; an in-circuit wide chain
    would need the alghash2 hash-block AIR of the recursion layer."""
    ls = leaves(calls, cursor, timestamp, wide=False)
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
