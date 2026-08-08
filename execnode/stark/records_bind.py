"""
Bind a RECORDS-half transition to the block span's COMMITTED effects — the records analogue of
exec_state_bind (doc/state-merge.md, the "what is still open" note in records_transition.py).

THE GAP THIS CLOSES. records_transition.prove_records_transition proves the records half advanced from one
root to another over a STATED update set. It does not prove the update set is the one the span's
transactions imply, so a prover may advance records to any state it likes. That is why block_records_inert
must stay strict and why any span carrying a bridge deposit, a dividend accrual, an asset transfer or a
shielded transfer cannot settle by proof at all. exec_state_bind solved the identical problem for the KV
half by deriving the net updates from the epoch's PROVEN io and demanding the transition prove exactly
that set; this does the same for records, deriving from data L1 already holds.

WHY THE VERIFIER CAN DERIVE THIS NATIVELY, AND WHY THAT IS NOT CIRCULAR. Records movements are not VM
work: they are arithmetic on committed inputs (credit a balance, move an escrow, distribute a pot). The KV
half needs a proof because re-deriving it means RE-EXECUTING the epoch, which is exactly the cost
settlement exists to avoid. Records cost O(#records-moving txs) to derive — the price of reading calldata
L1 reads anyway — so the proof is needed only for the TREE ADVANCE (the Merkle work over a depth-256
sparse tree), never for the values. Deriving the values natively and proving the advance is the whole
trick, and it is the same split exec_state_bind already makes.

FAIL CLOSED, AND WHY THAT MAKES INCOMPLETENESS SAFE. `bind_and_verify_records` requires
tr["updates"] == the derived set EXACTLY. So an effect this module does not know how to derive does not
become an unchecked effect — it becomes a MISMATCH, and the span is refused and falls back to the bonded
quorum. Missing a derivation costs coverage; it can never cost soundness. That is deliberately the same
allowlist shape as calls_commit.block_records_inert, whose comment records that the denylist shape
"rotted here twice: it fails OPEN when someone adds a tenth record type". A derivation added later widens
what can settle; until then the honest answer is `Unbindable`.

SCOPE TODAY. Two effect families are derivable and implemented, both verified against the code that
applies them:

  * L1 `bridge` deposit -> state.credit_deposit -> bridge[addr] += amount  (execnode/state.py credit_deposit).
    Pure function of the tx's (sender, amount), which are committed block data.

  * The per-epoch presence dividend -> state.accrue_dividend_epoch -> dividend[addr] += share
    (execnode/state.py _accrue_dividend_epoch_inner). Its own docstring calls it "a PURE FUNCTION of
    (inflow, weights)", both read from L1 consensus state (dividend_inflow_get(E), weights_at_epoch(E)),
    iterated `sorted(weights.items())` for cross-node determinism. This one matters disproportionately: it
    accrues with NO TRANSACTION AT ALL, in the exec node's tail loop, which is why the settle branch today
    can only refuse any span crossing an epoch boundary rather than account for it.

Everything else — shielded/field transfers, asset transfers and allowances, xmsg, outbox/inbox, withdrawal
records, and the PAY opcode's runtime bridge movement — raises `Unbindable` and keeps riding the quorum.

THE VERIFIER MUST SOURCE (inflow, weights) ITSELF. This is the same trap the settle branch already guards
for chain randomness ("the STARK only proves the computation is CONSISTENT with the BHASH/BEACON values in
the bundle's io log — a malicious prover may put ANY value there"). The exec node reads the dividend inputs
over HTTP from L1 (`/get_dividend_inflow`, `/get_open_weights`), and that read is NOT authenticated: on a
garbled response `execnode.tail_loop` silently accrues inflow 0 and still advances `last_div_epoch`. A
verifier that took those numbers from the proof would therefore be trusting the prover's HTTP client. It
must instead re-derive them from its own consensus state — `kv_ops.dividend_inflow_get(E)` and
`ops.dividend_ops.weights_at_epoch(E)`, the latter documented as exactly "what an L1 challenge re-derives".
A prover that accrued against wrong inputs then fails to bind, which is the correct outcome: refusal, not a
forged settlement.

NAMESPACE SCOPE. The tail credits `default_state` for all three recipient effects here, so these belong to
the DEFAULT namespace only. A caller binding another namespace's records half must not apply them.

WHY THIS IS NOT WIRED INTO CONSENSUS YET — read before trying. The derivation below is correct and
currently UNREACHABLE from the settle path, for a reason that has nothing to do with this file:

  a settle-with-proof is re-checked by EVERY node at block-validation time, so every input to that check
  must come from COMMITTED state. The settle branch therefore reads per-block exec summaries
  (kv_ops.exec_summary_get), NEVER block bodies — reading bodies made one transaction validate differently
  on a pruned node than on an archive node and forked the fleet, and a snapshot re-anchor wipes bodies
  wholesale so no depth fence repairs it.

  But calls_commit.block_summary extracts ONLY `blob` transactions with op == "call" — the KV half. A
  bridge deposit, a faucet donation, a treasury mirror, a shield, an xmsg appear NOWHERE in the summary.
  `inert` records only THAT records moved, never which effect or how much, and a boolean cannot be derived
  against. So `span_effects(txs)` has no txs to walk at the moment a verifier needs them.

Unblocking it means block_summary must also commit the block's records-moving effects at incorporate time.
exec summaries live in the `meta` sub-DB, which FEEDS THE L1 STATE ROOT — adding a field changes the root
on every node and is a consensus change that must ride a reroll, exactly as SETTLE_PROOF_RECURSIVE did. It
cannot be landed incrementally on a live chain. tests/test_records_settle_blocker.py pins this and is
expected to FAIL the day the summary is extended, which is the signal that the wiring is now possible.

ORDERING. The update list is sorted by KEY, matching records_transition.records_updates, because the two
must agree byte-for-byte or the binding rejects an honest span. Both derive NET effects: a key touched
twice in a span is ONE update carrying its pre-state old value and its final new value.
"""
from execnode.stark import field as F
from execnode import exec_root as ER


