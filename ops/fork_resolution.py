"""
FORK RESOLUTION — one measurement, one decision.

Recovery used to be inferred from weights, donor behaviour and bench state, spread across emergency mode,
_maybe_reanchor, its escalation, _rejoin_by_rollback and force_sync. Those interact badly, and on
2026-07-20 they mis-fired together: the node was simply ~500 blocks BEHIND on the correct chain, read that
as "forked", attempted a rollback, found no history beneath its imported snapshot ("Parent None … is not on
disk"), aborted, re-anchored, and looped for 40+ minutes across a restart. A human had to purge it by hand,
and even the purge left it mining its own chain from genesis until a peer was force-pinned.

The fix is not another special case. Every one of those situations is answered by a single number:

    ANCESTOR = the highest height where OUR block hash equals the MAJORITY's block hash.

From ancestor, our tip and our finality floor, the state is determined — no weights, no donor reputation,
no benching, no forced peers:

    ancestor == our tip        -> BEHIND      : we are on their chain, just short. FORWARD SYNC. Never roll back.
    ancestor >= finalized      -> REORG       : forked above the floor. Roll back to ancestor, then sync.
    ancestor <  finalized      -> DEAD_FORK   : forked at/below the floor. Finality forbids the rollback, so
                                                no local remedy exists — purge chain data and resync.
    no usable answers          -> UNKNOWN     : stay put. Doing nothing is always safe; acting blind is not.

Hash equality at a height is a fact, not a judgement, and it is cheap: a binary search over the range costs
~log2(depth) probes (17 for a 100k chain). This module is PURE — it takes a probe callable and returns a
verdict, so it is fully testable without a network, and it cannot be blinded by a collapsed peer set the
way consensus.status_pool can.
"""

BEHIND, REORG, DEAD_FORK, SYNCED, UNKNOWN = "behind", "reorg", "dead_fork", "synced", "unknown"

# Fraction of ANSWERING peers that must report the same hash at a height for it to count as "the majority's".
# Peers that do not answer are not evidence either way — an outage must never be read as a fork.
_AGREE = 0.5

# Uniform-sweep resolution used only when the doubling stride fails to land inside the peers' answerable
# window (see _find_answerable). Bounds the worst-case probe count while resolving any window wider than
# range/_SWEEP — ~200 blocks on a 13k chain, well under any real pruning retention.
_SWEEP = 64


def majority_hash(height, peers, probe, min_answers=2):
    """The hash a strict majority of ANSWERING WEIGHT reports at `height`, or None if there is no majority
    or too few answers.

    `probe(peer, height)` returns either `hash|None` (legacy headcount) or `(hash, seats)` — the
    STAKE-SIGNED probe (peer_ops.probe_block_hash_signed): a verified bonded validator's answer counts
    1 + its selection seats, an unsigned/unverifiable answer counts 1. This closes the Sybil-softness of
    the per-IP headcount without becoming a liveness dependency: a fleet with no signed answers degrades
    to exactly the old seeds-first headcount, while a single real validator outweighs any number of
    seatless IPs. min_answers stays a COUNT of answers — stake weighs the verdict, never quorum liveness."""
    answers = {}
    count = 0
    for p in peers:
        r = probe(p, height)
        h, seats = (r if isinstance(r, tuple) else (r, 0))
        if h:
            answers[h] = answers.get(h, 0) + 1 + max(0, int(seats or 0))
            count += 1
    if count < int(min_answers):
        return None
    total = sum(answers.values())
    top, n = max(answers.items(), key=lambda kv: kv[1])
    return top if n > total * _AGREE else None


def _find_answerable(floor, tip, agrees):
    """Any height in [floor, tip] the peer majority can actually answer, or None.

    The answerable range is a CONTIGUOUS WINDOW, not the whole chain: peers prune old history (rolling
    mode) so everything below their retention is gone, and a node that raced ahead sits above everything
    they hold. So a probe can come back empty from either end, and neither end can be assumed good.

    Walks back from the tip with a doubling stride because the window is always at the TOP of the range —
    recent heights are the ones peers are most likely to hold. O(log depth) probes, and each uses a low
    retry count: here an empty answer is the expected outcome we are searching for, not a flaky peer worth
    retrying eight times."""
    step, h = 1, tip
    while h > floor:
        if agrees(h, 2) is not None:
            return h
        step *= 2
        h = tip - step
    if agrees(floor, 2) is not None:
        return floor
    # The doubling stride can JUMP OVER a narrow window (its gaps grow to half the range), so fall back to
    # a uniform sweep of bounded cost. This finds any window wider than (range / _SWEEP) — far below any
    # real retention setting. A window narrower than that is simply not found and the verdict stays
    # UNKNOWN, which is the safe direction: UNKNOWN only ever means "change nothing", and no amount of
    # probing can make a purge safe on evidence this thin.
    span = tip - floor
    for i in range(1, _SWEEP):
        probe_h = tip - (span * i) // _SWEEP
        if probe_h <= floor:
            break
        if agrees(probe_h, 2) is not None:
            return probe_h
    return None


