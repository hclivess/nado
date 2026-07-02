"""
STARK over an AIR (execnode/stark/stark.py, doc/privacy.md): a valid execution trace verifies; a wrong
boundary, a tampered opening, or a trace that violates a transition constraint are all rejected.

Run: python3 tests/test_stark.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, stark

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


# --- AIR 1: squaring chain  a_{i+1} = a_i^2  (degree-2 transition) ---
def _sq_trace(seed, T):
    tr = [[seed]]
    for _ in range(T - 1):
        tr.append([F.mul(tr[-1][0], tr[-1][0])])
    return tr
SQ_TRANS = [lambda cur, nxt, per: F.sub(nxt[0], F.mul(cur[0], cur[0]))]

def t1_squaring_valid():
    T, seed = 8, 3
    tr = _sq_trace(seed, T)
    bnd = [(0, 0, seed), (T - 1, 0, tr[-1][0])]
    proof = stark.prove(tr, SQ_TRANS, bnd, max_degree=2)
    ok, why = stark.verify(proof, SQ_TRANS, bnd, max_degree=2)
    assert ok, f"valid squaring trace must verify: {why}"

def t2_wrong_boundary_rejected():
    T, seed = 8, 3
    tr = _sq_trace(seed, T)
    bnd = [(0, 0, seed), (T - 1, 0, tr[-1][0])]
    proof = stark.prove(tr, SQ_TRANS, bnd, max_degree=2)
    bad = [(0, 0, seed + 1), (T - 1, 0, tr[-1][0])]          # claim a different input
    ok, _ = stark.verify(proof, SQ_TRANS, bad, max_degree=2)
    assert not ok, "a boundary claim the trace doesn't meet must be rejected"

def t3_violating_trace_rejected():
    T, seed = 8, 3
    tr = _sq_trace(seed, T)
    tr[5][0] = F.add(tr[5][0], 1)                            # break the chain at row 5
    bnd = [(0, 0, seed), (T - 1, 0, tr[-1][0])]
    proof = stark.prove(tr, SQ_TRANS, bnd, max_degree=2)
    ok, why = stark.verify(proof, SQ_TRANS, bnd, max_degree=2)
    assert not ok, "a trace violating the transition must be rejected (composition not low-degree)"

def t4_tampered_opening_rejected():
    T, seed = 8, 3
    tr = _sq_trace(seed, T)
    bnd = [(0, 0, seed), (T - 1, 0, tr[-1][0])]
    proof = stark.prove(tr, SQ_TRANS, bnd, max_degree=2)
    proof["openings"][0]["cols"][0]["cur"] = F.add(proof["openings"][0]["cols"][0]["cur"], 1)
    ok, _ = stark.verify(proof, SQ_TRANS, bnd, max_degree=2)
    assert not ok, "a tampered trace opening must be rejected"


# --- AIR 2: Fibonacci  (col0=a_i, col1=a_{i+1}), two linear transition constraints ---
def _fib_trace(T):
    a, b = 1, 1
    tr = []
    for _ in range(T):
        tr.append([a, b]); a, b = b, F.add(a, b)
    return tr
FIB_TRANS = [lambda cur, nxt, per: F.sub(nxt[0], cur[1]),
             lambda cur, nxt, per: F.sub(nxt[1], F.add(cur[0], cur[1]))]

def t5_fibonacci_valid():
    T = 16
    tr = _fib_trace(T)
    bnd = [(0, 0, 1), (0, 1, 1)]
    proof = stark.prove(tr, FIB_TRANS, bnd, max_degree=1)
    ok, why = stark.verify(proof, FIB_TRANS, bnd, max_degree=1)
    assert ok, f"valid Fibonacci trace must verify: {why}"

def t6_fibonacci_wrong_seed_rejected():
    T = 16
    tr = _fib_trace(T)
    proof = stark.prove(tr, FIB_TRANS, [(0, 0, 1), (0, 1, 1)], max_degree=1)
    ok, _ = stark.verify(proof, FIB_TRANS, [(0, 0, 2), (0, 1, 1)], max_degree=1)
    assert not ok, "a wrong Fibonacci seed must be rejected"

for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
