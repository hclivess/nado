"""THE ARENA MUST COMPUTE EXACTLY WHAT PYTHON COMPUTES, IN WHATEVER FIELD extf SAYS.

The native prover is not an optimisation that may round differently — a proof is a transcript-driven
object, so any arithmetic difference anywhere in the native path changes the proof and the two halves of
the system stop agreeing. The failure mode is not a crash: a degree-mismatched or nonresidue-mismatched
arena composes a perfectly well-formed polynomial over the WRONG field, and the only symptom is
"trace/composition mismatch" at verification with nothing pointing at the field.

So this asserts IDENTITY, not equivalence, at three levels:
  1. sp_fold_ext vs fri._fold_ext, limb for limb
  2. a whole proof through the arena vs the same proof through pure Python, serialised and compared
  3. that the arena-produced proof actually verifies

It is degree-agnostic on purpose: it reads extf.DEGREE and exercises whatever field is live, so it keeps
working across the next migration instead of pinning the one this was written for.
"""
import sys, random
import os as _os
sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from execnode.stark import stark_native as sn, extf as E, fri, air_ir, field as F, stark

random.seed(20260729)
fails = []
def check(c, label):
    print(("PASS  " if c else "FAIL  ") + label)
    if not c: fails.append(label)

D = E.DEGREE
check(sn.ext_capable(), f"arena handshake at degree {D}")

# ---------------------------------------------------------------- 1. sp_fold_ext vs fri._fold_ext
M = 256
OFF = stark.OFF
vals = [tuple(random.randrange(F.P) for _ in range(D)) for _ in range(M)]
alpha = tuple(random.randrange(F.P) for _ in range(D))

dom = F.domain(M, OFF)
py = fri._fold_ext(vals, dom, alpha)

sn.reset(M, M, OFF)
ids = [sn.load_col([v[d] for v in vals]) for d in range(D)]
lo = sn.fold_ext(ids, OFF, alpha)
rust = [tuple(sn.read(lo + d, i) for d in range(D)) for i in range(M // 2)]
check(rust == py, f"sp_fold_ext is BIT-IDENTICAL to fri._fold_ext over {M} points at D={D}")
if rust != py:
    for i, (a, b) in enumerate(zip(rust, py)):
        if a != b:
            print(f"      first divergence at i={i}: rust={a} py={b}"); break
sn.free()

# ---------------------------------------------------------------- 2. compose: END-TO-END proof identity
# Stronger than comparing compose_ext to compose_python in isolation: prove the SAME statement twice, once
# through the arena and once through pure Python, and require the emitted proofs to be equal byte for byte.
# Everything is transcript-driven and deterministic, so any arithmetic difference anywhere in the native
# path — composition, LDE, Merkle, the challenge flattening — changes the proof.
import os, json
from execnode.stark import backend as BK

T, W = 64, 4
def c0(cur, nxt, per, chal):
    return F.sub(F.mul(cur[0], cur[1]), F.mul(nxt[0], per[0]))          # base-valued
def c1(cur, nxt, per, chal):
    return E.sub_f(E.mul_f(chal[0], cur[2]), E.mul_f(chal[0], nxt[2]))  # ext-valued -> D outputs
def c2(cur, nxt, per, chal):
    return F.sub(cur[3], nxt[3])                                        # base-valued
def c3(cur, nxt, per, chal):
    return E.mul_f(chal[0], F.sub(cur[3], nxt[3]))                       # ext-valued -> D outputs
cons = [c0, c1, c2, c3]

# a trace that SATISFIES them, so the proof is real and verify() is meaningful
tr = []
a, d = 3, 11
for i in range(T):
    tr.append([a, 1, 5, d])
    a = a                    # cur[0]*cur[1] = nxt[0]*per[0] with per=1, cur[1]=1 -> nxt[0]=cur[0]
per = [[1] * T]
trace = [[3, 1, 5, 11] for _ in range(T)]

NAUX = 1
def build_aux(tr_, chals):
    return [[0] * len(tr_) for _ in range(NAUX * D)]
aux_spec = {"num_challenges": 1, "num_aux": NAUX * D, "build": build_aux}

bnds = [(0, 3, 11), (T - 1, 3, 11)]

def run(native, bk, rc):
    env = dict(os.environ)
    if native:
        os.environ.pop("NADO_NO_HOLISTIC", None)
        os.environ["NADO_STRICT_NATIVE"] = "1"
    else:
        os.environ["NADO_NO_HOLISTIC"] = "1"
        os.environ.pop("NADO_STRICT_NATIVE", None)
    try:
        return stark.prove(trace, cons, bnds, periodic=per, max_degree=3, num_queries=12,
                           aux_spec=aux_spec, row_commit=rc, backend=bk)
    finally:
        os.environ.clear(); os.environ.update(env)

sr = lambda p: json.dumps(p, sort_keys=True, default=lambda o: list(o) if isinstance(o, tuple) else str(o))
for label, bk, rc in (("col-commit / DEFAULT", BK.DEFAULT, False),
                      ("row-commit / RECURSION", BK.RECURSION, True)):
    p_nat = run(True, bk, rc)
    p_py = run(False, bk, rc)
    check(sr(p_nat) == sr(p_py),
          f"{label}: arena proof is BIT-IDENTICAL to the pure-Python proof at D={D}")
    ok, why = stark.verify(p_nat, cons, bnds, periodic=per, max_degree=3, num_queries=12,
                           aux_spec=aux_spec, row_commit=rc, backend=bk)
    check(ok, f"{label}: the arena-produced GF(p^{D}) proof VERIFIES ({why})")

print()
if fails:
    print(f"{len(fails)} FAILED"); sys.exit(1)
print("ARENA IS BIT-IDENTICAL TO THE PYTHON REFERENCE AT D=%d" % D)
