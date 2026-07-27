"""
ML-DSA-44 verify AIR — sub-circuit 4: decompose + UseHint + hint weight (execnode/stark/mldsa_hint_air.py),
validated against dilithium_py.utilities.utils (decompose / use_hint / high_bits). See
doc/zk-signature-aggregation.md.

Run: python3 tests/test_mldsa_hint_air.py
"""
import os, sys, random, tempfile, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_hint_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from execnode.stark import mldsa_params as P, mldsa_hint_air as HA

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        fails += 1

NQ = 4
Q, A = P.Q, 2 * P.GAMMA_2


def _ref():
    from dilithium_py.utilities import utils
    return utils


def t_decompose_matches_reference():
    u = _ref()
    random.seed(7)
    vals = [0, 1, A, A - 1, A + 1, Q - 1, Q - 2, (Q - 1) // 2] + [random.randrange(Q) for _ in range(300)]
    ok_all = True
    for r in vals:
        if HA.decompose(r) != u.decompose(r, A, Q):
            ok_all = False
            print(f"   decompose mismatch at r={r}: ours={HA.decompose(r)} ref={u.decompose(r, A, Q)}")
            break
    check(f"decompose matches dilithium utils.decompose ({len(vals)} values incl. wrap edges)", ok_all)


def t_use_hint_matches_reference():
    u = _ref()
    random.seed(11)
    vals = [0, 1, A, Q - 1, Q - 2] + [random.randrange(Q) for _ in range(300)]
    ok_all = True
    for r in vals:
        for h in (0, 1):
            if HA.use_hint(h, r) != u.use_hint(h, r, A, Q):
                ok_all = False
                print(f"   use_hint mismatch r={r} h={h}: ours={HA.use_hint(h, r)} ref={u.use_hint(h, r, A, Q)}")
                break
        if not ok_all:
            break
    check("use_hint matches dilithium utils.use_hint (both hint values)", ok_all)


def t_high_bits_matches():
    u = _ref()
    random.seed(13)
    vals = [random.randrange(Q) for _ in range(200)]
    check("high_bits (decompose r1) matches the reference",
          all(HA.decompose(r)[0] == u.high_bits(r, A, Q) for r in vals))


def t_prove_verify():
    random.seed(3)
    items = [(random.randrange(Q), random.randrange(2)) for _ in range(24)]
    items += [(Q - 1, 1), (Q - 1, 0), (0, 1), (A, 1)]          # wrap + edge cases
    proof = HA.prove(items, num_queries=NQ)
    ok, why = HA.verify(proof, items, num_queries=NQ)
    check(f"UseHint batch (incl. wrap edges) proves + verifies ({why})", ok)
    # outputs the AIR pins must equal the reference
    u = _ref()
    check("pinned outputs equal the reference use_hint",
          HA.outputs(items) == [u.use_hint(h, r, A, Q) for r, h in items])


def t_tampered_rejected():
    random.seed(5)
    items = [(random.randrange(Q), random.randrange(2)) for _ in range(8)]
    proof = HA.prove(items, num_queries=NQ)
    bad = list(items); bad[2] = ((bad[2][0] + 1) % Q, bad[2][1])
    ok, _ = HA.verify(proof, bad, num_queries=NQ)
    check("a tampered public coefficient is rejected", not ok)
    flipped = list(items); flipped[1] = (flipped[1][0], 1 - flipped[1][1])
    ok2, _ = HA.verify(proof, flipped, num_queries=NQ)
    check("a flipped hint bit is rejected", not ok2)


def t_weight_bound():
    check("hint weight <= omega accepted", HA.weight_ok([1] * P.OMEGA))
    check("hint weight > omega rejected", not HA.weight_ok([1] * (P.OMEGA + 1)))


if __name__ == "__main__":
    try:
        t_decompose_matches_reference()
        t_use_hint_matches_reference()
        t_high_bits_matches()
        t_prove_verify()
        t_tampered_rejected()
        t_weight_bound()
    except Exception as e:
        fails += 1; print(f"FAIL  exception: {e}"); traceback.print_exc()
    print("\nALL PASS — decompose/UseHint/hint-weight match Dilithium" if fails == 0 else f"\n{fails} FAILURES")
    sys.exit(1 if fails else 0)
