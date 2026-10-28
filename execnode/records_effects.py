"""
THE RECORDS-HALF EFFECTS a block or a dividend epoch commits (SETTLE_PROOF_RECORDS; kv_ops.exec_summary_put).

incorporate_block derives, from every block body, the exec layer's RECORDS-half effects (block_records_effects) and,
on a dividend-epoch boundary, the presence-dividend accrual (epoch_accrual_due + dividend_accrual_effects), and persists
them in the block's exec summary in L1 `meta`, which FEEDS THE L1 STATE ROOT. dividend_accrual_effects is also THE
accrual rule the exec node applies (state.accrue_dividend_epoch), so the committed effects and the applied ones cannot
drift. Every function here is consensus and must stay byte-identical on replay.

An effect is (tag, parts, delta): tag is an exec_root_b2 record tag (T_BRIDGE_BAL / T_DIV_BAL / T_ASSET_BAL), parts the
record's key, delta a signed integer amount.

FAIL CLOSED. A block that moves records in a way this module cannot derive from committed data alone (a shield, an xmsg,
a withdrawal, an undecodable blob, a recipient added later) answers (None, False): non-derivable. An allowlist, the same
shape as calls_commit.block_records_inert, whose comment records that the denylist shape "rotted here twice: it fails
OPEN when someone adds a tenth record type".

G9 slice 4 moved this module out of execnode/stark (it was records_bind.py) and deleted what only the Goldilocks
settle-proof verifier (deleted in slice 2) read: the records-transition binding (net_records_updates, pinned_pre_get,
bind_and_verify_records), the pinned asset shadow (PinnedAssets, asset_records_effects) and the retired Goldilocks exec
root (execnode/exec_root.py) its record tags came from. The tags are exec_root_b2's, the same integers.
"""
from execnode import exec_root_b2 as ER


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


def dividend_accrual_effects(inflow, weights, div_carry, epoch=None):
    """The records effects of ONE epoch's presence-dividend accrual — THE rule, called by the live accrual
    (state.accrue_dividend_epoch) and by the settle binding alike, so the two cannot drift. Returns
    ([(tag, parts, delta), ...], new_carry). Integer-only, `sorted(weights.items())`, `max(1, w)` flooring.

    CARRY. No present set (or no pot): nothing is distributed and the whole pot carries forward. The carry is
    METERED at every epoch: an epoch releases at most max(inflow, floor) of the backlog on top of its own inflow, so
    a backlog built while everyone was on probation drains over hours to everyone leaving probation, not to the first
    identity out (epoch 194 of betanet-6 paid 113 NADO to one address). The gate that kept the old unmetered rule
    (gen 24's DIV_CARRY_METER_EPOCH, 0 from gen 25) and its `epoch is None` branch were deleted after the betanet-8
    reroll (SCHEDULED_CLEANUPS.md): every production caller passes the accrued epoch, an int >= 0
    (state.accrue_dividend_epoch from the exec tail, core_loop._accrual_effects, execnode's records derivation), for
    which the meter already applied. `epoch` stays in the signature so every caller reads the same.
    """
    from protocol import DIV_CARRY_RELEASE_FLOOR
    inflow, carry = int(inflow), int(div_carry)
    total_w = sum(max(1, int(w)) for w in weights.values()) if weights else 0
    release = min(max(0, carry), max(inflow, int(DIV_CARRY_RELEASE_FLOOR)))
    pot, held = inflow + release, carry - release
    if pot <= 0 or total_w <= 0:
        return [], max(0, pot) + held
    out, distributed = [], 0
    for addr, w in sorted(weights.items()):
        share = pot * max(1, int(w)) // total_w
        if share:
            out.append((ER.T_DIV_BAL, (addr,), share))
            distributed += share
    return out, (pot - distributed) + held

def epoch_accrual_due(height, epoch_length):
    """The dividend epoch that block `height` ACCRUES, or None if it accrues nothing.

    THE ATTRIBUTION HAS TO MATCH THE TAIL LOOP EXACTLY or every proof over a boundary is refused. The exec
    node accrues in `while state.last_div_epoch < cur_epoch - 1` with `cur_epoch = cursor // EPOCH_LENGTH`,
    so epoch E is accrued the moment the cursor first reaches epoch E+1 — i.e. at block (E+1)*EPOCH_LENGTH.
    Verified against a live accrual: "dividend epoch 760" was logged as the cursor passed 45660 = 761*60.

    A batch that crosses several epochs accrues each of them; each is attributed to its own boundary block
    here, so a span's effects come out in block order with the carry chaining epoch to epoch.
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
                # THE PROOF IS THAT VERDICT (protocol.SETTLE_PROOF_RECORDS_VALUE_CALLS). zkvm2.ZkVMRevert:
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
                    # An asset-denominated call value moves the ASSET ledger, not T_BRIDGE_BAL: the live apply
                    # escrows `value` of that asset from the caller's row to the contract's (execnode/state.py).
                    # The escrow is derived like the native one ("the proof is the verdict"), and
                    # (records_bind.PinnedAssets replayed it into the asset shadow for the Goldilocks settle verifier;
                    # deleted with it in G9.) This list is committed into the exec summary, i.e.
                    # the L1 state root. No height guard: gen 27's ZK_HARDEN_HEIGHT (1 from gen 28, deleted) kept
                    # the block non-derivable below it, and a transaction is never in block 0 (genesis is empty).
                    #
                    # KEYED EXACTLY AS THE LIVE APPLY KEYS IT: str(payload asset). A non-canonical spelling
                    # ("0123", " 123") names no asset live (the call is skipped) while the proof path reads it
                    # as an int, so such a block stays non-derivable rather than binding two different keys.
                    _aid = str(d.get("asset"))
                    if _aid != str(_asset):
                        return None, False
                    effects.append((ER.T_ASSET_BAL, (_aid, _sender), -v))
                    effects.append((ER.T_ASSET_BAL, (_aid, str(_cid)), v))
                    continue
                effects.append((ER.T_BRIDGE_BAL, (_sender,), -v))
                effects.append((ER.T_BRIDGE_BAL, (str(_cid),), v))
                continue
    return effects, True


# Mirrors calls_commit._RECORDS_SAFE_BLOB_OPS: the same allowlist on both sides of the summary (the inert bit and the
# effects), kept apart so neither module imports the other. tests/test_records_effects_are_derived_from_committed_data.py
# pins that the two agree.
_RECORDS_SAFE_BLOB_OPS = frozenset({"deploy", "lock", "upgrade", "transfer_contract", "call"})