def _VALUE_CALL_ESCROW():
    """Read protocol.SETTLE_PROOF_RECORDS_VALUE_CALLS at CALL time, not import time, so a test can flip it
    and so a node that predates the flag simply reads False. Never cache it: the value is a consensus rule
    and a stale copy would make one node derive effects another does not."""
    try:
        import protocol
        return bool(getattr(protocol, "SETTLE_PROOF_RECORDS_VALUE_CALLS", False))
    except Exception:
        return False


class Unbindable(Exception):
    """A span carries a records effect this module cannot derive from committed data. NOT an error in the
    span — the correct response is to decline the proof path and settle by bonded quorum."""


# ---- effect derivation -------------------------------------------------------------------------------
# Each entry maps an L1 reserved recipient to a function producing [(tag, parts, delta), ...]. ALLOWLIST:
# a recipient absent here is Unbindable, so a reserved recipient added later fails closed by default.

def _eff_bridge_deposit(tx):
    """L1 `bridge`: escrow on L1, credit exec-side. execnode.py's block tail calls
    credit_deposit(tx["sender"], tx["amount"]), so the credit is keyed by the DEPOSITOR."""
    addr = tx.get("sender")
    amount = int(tx.get("amount", 0))
    if not addr or amount <= 0:
        raise Unbindable("bridge deposit with no sender or non-positive amount")
    return [(ER.T_BRIDGE_BAL, (addr,), amount)]


def _eff_faucet_donation(tx):
    """L1 `faucet`: the donation is mirrored as spendable balance of the FIXED-NAME faucet CONTRACT —
    credit_deposit("faucet", amount). The literal string is the cid (state.FIXED_CIDS), so the position is
    fixed and the depositor is irrelevant."""
    amount = int(tx.get("amount", 0))
    if amount <= 0:
        raise Unbindable("faucet donation with non-positive amount")
    return [(ER.T_BRIDGE_BAL, ("faucet",), amount)]


