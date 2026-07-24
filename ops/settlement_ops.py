"""
Execution-layer SETTLEMENT (Phase 2): derive the canonical SETTLED execution-layer state root from bonded
validators' settlement attestations. A (exec_cursor, state_root) is SETTLED when the bonded shares
attesting it strictly exceed SETTLE_NUM/SETTLE_DEN of the total bonded shares — the same stake-quorum
shape as FFG-lite finality (ops/attestation_ops). Pure, deterministic, integer-only over committed state.

settlement_justified() is the single predicate L1 uses to accept an execution-layer state root. It is
justified TWO ways, both pure functions of committed on-chain state (so every node agrees — no fork):
  • VALIDITY PROOF (Phase-2b, trustless): a `settle`-with-proof tx carried a succinct recursion proof that
    every node verified DETERMINISTICALLY at block-validation, recording the on-chain marker
    kv_ops.settlement_proven(ns, cursor, root). One proven root justifies with NO quorum.
  • BONDED QUORUM (Phase-2a, liveness floor): bonded shares attesting the same (cursor, root) exceed
    SETTLE_NUM/SETTLE_DEN of the ACTIVE settler shares (the participation-windowed inactivity leak).
The proof path is checked first (cheapest + trustless); the quorum path keeps settlement live when no proof
has landed yet. The old node-local verifier callback is GONE — proof authority now lives on-chain, where
transaction-validation reads (cross-msg / dividend / unshield / bridge exit) stay deterministic by construction.
"""
from ops import kv_ops
from ops.account_ops import get_bonded_registry
from ops.mining_ops import total_bonded_shares, selection_shares
from protocol import SETTLE_NUM, SETTLE_DEN, DEFAULT_NS, SETTLE_ACTIVITY_CURSORS


def active_settler_shares(ns: str, bonded_registry: dict) -> int:
    """SETTLEMENT INACTIVITY LEAK (protocol.SETTLE_ACTIVITY_CURSORS — participation-windowed quorum):
    total bonded shares of validators that posted a settle attestation for `ns` within the activity
    window of the HIGHEST attested cursor. Bonded validators that never run an exec+settle node LEAK
    from the quorum denominator instead of blocking settlement forever — going dark forfeits their
    say in the settled root (their bond is untouched), and they re-enter the moment they attest.
    Deterministic: attestations are committed on-chain state, so every node derives the same set."""
    top = kv_ops.settlement_max_cursor(ns)
    if top < 0:
        return 0
    active = kv_ops.settlement_validators_since(ns, top - SETTLE_ACTIVITY_CURSORS)
    return sum(selection_shares(bonded_registry[v]["bonded"]) for v in active if v in bonded_registry)


def settlement_justified(ns: str, cursor: int, state_root: str, bonded_registry: dict) -> bool:
    """True when (ns, cursor, state_root) is justified: an ON-CHAIN validity-proof marker is set for it
    (a settle-with-proof verified deterministically at block-validation) OR the bonded shares attesting it
    STRICTLY EXCEED SETTLE_NUM/SETTLE_DEN of the ACTIVE settler shares (the inactivity leak above — the
    denominator was ALL bonded stake, which froze settlement, and with it every dividend/bridge/unshield
    claim, as soon as non-settling validators bonded past 1/3). Both branches read only committed on-chain
    state, so the result is identical on every node. Integer comparison (attesting*SETTLE_DEN > total*SETTLE_NUM).

    TRUSTLESS PROOF: DISABLED (quorum-only). The calls_commit DA-binding closes the "fabricated call sequence"
    hole for a single-block, revert-free, record-move-free epoch, but the trustless path is NOT yet safe to
    trust: (1) the on-chain binding check reads every block in the settled span via get_block_number, which
    returns falsy on a PRUNED node and the body on an archive node -> the same settle-with-proof validates
    differently across the fleet -> consensus fork (the first proof-settle spans block 0, guaranteed pruned).
    (2) the RECORDS half is unbound: a bound call with value>0 / PAY moves records, but the proof pins rec_hex
    to the tip's records -> a records-frozen root omitting real payouts is provable. (3) block_calls binds ALL
    op=='call' blobs (incl. skip/revert) but the prover can't build a bundle over a reverting call, and a
    multi-block segment folds one epoch-wide cursor/ts vs L1's per-block -> valid proofs are rejected. Until the
    prover emits per-call cursor/ts + in-proof skip/revert + a records-half binding, and the span is fenced to
    the retention window, settlement stays on the bonded quorum (which re-executes the REAL DA blobs and is
    sound). No live prover posts proofs today, so nothing regresses."""
    # if kv_ops.settlement_proven(ns, cursor, state_root):
    #     return True   # DISABLED — see above: DA-binding needs prover-side work + a prune-safe span before trust
    total = active_settler_shares(ns, bonded_registry)
    if total == 0:
        return False
    attesting = 0
    for validator, root in kv_ops.settlements_for_cursor(ns, cursor):
        if root == state_root and validator in bonded_registry:
            attesting += selection_shares(bonded_registry[validator]["bonded"])
    return attesting * SETTLE_DEN > total * SETTLE_NUM


