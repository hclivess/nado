"""
Registration-rate PoSW difficulty (doc/ip-spoofing-and-sybil.md) — CONSENSUS-BOUND, v3 (state-derived).

The required PoSW work for a `register` scales with recent registration volume, so a sudden flood of identities
gets progressively more expensive. This is enforced in validate_transaction: every node recomputes the required
difficulty and REJECTS a registration whose PoSW does not prove it. An attacker who edits their own node to
skip the client-side work simply produces proofs that every HONEST node rejects — the difficulty is not a
client courtesy, it is a validity rule.

WHY v2 (2026-07-17 betanet-6 split postmortem): v1 computed the multiplier from the LIVE recert_by_epoch
LMDB index and its window INCLUDED the anchor's own, still-filling epoch. Both silently broke the determinism
a validity rule requires:
  1. The index is incrementally maintained (insert on apply, delete on rollback) and SURVIVES upgrades — fleet
     nodes that kept pre-reroll rows computed an inflated trailing baseline and accepted 2× proofs, while a
     clean node's honest count demanded 3×. The clean nodes rejected the canonical block #2944 wholesale and
     wedged in emergency mode for 10+ hours re-excluding every tip the fleet advertised.
  2. Because the anchor epoch was still filling, a register landing between prove-time and land-time could
     raise the requirement and invalidate an honest in-flight proof (posw.verify is EXACT-T: over- or
     under-working both fail), randomly rejecting honest registrants.

v2 derived counts by COUNTING `register` txs in the BLOCKS of complete epochs strictly before the anchor.

WHY v3 (2026-07-18, the all-day re-anchor-churn postmortem): v2 was a pure function of (chain, LOCAL BODY
VISIBILITY) — and visibility is node-local. Nodes bootstrap from SNAPSHOTS and prune bodies; v2's silent
`return 0` for a locally-missing epoch turned heterogeneous retention into a consensus fork. Proven live
with numbers: a full-history fleet node counted ~57 registers in the recent window over a partially visible
trail (baseline floored at 20) and required 2×, while a snapshot-booted node saw only 9 (multiplier 1×);
posw.verify is EXACT-T, so each side rejects the other's honest registers and every register-bearing block
splits them — a freshly re-anchored node re-truncates its own visibility and loops forever, and EVERY new
node joining by snapshot inherits the incompatibility on arrival.

v3 therefore counts from the recert_by_epoch STATE INDEX, which since the betanet-6 generation is
CONSENSUS STATE, not a node-local convenience:
  · it is snapshot-carried and validated by the snapshot state_root at import (ops/snapshot_ops) — a
    snapshot-booted node holds EXACTLY the counts a from-genesis node derived, with zero bodies retained;
  · apply_register maintains it revert-symmetrically (recert_put on apply, recert_del on rollback);
  · validate_transaction enforces ONE register per (sender, epoch), so the DUPSORT pair-collapse is
    unreachable and rows == register txs exactly.
The v1 sin was never "an index" — it was an UNVALIDATED index (pre-reroll junk rows survived upgrades)
plus a still-filling window. Both stay cured: the carriage is state_root-validated, and windows still end
strictly before the anchor epoch, so every counted row is settled before the anchor block exists.

STRICT, NO COMPATIBILITY (policy): every node computes the identical v3 requirement for every height —
deployed as the PROTOCOL 4 flag day (old-rules nodes are shed at the handshake), never as a compat path
in consensus code.
"""
from protocol import (POSW_ENTRY_MULT, POSW_LEASE_EPOCHS, POSW_T, POSW_DIFF_WINDOW, POSW_DIFF_TRAIL,
                      POSW_DIFF_FLOOR, POSW_DIFF_MAX_MULT, EPOCH_LENGTH, POSW_DIFF_TRAIL_LONG, SYBIL_RULES_EPOCH)


def chain_register_count(epoch: int) -> int:
    """Number of `register` txs the CURRENT chain landed in `epoch` — read from the recert_by_epoch
    CONSENSUS state index (see the module docstring: snapshot-carried + state_root-validated, revert-
    symmetric, one-register-per-(sender,epoch) so rows == txs exactly). VISIBILITY-FREE: identical on a
    from-genesis node and a snapshot-booted node with zero bodies retained. Epochs before genesis (or with
    no registers) are a true 0 — never a silent stand-in for "blocks missing locally"."""
    from ops import kv_ops
    if epoch < 0:
        return 0
    return kv_ops.recert_count_in_window(epoch, epoch)


# Per-epoch register counts of epochs strictly below the hard-finality epoch are IMMUTABLE (no rollback may
# cross that floor), so they are memoised: the 14-day trail (POSW_DIFF_TRAIL_LONG = 3360 epochs) would
# otherwise cost 3360 index range-counts per register validation, and a block carries many registers.
# Keyed by env path so tests that switch HOME never read another home's counts; recent epochs recompute.
_count_memo = {}


def _memo_count(epoch: int) -> int:
    from ops import kv_ops
    from ops.account_ops import get_hard_finality
    key = (kv_ops.env_path(), epoch)
    v = _count_memo.get(key)
    if v is not None:
        return v
    v = chain_register_count(epoch)
    if epoch < int(get_hard_finality() or 0) // EPOCH_LENGTH - 1:
        if len(_count_memo) > 100_000:
            _count_memo.clear()
        _count_memo[key] = v
    return v