def _eff_treasury_execute(tx):
    """L1 `treasury_execute`: a MINED one is a completed payout. It moves records ONLY when the approved
    spend targets the reserved faucet name, in which case it mirrors exactly like a donation. Any other
    approved recipient leaves the records half untouched, so it contributes no effect (not Unbindable —
    the tail provably does nothing)."""
    spend = (tx.get("data") or {}).get("spend") or {}
    if spend.get("recipient") != "faucet":
        return []
    amount = int(spend.get("amount") or 0)
    if amount <= 0:
        return []
    return [(ER.T_BRIDGE_BAL, ("faucet",), amount)]


_RECIPIENT_EFFECTS = {
    "bridge": _eff_bridge_deposit,
    "faucet": _eff_faucet_donation,
    "treasury_execute": _eff_treasury_execute,
}

# Reserved recipients KNOWN to move records but whose effect is not derivable here yet. Listed explicitly
# so the refusal is a considered "not yet", not an oversight — and so a reader can see the remaining work.
# `shield` splits by data.field into the shielded pool or the field pool; both advance a Merkle root and a
# nullifier set (T_DIGEST), which is real derivation work, not a lookup.
_KNOWN_UNDERIVED = frozenset({
    "bridge_withdraw", "dividend", "dividend_withdraw", "shield", "unshield", "xmsg",
})


def dividend_accrual_effects(inflow, weights, div_carry):
    """The records effects of ONE epoch's presence-dividend accrual, re-derived exactly as
    state._accrue_dividend_epoch_inner computes them. Returns ([(tag, parts, delta), ...], new_carry).

    Mirrors the accrual line for line — integer-only, `sorted(weights.items())`, `max(1, w)` flooring, the
    pot carrying the previous remainder, and no distribution at all when the pot or the weight total is
    non-positive (the whole inflow carries forward). Any divergence here shows up as a binding MISMATCH
    rather than a bad settlement, but it would refuse honest spans, so it must track that function.
    """
    pot = int(inflow) + int(div_carry)
    total_w = sum(max(1, int(w)) for w in weights.values()) if weights else 0
    if pot <= 0 or total_w <= 0:
        return [], max(0, pot)
    out, distributed = [], 0
    for addr, w in sorted(weights.items()):
        share = pot * max(1, int(w)) // total_w
        if share:
            out.append((ER.T_DIV_BAL, (addr,), share))
            distributed += share
    return out, pot - distributed


def epoch_accrual_due(height, epoch_length):
    """The dividend epoch that block `height` ACCRUES, or None if it accrues nothing.

    THE ATTRIBUTION HAS TO MATCH THE TAIL LOOP EXACTLY or every proof over a boundary is refused. The exec
    node accrues in `while state.last_div_epoch < cur_epoch - 1` with `cur_epoch = cursor // EPOCH_LENGTH`,
    so epoch E is accrued the moment the cursor first reaches epoch E+1 — i.e. at block (E+1)*EPOCH_LENGTH.
    Verified against a live accrual: "dividend epoch 760" was logged as the cursor passed 45660 = 761*60.

    A batch that crosses several epochs accrues each of them; each is attributed to its own boundary block
    here, so a span's effects come out in block order with the carry chaining exactly as span_effects does.
    """
    h, L = int(height), int(epoch_length)
    if h <= 0 or L <= 0 or h % L != 0:
        return None
    E = h // L - 1
    return E if E >= 0 else None


