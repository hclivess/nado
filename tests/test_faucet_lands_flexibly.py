"""
A faucet donation must land like a bridge deposit, not on one exact block
(block_ops._lands_flexibly).

THE BUG. `match_transactions_target` has two inclusion paths: a tx that "lands flexibly" is eligible in
ANY block in [min_block, max_block]; everything else is eligible ONLY in the block numbered exactly
max_block, because it has a landing-block-dependent timing invariant (epoch-timed commit/reveal/attest,
release-timed bond/unbond, PoW-anchored register/msgkey, settle, governance).

`faucet` was never added to the flexible set, so a donation took the exact-landing branch. A donation has
NO timing invariant at all — validate_transaction checks only `amount > 0` and `fee >= MIN_TX_FEE`, and
the code there says outright "Same shape as a bridge deposit" — and `bridge` IS flexible. So the tx was
includable in exactly one block out of its whole window and otherwise sat in the mempool until it expired.

Observed on betanet-3 before the fix: a faucet tx pending across 47 blocks, re-validating cleanly at every
height (no "Candidate excludes" line ever logged for it) and never selected. That combination — valid,
present, unselected — is the signature of exact-landing on a height nobody targets.

WHY IT MATTERS BEYOND THE FAUCET: this is a CONSENSUS predicate. `_lands_flexibly` is used by the producer
(match_transactions_target) and by the verifier (check_target_match) from the same function, so the two
cannot disagree — but nodes running different versions of it WILL, and each will reject the other's blocks.
Any change here has to reach the whole fleet.

WHAT THESE CHECKS PIN: faucet is flexible; the recipients that genuinely need exact landing still get it
(a regression here would silently void a timing invariant rather than fail loudly); and a plain address
transfer is unaffected.
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


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ["HOME"] = d
        os.makedirs(os.path.join(d, "nado"), exist_ok=True)
        from ops.block_ops import _lands_flexibly, match_transactions_target

        def tx(recipient, **kw):
            t = {"recipient": recipient, "txid": "f" * 64, "max_block": 100, "amount": 1, "fee": 1000}
            t.update(kw)
            return t

        # ---- the fix ---------------------------------------------------------------------------------
        check("a faucet donation lands FLEXIBLY", _lands_flexibly(tx("faucet")))
        check("...like the bridge deposit it mirrors", _lands_flexibly(tx("bridge")))

        # ---- everything with a real timing invariant KEEPS exact landing ------------------------------
        for r in ("commit", "reveal", "attest", "duty",          # epoch-timed RANDAO / consensus
                  "bond", "unbond", "withdraw",                   # release-timed
                  "register", "msgkey",                           # PoW-anchored
                  "settle", "treasury", "treasury_vote", "treasury_execute",   # governance / settlement
                  "slash", "alias"):
            check(f"'{r}' still requires EXACT landing", not _lands_flexibly(tx(r)))

        # ---- the other flexible members are unchanged ------------------------------------------------
        for r in ("blob", "bridge_withdraw", "dividend_withdraw"):
            check(f"'{r}' still lands flexibly", _lands_flexibly(tx(r)))
        # a REAL address — is_address() checks the checksum, not just the shape, so "a"*46 is not one
        # (it fails the same way a typo'd address would, which is the point of the check).
        from signatures import make_address
        from ops.address_ops import is_address
        real = make_address("ebd27698662f14ee2389e509781d5ff57487f4289a")
        check("the fixture really is a valid address", is_address(real))
        check("a plain address transfer lands flexibly", _lands_flexibly(tx(real)))

        # ---- END TO END through the producer's own filter ---------------------------------------------
        # The real regression: a faucet tx must be selectable at a height that is NOT its max_block.
        class L:
            def info(self, *a):
                pass

            def error(self, *a):
                pass

        pool = [tx("faucet", txid="a" * 64, max_block=100, min_block=10)]
        mid = match_transactions_target(transaction_list=list(pool), block_number=55, logger=L())
        check("faucet is selected MID-window (the actual bug)", bool(mid) and len(mid) == 1)
        at_max = match_transactions_target(transaction_list=list(pool), block_number=100, logger=L())
        check("...and still at max_block", bool(at_max) and len(at_max) == 1)
        early = match_transactions_target(transaction_list=list(pool), block_number=9, logger=L())
        check("...but NOT before min_block", not early)
        late = match_transactions_target(transaction_list=list(pool), block_number=101, logger=L())
        check("...and NOT after max_block", not late)

        # an exact-landing recipient must still be refused mid-window
        pool2 = [tx("attest", txid="b" * 64, max_block=100)]
        check("an exact-landing tx is still refused mid-window",
              not match_transactions_target(transaction_list=list(pool2), block_number=55, logger=L()))

    print()
    print("ALL FAUCET LANDING CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
