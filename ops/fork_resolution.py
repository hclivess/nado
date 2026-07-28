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


def majority_hash(height, peers, probe, min_answers=2):
    """The hash a strict majority of ANSWERING peers report at `height`, or None if there is no majority or
    too few answers. `probe(peer, height) -> hash|None`."""
    answers = {}
    for p in peers:
        h = probe(p, height)
        if h:
            answers[h] = answers.get(h, 0) + 1
    total = sum(answers.values())
    if total < int(min_answers):
        return None
    top, n = max(answers.items(), key=lambda kv: kv[1])
    return top if n > total * _AGREE else None


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
    return {"state": classify(ancestor, tip, finalized), "ancestor": ancestor,
            "tip": tip, "finalized": finalized, "probes": probes}