def block_records_effects(block):
    """(effects, derivable) for ONE block, from committed block data alone.

    `derivable` is False when the block moves records in a way this module cannot yet re-derive — a
    bridge_withdraw, a shield, an xmsg, or a value>0 call (whose escrow is conditional on the VM not
    reverting, so its NET effect is not a function of the calldata alone). A non-derivable block must keep
    riding the bonded quorum: returning partial effects would let a prover settle a root that silently
    omits the rest, which is the precise failure block_records_inert exists to prevent.

    This is the piece that makes the derivation reachable at all. The L1 settle branch may only read
    COMMITTED state (per-block exec summaries), never block bodies — bodies made one transaction validate
    differently on a pruned node than an archive node and forked the fleet. So the effects must be derived
    at incorporate time, from the block, and committed alongside the calls; calls_commit.block_summary does
    that and kv_ops.exec_summary_put persists it.
    """
    effects = []
    for tx in block.get("block_transactions", []) or ():
        r = tx.get("recipient")
        fn = _RECIPIENT_EFFECTS.get(r)
        if fn is not None:
            try:
                effects.extend(fn(tx))
            except Unbindable:
                return None, False
            continue
        if r in _KNOWN_UNDERIVED:
            return None, False
        if r != "blob":
            continue                                   # transfer / bond / register / duty: no exec records
        d = tx.get("data")
        if not isinstance(d, dict):
            return None, False                         # undecodable blob — cannot establish safety
        op = d.get("op")
        if op not in _RECORDS_SAFE_BLOB_OPS:
            return None, False                         # emit / bridge_withdraw / collect_dividend / …
        if op == "call":
            try:
                v = int(d.get("value") or 0)
            except (TypeError, ValueError):
                return None, False
            if v != 0:
                # The escrow (sender -> cid, two T_BRIDGE_BAL positions) happens BEFORE the VM runs and is
                # REFUNDED when the call reverts, so the net records effect depends on the execution
                # outcome, not on the calldata. Deriving it needs the exec proof's own verdict.
                #
                # THE PROOF IS THAT VERDICT (protocol.SETTLE_PROOF_RECORDS_VALUE_CALLS). zkvm.ZkVMRevert:
                # "the interpreter reverts exactly where the AIR constraints would have no satisfying
                # witness, so 'provable' and 'executes successfully' are the same set of calls." A VALID
                # proof over a span therefore already establishes that every call in it succeeded, so every
                # escrow stuck and nothing was refunded — which IS a pure function of the calldata. These
                # effects are only ever CONSULTED while a proof is being validated (calls_commit's
                # `records_out is not None` branch), so a span that never gets one rides the quorum
                # untouched and this derivation is never used against it.
                #
                # It rests on settlement_proofs._run_call mirroring the live escrow rule (1fbf4c35) — check
                # affordability, debit the sender, credit the cid. Without that the prover would accept a
                # call the chain SKIPPED, and "provable" would stop meaning "what the chain did".
                #
                # OFF BY DEFAULT AND FLIPPED AT A REROLL: this changes what incorporate_block writes into
                # `meta`, which feeds the L1 state root, so enabling it live guarantees a fork.
                if not _VALUE_CALL_ESCROW():
                    return None, False
                _sender = tx.get("sender")
                _cid = d.get("contract")
                if not _sender or not _cid:
                    return None, False               # cannot place the two positions -> stay non-derivable
                _asset = int(d.get("asset") or 0)
                if _asset:
                    # An asset-denominated call value moves the ASSET ledger, not T_BRIDGE_BAL. That ledger
                    # is not part of the records projection this module derives, so it stays out of scope
                    # rather than being half-derived — the same fail-closed rule the module already applies.
                    return None, False
                effects.append((ER.T_BRIDGE_BAL, (_sender,), -v))
                effects.append((ER.T_BRIDGE_BAL, (str(_cid),), v))
                continue
    return effects, True


# Mirrors calls_commit._RECORDS_SAFE_BLOB_OPS. Duplicated rather than imported because calls_commit imports
# THIS module (block_summary calls block_records_effects), and the reverse import would be a cycle. The
# pairing is asserted in tests/test_records_bind.py so the two cannot drift apart silently.
_RECORDS_SAFE_BLOB_OPS = frozenset({"deploy", "lock", "upgrade", "transfer_contract", "call"})


