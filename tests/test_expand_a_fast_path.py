"""ExpandA's fast XOF path must be BIT-IDENTICAL to the proven sponge.

mldsa_sample_air._xof_stream serves two different needs. Generating a sponge WITNESS needs SP.shake, whose
whole value is the permutation trace the sponge AIR constrains. Computing a VALUE -- which is all ExpandA
does, since the matrix A is public data both prover and verifier derive independently -- needs only the
bytes, and hashlib's SHAKE128 is the same standard in C.

WHY THIS TEST IS NOT OPTIONAL. A is consensus data. If the two paths ever disagreed by one byte, nodes would
derive different matrices, w' would differ, and signatures valid on one node would be invalid on another --
a chain split arriving through a performance optimisation. So the equivalence is asserted here rather than
assumed, at the stream level AND at the matrix level.

Cost that motivated it: SP.shake at 17.14 ms per 4096-byte stream x K*L = 16 streams put expand_a at
285-456 ms, over a thousand times the ~195 us of an entire native ML-DSA verification, purely to recompute
public data. The fast path is 1.76 ms.

Run: python3 tests/test_expand_a_fast_path.py
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.stark import mldsa_sample_air as SA, mldsa_sponge_air as SP, mldsa_params as P

N, Q, MASK23 = P.N, P.Q, SA.MASK23
fails = 0


def check(ok, name):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def _reference_poly(rho, i, j, max_bytes=4096):
    """Rejection sampling driven by the PROVEN sponge — the path this optimisation replaces."""
    seed = SA.expand_a_seed(rho, i, j)
    stream = SP.shake(seed, max_bytes, SP.RATE_128)
    coeffs, pos = [], 0
    while len(coeffs) < N:
        if pos + 3 > len(stream):
            stream = SP.shake(seed, len(stream) * 2, SP.RATE_128)
            continue
        v = int.from_bytes(stream[pos:pos + 3], "little") & MASK23
        pos += 3
        if v < Q:
            coeffs.append(v)
    return coeffs


# 1. stream level, several lengths — including one that is not a multiple of the 168-byte rate
for nbytes in (168, 336, 4096, 4097):
    seed = bytes(range(34))
    check(bytes(SP.shake(seed, nbytes, SP.RATE_128)) == hashlib.shake_128(seed).digest(nbytes),
          f"XOF stream identical at {nbytes} bytes")

# 2. matrix level, over several seeds
mismatch = 0
for n in range(4):
    rho = bytes([n] * 32)
    fast = SA.expand_a(rho)
    for i in range(P.K):
        for j in range(P.L):
            if fast[i][j] != _reference_poly(rho, i, j):
                mismatch += 1
check(mismatch == 0, f"expand_a bit-identical to the proven-sponge path ({P.K * P.L * 4} entries)")

# 3. the witness path is NOT diverted — a caller asking for the trace still gets the proven sponge
seed = bytes(range(34))
check(bytes(SA._xof_stream(seed, 512, SP.RATE_128, witness=True)) ==
      bytes(SP.shake(seed, 512, SP.RATE_128)), "witness=True still routes to the proven sponge")

# 4. a non-128 rate is never diverted (SHAKE256 is a different function)
check(SA._xof_stream(seed, 256, SP.RATE_256) == SP.shake(seed, 256, SP.RATE_256)
      if hasattr(SP, "RATE_256") else True, "non-128 rate falls through to the proven sponge")

print()
print("ALL PASS — the fast ExpandA path is the same function" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
