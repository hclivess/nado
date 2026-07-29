"""CAN SIG_AGG_STARK ACTUALLY BE TURNED ON? — the flag nothing ever flipped.

Signature aggregation was built, wired, and left switched off. `SIG_AGG_STARK = False` makes
ops/block_ops.verify_auth_proof return False before it looks at anything, and until this file existed NO
test anywhere set that flag to True. So the aggregate path had exactly one property established: that it is
inert. Whether the chain could ever ACCEPT an aggregate envelope was unproven, and a consensus flag that
cannot be turned on is worse than a missing feature — it is a feature the release notes will claim.

This pins the ROUTING, deterministically and in milliseconds, by injecting the two verifier callables that
mldsa_block_auth.evidence_ok already takes as parameters. It deliberately does NOT prove a real signature:
that is tests/test_block_auth_wiring.py under NADO_HEAVY=1 (>1h at D=3), and the two answer different
questions. The heavy test asks "is the cryptography sound?". This one asks "when the flag flips, does the
node's decision actually change, and does it still reject everything it should?" — a real bundle cannot
answer that, because it passes identically whether or not the surrounding gate works.

THE IMPORT-TIME BINDING, which is why this test patches where it does. ops/block_ops.py does
`from protocol import ..., SIG_AGG_STARK` at module scope, so the value is captured ONCE at import;
reassigning protocol.SIG_AGG_STARK afterwards has no effect on it. Contrast settlement_sparse.py, which
imports SETTLE_PROOF_RECURSIVE INSIDE the function and therefore reads it live. Both are defensible for a
constant that only ever changes at a reroll, but they are not the same, and anyone who assumes the flag is
runtime-togglable will be wrong about one of them. The checks below pin that difference so it stays known.

WHAT THIS DOES NOT CLAIM. Per mldsa_sig_proof.py:196-202, today's sub-AIRs take the signature as a PUBLIC
input, so an aggregate envelope offloads the VERIFICATION ARITHMETIC of K signatures, not their BYTES — the
block still carries every signature. Byte savings need the signature moved into the witness, which is an AIR
change. The final check pins that honesty so no one reads "aggregation is on" as "blocks got smaller".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import protocol as P
from execnode.stark import mldsa_block_auth as AUTH
from ops import block_ops

fails = []


def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


# ---------------------------------------------------------------- a real block core (real commitment)
TXS = [{"txid": "aa" * 32, "sender": "0" * 42 + "beef", "recipient": "x",
        "amount": 1, "fee": 1, "signature": "00" * 8},
       {"txid": "bb" * 32, "sender": "1" * 42 + "cafe", "recipient": "y",
        "amount": 2, "fee": 1, "signature": "11" * 8}]

BLK = block_ops.construct_block(block_timestamp=1, block_number=7, parent_hash="00" * 32,
                                creator="2" * 42 + "0000", transaction_pool=list(TXS),
                                block_reward=0, state_root="ab" * 32, exec_root="cd" * 32, exec_cursor=0)
ROOT, COUNT = AUTH.auth_commitments(BLK)
check(COUNT == 2 and BLK["auth_count"] == 2, f"the fixture block commits to 2 authorizations (got {COUNT})")

ENVELOPE = AUTH.stark_evidence("mldsa44-block-auth-v1", {"bundles": ["proof-for-entry-0", "proof-for-entry-1"]})

# What the verifier passes down. Recording it lets us assert the statement is VERIFIER-derived.
seen = {}


def _accept(circuit_id, proof, statement):
    seen["circuit_id"], seen["proof"], seen["statement"] = circuit_id, proof, statement
    return True


def _reject(circuit_id, proof, statement):
    seen["circuit_id"], seen["proof"], seen["statement"] = circuit_id, proof, statement
    return False


# ---------------------------------------------------------------- THE FLAG, BOTH WAYS
# Patch block_ops' OWN binding, not protocol's — see the import-time note above.
_saved = block_ops.SIG_AGG_STARK
try:
    block_ops.SIG_AGG_STARK = False
    check(block_ops.verify_auth_proof("mldsa44-block-auth-v1", {"bundles": []}, {"auth_count": 0}) is False,
          "with SIG_AGG_STARK off, verify_auth_proof refuses EVERY envelope (the chain rule today)")

    ok, why = AUTH.evidence_ok(ENVELOPE, BLK, resolve_pubkey=lambda s: "ab" * 64,
                               verify_proof=block_ops.verify_auth_proof)
    check(ok is False,
          f"a block shipping a stark envelope is REJECTED while the flag is off — not silently accepted ({why})")

    block_ops.SIG_AGG_STARK = True
    # The real verify path would now call into mldsa_sig_proof; inject instead so this stays a wiring test.
    ok, why = AUTH.evidence_ok(ENVELOPE, BLK, resolve_pubkey=lambda s: "ab" * 64, verify_proof=_accept)
    check(ok is True, f"with the flag ON, a stark envelope whose proof verifies is ACCEPTED ({why})")
    check("2 authorizations" in why, f"the acceptance reason names the count it covered ({why})")

    ok, why = AUTH.evidence_ok(ENVELOPE, BLK, resolve_pubkey=lambda s: "ab" * 64, verify_proof=_reject)
    check(ok is False, "with the flag ON, an envelope whose proof does NOT verify is still rejected")

    # ------------------------------------------------------------ the statement is the VERIFIER'S
    AUTH.evidence_ok(ENVELOPE, BLK, resolve_pubkey=lambda s: "ab" * 64, verify_proof=_accept)
    st = seen["statement"]
    check(st["auth_root"] == ROOT and st["auth_count"] == COUNT,
          "the statement carries the verifier's OWN recomputed (auth_root, auth_count)")
    check(st["height"] == 7 and st["parent"] == "00" * 32,
          "the statement carries the block's own height and parent")
    check(st["pubkeys"] == ["ab" * 64] * 2,
          "pubkeys come from the verifier's PUBKEY-ONCE resolution, not from the envelope")
    check(all(k not in st for k in ("bundles", "proof", "circuit_id")),
          "NOTHING from the envelope leaks into the statement it is checked against")
    check(st["witnesses"] == [t["signature"] for t in TXS],
          "witnesses are the signatures the BLOCK carries (the sig is a public input today)")

    # ------------------------------------------------------------ commitment first, proof second
    # A tampered body must fail on the recomputed root BEFORE any proof is consulted — otherwise a valid
    # proof over a different transaction set would carry a block it does not describe.
    seen.clear()
    tampered = dict(BLK)
    tampered["block_transactions"] = [dict(TXS[0], txid="cc" * 32), TXS[1]]
    ok, why = AUTH.evidence_ok(ENVELOPE, tampered, resolve_pubkey=lambda s: "ab" * 64, verify_proof=_accept)
    check(ok is False, f"a block whose transactions were changed is rejected ({why})")
    check("auth_root" in why or "auth_count" in why,
          f"...and it is the COMMITMENT that rejects it, not the proof ({why})")
    check("statement" not in seen,
          "the proof verifier is never even called for a block that fails its own commitment")

    # a block understating its count must not slip through
    seen.clear()
    understated = dict(BLK, auth_count=1)
    ok, _ = AUTH.evidence_ok(ENVELOPE, understated, resolve_pubkey=lambda s: "ab" * 64, verify_proof=_accept)
    check(ok is False, "a block understating auth_count is rejected before the proof is consulted")
    check("statement" not in seen, "...and again the verifier is not called")

    # ------------------------------------------------------------ an absent envelope is still fine
    check(block_ops.check_block_auth_evidence(BLK)[0] is True,
          "a block with NO detached envelope stays valid with the flag on — per-tx signatures are the "
          "evidence, which is what every block ships today")
finally:
    block_ops.SIG_AGG_STARK = _saved

# ---------------------------------------------------------------- the flag is import-bound; say so
check(block_ops.SIG_AGG_STARK == _saved, "the flag was restored after the test")
check(_saved is False,
      "SIG_AGG_STARK ships OFF — flipping it is a CONSENSUS change and must ride a reroll")

import importlib
_probe = importlib.import_module("ops.block_ops")
P.SIG_AGG_STARK = not P.SIG_AGG_STARK
try:
    check(_probe.SIG_AGG_STARK != P.SIG_AGG_STARK,
          "block_ops binds SIG_AGG_STARK at IMPORT time — reassigning protocol.SIG_AGG_STARK at runtime does "
          "NOT change it (fine for a reroll-time constant; a trap for anyone expecting a live toggle)")
finally:
    P.SIG_AGG_STARK = not P.SIG_AGG_STARK

# ---------------------------------------------------------------- do not let anyone claim byte savings
saved, crossover = AUTH.byte_saving(COUNT, proof_bytes=100_000)
check(saved < 0,
      f"a 100 kB envelope over {COUNT} signatures SAVES NOTHING (byte_saving={saved}) — today's aggregate "
      f"offloads verification ARITHMETIC, not signature BYTES, because the sig is still a public input")
check(crossover > COUNT,
      f"the crossover ({crossover} signatures) is honest about how many it would take to pay for itself")

print()
if fails:
    print(f"{len(fails)} CHECK(S) FAILED:")
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("ALL SIG-AGG ACTIVATION CHECKS PASSED")
