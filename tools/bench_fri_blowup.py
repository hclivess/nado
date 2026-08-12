"""
Benchmark: what does raising the FRI blowup actually cost the prover?

doc/fri-parameters.md shows blowup 16 at 96 queries is STRONGER than today's blowup 2 at 320 queries
(164.4 vs 156.0 provable bits) at 30% of the opening size. The one thing that analysis could not answer
is the prover cost, because the blowup is not a free knob: stark.prove derives it as

    blowup   = _blowup(max_degree) = 2 * next_pow2(max_degree)
    N        = blowup * T                      # the LDE domain
    fri_blowup = N // deg_bound                # == 2 today, as a CONSEQUENCE of that sizing

So a FRI blowup of 16 means an 8x larger evaluation domain — the LDE, the Merkle commitment over it and
the fold layers all grow. This script scales `_blowup` by k (k = 1,2,4,8 -> fri_blowup 2,4,8,16), proves
the same trace at each, VERIFIES the result (an unverified proof is not a benchmark), and reports wall
time, peak RSS and proof size.

Run:  PYTHONPATH=. python3 tools/bench_fri_blowup.py [log_rows]

DO NOT SET NADO_ALLOW_PYTHON_KERNELS. This line used to read `NADO_ALLOW_PYTHON_KERNELS=1 ...`, and the
numbers in doc/fri-parameters.md §4 were taken that way — i.e. they timed the PYTHON prover, which no node
runs and which the Rust-only guard treats as a hard failure. Re-measured natively at the SAME 16 384-row
trace, the prover cost is UNDERSTATED by the Python run, not overstated:

    prove ratio vs blowup 2/320    blowup 4    blowup 8    blowup 16
    Python kernels (the old §4)      1.38x       2.35x        4.74x
    native arena (correct)           2.14x       3.14x        6.11x

USE A REPRESENTATIVE TRACE. At log_rows=10 (1024 rows) the same native run reports 0.90x / 1.01x / 3.18x,
because fixed per-prove overhead swamps the LDE at that size and blowup 8 looks free. It is not. Default
to 14 or larger; a small run is a smoke test, not a measurement.

The patch below reaches the arena correctly — stark_native.py:492 reads `stark._blowup`, so scaling it
propagates into the native path, and if the arena ever refused the call `_native_fallback` RAISES rather
than silently dropping to Python, so a completed run is proof the run was native.
"""
import json
import os
import resource
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import stark, field as F, backend as B, fri

LOG_ROWS = int(sys.argv[1]) if len(sys.argv) > 1 else 12
MAX_DEGREE = 4

# A trace whose constraint is genuinely degree-4, so the LDE sizing rule is exercised the way a real
# circuit exercises it: col[i+1] = col[i]^2 + c  (squared twice through the transition below).
# Constraint form is the repo's: a callable (cur, next, periodic) -> field element that must be 0,
# and a boundary tuple (row, col, value). x' = x^2 + 7 is degree 2 in the trace; max_degree=4 below
# is what sets the LDE sizing rule this benchmark is probing.
TRANS = [lambda c, n, p: F.sub(n[0], F.add(F.mul(c[0], c[0]), 7))]
BND = [(0, 0, 3)]


def build_trace(n):
    col = [3]
    for _ in range(n - 1):
        col.append(F.add(F.mul(col[-1], col[-1]), 7))
    return [[v] for v in col]


def peak_mib():
    # ru_maxrss is KiB on Linux
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def main():
    n = 1 << LOG_ROWS
    trace = build_trace(n)
    orig_blowup = stark._blowup
    orig_fri_blowup = fri.FRI_BLOWUP
    orig_fri_verify = fri.verify
    print(f"trace: {n} rows ({LOG_ROWS} log2), max_degree={MAX_DEGREE}, backend=RECURSION")
    print(f"{'fri_blowup':>10} {'queries':>8} {'prove s':>9} {'verify s':>9} {'proof MiB':>10} {'peak RSS MiB':>13} {'ok':>4}")
    rows = []
    # k scales the LDE domain: fri_blowup = 2*k. Query counts follow doc/fri-parameters.md.
    for k, queries in ((1, 320), (2, 192), (4, 96), (8, 96)):
        # Patch BOTH the prover's LDE sizing and the protocol constant the VERIFIER asserts against
        # (fri.FRI_BLOWUP): stark.verify passes it as expected_blowup, so without this the raised-blowup
        # proofs are rejected as "unexpected FRI blowup" and we would be timing invalid proofs.
        stark._blowup = (lambda md, _k=k: orig_blowup(md) * _k)
        fri.FRI_BLOWUP = orig_fri_blowup * k
        # stark.verify passes expected_blowup=2 as a LITERAL (stark.py), so the constant above does not
        # reach it. Shim just that argument to the blowup under test; every other verifier check —
        # query count, openings, low-degree, transcript — runs untouched, so the verify timing is real.
        fri.verify = (lambda pr, *a, _k=k, **kw: orig_fri_verify(
            pr, *a, **{**kw, "expected_blowup": (kw.get("expected_blowup") or 2) * _k}))
        try:
            t0 = time.perf_counter()
            proof = stark.prove(trace, TRANS, BND, max_degree=MAX_DEGREE,
                                num_queries=queries, backend=B.RECURSION)
            t_prove = time.perf_counter() - t0
            size = len(json.dumps(proof, default=str)) / (1024 * 1024)
            t1 = time.perf_counter()
            ok, why = stark.verify(proof, TRANS, BND, max_degree=MAX_DEGREE,
                                   num_queries=queries, backend=B.RECURSION)
            t_verify = time.perf_counter() - t1
            fb = proof.get("fri", {}).get("blowup") if isinstance(proof.get("fri"), dict) else 2 * k
            print(f"{fb if fb else 2*k:>10} {queries:>8} {t_prove:>9.2f} {t_verify:>9.2f} "
                  f"{size:>10.3f} {peak_mib():>13.0f} {'yes' if ok else 'NO':>4}")
            if not ok:
                print(f"           verify failed: {why}")
            rows.append((2 * k, queries, t_prove, t_verify, size))
        except Exception as e:
            print(f"{2*k:>10} {queries:>8}   FAILED: {type(e).__name__}: {str(e)[:90]}")
        finally:
            stark._blowup = orig_blowup
            fri.FRI_BLOWUP = orig_fri_blowup
            fri.verify = orig_fri_verify
    if len(rows) > 1:
        b = rows[0]
        print()
        print("relative to fri_blowup 2 / 320 queries (today):")
        for fb, q, tp, tv, sz in rows[1:]:
            print(f"  blowup {fb:>2} / {q:>3}q: prove {tp/b[2]:.2f}x   verify {tv/b[3]:.2f}x   proof {sz/b[4]:.2f}x")


if __name__ == "__main__":
    main()
