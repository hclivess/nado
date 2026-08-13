"""
Persisting the singleton-fold cache across restarts (storage_tree.save_fold_cache / load_fold_cache).

WHY IT EXISTS: measured 2026-08-13 on betanet-2 (8,376 slots, depth 256, native arena, a real 30-block
span), a settle prove is 58.9 s cold and 10.2 s warm — 50.0 s of the cold number is SparseStore.root()
rebuilding singleton folds. The in-memory _FOLD_CACHE removes that for the second prove in a process;
this removes it for the first. A restarted exec node and every verify in a fresh process pay it today.

WHAT MUST BE TRUE, and what these checks pin:

  * THE ROOT NEVER MOVES. The cache memoizes a pure function, so a root computed cold, warm, or from a
    loaded file must be bit-identical. If this ever fails the feature is a consensus bug, not a slow path
    — which is why it is the first check.
  * A WRONG FILE IS REFUSED, not partially trusted. Persisting turns an in-process cache into an on-disk
    input, so corruption and cross-parameter reuse become real: a torn write, a bit-flip, or a file
    written under different alghash2 parameters would otherwise feed silent garbage into a
    consensus-visible root. Both guards fail closed, and a tampered entry discards the WHOLE file.
  * REJECTION IS NOT AN ERROR. An unusable file must leave the caller computing the correct root the slow
    way — never raising, never returning a wrong root.

NATIVE KERNELS ARE REQUIRED and asserted below. Every fold here is an alghash2 permutation, and the
Python fallback is a different implementation of the same function — so a run under
NADO_ALLOW_PYTHON_KERNELS would be exercising code no node ships and could agree with itself while
disagreeing with production. That exact mistake (benchmarking with the Python kernels) produced two wrong
FRI conclusions on 2026-08-13; see doc/fri-parameters.md §4. If the .so is missing or stale, BUILD IT
(`cd native/alghash2 && cargo build --release`) — do not set the escape-hatch env var to make this pass.
"""
import json
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
    from execnode.stark import storage_tree as ST
    from execnode.stark import alghash2 as A2

    # HARD GUARD: refuse to certify anything on the Python permutation (see the module docstring).
    if os.environ.get("NADO_ALLOW_PYTHON_KERNELS"):
        print("FATAL: NADO_ALLOW_PYTHON_KERNELS is set — this test certifies the SHIPPED path only.")
        return 1
    if not A2._try_native():
        print("FATAL: native alghash2 not loaded (missing or stale .so). "
              "Build it: cd native/alghash2 && cargo build --release")
        return 1
    print("native alghash2: loaded")

    D = 64                                 # deep enough that every key is a long singleton fold
    vals = {(i * 2654435761) & ((1 << D) - 1): (i + 1) * 7 for i in range(120)}

    # ---- the root is the same cold and warm -------------------------------------------------------
    ST.clear_fold_cache()
    cold = ST.SparseStore(D, vals).root()
    warm = ST.SparseStore(D, vals).root()
    check("root identical cold vs warm (in-process cache)", cold == warm)

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "folds.json")
        n = ST.save_fold_cache(path, D)
        check("save wrote the folds", n > 0 and os.path.exists(path))

        # ---- a loaded cache reproduces the SAME root ----------------------------------------------
        ST.clear_fold_cache()
        loaded = ST.load_fold_cache(path, D)
        check("load accepted the file", loaded == n)
        check("root from a LOADED cache is bit-identical", ST.SparseStore(D, vals).root() == cold)

        # ---- and it actually populated the cache (not a silent no-op) -----------------------------
        check("loaded entries are in the live cache", any(k[0] == D for k in ST._FOLD_CACHE))

        # ---- guard 1: fingerprint mismatch is refused ---------------------------------------------
        blob = json.load(open(path))
        blob["fingerprint"] = "0" * 32
        json.dump(blob, open(path, "w"))
        ST.clear_fold_cache()
        check("fingerprint mismatch refused", ST.load_fold_cache(path, D) == 0)
        check("root still correct after a refused load", ST.SparseStore(D, vals).root() == cold)

        # a cache written at one depth must not load at another
        ST.clear_fold_cache()
        ST.SparseStore(D, vals).root()
        ST.save_fold_cache(path, D)
        ST.clear_fold_cache()
        check("wrong depth refused", ST.load_fold_cache(path, D + 1) == 0)

        # ---- guard 2: a tampered DIGEST is caught by spot-recompute --------------------------------
        ST.clear_fold_cache()
        ST.SparseStore(D, vals).root()
        ST.save_fold_cache(path, D)
        blob = json.load(open(path))
        for row in blob["rows"]:                       # corrupt every digest so the sample must hit one
            row[3] = [(int(x) + 1) % A2.F.P if hasattr(A2, "F") else int(x) + 1 for x in row[3]]
        json.dump(blob, open(path, "w"))
        ST.clear_fold_cache()
        check("tampered digests refused (spot-recompute)", ST.load_fold_cache(path, D) == 0)
        check("root correct after tampering was refused", ST.SparseStore(D, vals).root() == cold)

        # ---- malformed / truncated files fail closed, never raise ---------------------------------
        open(path, "w").write("{not json")
        ST.clear_fold_cache()
        check("garbage file refused without raising", ST.load_fold_cache(path, D) == 0)
        ST.clear_fold_cache()
        check("missing file is a silent 0", ST.load_fold_cache(os.path.join(d, "nope.json"), D) == 0)
        check("root correct with no cache at all", ST.SparseStore(D, vals).root() == cold)

    print()
    print("ALL FOLD-CACHE PERSIST CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
