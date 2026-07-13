"""
Native ML-DSA-44 backend (native/mldsa44 + nado_pq_native.py): FIPS 204 internal-mode interop
with the pure-Python reference — identical seeded keygen (addresses!), cross-verification in
both directions, negative rejection. SKIPS (passes) when the .so isn't built on this machine.

Run: scripts/build_pq_native.sh && python3 tests/test_pq_native.py
"""
import os, sys, secrets
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import nado_pq_native as native
except ImportError as e:
    print(f"SKIP  native backend not built ({e}) — run scripts/build_pq_native.sh")
    sys.exit(0)

from dilithium_py.ml_dsa import ML_DSA_44

seed = secrets.token_bytes(32)
pk_n, sk_n = native.keygen_internal(seed)
pk_p, sk_p = ML_DSA_44._keygen_internal(seed)
assert (pk_n, sk_n) == (pk_p, sk_p), "seeded keygen must be byte-identical (addresses derive from pk)"

msg = secrets.token_bytes(64)
rnd = secrets.token_bytes(32)
sig_n = native.sign_internal(sk_n, msg, rnd)
sig_p = ML_DSA_44._sign_internal(sk_p, msg, rnd)
assert ML_DSA_44._verify_internal(pk_p, msg, sig_n), "pure-python must verify a native signature"
assert native.verify_internal(pk_n, msg, sig_p), "native must verify a pure-python signature"
assert not native.verify_internal(pk_n, msg + b"x", sig_n), "tampered message must reject"
assert not native.verify_internal(pk_n, msg, bytes([sig_n[0] ^ 1]) + sig_n[1:]), "tampered sig must reject"

print("ALL PQ-NATIVE INTEROP CHECKS PASSED")
