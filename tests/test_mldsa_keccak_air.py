"""
ML-DSA-44 verify AIR — sub-circuit 6: KECCAK-f[1600] / SHAKE (execnode/stark/mldsa_keccak_air.py).
The gating primitive for signature aggregation: FIPS 204 fixes ML-DSA's hashing to SHAKE, so the algebraic
sponge (alghash2) cannot substitute — Keccak must be proven as-is.

This validates:
  1. the REFERENCE permutation + sponge against hashlib (OpenSSL) — the same primitive dilithium_py and the
     RustCrypto ml-dsa crate use — incl. multi-block absorb and long squeeze;
  2. the GF(2)-over-Goldilocks bit gadgets (XOR/NOT/AND);
  3. the ROUND ARITHMETISATION: every constraint of the single-round AIR is satisfied by a real Keccak round,
     and the trace's claimed output equals the reference round (this is the correctness of the circuit);
  4. the width reality: one round is 3*1600 = 4800 columns, which is what dictates the composition strategy
     for the full 24-round permutation (see the note at the end of this file).

Run: python3 tests/test_mldsa_keccak_air.py
"""
import os, sys, hashlib, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_keccak_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from execnode.stark import field as F, mldsa_keccak_air as K

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1


def t_sponge_matches_openssl():
    cases = {
        "shake256 empty": (K.shake256(b"", 32), hashlib.shake_256(b"").digest(32)),
        "shake128 empty": (K.shake128(b"", 32), hashlib.shake_128(b"").digest(32)),
        "shake256 abc": (K.shake256(b"abc", 64), hashlib.shake_256(b"abc").digest(64)),
        "shake128 abc": (K.shake128(b"abc", 64), hashlib.shake_128(b"abc").digest(64)),
    }
    for name, (ours, ref) in cases.items():
        check(f"{name} matches hashlib", ours == ref)
    # multi-block absorb + long squeeze (the ExpandA / mu / c_tilde shapes)
    for ln in (200, 1000):
        d = os.urandom(ln)
        check(f"shake256 len={ln} multi-block absorb + 200B squeeze matches hashlib",
              K.shake256(d, 200) == hashlib.shake_256(d).digest(200))
        check(f"shake128 len={ln} multi-block absorb + 200B squeeze matches hashlib",
              K.shake128(d, 200) == hashlib.shake_128(d).digest(200))


def t_bit_gadgets():
    for a in (0, 1):
        check(f"NOT {a}", K.notb(a) % F.P == (1 - a))
        for b in (0, 1):
            check(f"XOR {a},{b}", K.xor(a, b) % F.P == (a ^ b))
            check(f"AND {a},{b}", K.andb(a, b) % F.P == (a & b))


def t_round_arithmetisation():
    """THE circuit correctness check: a real Keccak round satisfies every constraint of the round AIR, and the
    trace's output bits decode to exactly the reference round's output."""
    st = [int.from_bytes(os.urandom(8), "little") for _ in range(25)]
    row, out = K.round_trace_row(st, K.RC[0])
    check("round trace output == reference keccak_round", out == K.keccak_round(st, K.RC[0]))
    cons = K.round_transitions(K.RC[0])
    bad = [ci for ci, con in enumerate(cons) if con(row, row, []) % F.P != 0]
    check(f"all {len(cons)} round constraints satisfied by a real Keccak round", not bad)
    # a WRONG output must violate the constraints (soundness of the arithmetisation)
    bad_row = list(row)
    bad_row[K.OUT0] ^= 1
    viol = [ci for ci, con in enumerate(cons) if con(bad_row, bad_row, []) % F.P != 0]
    check("a flipped output bit violates the constraints", len(viol) > 0)
    # the state<->bits mapping roundtrips
    check("state <-> bits roundtrip", K._state_of_bits(K._bits_of_state(st)) == st)


def t_permutation_matches():
    """The full 24-round permutation, as composed from the round function."""
    st = [int.from_bytes(os.urandom(8), "little") for _ in range(25)]
    s = list(st)
    for r in range(K.ROUNDS):
        s = K.keccak_round(s, K.RC[r])
    check("keccak_f == 24 chained rounds", K.keccak_f(st) == s)


def t_width_reality():
    """One round is 3*1600 = 4800 columns (in | out | chi AND-products). This EXCEEDS stark.MAX_COLUMNS, which
    is the engineering fact that dictates how the 24-round permutation must be composed (see the module note):
    a per-round proof at this width needs either a raised column cap or a lane/bit-sliced decomposition."""
    check("round AIR width is 3*1600", K.W == 3 * K.STATE_BITS == 4800)
    from execnode.stark import stark
    check("width exceeds the current MAX_COLUMNS (documents the composition constraint)",
          K.W > stark.MAX_COLUMNS)


if __name__ == "__main__":
    try:
        t_sponge_matches_openssl()
        t_bit_gadgets()
        t_round_arithmetisation()
        t_permutation_matches()
        t_width_reality()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — Keccak reference matches OpenSSL and the round arithmetisation is correct"
          if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
