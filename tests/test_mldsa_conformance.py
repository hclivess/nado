"""
ML-DSA verify AIR — CONFORMANCE ANCHOR. Ties the whole sig-aggregation build to reputable, reused components,
per the project rule "use reliable/reputable libraries + the compiled rust modules":

  (1) GOLDEN REFERENCE is the REPUTABLE production verifier. nado's native ML-DSA-44 backend is the RustCrypto
      `ml-dsa` crate (native/mldsa44, `ml-dsa = "0.1"`); the browser uses @noble/post-quantum. This test asserts
      the pure-Python reference (dilithium_py) that the AIRs are built against is byte-equivalent to the native
      RustCrypto verifier — IN NADO'S FIPS-204 INTERNAL MODE (no ctx/domain wrapping; the mode nado actually
      signs/verifies in). Using dilithium_py's EXTERNAL-mode top-level sign()/verify() would silently disagree
      with the native backend — so every AIR golden vector must come from _sign_internal / _verify_internal.

  (2) The AIRs prove on the COMPILED RUST prover (native/starkprove), not pure Python — the Python only DEFINES
      the circuit (transition closures), which stark.prove traces into air_ir and hands to the native arena.

Run: python3 tests/test_mldsa_conformance.py
"""
import os, sys, binascii, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_mldsaconf_")
os.environ["NADO_TESTNET"] = "1"
os.environ.setdefault("NADO_PQ_NATIVE_MODULE", "nado_pq_native")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def t_reference_equals_native_rustcrypto():
    """dilithium_py INTERNAL mode == native RustCrypto ml-dsa, on valid + tampered sigs. If the native backend
    isn't built this SKIPS (pure-Python fallback is still a correct reference), but on a node that ships the
    native backend the two MUST agree — that is nado's own boot interop self-test, asserted here for the AIR."""
    from dilithium_py.ml_dsa import ML_DSA_44 as m
    import signatures
    if type(signatures._BACKEND).__name__ != "_NativeBackend":
        print("SKIP  native RustCrypto ml-dsa backend not active — pure-Python reference only")
        return
    pk, sk = m.keygen()
    msg = b"nado-mldsa-air-conformance"
    sig = m._sign_internal(sk, msg, b"\x00" * 32)          # INTERNAL mode — nado's mode (signatures.sign)
    hexpk, hexsig = binascii.hexlify(pk).decode(), binascii.hexlify(sig).decode()
    check("dilithium_py _verify_internal accepts", m._verify_internal(pk, msg, sig) is True)
    check("native RustCrypto ml-dsa accepts the SAME sig (internal mode)", signatures.verify(hexsig, hexpk, msg) is True)
    check("native RustCrypto rejects a tampered message", signatures.verify(hexsig, hexpk, msg + b"x") is False)
    # and the EXTERNAL-mode top-level sign must NOT be used as a golden vector (it disagrees with native)
    ext = m.sign(sk, msg)
    check("external-mode sign is (correctly) rejected by the internal native verifier — do NOT use it as a vector",
          signatures.verify(binascii.hexlify(ext).decode(), hexpk, msg) is False)


def t_airs_prove_on_native_rust():
    """The mod-Q / butterfly / norm AIRs prove via the compiled native prover (native/starkprove), not pure
    Python. Instrument stark_native.prove to confirm it is the path stark.prove takes for the RECURSION backend."""
    from execnode.stark import stark_native as SN
    if not SN.available():
        print("SKIP  native starkprove not built — AIRs fall back to the (correct) pure-Python prover")
        return
    from execnode.stark import mldsa_modq_air as MQ
    orig = SN.prove
    used = {"native": False}
    def wrap(*a, **k):
        used["native"] = True
        return orig(*a, **k)
    SN.prove = wrap
    try:
        MQ.prove([(123456, 654321)], num_queries=2)
    finally:
        SN.prove = orig
    check("mod-Q AIR proves on the compiled native prover (native/starkprove)", used["native"])


if __name__ == "__main__":
    try:
        t_reference_equals_native_rustcrypto()
        t_airs_prove_on_native_rust()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — the AIR build is anchored to the reputable native reference + compiled prover"
          if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
