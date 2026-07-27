"""
ML-DSA-44 (Dilithium2, FIPS 204 INTERNAL mode) constants — the shared parameter table for the in-circuit
signature-VERIFICATION AIR (doc/zk-signature-aggregation.md: replace per-tx PQ signature checks with ONE STARK
proof of block validity). Pure data — no external deps, so `import execnode.stark.mldsa_*` is always safe.

These MUST match dilithium_py.ml_dsa.ML_DSA_44 (the golden reference) and static/vendor/nado-crypto.js (@noble,
the browser verifier) byte-for-byte — the circuit proves the SAME verification every on-chain signature and the
browser already run, so any drift here silently forks. tests/test_mldsa_norm_air.py asserts the match.

Field note: the STARK field is Goldilocks (P = 2^64 - 2^32 + 1, execnode/stark/field.py). Dilithium's modulus
Q = 8380417 < 2^23 is a DIFFERENT, much smaller prime, emulated over Goldilocks: a product of two reduced
coefficients is < 2^46 and fits one Goldilocks element without overflow, so mod-Q reduction is done by HINT
(quotient/remainder) + a range check rather than field-natively.
"""

# --- ring / modulus ---
Q = 8380417                      # Dilithium prime, 23-bit; NTT is 256-point negacyclic (root order 512)
N = 256                          # polynomial degree (coeffs per poly)
D = 13                           # dropped low bits of t (t1 = t >> d)

# --- ML-DSA-44 dimensions ---
K = 4                            # rows of A / size of t1, w
L = 4                            # cols of A / size of z
ETA = 2                          # secret coefficient bound
TAU = 39                         # # of +-1 entries in the challenge c
BETA = TAU * ETA                 # = 78; challenge*secret norm slack
GAMMA_1 = 1 << 17                # = 131072; y coefficient range (=> z = y + c*s1 bound)
GAMMA_2 = 95232                  # = (Q-1)//88; low-order rounding range (decompose)
OMEGA = 80                       # max total number of 1's in the hint h
C_TILDE_BYTES = 32               # length of the challenge seed c_tilde (lambda/4)

# --- byte lengths (FIPS 204, ML-DSA-44) ---
SEEDBYTES = 32                   # rho, K seeds
PK_BYTES = 1312                  # rho(32) + t1 packed(4*320)
SIG_BYTES = 2420                 # c_tilde(32) + z packed(4*576) + h packed(omega + k = 84)

# The z-coefficient bound the verify enforces: ||z||_inf < GAMMA_1 - BETA (FIPS 204 Alg 8 line "if ||z||>=..").
Z_BOUND = GAMMA_1 - BETA         # = 130994; a coefficient's centered abs value must be strictly below this

# consistency invariants (cheap self-checks; the real cross-check vs dilithium_py is in the tests)
assert 88 * GAMMA_2 == Q - 1, "GAMMA_2 must be (Q-1)/88"
assert BETA == TAU * ETA
assert GAMMA_1 == 131072 and GAMMA_2 == 95232
assert PK_BYTES == 1312 and SIG_BYTES == 2420
assert 0 < Z_BOUND < Q
