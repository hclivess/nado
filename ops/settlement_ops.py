"""
Execution-layer SETTLEMENT (Phase 2): derive the canonical SETTLED execution-layer state root from bonded
validators' settlement attestations. A (exec_cursor, state_root) is SETTLED when the bonded shares
attesting it strictly exceed SETTLE_NUM/SETTLE_DEN of the total bonded shares — the same stake-quorum
shape as FFG-lite finality (ops/attestation_ops). Pure, deterministic, integer-only over committed state.

This module IS the pluggable verifier seam. settlement_justified() is the single predicate L1 uses to
accept an execution-layer state root. Phase-2a implements it as a bonded-stake quorum; Phase-2b can
replace it with verification of ONE succinct validity proof (a STARK over the blob→state transition)
behind the exact same signature — nothing else in L1 changes.
"""
from ops import kv_ops
from ops.account_ops import get_bonded_registry
from ops.mining_ops import total_bonded_shares, selection_shares
from protocol import SETTLE_NUM, SETTLE_DEN, DEFAULT_NS, SETTLE_ACTIVITY_CURSORS

# PHASE-2b SEAM. A validity-proof verifier can be registered here to justify a settled root WITHOUT a bonded
# quorum: a callable (ns, cursor, state_root) -> bool that checks a single succinct STARK over the
# blob→state transition. Default None ⇒ Phase-2a bonded-quorum only. When set, a root is justified if the
# proof verifies OR the quorum is met (proof-preferred, quorum as liveness fallback during rollout). This is
# the ONLY line that changes to flip the settlement layer from committee-trust to cryptographic-trust; the
# arbitrary-execution zkVM prover that would back it is a separate crypto build (see doc/settlement-layer.md).
_PROOF_VERIFIER = None


def set_settlement_verifier(fn):
    """Install (or clear, with None) the Phase-2b validity-proof verifier. fn(ns, cursor, state_root)->bool."""
    global _PROOF_VERIFIER
    _PROOF_VERIFIER = fn


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
    """True when (ns, cursor, state_root) is justified: a Phase-2b validity proof verifies (if a verifier is
    installed) OR the bonded shares attesting it STRICTLY EXCEED SETTLE_NUM/SETTLE_DEN of the ACTIVE
    settler shares (the inactivity leak above — the denominator was ALL bonded stake, which froze
    settlement, and with it every dividend/bridge/unshield claim, as soon as non-settling validators
    bonded past 1/3). Integer comparison (attesting*SETTLE_DEN > total*SETTLE_NUM) — no floats."""
    if _PROOF_VERIFIER is not None:
        try:
            if _PROOF_VERIFIER(ns, cursor, state_root):
                return True
        except Exception:
            pass   # a broken/absent proof falls through to the bonded-quorum path (never blocks settlement)
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
