"""Leaf-digest cache in snapshot_ops.merkle_root (2026-08-20): pure memoization of
blake2b(_leaf(triple)) — the root must be BIT-IDENTICAL with a hot, cold, or poisoned-size cache,
and repeated walks must actually hit the cache (the per-block state-root walk was 31% of process
CPU; unchanged rows must cost a dict hit, not a pack+hash)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NADO_HOME", "/tmp/nado-leafcache-test-home")   # never the live home
from ops import snapshot_ops as so
import hashlib


def _uncached_root(triples):
    leaves = [hashlib.blake2b(so._leaf(t), digest_size=32).digest() for t in triples]
    if not leaves:
        return so._blake2b(b"")
    while len(leaves) > 1:
        if len(leaves) % 2:
            leaves.append(leaves[-1])
        leaves = [hashlib.blake2b(leaves[i] + leaves[i + 1], digest_size=32).digest()
                  for i in range(0, len(leaves), 2)]
    return leaves[0].hex()


TRIPLES = sorted(("db%d" % (i % 5), b"key%06d" % i, (b"value-%d" % i) * (1 + i % 7))
                 for i in range(5000))


def t1_bit_identical_cold_and_hot():
    so._leaf_cache.clear()
    ref = _uncached_root(TRIPLES)
    assert so.merkle_root(TRIPLES) == ref, "cold-cache root must equal the uncached computation"
    assert so.merkle_root(TRIPLES) == ref, "hot-cache root must equal the uncached computation"
    assert len(so._leaf_cache) == len(TRIPLES), "every leaf should be cached after a walk"


def t2_changed_row_changes_root():
    so._leaf_cache.clear()
    a = so.merkle_root(TRIPLES)
    mutated = list(TRIPLES)
    mutated[123] = (mutated[123][0], mutated[123][1], mutated[123][2] + b"x")
    b = so.merkle_root(mutated)
    assert a != b, "a mutated row must change the root even with a warm cache"
    assert so.merkle_root(TRIPLES) == a, "the original set must still produce the original root"


def t3_flush_bound_exists_and_recovers():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "ops", "snapshot_ops.py")).read()
    assert "if len(_leaf_cache) > 500_000:" in src and "_leaf_cache.clear()" in src, \
        "the cache must be size-bounded (stale deleted-row entries age out with the flush)"
    so._leaf_cache.clear()
    so._leaf_cache.update({("junk", b"%d" % i, b""): b"\0" * 32 for i in range(500_001)})
    ref = _uncached_root(TRIPLES)
    assert so.merkle_root(TRIPLES) == ref, "an over-size flush mid-call must not corrupt the root"
    assert len(so._leaf_cache) <= len(TRIPLES), "the flush must actually have happened"


def t4_hot_walk_faster_than_cold():
    so._leaf_cache.clear()
    t0 = time.perf_counter(); so.merkle_root(TRIPLES); cold = time.perf_counter() - t0
    t0 = time.perf_counter(); so.merkle_root(TRIPLES); hot = time.perf_counter() - t0
    assert hot < cold, f"hot walk ({hot:.4f}s) should beat cold ({cold:.4f}s)"
    print(f"      (cold {cold*1000:.1f}ms -> hot {hot*1000:.1f}ms, {cold/max(hot,1e-9):.1f}x)")


if __name__ == "__main__":
    fails = 0
    for name in ("t1_bit_identical_cold_and_hot", "t2_changed_row_changes_root",
                 "t3_flush_bound_exists_and_recovers", "t4_hot_walk_faster_than_cold"):
        try:
            globals()[name]()
            print(f"PASS  {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL  {name}: {e}")
    print("ALL PASS" if not fails else f"{fails} FAILURE(S)")
    raise SystemExit(1 if fails else 0)
