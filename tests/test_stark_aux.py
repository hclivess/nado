"""
Two-phase aux-column protocol + LogUp (execnode/stark/stark.py aux_spec, execnode/stark/logup.py): a valid
byte-table lookup verifies; a value outside the table, a tampered accumulator, a tampered multiplicity, and
mismatched aux geometry are all rejected; the one-phase path is untouched (legacy proof still verifies and
its proof dict has no aux columns).

Run: python3 tests/test_stark_aux.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, stark, logup

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


# --- the test AIR: "every active row's V is a byte" -------------------------------------------------
# Main columns V (values), M (table-side multiplicities). Aux columns H, G, Z (LogUp helpers + accumulator).
# Periodic: tbl = 0..255 then 0-padding, act = 1 on rows 0..T-2. Boundaries pin Z[0]=Z[T-1]=0 and M[T-1]=0.
V, M = 0, 1
H, G, Z = 2, 3, 4
T = 256

def _periodic():
    tbl = [i if i < 256 else 0 for i in range(T)]
    act = [1 if i < T - 1 else 0 for i in range(T)]
    return [tbl, act]

def _transitions():
    def c_h(cur, nxt, per, chal):
        """h·(β+V) = active — binds the helper to the committed value."""
        return F.sub(F.mul(cur[H], F.add(chal[0], cur[V])), per[1])
    def c_g(cur, nxt, per, chal):
        """g·(β+tbl) = m — binds the table helper to the public table + committed multiplicity."""
        return F.sub(F.mul(cur[G], F.add(chal[0], per[0])), cur[M])
    def c_z(cur, nxt, per, chal):
        """z' = z + h - g — the running log-derivative sum."""
        return F.sub(nxt[Z], F.add(cur[Z], F.sub(cur[H], cur[G])))
    return [c_h, c_g, c_z]

def _aux_spec(tamper=None):
    tbl, act = _periodic()
    def build(trace, chal):
        beta = chal[0]
        vals = [row[V] for row in trace]
        mult = [row[M] for row in trace]
        h = logup.helper_column(act, vals, beta)                # h = active/(β+V)
        g = logup.helper_column(mult, tbl, beta)                # g = m/(β+tbl)
        z = logup.running_sum(h, [F.neg(x) for x in g])
        if tamper:
            tamper(h, g, z)
        return [h, g, z]
    return {"num_challenges": 1, "num_aux": 3, "build": build}

def _trace(values):
    """Main trace from a list of T-1 active values (last row padding)."""
    assert len(values) == T - 1
    mult = logup.multiplicities(values, [i for i in range(256)]) + [0] * (T - 256)
    tr = [[values[i] if i < T - 1 else 0, mult[i]] for i in range(T)]
    return tr

BND = [(0, Z, 0), (T - 1, Z, 0), (T - 1, M, 0)]
VALUES = [(i * 37 + 11) % 254 + 1 for i in range(T - 1)]     # bytes in 1..254

def t1_valid_lookup():
    """A trace of genuine bytes proves and verifies through the two-phase protocol."""
    proof = stark.prove(_trace(VALUES), _transitions(), BND, periodic=_periodic(), max_degree=2,
                        aux_spec=_aux_spec())
    ok, why = stark.verify(proof, _transitions(), BND, periodic=_periodic(), max_degree=2,
                           aux_spec=_aux_spec())
    assert ok, f"valid lookup must verify: {why}"

def t2_value_outside_table_rejected():
    """A single non-byte value makes the sums unbalanceable — no multiplicity assignment can save it."""
    bad = list(VALUES); bad[7] = 300
    tr = _trace(VALUES)
    tr[7][V] = 300                                            # value not in the table; m stays a best effort
    proof = stark.prove(tr, _transitions(), BND, periodic=_periodic(), max_degree=2, aux_spec=_aux_spec())
    ok, why = stark.verify(proof, _transitions(), BND, periodic=_periodic(), max_degree=2,
                           aux_spec=_aux_spec())
    assert not ok, "value outside the table must be rejected"

def t3_tampered_multiplicity_rejected():
    """Inflating a multiplicity unbalances the sum → Z[T-1] boundary fails."""
    tr = _trace(VALUES)
    tr[5][M] += 1
    proof = stark.prove(tr, _transitions(), BND, periodic=_periodic(), max_degree=2, aux_spec=_aux_spec())
    ok, why = stark.verify(proof, _transitions(), BND, periodic=_periodic(), max_degree=2,
                           aux_spec=_aux_spec())
    assert not ok, "tampered multiplicity must be rejected"

def t4_tampered_accumulator_rejected():
    """A shifted Z column violates either the z-transition or its boundary pins."""
    def tamper(h, g, z):
        z[10] = F.add(z[10], 1)
    proof = stark.prove(_trace(VALUES), _transitions(), BND, periodic=_periodic(), max_degree=2,
                        aux_spec=_aux_spec(tamper))
    ok, why = stark.verify(proof, _transitions(), BND, periodic=_periodic(), max_degree=2,
                           aux_spec=_aux_spec())
    assert not ok, "tampered accumulator must be rejected"

def t5_aux_geometry_pinned():
    """A proof made with the aux protocol must not verify with a different declared aux geometry."""
    proof = stark.prove(_trace(VALUES), _transitions(), BND, periodic=_periodic(), max_degree=2,
                        aux_spec=_aux_spec())
    spec = _aux_spec(); spec["num_aux"] = 2
    ok, why = stark.verify(proof, _transitions(), BND, periodic=_periodic(), max_degree=2, aux_spec=spec)
    assert not ok, "wrong aux geometry must be rejected"

def t6_one_phase_untouched():
    """The plain protocol still round-trips and its proof has exactly the main columns (no aux leak)."""
    tr = [[3]]
    for _ in range(7):
        tr.append([F.mul(tr[-1][0], tr[-1][0])])
    trans = [lambda cur, nxt, per: F.sub(nxt[0], F.mul(cur[0], cur[0]))]
    bnd = [(0, 0, 3), (7, 0, tr[-1][0])]
    proof = stark.prove(tr, trans, bnd, max_degree=2)
    assert proof["W"] == 1 and len(proof["col_roots"]) == 1
    ok, why = stark.verify(proof, trans, bnd, max_degree=2)
    assert ok, f"legacy path must verify: {why}"


if __name__ == "__main__":
    check("valid byte lookup verifies (two-phase)", t1_valid_lookup)
    check("value outside table rejected", t2_value_outside_table_rejected)
    check("tampered multiplicity rejected", t3_tampered_multiplicity_rejected)
    check("tampered accumulator rejected", t4_tampered_accumulator_rejected)
    check("aux geometry pinned", t5_aux_geometry_pinned)
    check("one-phase path untouched", t6_one_phase_untouched)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
