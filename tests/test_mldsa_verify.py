"""
ML-DSA-44 — the ASSEMBLED verification (execnode/stark/mldsa_verify.py) built from every sub-circuit, checked
against BOTH golden references on REAL signatures: dilithium_py (internal mode) and, when built, the native
RustCrypto ml-dsa backend that nado actually verifies with.

This is the test that says whether the sub-circuits compose into a correct ML-DSA verifier: it must ACCEPT
valid signatures and REJECT tampered messages, tampered signatures, wrong keys, and out-of-bound/malleable
encodings — agreeing with the reference on every case.

Run: python3 tests/test_mldsa_verify.py
"""
import os, sys, binascii, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_verify_")
os.environ["NADO_TESTNET"] = "1"
os.environ.setdefault("NADO_PQ_NATIVE_MODULE", "nado_pq_native")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from execnode.stark import mldsa_params as P, mldsa_verify as MV

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def _golden():
    from dilithium_py.ml_dsa import ML_DSA_44 as m
    return m


_M = _golden()
_PK, _SK = _M.keygen()
_MSG = b"nado-assembled-verify"
_SIG = _M._sign_internal(_SK, _MSG, b"\x00" * 32)          # INTERNAL mode — nado's mode
assert _M._verify_internal(_PK, _MSG, _SIG), "reference signature must verify"


def t_accepts_valid():
    check("assembled verifier ACCEPTS a real valid signature", MV.verify(_PK, _MSG, _SIG) is True)


def t_agrees_with_native_backend():
    """The reputable production verifier (RustCrypto ml-dsa via nado_pq_native) must agree."""
    import signatures
    if type(signatures._BACKEND).__name__ != "_NativeBackend":
        print("SKIP  native RustCrypto backend not active")
        return
    hexpk, hexsig = binascii.hexlify(_PK).decode(), binascii.hexlify(_SIG).decode()
    check("native RustCrypto also accepts", signatures.verify(hexsig, hexpk, _MSG) is True)
    check("assembled verifier agrees with native on the valid case",
          MV.verify(_PK, _MSG, _SIG) == signatures.verify(hexsig, hexpk, _MSG))


def t_rejects_tampered():
    check("REJECTS a tampered message", MV.verify(_PK, _MSG + b"x", _SIG) is False)
    bad_sig = bytearray(_SIG); bad_sig[0] ^= 1
    check("REJECTS a tampered c_tilde", MV.verify(_PK, _MSG, bytes(bad_sig)) is False)
    bad_z = bytearray(_SIG); bad_z[P.C_TILDE_BYTES + 5] ^= 1
    check("REJECTS a tampered z", MV.verify(_PK, _MSG, bytes(bad_z)) is False)
    bad_pk = bytearray(_PK); bad_pk[40] ^= 1
    check("REJECTS a tampered public key", MV.verify(bytes(bad_pk), _MSG, _SIG) is False)
    pk2, _sk2 = _M.keygen()
    check("REJECTS a different signer's key", MV.verify(pk2, _MSG, _SIG) is False)


def t_rejects_malformed():
    check("REJECTS a short signature", MV.verify(_PK, _MSG, _SIG[:-1]) is False)
    check("REJECTS a short public key", MV.verify(_PK[:-1], _MSG, _SIG) is False)
    # non-canonical hint encoding (malleability) must be refused by the decoder
    bad = bytearray(_SIG)
    hint_off = P.C_TILDE_BYTES + P.L * MV.Z_BYTES
    bad[hint_off + P.OMEGA] = 255                      # impossible cut
    check("REJECTS a non-canonical hint encoding", MV.verify(_PK, _MSG, bytes(bad)) is False)


def t_multiple_signatures():
    """Several independent keypairs/messages, cross-checked against the reference both ways."""
    ok_all = True
    for n in range(3):
        pk, sk = _M.keygen()
        msg = b"msg-%d" % n
        sig = _M._sign_internal(sk, msg, bytes([n]) * 32)
        if MV.verify(pk, msg, sig) is not True or _M._verify_internal(pk, msg, sig) is not True:
            ok_all = False; break
        if MV.verify(pk, msg + b"!", sig) is not False:
            ok_all = False; break
    check("3 independent signatures: accepted valid, rejected tampered (agrees with reference)", ok_all)


def t_workload_statement():
    """The measured per-sub-circuit workload a full proof must cover."""
    st = MV.statement(_PK, _MSG, _SIG)
    for k in ("decode_coeffs", "norm_rows", "usehint_rows", "ntt_transforms", "ntt_butterflies",
              "modq_products", "expand_a_draws", "keccak_permutations"):
        check(f"statement reports {k} = {st[k]}", isinstance(st[k], int) and st[k] > 0)
    print(f"      -> per signature: {st['keccak_permutations']} Keccak permutations, "
          f"{st['ntt_butterflies']} NTT butterflies, {st['modq_products']} mod-Q products, "
          f"{st['norm_rows'] + st['usehint_rows']} range rows")


if __name__ == "__main__":
    try:
        t_accepts_valid()
        t_agrees_with_native_backend()
        t_rejects_tampered()
        t_rejects_malformed()
        t_multiple_signatures()
        t_workload_statement()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — the assembled ML-DSA-44 verification agrees with the reference"
          if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
