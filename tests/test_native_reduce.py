"""
Fast Goldilocks reduction (native/alghash2, wasm/goldilocks, native/starkcompose): the field multiply uses a
division-free Goldilocks reduction (reduce128) instead of a generic u128 % p. It is the prover's hottest inner
op (permute/NTT/composition), so it must be BIT-IDENTICAL to Python `% P` — a one-bit divergence silently
invalidates every proof. This guards that across the three native surfaces that expose the field math.
(Run: python3 tests/test_native_reduce.py — needs the native libs built; skips cleanly if not.)
"""
import os, sys, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import alghash2 as a2, goldilocks_native as gn, field as F
import execnode.stark.field as Fm

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _py_permute(state):
    s = list(state)
    for r in range(a2.ROUNDS):
        s = [a2.sbox(F.add(s[i], a2.RC[r][i])) for i in range(a2.WIDTH)]
        s = [sum(F.mul(a2._MDS[i][j], s[j]) for j in range(a2.WIDTH)) % F.P for i in range(a2.WIDTH)]
    return s


def _py_hashn(els):
    full = [len(els)] + [int(e) % F.P for e in els]
    st = [0] * a2.RATE + list(a2.IV)
    for off in range(0, len(full), a2.RATE):
        for i, m in enumerate(full[off:off + a2.RATE]):
            st[i] = F.add(st[i], m)
        st = _py_permute(st)
    return tuple(st[:a2.CAPACITY])


def _py_ntt(vals):
    N = len(vals); a = [v % F.P for v in vals]; Fm._bitrev(a)
    w = Fm.primitive_root_of_unity(N); L = 2
    while L <= N:
        wl = pow(w, N // L, F.P)
        for i in range(0, N, L):
            wn = 1
            for k in range(i, i + L // 2):
                u = a[k]; v = a[k + L // 2] * wn % F.P
                a[k] = (u + v) % F.P; a[k + L // 2] = (u - v) % F.P; wn = wn * wl % F.P
        L <<= 1
    return a


def t_hashn_native_eq_python():
    if not a2._try_native():
        print("  (native alghash2 unbuilt — skip)"); return
    random.seed(11); bad = 0
    for _ in range(4000):
        els = [random.randrange(F.P) for _ in range(random.randint(1, 24))]
        if a2.hashn(els) != _py_hashn(els):
            bad += 1
    # edge values that stress the reduction (near-p products)
    for els in ([F.P - 1], [F.P - 1, F.P - 1], [1, F.P - 1], [0], [F.P - 1] * 8):
        if a2.hashn(els) != _py_hashn(els):
            bad += 1
    assert bad == 0, f"{bad} hashn mismatches (fast-reduce divergence)"


def t_ntt_native_eq_python():
    if not gn.available():
        print("  (native goldilocks unbuilt — skip)"); return
    for Nexp in (6, 10, 14, 17):
        N = 1 << Nexp; random.seed(Nexp)
        vals = [random.randrange(F.P) for _ in range(N)]
        # include extreme values
        vals[0] = F.P - 1; vals[1] = 1; vals[2] = 0
        assert gn.ntt(vals, False) == _py_ntt(vals), f"NTT mismatch 2^{Nexp}"


def t_rmerkle_native_eq_python():
    if not a2._try_native() or not hasattr(a2._try_native()[0], "rmerkle_commit"):
        print("  (native rmerkle unbuilt — skip)"); return
    for exp in (1, 4, 9, 12):
        n = 1 << exp; random.seed(exp + 3)
        vals = [random.randrange(F.P) for _ in range(n)]
        rn, ln = a2.rmerkle_commit(vals)
        layer = [a2.rleaf(v) for v in vals]; lp = [layer]
        while len(layer) > 1:
            layer = [a2.rnode(layer[i], layer[i + 1]) for i in range(0, len(layer), 2)]; lp.append(layer)
        assert rn == lp[-1][0] and ln == lp, f"rmerkle mismatch n={n}"


if __name__ == "__main__":
    check("hashn native (fast reduce) == python (4000 random + edge values)", t_hashn_native_eq_python)
    check("NTT native (fast reduce) == python (2^6..2^17)", t_ntt_native_eq_python)
    check("rmerkle native (fast reduce) == python", t_rmerkle_native_eq_python)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