def _lowest_answerable(floor, anchor, agrees):
    """The LOWEST height in [floor, anchor] the majority can answer, given `anchor` IS answerable.

    Mirror of _highest_answerable for the other end of the window. Without it the search floor stays at 0,
    where a pruned fleet can never answer — which collapsed every verdict to UNKNOWN and, on 2026-07-28,
    left two nodes that had ALREADY detected they were stranded unable to confirm it, so the self-heal
    could not fire. (`ancestor=None, probes=9`: eight retries at the tip, then one at the floor.)"""
    if agrees(floor, 2) is not None:
        return floor
    lo, hi = floor, anchor                        # invariant: unanswerable at lo, answerable at hi
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if agrees(mid, 2) is None:
            lo = mid
        else:
            hi = mid
    return hi


def _highest_answerable(tip, floor, agrees):
    """The highest height in [floor, tip] the peer majority can actually answer, or None.

    Used only when we are AHEAD of every peer (they hold no block at our tip). Binary-searches the
    answerability boundary — `agrees(h)` returns None exactly when the majority could not be established at h
    — so it costs O(log tip) probes and never changes the verdict at a height that IS answerable."""
    if agrees(floor) is None:
        return None                              # they cannot even answer at the floor -> genuinely no majority
    lo, hi = floor, tip                           # invariant: answerable at lo, unanswerable at hi
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if agrees(mid) is None:
            hi = mid
        else:
            lo = mid
    return lo


def find_common_ancestor(our_hash_at, tip, peers, probe, floor=0, min_answers=2):
    """Highest height in [floor, tip] where our hash equals the majority's, by binary search.

    Returns (ancestor, probes) with ancestor=None when the majority could not be established (peers silent
    or split) — which the caller MUST treat as "do nothing", never as a fork. If we disagree even at
    `floor`, returns floor-1 to signal "the divergence is below everything we can see", which is exactly the
    dead-fork case."""
    probes = 0

    def agrees(h, _attempts=8):
        """None only when the majority genuinely cannot be established — RETRIED first.

        With a small peer set this search is brutally fragile: min_answers=2 against 2 reachable peers means
        BOTH must answer on EVERY one of the ~26 probes a binary search makes, so one dropped packet anywhere
        collapses the whole verdict to UNKNOWN. Measured live on .141: stranded_below_finality said stranded
        with 2 peers disagreeing and none agreeing, yet the fork state stayed 'unknown' pass after pass and
        blocked the purge. Retrying an inconclusive probe costs nothing when peers are healthy and is what
        makes the verdict obtainable at all on a 2-peer node. This does NOT weaken the test: a real majority
        is still required, we just decline to abandon it over one timeout."""
        nonlocal probes
        for _ in range(max(1, int(_attempts))):
            probes += 1
            theirs = majority_hash(h, peers, probe, min_answers=min_answers)
            if theirs is not None:
                return our_hash_at(h) == theirs
        return None

    # DISCOVER THE FLOOR. `floor` is a REQUEST, not a fact. Peers prune history, so on a pruned fleet
    # NOBODY can serve block 0 and every probe there is empty — which the old code read as "no majority
    # could be established" and turned into UNKNOWN, permanently. Measured live on 2026-07-28: no peer
    # could answer at h0, h1, h5000 or h11000, the lowest commonly-held height was ~h12000, and two nodes
    # that had already PROVEN they were stranded could never confirm it, so the purge never fired.
    # Anchor inside the answerable window first, then find its lower edge and search from there. Agreement
    # at the lowest height they can serve is just as conclusive: any height they hold is one we must also
    # match to be on their chain.
    _requested_floor = floor
    _anchor = _find_answerable(floor, tip, agrees)
    if _anchor is None:
        return None, probes                      # they can answer nowhere in range -> genuinely unknown
    floor = _lowest_answerable(floor, _anchor, agrees)

    top = agrees(tip)
    if top is None:
        # PEERS CANNOT ANSWER AT OUR TIP — the signature of a node that is AHEAD of everyone, which is exactly
        # what a lone forker looks like: it mines every slot unopposed and outruns the honest majority. Giving
        # up here meant such a node could never obtain ANY verdict (always UNKNOWN), so the dead-fork escape's
        # second confirmation could never be satisfied and it stayed forked forever — .141 sat 350+ blocks past
        # the majority for hours (2026-07-28). Retry from the highest height the peers CAN answer; comparing
        # there is just as conclusive, since any height they hold is one we must also agree on to be on their
        # chain. Costs O(log tip) extra probes and only on this path.
        ceiling = _highest_answerable(tip, floor, agrees)
        if ceiling is None:
            return None, probes
        tip = ceiling
        top = agrees(tip)
        if top is None:
            return None, probes
    if top:
        return tip, probes                      # we match at our own tip: not forked at all, just short
    bottom = agrees(floor)
    if bottom is None:
        return None, probes
    if not bottom:
        # We disagree at the lowest height in range. If that IS the floor the caller asked about, the
        # divergence really is below everything and the dead-fork reading is sound.
        #
        # But when PRUNING raised the floor, "below the floor" only means "below what anyone can still
        # see" — the true fork point may sit either side of our finality horizon and nothing in range can
        # tell us which. Returning floor-1 there would hand classify() an ancestor we never established:
        # with a floor above our finalized height it reads as REORG and the node attempts a rollback that
        # cannot reach the real divergence. UNKNOWN is the honest answer, and the safe one.
        if floor > _requested_floor:
            return None, probes
        return floor - 1, probes                # divergence is at or below the floor -> dead fork

    lo, hi = floor, tip                          # invariant: agree at lo, disagree at hi
    while hi - lo > 1:
        mid = (lo + hi) // 2
        a = agrees(mid)
        if a is None:
            return None, probes
        if a:
            lo = mid
        else:
            hi = mid
    return lo, probes