def pay_effects_from_segment(seg, reg=None):
    """Records effects of every native PAY proven in ONE settle segment, as [(tag, parts, delta), ...].

    WHY THIS CAN BE DERIVED AT ALL, when block_records_effects cannot. A payout is an EXECUTION outcome: it
    never appears in the calldata, so L1 — which does not execute contracts — is blind to it at incorporate
    time. That is why a PAY has always made a span unprovable. But the io log IS the proof: the STARK
    commits to it, and settlement_proofs._run_call "raises on revert/bad payout" using the SAME rules the
    live path applies (over-pay reverts and refunds, unresolvable payee reverts). So a VALID proof over a
    span already establishes that each payout was affordable and actually applied — exactly the argument
    SETTLE_PROOF_RECORDS_VALUE_CALLS makes for the escrow.

    THE PAYEE RESOLVES WITHOUT TRUSTING THE PROVER. `zkvm_statement` registers digest→address for the
    caller and every string arg of each call, and the prover starts from `registry = {}` and accumulates
    only within the span (settlement_proofs). Rebuilding that registry here from the segment's own COMMITTED
    calls therefore resolves exactly what the prover resolved — no more (a digest registered by some older
    call is unprovable for the prover too, so this can never refuse an honest proof) and no less. Nothing is
    read from the prover's side of the proof except the io log the STARK vouches for.

    Attribution uses the io log's own structure: replay_io requires exactly one RET, last, per call, so the
    flat epoch io splits into one RET-terminated chunk per call, in call order. The chunk count must equal
    the call count — that equality is the check that the split is real and not a coincidence.

    ASSET payouts are OUT OF SCOPE and refuse the span, matching block_records_effects: the asset ledger is
    not part of the records projection this module derives, and half-deriving it would let a prover settle a
    root that silently omits the rest.

    `reg` is the digest→address registry, SHARED across a proof's segments by pay_effects_from_proof. It is
    accumulated span-wide rather than reset per segment so the prover can derive the same set from one
    dry-run without reproducing the segmenter's boundaries. That cannot accept a payout the prover rejected:
    prove_epoch resets its registry per segment, so a payee resolvable only via an EARLIER segment makes
    split_io return None, _run_call raise, and the whole prove fail — there is no such proof to verify.
    """
    from execnode import runtimes as _rt
    from execnode import zkvm as _z
    calls = seg.get("calls") or []
    io = []
    for e in (seg.get("io") or ()):
        if not (isinstance(e, (list, tuple)) and len(e) == 3):
            raise Unbindable("malformed io entry in settle proof")
        io.append(tuple(int(x) for x in e))
    chunks, cur = [], []
    for e in io:
        cur.append(e)
        if e[0] == _z.IO_RET:
            chunks.append(cur)
            cur = []
    if cur or len(chunks) != len(calls):
        raise Unbindable(f"proof io does not split into one RET-terminated log per call "
                         f"({len(chunks)} logs vs {len(calls)} calls)")
    if reg is None:
        reg = {}
    effects = []
    for call, chunk in zip(calls, chunks):
        try:
            _rt.zkvm_statement(call.get("caller", "epoch"), call.get("args", []) or [], reg)
        except Exception as e:
            raise Unbindable(f"call statement not encodable: {e}")
        split = _rt.split_io(chunk, reg)
        if split is None:
            raise Unbindable("proof io is not a settleable log (pairing or payee resolution failed)")
        payouts, asset_fx = split
        if asset_fx:
            raise Unbindable("asset effects are outside the records projection this module derives")
        cid = call.get("cid")
        if not cid:
            raise Unbindable("segment call has no cid to debit")
        for addr, amt in payouts:
            amt = int(amt)
            if amt <= 0:
                continue                       # split_io already drops non-positive bare payouts
            # The exact pair execnode/state.py writes: bridge[cid] -= amt, bridge[to] += amt.
            effects.append((ER.T_BRIDGE_BAL, (str(cid),), -amt))
            effects.append((ER.T_BRIDGE_BAL, (str(addr),), amt))
    return effects


