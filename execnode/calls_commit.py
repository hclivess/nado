"""
THE EXEC SUMMARY'S CALL LEAVES (settle-with-proof binding, doc/zk-recursion.md 5b; kv_ops.exec_summary_put).

incorporate_block derives, from every block body, the ORDERED execution entries its `blob` txs carry (block_calls: the
calls, and from EXEC_ROOT_V2_HEIGHT the code events), one 256-bit leaf per entry (call_leaf / event_leaf), and the
records-inertness bit (block_records_inert). block_summary returns them; they persist in the exec summaries in L1 `meta`,
which FEEDS THE L1 STATE ROOT — so every function here is consensus and must stay byte-identical on replay.

G9 slice 4 moved this module out of execnode/stark and deleted the Goldilocks parts no generation-29 path runs: the
narrow alghash chain, the wide alghash2 chain and every settle-binding verifier that folded them (their caller, the
Goldilocks settle-proof verifier, went in slice 2), io_commitment and the in-circuit membership demo. What gen 29 runs
is the leaves, the inert bit, and the BLAKE2s calls fold for the Stwo settlement (fold_leaves_b2).

THE LEAVES ARE WIDE FROM HEIGHT 1 (audit 2026-09-24/25 HIGH, "settle calldata binding is ONE field element"; gen 27's
ZK_HARDEN_HEIGHT, 1 from gen 28): a leaf is the full 256-bit blake2b digest of the entry's canonical payload,
domain-tagged "wide". The narrow leaf (blake2b % P, one Goldilocks element) still answers cursor < 1, exactly as before:
block 0 (genesis) carries no transaction, so no persisted leaf was ever narrow, but the function keeps its answer at every
input rather than rest that on an argument.
"""
from hashing import blake2b_hash

# The Goldilocks prime (execnode/stark/field.P until G9 slice 4), kept ONLY as a reduction inside frozen leaf formats: the
# code commitment an event leaf hashes, and the narrow leaf of cursor < 1. Both persist in the exec summaries (L1 state
# root), so the values must stay exactly what they were. Not a field: no arithmetic happens in it any more.
_P_GOLDILOCKS = 2**64 - 2**32 + 1


def _leaf_value(payload, cursor):
    """A leaf's stored value. From cursor 1: the WHOLE 256-bit blake2b digest of ["wide", payload] as one int. INVARIANT
    (audit 2026-09-24/25 HIGH, one-element calldata binding): never reduce or truncate a wide leaf — a 64-bit leaf is a
    ~2^32 birthday search for a second calldata with the same binding. Below cursor 1 (genesis, which carries no entry):
    the narrow blake2b % P it always was (the `>= 1` is the deleted gate's value, ZK_HARDEN_HEIGHT)."""
    if int(cursor) < 1:
        return int(blake2b_hash(payload), 16) % _P_GOLDILOCKS
    return int(blake2b_hash(["wide", payload]), 16)


def code_commitment(code):
    """The code commitment an event leaf carries (exec_state_bind.code_commitment until G9 slice 4, value for value): a
    NONZERO int in [1, P) committing to a contract's code map {method: bytecode}, canonical (sorted method order via
    canonical_bytes) so every node commits the same value for the same code."""
    from hashing import canonical_bytes
    n = int(blake2b_hash(["code", canonical_bytes(code).hex()]), 16)
    return 1 + (n % (_P_GOLDILOCKS - 1))


def call_leaf(call, cursor=0, timestamp=0):
    """A field element committing to ONE call's PUBLIC fields (cid, method, caller, args, value, cursor,
    timestamp) — the leaf the calls-commitment chains. Deterministic; a verifier recomputes it from the call.
    cursor/timestamp come from the CALL dict when present (per-call execution context, the DA-binding form),
    else from the passed epoch-wide defaults (the legacy single-context form). Identical bytes on every layer:
    blake2b over a canonical list, so Python (L1/exec) and the Rust prover agree."""
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
    # INVARIANT (audit 2026-09-24/25 HIGH, one-element calldata binding): from height 1 the leaf is the full 256-bit
    # digest (_leaf_value), keyed on the call's own cursor — the L1 height block_calls stamps.
    return _leaf_value(payload, cur)


EVENT_OPS = ("deploy", "upgrade", "lock", "transfer_contract")   # the blob ops that change a contract's code or meta leaves


