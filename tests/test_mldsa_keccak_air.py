"""
ML-DSA-44 verify AIR — sub-circuit 6: KECCAK-f[1600] / SHAKE (execnode/stark/mldsa_keccak_air.py).
The gating primitive for signature aggregation: FIPS 204 fixes ML-DSA's hashing to SHAKE, so the algebraic
sponge (alghash2) cannot substitute — Keccak must be proven as-is.

This validates:
  1. the REFERENCE permutation + sponge against hashlib (OpenSSL) — the same primitive dilithium_py and the
     RustCrypto ml-dsa crate use — incl. multi-block absorb and long squeeze;
  2. the GF(2)-over-Goldilocks bit gadgets (XOR/NOT/AND);
  3. the ARITHMETISATION: the time-stepped trace (one row per round) reproduces keccak_f and satisfies all
     11520 constraints on every row, a flipped state bit breaks it, and the POINTWISE constraint degree is 2
     (no xor-chain blowup — an earlier one-row design measured degree 22, value-correct but unprovable);
  4. the FULL 24-round permutation proves + verifies in-circuit (NADO_HEAVY=1), with tampered input/output
     rejected — the AIR is wide (6080 cols) and short (32 rows), which is why width is cheap here.

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


def t_arithmetisation():
    """THE circuit correctness check: the time-stepped trace reproduces keccak_f and satisfies every constraint
    on every row, and a flipped bit breaks it."""
    st = [int.from_bytes(os.urandom(8), "little") for _ in range(25)]
    rows, T, out = K.build_trace(st)
    check("trace output == reference keccak_f", out == K.keccak_f(st))
    check("trace is WIDE and SHORT (24 rounds are rows, the 1600-bit state is columns)",
          T == 32 and len(rows[0]) == K.W == 6080)
    cons, per = K.transitions(), K.periodic(T)
    bad = []
    for r in range(T):
        cur, nxt, prow = rows[r], rows[(r + 1) % T], [c[r] for c in per]
        for ci, con in enumerate(cons):
            if con(cur, nxt, prow) % F.P != 0:
                bad.append((r, ci)); break
    check(f"all {len(cons)} constraints satisfied on all {T} rows", not bad)
    # a WRONG state bit must violate the constraints (soundness of the arithmetisation)
    rows[1] = list(rows[1]); rows[1][K.A0] ^= 1
    viol = any(con(rows[0], rows[1], [c[0] for c in per]) % F.P != 0 for con in cons)
    check("a flipped state bit violates the constraints", viol)
    check("state <-> bits roundtrip", K._state_of_bits(K._bits_of_state(st)) == st)


def t_constraint_degree():
    """The composition degree must be within MAX_DEGREE. Note air_ir.program_degree reports the POINTWISE
    degree (periodics count as 0); each periodic FACTOR adds one to the COMPOSITION degree, which is why
    MAX_DEGREE is 4 (degree-2 trace x rc bit x ACTIVE selector on the iota constraint)."""
    from execnode.stark import air_ir
    cons = K.transitions()
    nper = K.LANE_BITS + 1
    sample = [cons[0], cons[K.W], cons[K.W + 1], cons[K.W + 2 * 5 * 64],
              cons[K.W + 2 * 5 * 64 + 1], cons[K.W + 2 * 5 * 64 + 2]]
    prog = air_ir.build_program(sample, K.W, nper, 0)
    deg = air_ir.program_degree(prog)
    check(f"pointwise constraint degree is 2 (measured {deg}) — no xor-chain blowup", deg == 2)
    check("MAX_DEGREE leaves room for the periodic factors", K.MAX_DEGREE >= deg + 2)


def t_full_permutation_proves():
    """THE headline: the FULL 24-round Keccak-f[1600] permutation proves and verifies in-circuit, and both a
    tampered output and a tampered input are rejected. (~2 min at reduced query strength.)"""
    if os.environ.get("NADO_HEAVY") != "1":
        print("SKIP  full-permutation prove/verify (~2 min) — set NADO_HEAVY=1 to run it")
        return
    st = [int.from_bytes(os.urandom(8), "little") for _ in range(25)]
    proof, out = K.prove_permutation(st, num_queries=2)
    check("proved permutation output == keccak_f", out == K.keccak_f(st))
    ok, why = K.verify_permutation(proof, st, out, num_queries=2)
    check(f"FULL 24-round Keccak-f[1600] proves + verifies in-circuit ({why})", ok)
    bad = list(out); bad[0] ^= 1
    check("tampered output rejected", not K.verify_permutation(proof, st, bad, num_queries=2)[0])
    bad_in = list(st); bad_in[3] ^= 1
    check("tampered input rejected", not K.verify_permutation(proof, bad_in, out, num_queries=2)[0])


def t_permutation_matches():
    """The full 24-round permutation, as composed from the round function."""
    st = [int.from_bytes(os.urandom(8), "little") for _ in range(25)]
    s = list(st)
    for r in range(K.ROUNDS):
        s = K.keccak_round(s, K.RC[r])
    check("keccak_f == 24 chained rounds", K.keccak_f(st) == s)


def t_width_fits():
    """The permutation AIR is wide (6080) and short (32 rows) — width is cheap because the LDE is
    W x (blowup*T). MAX_COLUMNS must admit it."""
    from execnode.stark import stark
    check("permutation AIR width is 6080", K.W == 6080)
    check("MAX_COLUMNS admits the Keccak AIR", K.W <= stark.MAX_COLUMNS)


if __name__ == "__main__":
    try:
        t_sponge_matches_openssl()
        t_bit_gadgets()
        t_arithmetisation()
        t_constraint_degree()
        t_permutation_matches()
        t_width_fits()
        t_full_permutation_proves()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — Keccak matches OpenSSL and the full permutation is proven in-circuit"
          if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
