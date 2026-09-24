"""A shielded-contract deposit cannot commit a note worth more than it paid (review 2026-09-24, reproduced).

The deposit statement never pinned VIN (the input value): c_hold kept it constant and the range block kept it below 2^61,
but CONS = VIN - VOUT = -delta was the only tie to the public amount. A deposit of 1 could therefore commit a note worth
1 + X, and an honest spend of that note drained the contract's WHOLE bridge balance (reproduced against 1,000,000 units).
The boundary (0, VIN, 0) closes it; honest deposits are unchanged.

Run: python3 tests/test_appnote_deposit_vin.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-appnote-vin-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode import shielded_state as S
from execnode.stark import appnote_circuit as AC, field as F, stark, backend as BK

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

GAME = "d0be764f3da9c9cc6bb609280a887929"
CID = S.cid_element(GAME)
KIND = S.KIND_VALUE
OWNER, RHO = S.owner_of(0x5EC7E7), 777


def t_an_honest_deposit_still_verifies():
    proof, cm = AC.prove_deposit(CID, KIND, [5], OWNER, RHO, 5)
    ok, why = AC.verify_deposit(proof, CID, KIND, cm, 5)
    assert ok, why


def t_a_deposit_whose_input_value_is_not_zero_is_refused():
    DELTA, X = 1, 999_999
    v_out = DELTA + X
    arity = 1
    g = AC.deposit_geometry(arity); T = AC.deposit_trace_len(arity)
    tr, _T0, cm = AC.build_deposit_trace(CID, KIND, [v_out], OWNER, RHO)
    rfill = AC._range_fill(g["out_end"], (X, v_out))
    for r in range(T):
        tr[r][AC.VIN] = X
        tr[r][AC.CONS] = F.sub(X, v_out)
        acc, b0, b1, b2, b3 = rfill.get(r, (0, 0, 0, 0, 0))
        tr[r][AC.ACC], tr[r][AC.RB0], tr[r][AC.RB1], tr[r][AC.RB2], tr[r][AC.RB3] = acc, b0, b1, b2, b3
    proof = stark.prove(tr, AC.transitions(), AC._deposit_boundaries(g, cm, DELTA),
                        periodic=AC.deposit_periodic(T, arity, CID, KIND), max_degree=AC.MAX_DEGREE,
                        aux="", backend=BK.get(AC.BACKEND))
    proof["arity"], proof["deposit"] = arity, True
    ok, why = AC.verify_deposit(proof, CID, KIND, cm, DELTA)
    assert not ok, "THE FINDING: a 1-unit deposit committed a note worth 1,000,000"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("t_"):
            check(name[2:].replace("_", " "), fn)
    print("ALL PASS" if not fails else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
