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
# Main columns V (values), M (table-side multiplicities). LOGICAL aux columns H, G, Z (LogUp helpers +
# accumulator). Periodic: tbl = 0..255 then 0-padding, act = 1 on rows 0..T-2. Boundaries pin Z[0]=Z[T-1]=0
# and M[T-1]=0.
#
# EXTENSION LAYOUT (stark.ext_challenges_active is True on every backend since fri.EXT_CHALLENGES): the
# LogUp challenge β is a GF(p^DEGREE) element, so every aux column is extension-valued and occupies DEGREE
# contiguous base columns (limbs), constraints read/return DEGREE-tuples, and the Z boundaries pin every
# limb. This mirrors execnode/stark/vm_circuit (_aux_limbs / _algebra); the pre-2026-08 base-only builder
# here handed a tuple β to F.add and could never build a witness.
from execnode.stark import extf as E
D = E.DEGREE
V, M = 0, 1
W_MAIN = 2
H, G, Z = 2, 3, 4                  # logical aux indices
T = 256

def _limbs(idx):
    k = idx - W_MAIN
    return range(W_MAIN + D * k, W_MAIN + D * k + D)

def _rd(row, idx):
    return tuple(row[c] for c in _limbs(idx))

def _periodic():
    tbl = [i if i < 256 else 0 for i in range(T)]
    act = [1 if i < T - 1 else 0 for i in range(T)]
    return [tbl, act]

def _transitions():
    # *_f forms only: air_ir traces these constraints symbolically for the native composer
    def c_h(cur, nxt, per, chal):
        """h·(β+V) = active — binds the helper to the committed value."""
        return E.sub_f(E.mul_f(_rd(cur, H), E.add_f(chal[0], cur[V])), per[1])
    def c_g(cur, nxt, per, chal):
        """g·(β+tbl) = m — binds the table helper to the public table + committed multiplicity."""
        return E.sub_f(E.mul_f(_rd(cur, G), E.add_f(chal[0], per[0])), cur[M])
    def c_z(cur, nxt, per, chal):
        """z' = z + h - g — the running log-derivative sum."""
        return E.sub_f(_rd(nxt, Z), E.add_f(_rd(cur, Z), E.sub_f(_rd(cur, H), _rd(cur, G))))
    return [c_h, c_g, c_z]

def _aux_spec(tamper=None):
    tbl, act = _periodic()
    def build(trace, chal):
        beta = E.lift(chal[0])
        vals = [row[V] for row in trace]
        mult = [row[M] for row in trace]
        def helper(active, fvals):                                # a_i / (β + f_i), zero on inactive rows
            return [E.scalar_mul(E.inv(E.add(beta, E.lift(f))), a) if a else E.lift(0)
                    for a, f in zip(active, fvals)]
        h = helper(act, vals)                                     # h = active/(β+V)
        g = helper(mult, tbl)                                     # g = m/(β+tbl)
        z = [E.lift(0)] * T
        for i in range(1, T):
            z[i] = E.add(z[i - 1], E.sub(h[i - 1], g[i - 1]))
        if tamper:
            tamper(h, g, z)
        cols = []
        for logical in (h, g, z):                                 # each logical column -> D limb columns
            for i in range(D):
                cols.append([E.lift(v)[i] for v in logical])
        return cols
    return {"num_challenges": 1, "num_aux": 3 * D, "build": build}

def _trace(values):
    """Main trace from a list of T-1 active values (last row padding)."""
    assert len(values) == T - 1
    mult = logup.multiplicities(values, [i for i in range(256)]) + [0] * (T - 256)
    tr = [[values[i] if i < T - 1 else 0, mult[i]] for i in range(T)]
    return tr

BND = [(0, c, 0) for c in _limbs(Z)] + [(T - 1, c, 0) for c in _limbs(Z)] + [(T - 1, M, 0)]
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
        z[10] = E.add(z[10], E.lift(1))
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