def event_leaf(ev):
    """A field element committing to ONE code event's public fields (EXEC_ROOT_V2_HEIGHT, S1): the op, the
    sender, the target cid (or the deploy's fixed name and nonce), the CODE COMMITMENT of the decoded code the
    exec layer will apply (not the codez bytes — two encodings of one code are one code), the runtime, the
    lock flag or the transferee, and the block. Chained with call_leaf in tx order, so a settle proof's
    calls_commitment binds the code changes of its span as tightly as its calls. Domain-separated from
    call_leaf by the leading tag. Never raises: block_summary derives a whole block at once (see _arg_field)."""
    code = ev.get("code")
    cc = code_commitment(code) if isinstance(code, dict) else 0
    rt = ev.get("runtime")
    payload = ["event", str(ev.get("op", "")), str(ev.get("caller", "")), str(ev.get("cid") or ""),
               str(ev.get("at") or ""), str(ev.get("nonce") or ""), int(cc),
               "" if rt is None else str(rt), 1 if ev.get("upgradable", True) else 0, str(ev.get("to") or ""),
               int(ev.get("cursor", 0)), int(ev.get("timestamp", 0))]
    # INVARIANT (audit 2026-09-24/25 HIGH): wide from height 1, exactly as call_leaf — an event leaf rides the same
    # chain, so a 64-bit event leaf would reopen the same collision.
    return _leaf_value(payload, int(ev.get("cursor", 0)))


def entry_leaf(entry, cursor=0, timestamp=0):
    """call_leaf or event_leaf, by the entry's op — the one dispatch every chain of leaves goes through."""
    return (event_leaf(entry) if entry.get("op") in EVENT_OPS
            else call_leaf(entry, cursor, timestamp))


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
    # the gen-29 VM's 256-bit digest at every cursor (call_leaf passed v2=True since BLAKE_EXEC_HEIGHT was inlined; the
    # field digest and the switch went with the field VM in G9 slice 3b) — the leaf binds the statement the VM actually
    # ran, so it digests as the runtime does
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
    #     span (S1). Their public fields are exactly what ExecState.apply_blob judges.
    # Below the gate the list is calls only with ts=0, exactly as before: the leaves persist in the exec
    # summaries, which feed the L1 state root.
    # `h >= 1` is exec_state_bind.root_v2 (EXEC_ROOT_V2_HEIGHT, 1 from gen 26), inlined in G9 slice 4 with the module:
    # block 0 keeps the calls-only, ts=0 list it always had
    v2 = h >= 1
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
    the shapes ExecState.apply_blob judges (a non-string cid or transferee becomes "", which it
    refuses exactly as the chain refuses the original). The code is DECODED here — the same bytes the exec
    layer applies — and None when undecodable, which the chain refuses."""
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
        # Every leaf is 256-bit (audit 2026-09-24/25 HIGH). Genesis carries no transactions, so it persists no leaves.
        calls_by_ns[ns] = [entry_leaf(c) for c in block_calls(block, ns)]
    return block_records_inert(block), calls_by_ns


def _summary_ops(block):
    """The blob ops a block's summary discovers namespaces from: calls, plus the code events from
    EXEC_ROOT_V2_HEIGHT (block_calls carries them from the same height)."""
    # `>= 1` is exec_state_bind.root_v2, inlined in G9 slice 4 (see block_calls)
    return ("call",) + (EVENT_OPS if int(block.get("block_number", 0)) >= 1 else ())


# THE GEN-29 CALLS FOLD (Goldilocks retirement G4, doc/stwo/g4-settlement-statement.md 2.3). The same persisted leaves
# (256-bit BLAKE2b digests of the canonical call, block_summary) folded with BLAKE2s instead of the alghash2 sponge, so
# the Stwo settlement circuit proves the fold with the same Blake component as the tree and the VM: c_0 = 32 zero bytes,
# c_i = BLAKE2s(c_{i-1} || leaf_i as 32 bytes big-endian, person=CALLS_PERSON). FROZEN at the reroll. Nothing calls it on
# a consensus path yet: the gen-29 proof branch is refused (option R) until the Stwo settlement gate.
CALLS_PERSON = b"NADOcll1"


def chain_start_b2():
    return bytes(32)


def fold_leaves_b2(node, leaves):
    """Extend a gen-29 calls chain (32 bytes) by `leaves` (256-bit ints, the persisted wide leaves) in order."""
    import hashlib
    node = bytes(node)
    if len(node) != 32:
        raise ValueError("a gen-29 calls chain node is 32 bytes")
    for lf in leaves:
        x = int(lf)
        if isinstance(lf, bool) or x < 0 or x >> 256:
            raise ValueError("calls leaf out of range")
        node = hashlib.blake2s(node + x.to_bytes(32, "big"), digest_size=32, person=CALLS_PERSON).digest()
    return node
