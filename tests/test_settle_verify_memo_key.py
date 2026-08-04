"""The settle-proof verdict cache must key on the proof's BYTES, never on the claims it makes.

WHY THIS EXISTS. A pooled settle tx is re-validated on EVERY block-candidate build, and re-running the
proof verification each time is what turned the block-producing core loop into a 91 s loop and took the
node OUT OF CONSENSUS (blocks frozen 221 s, 219 unhealthy episodes, 2026-08-04). The fix was to memoise
the cryptographic verdict — but the first version keyed it on

    (cursor, kv_pre, kv_post, rec, rec_post)

which is everything the proof ASSERTS and nothing it PROVES. The FRI openings — the part that is actually
verified — were not in the key. So two proofs making identical claims shared one entry, and verifying an
HONEST settle cached ok=True under a key a CORRUPTED settle also matched: the tampered proof was then
accepted having never been verified at all. tests/test_settle_depth_gate caught it ("corrupted proof is
REJECTED near the tip") by truncating seg["proof"]["openings"] while leaving every claim untouched.

A CACHE THAT ANSWERS FOR INPUT IT NEVER SAW IS NOT A CACHE — it is a bypass. Speed work on a consensus
path must not widen what verifies; that is the whole trade being tested here.

Run: python3 tests/test_settle_verify_memo_key.py
"""
import os
import sys
import copy
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_memokey_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.transaction_ops import settle_verify_key

fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


# A proof and a TAMPERED one that makes byte-for-byte identical CLAIMS — only the verified body differs.
HONEST = {
    "cursor": 23323,
    "kv_pre": "aa" * 32,
    "kv_post": "bb" * 32,
    "rec": "cc" * 32,
    "rec_post": "cc" * 32,
    "segments": [{"proof": {"openings": [{"lo": 1}, {"lo": 2}, {"lo": 3}], "fri": {"queries": [1, 2, 3]}}}],
}
TAMPERED = copy.deepcopy(HONEST)
TAMPERED["segments"][0]["proof"]["openings"] = TAMPERED["segments"][0]["proof"]["openings"][:-1]

# ---- THE PROPERTY THE OLD KEY VIOLATED ----------------------------------------------------------------
for f in ("cursor", "kv_pre", "kv_post", "rec", "rec_post"):
    assert HONEST[f] == TAMPERED[f], "fixture must differ ONLY in the proof body"
check("the fixture differs only in the verified body, not in any claim", HONEST != TAMPERED)

k_honest = settle_verify_key(HONEST, None, False)
k_tamper = settle_verify_key(TAMPERED, None, False)
check("a tampered inline proof gets a DIFFERENT key (so it is verified afresh)", k_honest != k_tamper)

# The exact shape of the old key, rebuilt here: it CANNOT distinguish these two. This is the regression.
old = lambda p: (str(p.get("cursor")), str(p.get("kv_pre")), str(p.get("kv_post")),
                 str(p.get("rec")), str(p.get("rec_post")))
check("...whereas the old claims-only key could not tell them apart at all", old(HONEST) == old(TAMPERED))

# ---- THE CACHE MUST STILL CACHE (or the outage comes straight back) -----------------------------------
check("the same inline proof keys identically (the memo still hits)",
      settle_verify_key(HONEST, None, False) == settle_verify_key(copy.deepcopy(HONEST), None, False))

# ---- DA PROOFS KEY ON THE COMMITMENT ------------------------------------------------------------------
# The commitment is a hash-based Merkle root over the exact shard set, so different bytes cannot present
# the same commitment; the local DA store checks that round-trip before handing the blob back.
C1 = "4441ea8a9e6db120fc68359979a3989e0caebffc80ce480e4d84e041c4cc3763"
C2 = "ea5f1f53ed52afee7ac4bdc67a73b0481b0c29f847f9ca5a8a9048bad9361d07"
check("a DA proof keys on its commitment", settle_verify_key(HONEST, C1, True) == ("da", C1))
check("two DA commitments never share an entry",
      settle_verify_key(HONEST, C1, True) != settle_verify_key(HONEST, C2, True))
check("the same DA commitment hits the memo (this is what keeps the core loop off 91 s)",
      settle_verify_key(HONEST, C1, True) == settle_verify_key(TAMPERED, C1, True))

# A DA-carried proof and an INLINE one must never collide even at the same commitment string: the inline
# body was never bound to that commitment by anything.
check("an inline proof and a DA proof never share a key",
      settle_verify_key(HONEST, C1, True) != settle_verify_key(HONEST, C1, False))

# ---- the shipped code must actually use it ------------------------------------------------------------
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "ops", "transaction_ops.py")).read()
check("validate_transaction builds its key through settle_verify_key",
      "_vk = settle_verify_key(proof, _pda, _from_da)" in src)
check("_from_da is only set once the proof actually came back from DA",
      "_from_da = False" in src and "_from_da = True" in src)
check("the claims-only key is gone", 'str(proof.get("kv_pre"))' not in src)

print()
print("ALL PASS — the verdict cache is bound to the bytes that were verified"
      if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