def pay_effects_from_proof(proof):
    """Every native PAY effect across a settle proof's segments, in order.

    Raises Unbindable if any segment's io cannot be settled — fail-closed, so a span this cannot fully
    account for keeps riding the bonded quorum rather than settling a partial root.

    ONE registry for the whole proof, so execnode's prover-side derivation (a single dry-run over the span,
    settlement_proofs.span_payout_effects) produces the identical set without having to reproduce the
    segmenter's boundaries. See pay_effects_from_segment for why span-wide accumulation cannot admit a
    payout the prover itself rejected.
    """
    reg, out = {}, []
    for seg in (proof.get("segments") or ()):
        out.extend(pay_effects_from_segment(seg, reg))
    return out


def span_effects(txs, accruals=(), div_carry=0):
    """Derive every records effect of a span, as [(tag, parts, delta), ...] in application order.

    `txs` is the span's transactions in block order (each a dict with at least `recipient`); `accruals` is
    an ordered iterable of (inflow, weights) — one per epoch the span accrues, which the caller reads from
    L1 consensus state (dividend_inflow_get(E) / weights_at_epoch(E)); `div_carry` is the exec PRE-state's
    carried sub-unit remainder. Raises Unbindable on the first effect that cannot be derived.

    The carry CHAINS across epochs exactly as the tail loop's `while state.last_div_epoch < cur_epoch - 1`
    does: epoch E's leftover is epoch E+1's pot. Taking a per-epoch carry from the caller instead would let
    a two-epoch span be derived with the wrong pot and refuse an honest proof.
    """
    effects = []
    for tx in txs or ():
        r = tx.get("recipient")
        fn = _RECIPIENT_EFFECTS.get(r)
        if fn is not None:
            effects.extend(fn(tx))
        elif r in _KNOWN_UNDERIVED:
            raise Unbindable(f"records effect of reserved recipient '{r}' is not derivable yet")
        # A recipient with no records effect at all (a plain transfer, a duty tx, a value-0 call) adds
        # nothing. It is NOT asserted safe here: calls_commit.block_records_inert is the allowlist that
        # decides that question, and this module is only reached for spans it has already vetted.
    carry = int(div_carry)
    for (inflow, weights) in accruals or ():
        eff, carry = dividend_accrual_effects(inflow, weights, carry)
        effects.extend(eff)
    return effects


def net_records_updates(pre_get, effects, depth=ER.DEPTH):
    """Fold derived effects into the ordered NET update list the records transition must prove.

    `pre_get(tag, parts) -> int` reads the PRE-state value of a record position. Returns
    [(key, old, new), ...] sorted by key, one entry per position whose net value differs from its
    pre-state — the same shape state_transition stores in tr["updates"], and the same sort order
    records_transition.records_updates produces.
    """
    # MASK TO `depth` EXACTLY AS SparseStore DOES (kk = int(k) & ((1<<depth)-1)). record_key returns the
    # full 256-bit position; at the production DEPTH=256 the mask is the identity, but a caller running a
    # smaller tree would otherwise derive unmasked keys that can never equal the store's masked ones, and
    # every honest span would fail to bind. Same trap records_transition.records_updates documents from the
    # other side — it diffs THROUGH the store rather than the raw projection for exactly this reason.
    mask = (1 << depth) - 1
    pre, cur = {}, {}
    for (tag, parts, delta) in effects:
        key = ER.record_key(tag, *parts) & mask
        if key not in cur:
            pv = int(pre_get(tag, parts)) % F.P
            pre[key] = pv
            cur[key] = pv
        cur[key] = (cur[key] + int(delta)) % F.P
    out = []
    for key in sorted(cur):
        if cur[key] != pre[key]:
            out.append((int(key), pre[key], cur[key]))
    return out


