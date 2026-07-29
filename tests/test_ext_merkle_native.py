"""THE NATIVE EXTENSION-LEAF MERKLE TREE MUST BE BIT-IDENTICAL TO THE PYTHON ONE.

FRI commits an extension leaf per element on every layer once folding starts. Only the BASE-field whole-tree
builds were native, so each of those layers ran n leaf permutations plus n-1 node permutations in a Python
loop — the dominant cost of an extension proof, landing squarely on the settlement fold that the extension
migration exists to make sound. (Profiled live: one in-circuit fold test sat 45 minutes inside
alghash2.permute, reached through _commit_ext.)

A Merkle root is consensus. "Faster" is worth nothing here unless it is the SAME TREE, so this asserts the
root AND every intermediate layer — merkle.open_at walks those layers, so a tree that agrees only at the root
would still produce unopenable paths. Both backends are checked because they frame a leaf differently
(recursion: one permutation, rleaf_ext; sponge: a hashn frame), and using the wrong one yields a well-formed
tree with the wrong root.

Degree-agnostic: it reads extf.DEGREE, so it keeps testing across the next field migration.
"""
import sys, time, random
import os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from execnode.stark import fri, merkle, backend as BK, field as F, extf as E, alghash2 as a2

random.seed(11)
D = E.DEGREE
fails = []
def check(c, l):
    print(("PASS  " if c else "FAIL  ") + l)
    if not c: fails.append(l)

for name, b in (("alghash2", BK.ALGHASH2), ("recursion", BK.RECURSION)):
    for n in (8, 1024):
        vals = [tuple(random.randrange(F.P) for _ in range(D)) for _ in range(n)]
        t0 = time.time()
        py_root, py_layers = merkle.commit_digests([fri._ext_leaf(b, v) for v in vals], b)
        t_py = time.time() - t0
        t0 = time.time()
        nat = a2.rmerkle_commit_ext(vals) if name == "recursion" else a2.merkle_commit_ext(vals)
        t_nat = time.time() - t0
        check(nat is not None, f"{name} n={n}: native build available")
        if nat:
            nr, nl = nat
            check(nr == py_root, f"{name} n={n}: root is BIT-IDENTICAL")
            check([list(x) for x in nl] == [list(x) for x in py_layers],
                  f"{name} n={n}: every layer is bit-identical (open_at walks these)")
            if n >= 1024:
                print(f"        python {t_py:7.3f}s   native {t_nat:7.3f}s   speedup {t_py/max(t_nat,1e-9):6.1f}x")
        # and the live path picks it
        r2, l2 = fri._commit_ext(vals, b)
        check(r2 == py_root, f"{name} n={n}: fri._commit_ext returns the same root")

print()
if fails:
    print(f"{len(fails)} FAILED"); sys.exit(1)
print("NATIVE EXTENSION-LEAF TREES ARE BIT-IDENTICAL")