def latest_settled(ns: str = DEFAULT_NS):
    """The (exec_cursor, state_root) with the HIGHEST cursor currently justified in namespace `ns`, or
    (-1, None) if none. DERIVED (not a stored watermark) so it is revert-safe — rolling back a settle tx
    removes its attestation and this recomputes. Uses the current committed bonded registry."""
    reg = get_bonded_registry()
    if total_bonded_shares(reg) == 0:
        return (-1, None)
    # walk DESCENDING and return the first justified (cursor, root) — the old ascending full scan
    # re-evaluated every cursor ever attested (O(history) per call, on the claim-validation path).
    for cursor in reversed(kv_ops.settlement_cursors(ns)):
        seen = set()
        for _v, root in kv_ops.settlements_for_cursor(ns, cursor):
            if root in seen:
                continue
            seen.add(root)
            if settlement_justified(ns, cursor, root, reg):
                return (cursor, root)
    return (-1, None)


def settled_header_commitment(ns: str = DEFAULT_NS):
    """The (exec_cursor, exec_root) the L1 block header commits to BIND L2 into the L1 hash chain: the
    highest L1-JUSTIFIED settled (cursor, root) for `ns` as of committed state, or the empty sentinel
    (-1, EXEC_GENESIS_ROOT) before any settlement is justified (so the field is always a valid 64-hex).

    This is a PURE read of on-chain settlement attestations + the bonded registry — BOTH of which already
    live in SNAPSHOT_DBS and are therefore already folded into the L1 state_root. So every node at the same
    parent state derives the IDENTICAL pair, which is exactly what makes it safe to fold into the block
    hash. The live per-block exec root can NOT be committed (the exec node applies only FINALIZED blocks —
    a ~FINALITY_DEPTH lag — in a separate process, and the root is expensive + prunable), so the strongest
    per-block-available L2 anchor is this justified SETTLED root. It binds the settled root into the
    immutable L1 hash (reorg-consistent, unforgeable-by-a-relay, first-class for exits/light-clients); it
    does NOT by itself re-derive the exec computation — that trust stays on the bonded settle quorum until
    the trustless proof path is enabled. Default ns only is committed EXPLICITLY; every other ns stays bound
    transitively through the settlement attestations already inside state_root."""
    from protocol import EXEC_GENESIS_ROOT
    cursor, root = latest_settled(ns)
    if root is None:
        return -1, EXEC_GENESIS_ROOT
    return int(cursor), root


def _vote_activated(info: dict, current_epoch: int) -> bool:
    """A validator's bonded stake counts toward a treasury vote only once it has AGED
    TREASURY_VOTE_ACTIVATION_EPOCHS (anti flash/exchange capture). bond_since == 0 is genesis/fully-aged."""
    from protocol import TREASURY_VOTE_ACTIVATION_EPOCHS
    bs = int(info.get("bond_since", 0) or 0)
    return bs == 0 or (current_epoch - bs) >= TREASURY_VOTE_ACTIVATION_EPOCHS


def treasury_justified(pid: str, bonded_registry: dict, current_epoch: int) -> bool:
    """True when the ACTIVATED bonded shares that voted to approve treasury proposal `pid` STRICTLY EXCEED
    SETTLE_NUM/SETTLE_DEN of the total ACTIVATED bonded shares — the identical 2/3 stake quorum shape as
    settlement/finality (approving*SETTLE_DEN > total*SETTLE_NUM, integer-only). The electorate is bonded
    stake that has aged past TREASURY_VOTE_ACTIVATION_EPOCHS, so freshly-bonded stake neither approves NOR
    dilutes the vote. Sole authorization for a treasury_execute payout; the bonded lane IS the multisig.
    (doc/treasury.md §3.3)"""
    # DENOMINATOR: the live activated electorate (fresh stake is outside it entirely).
    total = sum(selection_shares(info["bonded"]) for info in bonded_registry.values() if _vote_activated(info, current_epoch))
    if total == 0:
        return False
    # NUMERATOR: each approval counted at the weight SNAPSHOTTED when the vote was cast (not the live weight),
    # so topping up bonded stake AFTER voting cannot inflate an approval, and a voter who has since unbonded
    # below B_MIN (not in bonded_registry) contributes nothing.
    approving = sum(kv_ops.treasury_vote_weight(pid, v) for v in kv_ops.treasury_voters(pid) if v in bonded_registry)
    return approving * SETTLE_DEN > total * SETTLE_NUM
