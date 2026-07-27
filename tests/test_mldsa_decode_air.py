"""
ML-DSA-44 verify AIR — sub-circuit 5: the signature/pubkey DECODER (execnode/stark/mldsa_decode_air.py).
Validated against dilithium_py's real bit_unpack_t1 / bit_unpack_z / bit_unpack_w and _unpack_h, using a REAL
ML-DSA-44 signature + public key (internal mode — nado's mode). See doc/zk-signature-aggregation.md.

Run: python3 tests/test_mldsa_decode_air.py
"""
import os, sys, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_decode_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from execnode.stark import mldsa_params as P, mldsa_decode_air as DEC

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1

NQ = 4


def _golden():
    from dilithium_py.ml_dsa import ML_DSA_44 as m
    return m


# a REAL keypair + signature, INTERNAL mode (nado's mode; see tests/test_mldsa_conformance.py)
_M = _golden()
_PK, _SK = _M.keygen()
_MSG = b"nado-decode-air"
_SIG = _M._sign_internal(_SK, _MSG, b"\x00" * 32)
assert _M._verify_internal(_PK, _MSG, _SIG), "reference signature must verify"


def t_t1_decode_matches_reference():
    """Public key = rho(32) || t1 packed at 10 bits/coeff, k=4 polys of 320 bytes."""
    rho, t1 = _M._unpack_pk(_PK)
    check("pk splits as rho(32) + t1", len(rho) == 32 and len(_PK) == P.PK_BYTES)
    t1_bytes = _PK[32:]
    ok_all = True
    for i in range(P.K):
        chunk = t1_bytes[i * 320:(i + 1) * 320]
        ours = DEC.unpack_t1(chunk)
        ref = t1._data[0][i].coeffs if hasattr(t1, "_data") else None
        if ref is None or ours != [c % (1 << 10) for c in ref]:
            ok_all = ours == list(ref)
            if not ok_all:
                print(f"   t1 poly {i} mismatch: ours[:4]={ours[:4]} ref[:4]={list(ref)[:4]}")
                break
    check("t1 10-bit decode matches dilithium bit_unpack_t1 (all 4 polys)", ok_all)


def t_z_decode_matches_reference():
    """Signature = c_tilde(32) || z packed at 18 bits/coeff (l=4 x 576 bytes) || h(omega+k)."""
    c_tilde, z, h = _M._unpack_sig(_SIG)
    check("sig splits as c_tilde(32) + z + h", len(c_tilde) == P.C_TILDE_BYTES and len(_SIG) == P.SIG_BYTES)
    z_bytes = _SIG[32:32 + P.L * 576]
    ok_all = True
    for i in range(P.L):
        chunk = z_bytes[i * 576:(i + 1) * 576]
        ours = DEC.unpack_z(chunk)
        ref = list(z._data[0][i].coeffs)
        if ours != ref:
            ok_all = False
            print(f"   z poly {i} mismatch: ours[:4]={ours[:4]} ref[:4]={ref[:4]}")
            break
    check("z 18-bit decode (gamma_1 - x) matches dilithium bit_unpack_z (all 4 polys)", ok_all)


def t_h_decode_matches_reference():
    _c, _z, h = _M._unpack_sig(_SIG)
    h_bytes = _SIG[32 + P.L * 576:]
    ours = DEC.unpack_h(h_bytes)
    check("hint bytes are omega+k long", len(h_bytes) == P.OMEGA + P.K)
    ok = ours is not None and all(ours[i] == list(h._data[0][i].coeffs) for i in range(P.K))
    check("hint decode matches dilithium _unpack_h (all 4 polys)", ok)
    # canonicality: a non-monotonic cut or unsorted positions must be rejected
    bad = bytearray(h_bytes); bad[P.OMEGA + 1] = 0        # make cuts non-monotonic (cut[1] < cut[0]) if cut[0]>0
    if h_bytes[P.OMEGA] > 0:
        check("non-monotonic hint cuts rejected (malleability)", DEC.unpack_h(bytes(bad)) is None)
    else:
        print("SKIP  non-monotonic cut case (this signature has an empty first hint poly)")


def t_prove_verify_decode():
    """PROVE the decode of a real z polynomial and a real t1 polynomial."""
    z_chunk = _SIG[32:32 + 576]
    proof, coeffs = DEC.prove_field(z_chunk, "z", num_queries=NQ)
    ok, why = DEC.verify_field(proof, z_chunk, "z", coeffs, num_queries=NQ)
    check(f"z decode proves + verifies against the real signature bytes ({why})", ok)
    bad = list(coeffs); bad[0] += 1
    ok2, _ = DEC.verify_field(proof, z_chunk, "z", bad, num_queries=NQ)
    check("a tampered claimed coefficient is rejected", not ok2)

    t1_chunk = _PK[32:32 + 320]
    p2, c2 = DEC.prove_field(t1_chunk, "t1", num_queries=NQ)
    ok3, why3 = DEC.verify_field(p2, t1_chunk, "t1", c2, num_queries=NQ)
    check(f"t1 decode proves + verifies against the real pubkey bytes ({why3})", ok3)


def t_w1_width():
    """w1 packs at 6 bits for gamma_2 = 95232 (level-2) — 192 bytes per poly."""
    import os as _os
    blob = _os.urandom(192)
    ours = DEC.unpack_w1(blob)
    from dilithium_py.polynomials.polynomials import PolynomialRing
    ref = PolynomialRing().bit_unpack_w(blob, P.GAMMA_2).coeffs
    check("w1 6-bit decode matches dilithium bit_unpack_w", ours == list(ref))


if __name__ == "__main__":
    try:
        t_t1_decode_matches_reference()
        t_z_decode_matches_reference()
        t_h_decode_matches_reference()
        t_w1_width()
        t_prove_verify_decode()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — the decoder matches Dilithium on a real signature" if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
