"""storage_tree's cross-store singleton-fold cache must be INVISIBLE except in the clock.

MEASURED 2026-08-06 on production state (25 zkVM contracts, 9,016 slots, depth 256): building the sparse
root cost 65.1 s, which is 2,308,096 alghash2 permutations at ~24 us each. The permutation is already
native Rust and genuinely does ~10k Goldilocks multiplications (54 rounds x a dense 12x12 MDS), so there
was no FFI overhead left to shave — the only way down was to perform FEWER permutations. With the cache
the same root takes 0.46 s (141x), and rebuilding after 40 changed slots — a realistic settle span —
takes 0.58 s.

That matters because settlement_sparse builds a FRESH SparseStore on every prove AND on every verify, so
this cost was paid over and over. It was the whole of the `sparse_projection` stage, which had become the
dominant term (237.9 s of a 308.7 s prove) once the K=1 fold was gated off.

THE RISK THE CACHE CARRIES is that a memo returns a digest that does not match a from-scratch fold — that
would silently change the settled state root and fork L2. These checks pin the invariant: cold, warm and
delta roots must be IDENTICAL, authentication paths must still fold to the root, and entries must not
leak across DEPTHS (a test store at depth 16 shares the process with a production store at depth 256).

Run: python3 tests/test_fold_cache.py
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import storage_tree as ST, field as F

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


DEPTH = 32
# keys spread over the space so most of each key's chain is a singleton fold — the case the cache targets
VALS = {(i * 0x9E3779B97F4A7C15) % (1 << DEPTH): (i * 7 + 11) % F.P for i in range(1, 60)}


def _root(values, depth=DEPTH):
    return ST.SparseStore(depth, values).root()


def t_warm_root_equals_cold_root():
    ST.clear_fold_cache()
    cold = _root(VALS)
    warm = _root(VALS)                       # second build reads the cache for every key
    assert cold == warm, "a warm build produced a DIFFERENT root — the cache is not a pure memo"


def t_delta_root_equals_from_scratch():
    """The dangerous case: a warm cache holding the OLD value of a slot that has since changed."""
    ST.clear_fold_cache()
    _root(VALS)
    changed = dict(VALS)
    for k in sorted(changed)[:5]:
        changed[k] = (changed[k] * 13 + 29) % F.P
    warm = _root(changed)
    ST.clear_fold_cache()
    cold = _root(changed)
    assert warm == cold, "root after a delta differs cold vs warm — stale entries are being reused"


def t_deletion_agrees():
    """Writing 0 deletes a key; the deleted key's cached fold must not resurface."""
    ST.clear_fold_cache()
    _root(VALS)
    thinned = {k: v for k, v in VALS.items() if k != sorted(VALS)[0]}
    warm = _root(thinned)
    ST.clear_fold_cache()
    assert warm == _root(thinned), "root after a deletion differs cold vs warm"


def t_incremental_set_agrees_with_rebuild():
    ST.clear_fold_cache()
    s = ST.SparseStore(DEPTH, VALS)
    s.root()
    changed = dict(VALS)
    for k in sorted(VALS)[:5]:
        changed[k] = (VALS[k] * 3 + 1) % F.P
        s.set(k, changed[k])
    assert s.root() == _root(changed), "set()-driven root != rebuilt root under a warm cache"


def t_paths_still_authenticate():
    ST.clear_fold_cache()
    s = ST.SparseStore(DEPTH, VALS)
    r = s.root()
    for k in sorted(VALS)[:6]:
        assert ST.fold(VALS[k], k, s.path(k)) == r, f"path for {k} no longer folds to the root"
    for k in sorted(VALS)[:6]:                # again, now that every fold is cached
        assert ST.fold(VALS[k], k, s.path(k)) == r, f"warm path for {k} no longer folds to the root"


def t_depth_isolation():
    """The cache key must carry `depth` — the empty roots e[i] differ per depth, so a depth-16 entry
    reused at depth 256 (or the reverse) would be a wrong digest with a valid-looking shape."""
    small = {1: 5, 2: 9, 300: 11}
    ST.clear_fold_cache()
    a16 = _root(small, 16)
    a20 = _root(small, 20)
    ST.clear_fold_cache()
    assert a16 == _root(small, 16), "depth-16 root polluted by another depth"
    ST.clear_fold_cache()
    assert a20 == _root(small, 20), "depth-20 root polluted by another depth"
    assert a16 != a20, "different depths must give different roots (the fixture is degenerate)"


def t_cache_is_bounded():
    """An unbounded memo on a long-running exec node is a leak; the module must cap and reset it."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "execnode", "stark", "storage_tree.py")).read()
    assert "_FOLD_CACHE_MAX" in src, "the cache must declare a maximum size"
    assert "_FOLD_CACHE.clear()" in src, "the cache must reset when it hits its cap"


def t_lower_level_request_is_correct():
    """A request BELOW the cached high-water mark recomputes rather than returning the higher digest."""
    ST.clear_fold_cache()
    s = ST.SparseStore(DEPTH, VALS)
    s.root()                                  # folds every key to its separation level
    k = sorted(VALS)[0]
    lo = s._singleton_fold(k, 3)
    ST.clear_fold_cache()
    assert lo == s._singleton_fold(k, 3), "a below-high-water fold returned a cached HIGHER level"


for nm, fn in [("warm root == cold root", t_warm_root_equals_cold_root),
               ("root after a delta == from scratch", t_delta_root_equals_from_scratch),
               ("root after a deletion == from scratch", t_deletion_agrees),
               ("incremental set() == rebuild", t_incremental_set_agrees_with_rebuild),
               ("paths still authenticate", t_paths_still_authenticate),
               ("entries do not leak across depths", t_depth_isolation),
               ("the cache is bounded", t_cache_is_bounded),
               ("a below-high-water fold is recomputed", t_lower_level_request_is_correct)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
