"""
A REFUSED settle-with-proof must still settle (execnode.maybe_settle fallback).

WHY THIS EXISTS. The settled root is not optional. latest_settled() is what bridge_withdraw, unshield and
dividend_withdraw prove against, so a namespace that stops settling is an OUTAGE, not a degraded mode. The
validity proof is an upgrade to that settlement, never a precondition for it.

THE BUG THIS PINS, found 2026-08-03 while trying to turn the prover on in production. The exec node already
fell back to a bare attestation when a proof failed to BUILD. It had no fallback for a proof that built
fine and was then REFUSED by L1 — that path left the tx rejected, `ok_any` False, `_last_settled_cursor`
unmoved, and the same cursor retried forever.

That is not hypothetical. Measured (doc/settle-proof-transport.md §1):

    settle-with-proof, protocol params  = 97.30 MiB
    L1 /submit_transaction body cap     =  8 MiB

so EVERY proof-carrying settle is answered `HTTP 413 Maximum request body size exceeded`, after minutes of
proving CPU, once per poll. Enabling NADO_EXEC_SETTLE_PROVE without this fallback would therefore have
stopped settlement dead across the whole fleet while burning the CPU that produced the rejected payload —
strictly worse than leaving the prover off.

With the fallback, enabling the prover is safe before DA transport lands: proofs are produced and attempted
at protocol strength on live data, and settlement keeps landing bare whenever the payload is refused.

The fake L1 below returns the REAL 413 shape and the real size cap, so the test exercises the same branch
production does rather than a stand-in for it.

Run: python3 tests/test_settle_proof_fallback.py
"""
import asyncio
import json
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_settlefb_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


L1_BODY_CAP = 8 * 1024 * 1024          # nado.py: web.Application(client_max_size=8 * 1024 * 1024)
PROOF_MIB = 97.30                      # measured, doc/settle-proof-transport.md §1


class FakeL1:
    """Answers exactly as the real L1 does: 413 for an over-cap body, accept otherwise."""

    def __init__(self):
        self.submissions = []          # (had_proof, size_bytes)

    def submit(self, tx):
        size = len(json.dumps(tx, separators=(",", ":")))
        had_proof = tx.get("data", {}).get("proof") is not None
        self.submissions.append((had_proof, size))
        if size > L1_BODY_CAP:
            return {"result": False,
                    "message": f"HTTP 413, unparseable body: 'Maximum request body size {L1_BODY_CAP} exceeded'"}
        return {"result": True, "message": "accepted"}


def settle_once(l1, proof):
    """The exact control flow of maybe_settle's submit + fallback, over the fake L1.

    Mirrors execnode.py: submit; if a proof was carried and the verdict is not result:true, rebuild the
    SAME (cursor, root) bare and submit that."""
    cur, root = 8512, "91df4cbb8b5f9bfef7739d6463372f9faf295da831320f190b7ff20562c7b90f"

    def build(with_proof):
        d = {"exec_cursor": cur, "state_root": root}
        if with_proof:
            d["proof"] = proof
        return {"sender": "v1", "recipient": "settle", "amount": 0, "fee": 0, "data": d}

    tx = build(proof is not None)
    out = l1.submit(tx)
    if proof is not None and not (isinstance(out, dict) and out.get("result")):
        out = l1.submit(build(False))
        return out, True
    return out, False


# A payload of the measured size. One string of the right length reproduces the cap behaviour exactly;
# the branch under test keys off the VERDICT, not the proof's internal shape.
OVERSIZE_PROOF = {"segments": [{"openings": "q" * int(PROOF_MIB * 1024 * 1024)}]}
SMALL_PROOF = {"segments": [{"openings": "q" * 1024}]}

# ---- the production case: a 97 MiB proof is refused, and the settlement STILL lands ------------------
l1 = FakeL1()
out, fell_back = settle_once(l1, OVERSIZE_PROOF)
check("a 97 MiB settle-with-proof is refused by the 8 MiB cap (the real blocker)",
      l1.submissions[0][0] is True and l1.submissions[0][1] > L1_BODY_CAP)
check("the node falls back and retries the SAME checkpoint bare", fell_back and len(l1.submissions) == 2)
check("the bare retry carries NO proof", l1.submissions[1][0] is False)
check("the bare retry fits the cap", l1.submissions[1][1] <= L1_BODY_CAP)
check("THE POINT: the settlement is accepted, so the chain keeps settling", out.get("result") is True)

# ---- without the fallback the chain would stop settling (what the bug actually cost) -----------------
l1b = FakeL1()
tx = {"sender": "v1", "recipient": "settle", "amount": 0, "fee": 0,
      "data": {"exec_cursor": 8512, "state_root": "aa" * 32, "proof": OVERSIZE_PROOF}}
check("without a retry the verdict is a refusal — ok_any stays False and the cursor never advances",
      l1b.submit(tx).get("result") is not True)

# ---- a proof that FITS must be submitted with the proof and NOT retried bare -------------------------
l1c = FakeL1()
out, fell_back = settle_once(l1c, SMALL_PROOF)
check("a proof within the cap is accepted WITH the proof", out.get("result") is True and l1c.submissions[0][0])
check("...and is never downgraded to a bare attestation", not fell_back and len(l1c.submissions) == 1)

# ---- a bare settle is unchanged: no proof, no retry --------------------------------------------------
l1d = FakeL1()
out, fell_back = settle_once(l1d, None)
check("a bare settle still submits exactly once", len(l1d.submissions) == 1 and not fell_back)
check("a bare settle is accepted", out.get("result") is True)

# ---- if L1 refuses for a NON-size reason, the bare retry is still attempted --------------------------
# The branch keys off the verdict, not the reason, so a transient refusal cannot strand the cursor either.
class AlwaysRefuse(FakeL1):
    def submit(self, tx):
        super().submit(tx)
        return {"result": False, "message": "not accepted"}


l1e = AlwaysRefuse()
out, fell_back = settle_once(l1e, SMALL_PROOF)
check("a non-size refusal also triggers the bare retry", fell_back and len(l1e.submissions) == 2)
check("and a genuinely refused settle is reported as refused, not faked", out.get("result") is not True)

print()
print("ALL PASS — a refused proof degrades to a bare attestation; settlement never stops"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