def _window_count(lo_epoch: int, hi_epoch: int) -> int:
    """Sum of chain_register_count over epochs [lo_epoch, hi_epoch] inclusive (negatives skipped)."""
    if hi_epoch < lo_epoch:
        return 0
    return sum(_memo_count(e) for e in range(max(0, lo_epoch), hi_epoch + 1))


def difficulty_multiplier(anchor_epoch: int) -> int:
    """Integer PoSW multiplier for a registration anchored in `anchor_epoch`. 1× under normal load; rises as
    the recent registration rate exceeds the trailing-average baseline, capped at POSW_DIFF_MAX_MULT.
    Windows END at anchor_epoch − 1: every counted epoch is COMPLETE before the anchor block exists, so the
    prover (who needs the anchor hash) and every validator (whose chain contains the anchor) read identical,
    settled chain data — the requirement can never change between prove-time and land-time."""
    last = anchor_epoch - 1
    if last < 0:
        return 1
    recent = _window_count(last - POSW_DIFF_WINDOW + 1, last)
    trail = _window_count(last - POSW_DIFF_TRAIL + 1, last)
    baseline = max(POSW_DIFF_FLOOR, trail * POSW_DIFF_WINDOW // POSW_DIFF_TRAIL)
    if anchor_epoch >= SYBIL_RULES_EPOCH:
        # SLOW-ADAPTING BASELINE (protocol "SYBIL RULES", rule 3). The 2-day trail alone let a sustained burst
        # become its own baseline: measured 2026-09-01, 189 registrations per window on day 3 of a burst and a
        # multiplier of 1x. Cap the baseline by the 14-day rate as well, so a burst pays the multiplier for a
        # fortnight while the honest steady state (2-day rate == 14-day rate) is untouched.
        trail_long = _window_count(last - POSW_DIFF_TRAIL_LONG + 1, last)
        baseline = max(POSW_DIFF_FLOOR, min(baseline, trail_long * POSW_DIFF_WINDOW // POSW_DIFF_TRAIL_LONG))
    return min(POSW_DIFF_MAX_MULT, max(1, recent // baseline))


def is_entry_registration(sender: str, anchor_epoch: int) -> bool:
    """True if `sender` held NO valid presence lease as of `anchor_epoch` — a NEW identity (or one that let
    its lease lapse) ENTERING the open lane, rather than an established one renewing.

    DETERMINISM, which is the whole difficulty of putting this in consensus. Every input is settled chain
    state that both the prover and every validator read identically:
      * `anchor_epoch` is derived from the tx's own max_block (minus POSW_ANCHOR_OFFSET), so it is a
        FINALIZED past epoch, not a moving target;
      * the recert history is the snapshot-carried, state_root-validated recert index, read only as far
        back as POSW_LEASE_EPOCHS (240) — far inside any GC horizon, so a snapshot-booted node and a
        from-genesis node agree (the failure mode that split betanet-6; see the v2/v3 notes above);
      * it depends ONLY on the sender's own recerts, which only the sender can extend and only once per
        epoch — so nothing another actor does can change the answer between prove-time and land-time.
    """
    if anchor_epoch < 0:
        return True
    from ops import kv_ops                              # local, mirroring chain_register_count above
    hist = kv_ops.recert_epochs(sender, upto_epoch=anchor_epoch)
    if not hist:
        return True                                    # never registered -> entry
    return (anchor_epoch - hist[-1]) > POSW_LEASE_EPOCHS   # lease had lapsed -> re-entry


def entry_multiplier(sender, anchor_epoch: int) -> int:
    """POSW_ENTRY_MULT for a new/lapsed identity, else 1. UNCONDITIONAL: this ships with a genesis reroll,
    so there are no pre-rule proofs to keep valid and no historical blocks to re-validate."""
    if sender is None:
        return 1
    return POSW_ENTRY_MULT if is_entry_registration(sender, anchor_epoch) else 1


def required_posw_t(anchor_epoch: int, sender=None) -> int:
    """The CONSENSUS number of sequential PoSW steps a registration anchored in `anchor_epoch` must prove =
    POSW_T × rate multiplier × entry multiplier. Recomputed by every node in validation and enforced against
    the proof. `sender` is optional only so callers that merely want to DISPLAY the rate multiplier (the
    /posw_difficulty endpoint with no address) keep working; validation always passes it."""
    return POSW_T * difficulty_multiplier(anchor_epoch) * entry_multiplier(sender, anchor_epoch)


# mint_multiplier() lived here: "the multiplier OUR OWN prover works at". It returned the RATE multiplier
# only, so anything minting from it under-worked an ENTRY registration by POSW_ENTRY_MULT and had the proof
# rejected by every node. Its last caller (core_loop.maybe_auto_register) had already been moved onto
# required_posw_t(); leaving the function behind as the obvious-looking thing to reach for is how the same
# bug gets reintroduced. There is exactly one way to ask what a registration owes: required_posw_t().
