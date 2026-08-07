"""The RECORDS verdict must be memoized, and the key must bind the proof's BYTES.

WHY IT EXISTS. The KV half has been memoized since settle_verify_key was written; the records half was not,
so every revalidation of a mempool transaction re-ran a ~900-1050 s verification. Measured live on span
7800->7866 (29 effects):

    08:41:17  [settle-verify] KV half        15.7s ok=True    <- once, memo hits thereafter
    08:58:55  [settle-verify] RECORDS half 1057.2s ok=True    <- the submit
    09:13:50  [settle-verify] RECORDS half  878.9s ok=True    <- AGAIN, 15 minutes later

That cost stalled this node at block 7364 and again at 8203 while the rest of the fleet ran on, and it was
GUARANTEED to recur: a proof-carrying settle is an exact-landing tx that waits ~280 blocks for its slot, so
it sits across many block-production attempts and is revalidated by construction.

WHY THE KEY SHAPE IS THE DANGEROUS PART. settle_verify_key's docstring records the original defect: the
cache was keyed on the proof's CLAIMS (cursor, roots), so a CORRUPTED proof asserting the same claims
matched an honest proof's cached ok=True and was accepted WITHOUT EVER BEING VERIFIED. A verdict cache that
does not bind bytes is a soundness hole, not a speedup — so these checks are mostly about the key, not about
the caching.

Run: python3 tests/test_records_verdict_memo.py
"""
import ast
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SRC_PATH = os.path.join(ROOT, "ops", "transaction_ops.py")
SRC = open(SRC_PATH).read()
TREE = ast.parse(SRC)

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _records_key_expr():
    """The assignment that builds the records memo key, as source text."""
    for n in ast.walk(TREE):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "_rvk"):
            return ast.get_source_segment(SRC, n.value) or ""
    raise AssertionError("no _rvk (records memo key) assignment in transaction_ops.py")


def t_the_records_half_is_memoized_at_all():
    """The whole point: without this the node re-verifies ~1000 s per revalidation and falls behind."""
    assert "_rvk" in SRC, "the records verdict must be cached"
    got = SRC.count("_SETTLE_VERIFY_MEMO[")
    assert got >= 2, f"expected both halves to populate the memo, found {got} writes"


def t_the_key_binds_the_proof_identity_not_just_claims():
    """settle_verify_key binds BYTES (blake2b over the inline proof, or the DA commitment). The records key
    must be built ON TOP of it — keying on roots alone is exactly the bug that once accepted a tampered
    proof without verifying it."""
    expr = _records_key_expr()
    assert "_vk" in expr, (
        f"the records key must include _vk (the byte-binding proof identity), got: {expr}")


def t_the_key_also_binds_the_roots_and_the_effects():
    """Same proof bytes can be presented against different asserted roots or a different derived effect set;
    those are different questions and must not share a verdict."""
    expr = _records_key_expr()
    for needed in ("rec_hex", "rec_post_hex"):
        assert needed in expr, f"the records key must bind {needed}, got: {expr}"
    assert "_eff" in expr, f"the records key must bind the derived effect set, got: {expr}"
    assert "blake2b_hash" in expr, (
        f"the effect set must be DIGESTED into the key, not compared by object identity: {expr}")


def t_a_miss_still_verifies_in_full():
    """The cache may skip work only on a hit. On a miss bind_and_verify_records must still run — a memo that
    swallows the verification on a miss would accept anything."""
    fn_src = SRC[SRC.index("_rvk = "):]
    head = fn_src[:1200]
    assert "_rhit is not None" in head, "must branch on a real hit"
    assert "bind_and_verify_records" in head, "a miss must fall through to the full verification"


def t_the_verdict_is_stored_only_after_verifying():
    """Store-after-verify, never before — a pre-populated entry would be a verdict nobody computed."""
    i_ver = SRC.index("bind_and_verify_records(")
    i_store = SRC.index("_SETTLE_VERIFY_MEMO[_rvk]")
    assert i_store > i_ver, "the records verdict must be written AFTER the verification that produced it"


def t_the_memo_stays_bounded():
    """A proof is tens of MiB; entries are tiny, but the dict must still not grow without bound."""
    seg = SRC[SRC.index("_rvk = "):]
    assert "_SETTLE_VERIFY_MEMO_MAX" in seg[:1500], "the records path must respect the size bound too"


def t_the_effect_digest_is_deterministic():
    """Resolve and CALL: the key is only stable if hashing the same effect list twice agrees."""
    from hashing import blake2b_hash
    eff = [(2, ("a",), 1), (2, ("b",), 2)]
    assert blake2b_hash(eff) == blake2b_hash(list(eff)), "same effects must digest identically"
    assert blake2b_hash(eff) != blake2b_hash(eff[:1]), "different effects must digest differently"


for nm, fn in [("the records half is memoized at all", t_the_records_half_is_memoized_at_all),
               ("the key binds the proof identity", t_the_key_binds_the_proof_identity_not_just_claims),
               ("the key binds roots and effects", t_the_key_also_binds_the_roots_and_the_effects),
               ("a miss still verifies in full", t_a_miss_still_verifies_in_full),
               ("the verdict is stored only after verifying", t_the_verdict_is_stored_only_after_verifying),
               ("the memo stays bounded", t_the_memo_stays_bounded),
               ("the effect digest is deterministic", t_the_effect_digest_is_deterministic)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