def pinned_pre_get(projection, expected_pre_root, depth=ER.DEPTH):
    """Verify a prover-supplied records PROJECTION hashes to `expected_pre_root`, then return a
    pre_get(tag, parts) over it. Raises Unbindable on mismatch.

    THE PIN IS THE POINT, and it is the same one verify_bound_epoch makes for the KV half. The binding
    needs each touched record's PRE value to compute the net update, and those values come from the
    prover. Taking them on trust would let a forged pre-value drive the arithmetic while the roots still
    chained — the settled root would then be a number the prover chose. Requiring the whole projection to
    hash to the tip's committed records root makes every read authenticated, read-only positions included.
    """
    from execnode.stark import storage_tree as ST
    mask = (1 << depth) - 1
    proj = {int(k) & mask: int(v) % F.P for k, v in (projection or {}).items()}
    got = tuple(int(x) % F.P for x in ST.SparseStore(depth, proj).root())
    want = tuple(int(x) % F.P for x in expected_pre_root)
    if got != want:
        raise Unbindable("supplied records pre-state does not hash to the committed records root")

    def _get(tag, parts):
        return proj.get(ER.record_key(tag, *parts) & mask, 0)
    return _get


def bind_and_verify_records(tr, pre_root, post_root, pre_get, effects, depth=ER.DEPTH,
                            num_queries=None, outer_queries=None):
    """Verify a records transition AND that its updates are EXACTLY the span's derived records effects.

    (1) derive the net updates from committed data; (2) require tr["updates"] == that set, in order;
    (3) verify the transition advances pre_root -> post_root. All three together mean the transition is
    THIS span's records transition and not an arbitrary one — the property records_transition alone could
    not provide, and the reason block_records_inert has to be as strict as it is. Returns (ok, reason).
    """
    from execnode.stark import records_transition as RT
    # SPLIT THE TWO COSTS. This call is the single most expensive thing L1 does — measured 878-1073 s live,
    # and on 2026-08-07 it grew past the 1200 s submit budget, so the client disconnected and ~20 minutes of
    # proving plus ~20 minutes of verification were discarded with NOTHING logged (the timing print only
    # runs on completion, so a cancelled verify is indistinguishable from one that never started).
    #
    # There are exactly two phases and they call for OPPOSITE fixes: `derive` is 29 effects x depth-256
    # authenticated merkle reads through pinned_pre_get, and `stark` is the batch-proof verification. If
    # `stark` dominates, the K->1 recursion fold is the fix, because a folded bundle is ONE verification
    # instead of ceil(updates/K). If `derive` dominates, the fold buys nothing and the projection is the
    # target. Guessing between them is how I lost this night twice already — so measure them apart.
    import time as _t
    try:
        _t0 = _t.time()
        want = [(int(k), int(o) % F.P, int(n) % F.P)
                for (k, o, n) in net_records_updates(pre_get, effects, depth)]
        _derive_s = _t.time() - _t0
        got = [(int(k), int(o) % F.P, int(n) % F.P) for (k, o, n) in tr.get("updates", [])]
        if got != want:
            return False, (f"records transition updates do not match the span's derived effects "
                           f"({len(got)} vs {len(want)})")
        _t1 = _t.time()
        _res = RT.verify_records_transition(tr, pre_root, post_root, num_queries=num_queries,
                                            outer_queries=outer_queries)
        print(f"[records-bind] derive {_derive_s:.1f}s ({len(want)} update(s)) · "
              f"stark {_t.time() - _t1:.1f}s · total {_t.time() - _t0:.1f}s", flush=True)
        return _res
    except Unbindable as e:
        return False, f"span carries an underivable records effect: {e}"
    except Exception as e:
        return False, f"records binding failed: {type(e).__name__}: {e}"
