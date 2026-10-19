"""The incremental state root re-folds only what changed, and is bit-identical to the full fold.

snapshot_ops._fold_levels keeps the previous merkle tree and re-hashes only the pairs whose inputs changed
(2026-10-19: the whole tree used to be re-folded every block, the largest per-block cost of a resync). The L1 state
root is CONSENSUS: one differing bit is a fork. So this drives it through long random edit sequences — value changes,
inserts and deletes anywhere, appends, truncation to 0/1/2 leaves, odd and even lengths, the tree growing and
shrinking a level — and checks every root against _merkle_from_leaves (the definition), then checks that a
value-only change really is cheap (it re-hashes O(log N) pairs, not N).

Run: python3 tests/test_the_incremental_state_root_refolds_only_what_changed.py
"""
import _harness
HOME = _harness.isolate("nado-test-incremental-root-fold-")
import hashlib
import random

from ops import snapshot_ops as SO

T = _harness.Report()
rnd = random.Random(20261019)
leaf = lambda: hashlib.blake2b(rnd.randbytes(16), digest_size=32).digest()


def full(flat):
    return SO._merkle_from_leaves(list(flat))       # it pads in place: give it a copy, as the walk does


bad, steps = [], 0
for trial in range(60):
    flat, levels = [leaf() for _ in range(rnd.choice([0, 1, 2, 3, 7, 64, 65, 300]))], None
    for step in range(120):
        op = rnd.random()
        flat = list(flat)                              # _root_from_inc builds a fresh list every call
        if op < 0.45 and flat:                         # value changes (the common block)
            for _ in range(rnd.randint(1, 4)):
                flat[rnd.randrange(len(flat))] = leaf()
        elif op < 0.65:                                # inserts anywhere
            for _ in range(rnd.randint(1, 3)):
                flat.insert(rnd.randint(0, len(flat)), leaf())
        elif op < 0.80 and flat:                       # deletes anywhere
            for _ in range(min(len(flat), rnd.randint(1, 3))):
                del flat[rnd.randrange(len(flat))]
        elif op < 0.88:                                # appends (new heights)
            flat.extend(leaf() for _ in range(rnd.randint(1, 5)))
        elif op < 0.93:                                # truncate to a tiny tree, a level collapses
            flat = flat[:rnd.choice([0, 1, 2, 3])]
        # else: nothing changed at all
        root, levels = SO._fold_levels(levels, flat)
        steps += 1
        if root != full(flat):
            bad.append((trial, step, len(flat)))
T.check(f"every incremental root equals the full fold ({steps} random edits)", not bad, bad[:5])

# the same leaves through a fresh call (levels=None) and an incremental one agree
flat = [leaf() for _ in range(1000)]
r0, lv = SO._fold_levels(None, flat)
T.check("a first fold (no previous tree) equals the full fold", r0 == full(flat))
T.check("an unchanged leaf list re-folds to the same root", SO._fold_levels(lv, list(flat))[0] == r0)
T.check("the empty state's root is blake2b of nothing, as the walk's", SO._fold_levels(lv, [])[0] == full([]))

# cost: count blake2b calls for one changed value in 100k leaves
flat = [leaf() for _ in range(100_000)]
_, lv = SO._fold_levels(None, flat)
calls = [0]
real = SO.hashlib.blake2b


class Counting:
    def __getattr__(self, n):
        return getattr(hashlib, n)

    @staticmethod
    def blake2b(*a, **k):
        calls[0] += 1
        return real(*a, **k)


SO.hashlib = Counting()
try:
    flat2 = list(flat)
    flat2[54321] = leaf()
    r, _ = SO._fold_levels(lv, flat2)
finally:
    SO.hashlib = hashlib
T.check("one changed value in 100,000 leaves re-hashes one path (17 pairs), not the tree (~100,000)",
        calls[0] <= 20 and r == full(flat2), calls[0])
T.done("ALL PASS — the incremental state root re-folds only what changed, bit-identically")
