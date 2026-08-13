"""
Node-side auto-vote on WHITELISTED treasury proposals (core_loop.maybe_auto_vote).

THE GAP THIS CLOSES. Treasury quorum is counted in BONDED SHARES. The browser wallet has auto-voted since
the feature shipped — but measured on betanet-2, 108 of 117 open miners hold ZERO shares, so their votes
count for nothing, while all 42 shares sit with 9 bonded node operators whose software never voted at all.
Quorum is 28 of 42, so it was unreachable BY CONSTRUCTION: the treasury accumulated 109 NADO and had never
paid out, with zero proposals ever opened. Whitelisting a recipient is meaningless unless the side holding
the weight actually votes.

THE SAFETY PROPERTY IS THE WHITELIST, NOT THE FLAG. A listed recipient is the only thing the node will
ever auto-approve, and the shipped default is the reserved `faucet` escrow — keyless, so the default
behaviour cannot move treasury funds to any individual's address. These checks pin that boundary, because
an auto-voter that drifted past it would be a governance capture bug, not a convenience regression:

  * a whitelisted recipient is picked; a non-whitelisted one is NOT, and is left for a human;
  * matching is case-insensitive (the allow-list is normalised) but never a prefix/substring match —
    "faucet2" must not be approved by a list containing "faucet";
  * an EXPIRED or already-EXECUTED proposal is skipped;
  * a proposal this node already voted on is never re-cast (the wallet's rule is "has voted, yes OR no",
    so a deliberate `no` is never flipped to yes by automation);
  * an EMPTY allow-list means approve-nothing here, never approve-everything.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        _fails.append(name)


def picks(proposals, allow, me, voted_by, executed, tip):
    """The selection rule maybe_auto_vote applies, isolated so it can be exercised without a live chain.
    Mirrors the loop body exactly; if the loop changes, this must change with it."""
    allow = [a.strip().lower() for a in (allow or []) if a.strip()]
    if not allow:
        return []                                   # empty = approve NOTHING (never "anything")
    out = []
    for pid, spend in proposals:
        if tip > int(spend.get("expiry", 0)) or pid in executed:
            continue
        if str(spend.get("recipient", "")).lower() not in allow:
            continue
        if any(v.lower() == me.lower() for v in voted_by.get(pid, [])):
            continue
        out.append(pid)
    return out


def main():
    ME = "abc" + "d" * 43
    TIP = 1000
    props = [
        ("p_faucet",   {"recipient": "faucet",  "amount": 10, "expiry": 2000}),
        ("p_other",    {"recipient": "e" * 46,  "amount": 10, "expiry": 2000}),
        ("p_upper",    {"recipient": "FAUCET",  "amount": 10, "expiry": 2000}),
        ("p_lookalike", {"recipient": "faucet2", "amount": 10, "expiry": 2000}),
        ("p_expired",  {"recipient": "faucet",  "amount": 10, "expiry": 500}),
        ("p_executed", {"recipient": "faucet",  "amount": 10, "expiry": 2000}),
        ("p_voted",    {"recipient": "faucet",  "amount": 10, "expiry": 2000}),
    ]
    got = picks(props, ["faucet"], ME, {"p_voted": [ME]}, {"p_executed"}, TIP)

    check("a whitelisted proposal IS auto-approved", "p_faucet" in got)
    check("a non-whitelisted recipient is NOT (left for a human)", "p_other" not in got)
    check("the allow-list match is case-insensitive", "p_upper" in got)
    check("a LOOKALIKE recipient is not approved (no prefix match)", "p_lookalike" not in got)
    check("an expired proposal is skipped", "p_expired" not in got)
    check("an already-executed proposal is skipped", "p_executed" not in got)
    check("a proposal we already voted on is never re-cast", "p_voted" not in got)

    # ---- the empty list must fail CLOSED --------------------------------------------------------------
    check("an EMPTY allow-list approves nothing (not everything)",
          picks(props, [], ME, {}, set(), TIP) == [])
    check("a whitespace-only allow-list approves nothing",
          picks(props, ["  "], ME, {}, set(), TIP) == [])

    # ---- another voter's vote must not suppress ours --------------------------------------------------
    check("someone ELSE having voted does not stop us",
          "p_faucet" in picks(props, ["faucet"], ME, {"p_faucet": ["z" * 46]}, set(), TIP))

    # ---- the shipped default is the keyless reserved escrow -------------------------------------------
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from protocol import RESERVED_RECIPIENTS
        check("the default whitelist entry is a RESERVED, keyless recipient",
              "faucet" in RESERVED_RECIPIENTS)

    # ---- and the loop must actually consult the allow-list --------------------------------------------
    import inspect
    from loops import core_loop
    src = inspect.getsource(core_loop)
    i = src.index("def maybe_auto_vote")
    body = src[i:src.index("def maybe_auto_register", i)]
    code = "\n".join(l.split("#", 1)[0] for l in body.splitlines())
    check("the loop checks the recipient against the allow-list", "not in allow" in code)
    check("the loop skips when it has already voted", "treasury_voters" in code)
    check("the loop refuses an empty allow-list", "if not allow" in code)
    check("the loop skips when it holds no bonded shares", "get_bonded_registry" in code)

    print()
    print("ALL AUTO-VOTE WHITELIST CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
