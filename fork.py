"""
fork.py — the chain's FORK SCHEDULE: every consensus-rule activation pinned to a block height, in ONE
named, documented place.

WHY THIS EXISTS (2026-07-17/18 postmortems): alphanet's convention is "no activation gates — consensus
changes go live immediately", which works only while every producing node updates in lockstep. Twice in
two days it didn't, and the network split:
  • #2944  — registration-PoSW difficulty computed from divergent node-local index state; clean nodes
             demanded 3x, the fleet accepted 2x, and exact-T verification turned the disagreement into
             wholesale block rejection (10h wedge).
  • #13626 — the day's audit commits changed consensus state evolution; new-code nodes refuse every
             old-code block because the deterministic rebuild (winner/weight) no longer reproduces the
             claimed hash.
The lesson: a consensus change that cannot RE-VALIDATE the already-finalized chain is a HARD FORK,
whether or not we call it one — and it needs an explicit activation height with the old rule kept
(grandfathered) below it, or freshly syncing nodes can never cross the historical range. This module is
where those heights live. Rules for adding one:

  1. Pick the height COMFORTABLY ahead of the live tip — far enough for every producing node to update
     before the chain reaches it (a boundary that lands before the fleet updates just schedules the next
     split). ~14,400 blocks/day at the 6s block time.
  2. The pre-fork rule must remain implemented (validity grandfathering) so the finalized past — and
     interim blocks from not-yet-updated producers — keep validating forever.
  3. APPLY-SIDE changes (how a block mutates state) are stricter than validity relaxations: replaying
     old blocks under new apply rules computes DIFFERENT STATE than the nodes that originally applied
     them, and the fork reappears downstream. Gate the apply path on the same height, or provide a
     snapshot re-anchor across the range.
  4. Heights are CONSENSUS constants: every node must agree, so they change only with the code — never
     via config.

Dependency-free on purpose: protocol.py, ops/ and the exec layer may all import it.
"""

FORKS = {
    # registration-PoSW difficulty v2 (ops/reg_difficulty.py, 2026-07-17 #2944 split fix): at/below the
    # height any 1..POSW_DIFF_MAX_MULT proof multiplier is accepted (the v1 era's proofs were minted
    # against per-node index state that provably diverged); above it, the strict chain-derived
    # requirement is enforced exactly.
    "reg_difficulty_v2": 50_000,
}


def height(name: str) -> int:
    """The activation height of a named fork. KeyError on an unknown name — a typo must fail loudly,
    silently treating a rule as never-active would itself fork the network."""
    return FORKS[name]


def active(name: str, block_height: int) -> bool:
    """Is the named fork's NEW rule in force for a tx/block bound to `block_height`? Strictly ABOVE the
    pin: the boundary block itself still validates under the old (grandfathered) rule, so the constant
    reads as 'the last old-rules height'."""
    return block_height > FORKS[name]
