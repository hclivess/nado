"""
TWO-PHASE + ROW-MODE recursion (execnode/stark/recursive_verify.py over rowcomp_verify.py): the execution-AIR
shape, at demo scale. Proves a two-phase (LogUp-style: main commit → challenge γ → aux running-sum commit)
ROW-COMMITTED STARK with a dense public periodic column, collapses TWO chained instances into ONE recursion
bundle, and verifies it from the proofs' public parts alone: the transcript replay is two-phase (main root →
γ → aux root → α's), the challenge and the periodic values at each FS-derived query point are verifier-computed
and fed to the composition check, and the opened ROWS are authenticated in-circuit with one path per tree
(4 paths per point — W-independent, the wide-AIR enabler). Wrong challenge protocol, tampered seam, and a lied
boundary are rejected.
(Run: python3 tests/test_recursive_row.py — a few slow alghash2 proofs.)
"""
import os, sys, copy, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, stark, backend as B, recursive_verify as RV, extf as ext2

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

T, SEED, K, NQ, NQO = 8, 123456789 % F.P, 2, 2, 4
PER0 = {"period": 4, "base": [3, 1, 4, 1]}                       # a public periodic column (structured form)
PER0_DENSE = [PER0["base"][i % 4] for i in range(T)]

# AIR: col0' = col0^2 + per0;  col1 = col0^2 (same row);  aux acc' = acc + γ·col0'  (needs the phase-2 γ)
#
# γ IS AN EXTENSION ELEMENT whenever the live challenge field is one, so the accumulator it drives is too and
# is carried as DEGREE base columns. The base-only version of this file did `F.mul(g, row[0])` with g a
# tuple, which Python happily reads as tuple-repetition and turns into a MemoryError several frames away —
# a wrong TYPE surfacing as an allocation failure. Written against the live authority and extf.DEGREE so it
# tracks the field instead of pinning one.
_EXT = stark.ext_challenges_active(B.RECURSION)
D = ext2.DEGREE if _EXT else 1
NAUX = D
ACC0 = 2                                                # aux limbs occupy columns 2 .. 2+D-1


def _acc_c3(c, n, p, ch):
    if not _EXT:
        return F.sub(n[ACC0], F.add(c[ACC0], F.mul(ch[0], n[0])))
    cur = tuple(c[ACC0 + i] for i in range(D))
    nxt = tuple(n[ACC0 + i] for i in range(D))
    return ext2.sub_f(nxt, ext2.add_f(cur, ext2.mul_f(ch[0], n[0])))


TRANS = [lambda c, n, p, ch: F.sub(n[0], F.add(F.mul(c[0], c[0]), p[0])),
         lambda c, n, p, ch: F.sub(c[1], F.mul(c[0], c[0])),
         _acc_c3]
WRONG = [lambda c, n, p, ch: F.sub(n[0], F.add(F.mul(c[0], c[0]), F.add(p[0], 1))),
         TRANS[1], TRANS[2]]


def _build_aux(trace, chals):
    g = chals[0]
    if not _EXT:
        acc, out = 0, []
        for i, row in enumerate(trace):
            if i > 0:
                acc = F.add(acc, F.mul(g, row[0]))
            out.append(acc)
        return [out]
    acc, outs = ext2.ZERO, [[] for _ in range(D)]
    for i, row in enumerate(trace):
        if i > 0:
            acc = ext2.add(acc, ext2.mul(g, row[0]))
        for k in range(D):
            outs[k].append(acc[k])
    return outs


SPEC = {"num_challenges": 1, "num_aux": NAUX, "build": _build_aux}


def _chain():
    proofs, bnds, seed = [], [], SEED
    for _ in range(K):
        col = [seed]
        for i in range(T - 1):
            col.append(F.add(F.mul(col[-1], col[-1]), PER0_DENSE[i]))
        trace = [[v, F.mul(v, v)] for v in col]
        # EVERY limb of the accumulator is pinned at row 0 — pinning one would leave the rest free.
        bl = [(0, 0, seed)] + [(0, ACC0 + i, 0) for i in range(D)]
        proof = stark.prove(trace, TRANS, bl, periodic=[PER0], max_degree=2, num_queries=NQ,
                            aux_spec=SPEC, backend=B.RECURSION, row_commit=True)
        assert stark.verify(proof, TRANS, bl, periodic=[PER0], max_degree=2, num_queries=NQ,
                            aux_spec=SPEC, backend=B.RECURSION, row_commit=True)[0]
        proofs.append(proof); bnds.append(bl)
        seed = F.add(F.mul(col[-1], col[-1]), PER0_DENSE[(T - 1) % 4])
    return proofs, bnds


_PROOFS, _BNDS = _chain()
_BUNDLE = RV.prove(_PROOFS, TRANS, _BNDS, num_queries_outer=NQO, periodic=[PER0],
                   num_challenges=1, num_aux=NAUX)
_PUBLICS = [RV.public_part(p) for p in _PROOFS]


def t_two_phase_row_k_to_1():
    ok, why = RV.verify(_PUBLICS, TRANS, _BNDS, _BUNDLE, num_queries_outer=NQO, periodic=[PER0],
                        num_challenges=1, num_aux=NAUX)
    assert ok, f"two-phase row-mode K={K} must verify from public parts: {why}"


def t_wrong_air_rejected():
    ok, _ = RV.verify(_PUBLICS, WRONG, _BNDS, _BUNDLE, num_queries_outer=NQO, periodic=[PER0],
                      num_challenges=1, num_aux=NAUX)
    assert not ok, "a different AIR must be rejected by the composition half"


def _bump(v):
    """Perturb a seam value by one, whatever field it lives in. `+ 1` was written for a scalar and raises on
    a tuple — and a tamper test that raises still 'passes' a naive assert-not-ok, so this had to move with
    the field or it would have stopped testing anything the moment the seam became extension-valued."""
    if isinstance(v, tuple):
        return ((v[0] + 1) % F.P,) + tuple(v[1:])
    return (v + 1) % F.P


def t_tampered_seam_rejected():
    bad = copy.deepcopy(_PUBLICS)
    bad[0]["layer0"][0] = _bump(bad[0]["layer0"][0])
    ok, _ = RV.verify(bad, TRANS, _BNDS, _BUNDLE, num_queries_outer=NQO, periodic=[PER0],
                      num_challenges=1, num_aux=NAUX)
    assert not ok, "a declared layer-0 != the committed one must be rejected (seam integrity)"


def t_lied_boundary_rejected():
    bad = [list(bl) for bl in _BNDS]
    bad[1][0] = (0, 0, (SEED + 1) % F.P)
    ok, _ = RV.verify(_PUBLICS, TRANS, bad, _BUNDLE, num_queries_outer=NQO, periodic=[PER0],
                      num_challenges=1, num_aux=NAUX)
    assert not ok, "a lied segment seed must be rejected by the composition half"


def t_wrong_periodic_rejected():
    ok, _ = RV.verify(_PUBLICS, TRANS, _BNDS, _BUNDLE, num_queries_outer=NQO,
                      periodic=[{"period": 4, "base": [3, 1, 4, 2]}], num_challenges=1, num_aux=NAUX)
    assert not ok, "a different public periodic must be rejected"


if __name__ == "__main__":
    check(f"two-phase ROW-mode K={K}→1 verifies from public parts", t_two_phase_row_k_to_1)
    check("wrong AIR rejected", t_wrong_air_rejected)
    check("tampered layer-0 seam rejected", t_tampered_seam_rejected)
    check("lied segment boundary rejected", t_lied_boundary_rejected)
    check("wrong public periodic rejected", t_wrong_periodic_rejected)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
