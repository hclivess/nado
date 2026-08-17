"""CANONICAL-CHAIN RESTORE across a re-anchor — the plan that lets an archive node come out of wedge
recovery with every canonical block it went in with.

WHY THIS EXISTS. On 2026-08-17 this node's archive was truncated TWICE by wedge recovery — history 0 →
49735 at 01:47, then 49735 → 56735 at 13:32 — without a single block being pruned. Re-anchoring did it,
in three ways at once:

  1. adopt_new_identity dropped every block-body locator and reset the segment store, then the backfill
     re-fetched only a fixed window (REWARD_WINDOW + 2*EPOCH_LENGTH + FINALITY_DEPTH) below the anchor.
  2. import_snapshot REPLACES block_by_num / block_by_hash with the donor's payload, and that payload is
     WINDOWED to [C-INDEX_RETENTION_NUM, C] / [C-INDEX_RETENTION_HASH, C]. An archive's deep number<->hash
     index is gone after any import, even from an archive donor.
  3. Nothing distinguished "a block on the fork we are leaving" from "a block below the fork point" — and
     the latter is the majority chain's own history, common to both chains, which we were serving a minute
     earlier.

The requirement (operator, 2026-08-17): an archive node must never lose any block of the CANONICAL chain.
Blocks on the abandoned fork are not history and go; blocks below the fork point are history and stay.

HOW. This module is the PURE decision — no LMDB, no network — so it can be tested exhaustively and the
executor in loops/core_loop.py is a thin walk over its answer.

  * The old index (captured BEFORE import) is our own chain, top to bottom. The new index (read back AFTER
    import) is the canonical chain, windowed. Where they agree at a height, that height and EVERYTHING
    BELOW IT is canonical by chain induction (each block's parent_hash pins the one beneath), so the fork
    point F is the highest agreeing height and the old index below F is authoritative — no body reads.
  * Above F the new index is authoritative. Between them (only when the fork is deeper than the donor's
    index window — an escalated recovery) hashes are UNDETERMINED here and the executor resolves them by
    walking parent_hash down from the lowest determined block, fetching from the donor as it goes.
  * KEEP a local body iff its hash is canonical. Non-canonical bodies ABOVE F are the fork and are
    unreferenced; bodies at or below F that we cannot name (older than any index we hold) are kept as
    presumptively canonical — nothing that deep can be a fork of a chain we just verified above it, and
    deleting history on the strength of "I can't prove it" is the failure this exists to end.
  * RE-PUT every deep index row the import dropped, from the old index. Those rows sit outside the
    snapshot identity (the payload window), so restoring them is unobservable to consensus and restores
    get_block_number for the whole archive.
  * REPORT what is missing so the executor can fetch it — ALL of it on an archive node, the rollback
    window on a rolling one — rather than a fixed depth.

Nothing here decides how much to fetch; that is the archive/rolling policy in the executor.
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class RestorePlan:
    anchor: int
    fork_point: Optional[int]                 # highest height old and new agree on; None = no overlap agrees
    new_floor: Optional[int]                  # lowest height the imported index covers; None = empty index
    canonical: Dict[int, str]                 # height -> hash, for every height this plan can NAME
    reput: List[Tuple[int, str]]              # deep index rows the import dropped, to be re-put
    missing: List[Tuple[int, str]]            # canonical (height, hash) with no local body — highest first
    undetermined: Optional[Tuple[int, int]]   # (lo, hi) heights whose hash needs a parent-hash walk
    kept: int = 0                             # local bodies confirmed canonical
    notes: List[str] = field(default_factory=list)

    def is_fork_body(self, height: int, block_hash: str) -> bool:
        """A local body is a FORK body — safe to unreference — iff we can NAME the canonical block at its
        height and it is a different one. A body at a height we cannot name is kept: it may be deep
        canonical history older than any index we hold, and deleting it on the strength of "I can't
        prove it" is the failure this module exists to end."""
        return height in self.canonical and self.canonical[height] != block_hash


def fork_point(old_index: Dict[int, str], new_index: Dict[int, str]) -> Optional[int]:
    """Highest height at which our old chain and the adopted chain carry the SAME hash, or None.

    Highest, not lowest: two chains that share genesis agree at 0 trivially; the fork point is where
    they STOP agreeing. Below it, chain induction makes the old index authoritative."""
    common = set(old_index) & set(new_index)
    agree = [h for h in common if old_index[h] == new_index[h]]
    return max(agree) if agree else None


def plan(old_index: Dict[int, str], new_index: Dict[int, str], anchor: int,
         has_body: Callable[[str], bool]) -> RestorePlan:
    """Decide what is canonical, what to keep, what to re-index and what to fetch. See module doc.

    `old_index`  our number->hash rows captured BEFORE import (may itself be partial on a node that was
                 truncated before — today's box).
    `new_index`  the rows present AFTER import (the donor's windowed payload).
    `anchor`     the imported checkpoint height C. Everything above C is the tail sync's business.
    `has_body`   hash -> whether a local body is referenced (a block_loc lookup; no body read)."""
    old_index = {int(h): v for h, v in (old_index or {}).items()}
    new_index = {int(h): v for h, v in (new_index or {}).items() if int(h) <= anchor}
    F = fork_point(old_index, new_index)
    new_floor = min(new_index) if new_index else None
    canonical: Dict[int, str] = {}
    notes: List[str] = []

    # Above the fork point (or everywhere the new index reaches, if no fork point): the adopted chain.
    for h, bh in new_index.items():
        canonical[h] = bh
    # At and below the fork point: our own chain, by induction.
    if F is not None:
        for h, bh in old_index.items():
            if h <= F:
                canonical[h] = bh
    else:
        notes.append("old and new index share no agreeing height — the fork is deeper than the donor's "
                     "index window; the deep chain must be recovered by parent-hash walk")

    # Heights the plan cannot name: below the new index's floor and above F (deep fork), or below the
    # new floor when there is no F at all. The executor walks parent_hash down through them.
    undetermined = None
    if new_floor is not None and new_floor > 0:
        lo_named = F + 1 if F is not None else 0
        if lo_named < new_floor:
            undetermined = (lo_named, new_floor - 1)

    # Deep index rows the import threw away: every canonical height below the new floor that we can name.
    reput = sorted((h, bh) for h, bh in canonical.items()
                   if new_floor is None or h < new_floor)

    # Bodies: keep what is canonical and present; list what is canonical and absent, highest first, so
    # an interrupted fetch has already filled the rollback window nearest the tip.
    kept = 0
    missing: List[Tuple[int, str]] = []
    for h in sorted(canonical, reverse=True):
        if has_body(canonical[h]):
            kept += 1
        else:
            missing.append((h, canonical[h]))

    return RestorePlan(anchor=anchor, fork_point=F, new_floor=new_floor, canonical=canonical,
                       reput=reput, missing=missing, undetermined=undetermined, kept=kept, notes=notes)


def contiguous_floor(canonical: Dict[int, str], has_body: Callable[[str], bool], anchor: int) -> int:
    """The lowest height from which bodies are present WITHOUT A GAP up to the anchor — what
    earliest_block should be set to. Serving "history from N" must mean every block from N."""
    h = anchor
    while h - 1 in canonical and has_body(canonical[h - 1]):
        h -= 1
    return h
