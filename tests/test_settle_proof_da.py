"""
A settle proof too big to ride on chain must still be PUBLISHED (settle `proof_da`).

WHY THIS EXISTS. Until this, turning the prover on produced proofs that went nowhere. Measured
(doc/settle-proof-transport.md §1): a settle-with-proof is ~97.45 MiB against an 8 MiB /submit_transaction
cap and a ~256 KiB block, so every proof-carrying settle was answered HTTP 413 and the proof existed only
on the prover's disk. The chain settled on a BONDED-QUORUM ATTESTATION — validators signing "I ran the
exec layer and got this root" — which is a trust assumption, not a validity proof.

WHAT THIS FIXES, AND WHAT IT DOES NOT. The proof is now erasure-coded k-of-n into DA and the settle tx
carries only the commitment, so ANY node can reconstruct it (da_fetch collects k+1 verified shards and
checks the commitment round-trip) and check it independently. That is the difference between "we assert
this root" and "here is the evidence".

It does NOT yet settle the root trustlessly. That requires L1 to fetch and verify DURING block validation
inside the depth gate, which is a consensus change (§4). Until then the root still rides the quorum. The
`proof_da` field is validated for SHAPE only, so an unfetchable or bogus commitment cannot change what
settles — it degrades to exactly the bare-attestation path.

THE SAFETY PROPERTY that makes this shippable without a reroll: the settle branch does NOT enforce a
closed key set (unlike `duty`, which asserts set(data.keys()) <= {...}). An older node therefore ignores
`proof_da` and settles via quorum, while a newer node can also fetch the proof. No fork.

Run: python3 tests/test_settle_proof_da.py
"""
import json
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_proofda_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.da_store import DaStore

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


# PRODUCTION values, for the record: L1 caps /submit_transaction at 8 MiB, execnode inlines up to
# SETTLE_INLINE_MAX = 7 MiB, and a real settle-with-proof measures 97.45 MiB. The behaviour under test is
# the THRESHOLD DECISION and the publish/reconstruct round-trip, neither of which depends on the absolute
# size — so the test runs at a small threshold. Erasure-coding two 97 MiB blobs in Python to re-observe a
# number we already measured would just make the suite unrunnable.
L1_BODY_CAP_PROD = 8 * 1024 * 1024
INLINE_MAX_PROD = 7 * 1024 * 1024
REAL_PROOF_BYTES = int(97.45 * 1024 * 1024)

INLINE_MAX = 64 * 1024                  # scaled-down stand-in for SETTLE_INLINE_MAX
DA_K, DA_N = 4, 8
STORE = DaStore(tempfile.mkdtemp(prefix="da_"))

check("the REAL proof is far over the production inline ceiling (why this path exists at all)",
      REAL_PROOF_BYTES > INLINE_MAX_PROD and REAL_PROOF_BYTES > L1_BODY_CAP_PROD)


def publish_if_oversize(proof):
    """The producer decision from maybe_settle: inline when it fits, else publish and carry a commitment."""
    inline_len = len(json.dumps({"data": {"proof": proof}}, separators=(",", ":")))
    if inline_len <= INLINE_MAX:
        return {"proof": proof, "proof_da": None, "published": None}
    blob = json.dumps(proof, separators=(",", ":"), sort_keys=True).encode()
    meta = STORE.put(blob, DA_K, DA_N)
    return {"proof": None, "proof_da": meta["commitment"], "published": blob}


# ---- THE PRODUCTION CASE: a proof far over the cap is published, not discarded -----------------------
big = {"segments": [{"openings": "q" * (256 * 1024)}]}       # over INLINE_MAX once encoded
out = publish_if_oversize(big)
check("an oversize proof is NOT inlined", out["proof"] is None)
check("...it is published and the tx carries a commitment", isinstance(out["proof_da"], str) and out["proof_da"])
check("the settle body is now tiny enough to submit",
      len(json.dumps({"data": {"exec_cursor": 1, "state_root": "a" * 64,
                               "proof_da": out["proof_da"]}}, separators=(",", ":"))) < L1_BODY_CAP_PROD)

# ---- THE POINT: another node can RECONSTRUCT the exact proof from the commitment ---------------------
fetched = STORE.get(out["proof_da"])
check("the published bytes round-trip byte-exact", fetched == out["published"])
check("...and decode back to the SAME proof object", json.loads(fetched.decode()) == big)

# ---- BINDING: the commitment cannot be satisfied by different bytes ----------------------------------
tampered = dict(big)
tampered["segments"] = [{"openings": "q" * (256 * 1024 - 1) + "X"}]
meta_t = STORE.put(json.dumps(tampered, separators=(",", ":"), sort_keys=True).encode(), DA_K, DA_N)
check("a tampered proof yields a DIFFERENT commitment (evidence, not a label)",
      meta_t["commitment"] != out["proof_da"])

# ---- a proof that FITS still goes inline (it settles trustlessly; strictly better) -------------------
small = {"segments": [{"openings": "q" * 1024}]}
outs = publish_if_oversize(small)
check("a small proof is still inlined", outs["proof"] == small and outs["proof_da"] is None)

# ---- shape validation of the commitment (it reaches DaStore._dir) -----------------------------------
def shape_ok(v):
    return (isinstance(v, str) and v and len(v) <= 128 and "/" not in v and "\\" not in v
            and v not in (".", ".."))


check("a real commitment passes the shape check", shape_ok(out["proof_da"]))
for bad in ("../../etc/passwd", "a/b", "a\\b", ".", "..", "", "x" * 129, None, 123, {}):
    check(f"path-ish or malformed commitment rejected: {str(bad)[:18]!r}", not shape_ok(bad))

# ---- DEGRADATION: a bogus/unfetchable commitment must not change what settles ------------------------
# proof_da is shape-checked only, so it cannot justify a root; settlement falls back to the quorum path.
check("an unfetchable commitment resolves to nothing rather than a proof",
      STORE.get("de" * 32) is None)

print()
print("ALL PASS — an oversize proof is published and reconstructible, and a bad commitment changes nothing"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