def tie_winner(ours_first_divergent: str, theirs_first_divergent: str) -> str:
    """STABLE equal-weight fork choice: which branch is canonical when two branches carry EXACTLY equal
    cumulative weight (weight increments are content-independent, so every same-height split is a
    permanent exact tie).

    The old tie-break compared TIP hashes — which re-roll every block, so which side "wins" flipped
    every ~6 s and neither side could finish a reorg before the verdict inverted; splits see-sawed for
    hours (observed 2026-08-17/18 at 62655 and 62895). The FIRST DIVERGENT block (ancestor+1) never
    changes as the branches grow, so this comparison is computed identically and PERMANENTLY by both
    sides: exactly one side reorgs, once.

    Returns "ours" / "theirs". Missing or equal inputs return "ours" — no evidence never switches a
    node off its own chain (the same asymmetry as everything else in this module)."""
    if (not ours_first_divergent or not theirs_first_divergent
            or ours_first_divergent == theirs_first_divergent):
        return "ours"
    return "ours" if ours_first_divergent < theirs_first_divergent else "theirs"


def classify(ancestor, tip, finalized):
    """Turn the ancestor into the single action to take. Pure arithmetic — see the module docstring."""
    if ancestor is None:
        return UNKNOWN
    if ancestor >= tip:
        # Our whole chain is a PREFIX of theirs. Whether they are ahead or level is irrelevant here: the
        # action is the same and it is forward sync. (Level makes it a no-op.) Never a rollback — reading
        # this case as a fork is precisely what wedged the node on 2026-07-20.
        return BEHIND
    if ancestor >= finalized:
        return REORG
    return DEAD_FORK


def resolve(our_hash_at, tip, finalized, peers, probe, min_answers=2):
    """Full verdict: {state, ancestor, tip, finalized, probes}. The caller maps state -> action:
    BEHIND/SYNCED -> ordinary forward sync (NEVER a rollback); REORG -> roll back to ancestor;
    DEAD_FORK -> purge chain data + resync; UNKNOWN -> do nothing this pass."""
    ancestor, probes = find_common_ancestor(our_hash_at, tip, peers, probe, floor=0,
                                            min_answers=min_answers)
    if ancestor is None and finalized and finalized > 0:
        # RE-ANCHORED-ONTO-A-FORK RESCUE (2026-07-30, the h15076 aftermath). A node that snapshot-anchored
        # onto a minority fork holds NO block at any height it shares with the canonical chain's history —
        # find_common_ancestor's raised-floor caution then honestly answers UNKNOWN ("the true fork point
        # may sit either side of our finality horizon"), and UNKNOWN blocks the dead-fork escape forever.
        # Three such nodes sat mining a private branch with the verdict permanently unknowable.
        #
        # But one comparison IS still available and conclusive: our own FINALIZED height. We always hold
        # that block (earliest <= finalized by construction), and if the peer majority serves a DIFFERENT
        # block there, the divergence is proven to lie at/below our floor — the exact DEAD_FORK
        # definition, and the same "disagreement at a height that is final on our side" principle
        # stranded_below_finality already stands on. Report ancestor as finalized-1 ("at or below the
        # floor"); the purge itself stays behind the escape's quorum/weight/unanimity gates.
        ours_f = our_hash_at(finalized)
        theirs_f = majority_hash(finalized, peers, probe, min_answers=min_answers)
        probes += 1
        if ours_f is not None and theirs_f is not None and ours_f != theirs_f:
            return {"state": DEAD_FORK, "ancestor": finalized - 1,
                    "tip": tip, "finalized": finalized, "probes": probes,
                    "via": "finalized-height disagreement (ancestor unlocatable)"}
    return {"state": classify(ancestor, tip, finalized), "ancestor": ancestor,
            "tip": tip, "finalized": finalized, "probes": probes}
