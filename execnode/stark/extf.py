"""
Extension field GF(p^DEGREE) over Goldilocks, p = 2^64 - 2^32 + 1.

WHY THIS EXISTS
---------------
FRI soundness is a MINIMUM over the query phase and the commit phase.
`fri.NUM_QUERIES` buys query-phase bits. NOTHING buys commit-phase bits except a
bigger field — not queries, not grinding. Every algebraic term in the system
(the FRI folding challenge, the DEEP point, the constraint alphas, the LogUp
bus challenges) is bounded by the space its challenge is drawn from.

WHY IT IS DEGREE-PARAMETERISED, NOT ext2 + ext3
-----------------------------------------------
This file replaces ext2.py, which hardcoded degree 2 in 24 places — the
constants, every destructuring `a, b = v`, the mul/inv formulas, is_base. The
migration to GF(p^3) turned up 118 such assumptions across 16 files, and the
lesson of this codebase is unambiguous: a duplicated field assumption drifts.
Five copies of "the recursion backend is base-field" let a prover choose its own
security level; the same rule expressed twice (alphas flattened to limbs, the
challenges beside them not) produced the same bug in two different files days
apart. So the degree lives in ONE constant and every operation is written for
arbitrary D.

The cost is that mul is a generic O(D^2) convolution rather than a hand-expanded
karatsuba, and inv is extended-Euclid rather than a closed form. At D = 3 that is
a handful of multiplies on a path that runs once per challenge, not per row; the
per-row hot paths are add and scalar_mul, which are linear in D either way.

REPRESENTATION
--------------
GF(p^D) = F_p[X] / (X^D - NONRESIDUE), with NONRESIDUE chosen so the polynomial
is irreducible (verified at import). An element is a D-tuple (a0, ..., a_{D-1})
meaning a0 + a1*X + ... . Base elements embed as (a, 0, ..., 0). Every function
accepts a tuple OR a bare int (treated as base) and always returns a D-tuple.

DEGREE 2 vs 3: X^2 - 7 is what Plonky2 uses over this base field (~112-bit
ceiling). X^3 - 3 gives ~176 and, more importantly for NADO, moves the binding
term OFF the LogUp bus: at 2^17 rows the aux term is E - log2(buses*rows), so
degree 2 binds the whole system at 109 bits and DECAYS one bit per trace
doubling, while degree 3 puts it at 173 and hands the bound to the query phase
(150.8), which does not move with trace size until ~2^39 rows.
"""

from execnode.stark import field as F

P = F.P

# ---- THE ONE PLACE THE DEGREE IS WRITTEN -------------------------------------------------------
DEGREE = 3
NONRESIDUE = 3          # X^3 - 3 is irreducible over F_p (verified below)

ZERO = tuple([0] * DEGREE)
ONE = tuple([1] + [0] * (DEGREE - 1))
X = tuple([0, 1] + [0] * (DEGREE - 2))


def _check_irreducible():
    """X^D - NONRESIDUE is irreducible over F_p iff NONRESIDUE is not a d-th power for any prime d | D
    (Serret's criterion for binomials, plus D | p-1 for the clean case). For D prime this reduces to
    "NONRESIDUE is not a D-th residue", i.e. NONRESIDUE^((p-1)/D) != 1.

    Checked at import rather than asserted in a comment: a reducible modulus does not fail loudly, it
    silently makes the ring have zero divisors, and then inv() returns garbage for exactly the elements an
    attacker would search for."""
    if (P - 1) % DEGREE != 0:
        return True                       # D does not divide p-1: the residue test does not apply
    return F.pw(NONRESIDUE % P, (P - 1) // DEGREE) != 1


if not _check_irreducible():
    raise ValueError(f"X^{DEGREE} - {NONRESIDUE} is REDUCIBLE over F_p — the extension would have zero "
                     f"divisors and inv() would silently return wrong results")


def lift(v):
    """Accept an int (base element) or a tuple of any length <= DEGREE; always return a normalised D-tuple.

    THE NORMALISATION FUNNEL — everything else goes through it. It accepts a SHORT tuple so a value written
    against an older degree is widened rather than silently mis-read; it rejects a LONG one, because that
    means the caller believes in a bigger field than this module implements and the extra limbs would be
    dropped without trace."""
    # A LIST IS A TUPLE THAT HAS BEEN THROUGH JSON. Proofs are transmitted as JSON, and json.loads turns
    # every tuple into a list, so an extension element arrives here as [a, b] rather than (a, b). This
    # tested `type(v) is tuple` — strictly — and a round-tripped element therefore fell through to the
    # base-field branch, where `v % P` on a list raises. Since this is the normalisation funnel, that one
    # strict check broke every ext-field path in the verifier for any proof that had crossed the wire.
    # Observed live 2026-08-04 on the first settle proof ever to reach verification:
    #     composition is not low-degree: TypeError: unsupported operand type(s) for %: 'list' and 'int'
    #     [extf.py:86 in lift: return tuple([v % P] + [0] * (DEGREE - 1))]
    # Accepting both leaves the tuple path byte-identical, so nothing that worked before changes.
    if isinstance(v, (tuple, list)):
        if len(v) > DEGREE:
            raise ValueError(f"element has {len(v)} limbs but the field is degree {DEGREE}")
        return tuple(v[i] % P if i < len(v) else 0 for i in range(DEGREE))
    return tuple([v % P] + [0] * (DEGREE - 1))


def is_base(v):
    """True iff the element lies in the base field — i.e. EVERY non-constant limb is zero. Testing only one
    limb (which the degree-2 version could get away with) reports (a, 0, c) as base and loses c."""
    return all(limb == 0 for limb in lift(v)[1:])


def to_base(v):
    """The base-field value, or None if the element is genuinely extension-valued."""
    e = lift(v)
    return e[0] if is_base(e) else None


def add(u, v):
    a, b = lift(u), lift(v)
    return tuple((a[i] + b[i]) % P for i in range(DEGREE))


def sub(u, v):
    a, b = lift(u), lift(v)
    return tuple((a[i] - b[i]) % P for i in range(DEGREE))


def neg(u):
    a = lift(u)
    return tuple((-a[i]) % P for i in range(DEGREE))


def mul(u, v):
    """Polynomial product reduced mod X^D - NONRESIDUE.

    Terms of degree >= D wrap with a NONRESIDUE factor: X^(D+k) = NONRESIDUE * X^k. Written as a generic
    convolution so the degree is data, not code."""
    a, b = lift(u), lift(v)
    acc = [0] * (2 * DEGREE - 1)
    for i in range(DEGREE):
        ai = a[i]
        if ai:
            for j in range(DEGREE):
                acc[i + j] = (acc[i + j] + ai * b[j]) % P
    out = list(acc[:DEGREE])
    for k in range(DEGREE, 2 * DEGREE - 1):
        if acc[k]:
            out[k - DEGREE] = (out[k - DEGREE] + NONRESIDUE * acc[k]) % P
    return tuple(out)


def scalar_mul(u, s):
    """Extension element times a BASE scalar — one multiply per limb, no cross terms. This is the per-row
    hot path (every constraint value scaled by invZ, every fold scaled by 1/2x), so it stays linear in D."""
    a = lift(u)
    s %= P
    return tuple((a[i] * s) % P for i in range(DEGREE))


def square(u):
    return mul(u, u)


def inv(u):
    """Multiplicative inverse.

    FAST PATH FOR D = 3, generic extended Euclid otherwise. The generic path is still the definition and
    still runs for any other degree; the cubic closed form is checked against it at import (see
    _check_inv_agreement), so "a wrong closed form returns a plausible non-inverse" cannot happen silently —
    which is the exact objection this docstring used to raise against having one at all.

    WHY IT EARNED THE EXCEPTION. vm_circuit's LogUp aux build calls this 20-40 times PER ROW (one per bus
    denominator: gio, ha, ga, every byte pair, every 7-bit pair, GB, GS). At 2^17 rows that is millions of
    inversions on the settlement proving path, and extended Euclid does several base-field inversions plus
    Python list surgery for each one. This is where GF(p^3) proving time actually goes."""
    a = lift(u)
    if all(x == 0 for x in a):
        raise ZeroDivisionError("inverse of zero in GF(p^%d)" % DEGREE)
    if DEGREE == 3:
        return _inv3(a)
    return _inv_euclid(a)


def _inv3(a):
    """Closed-form inverse in GF(p^3) = F_p[X]/(X^3 - N), by cofactors of the norm.

    With a = a0 + a1*X + a2*X^2 and X^3 = N:
        t0 = a0^2 - N*a1*a2      t1 = N*a2^2 - a0*a1      t2 = a1^2 - a0*a2
        d  = a0*t0 + N*(a2*t1 + a1*t2)      (= the norm, an element of F_p)
        a^-1 = (t0 + t1*X + t2*X^2) / d
    Nine base multiplies and ONE base inversion, against extended Euclid's several inversions and list
    rebuilds per call."""
    a0, a1, a2 = a
    n = NONRESIDUE
    t0 = (a0 * a0 - n * a1 * a2) % P
    t1 = (n * a2 * a2 - a0 * a1) % P
    t2 = (a1 * a1 - a0 * a2) % P
    d = (a0 * t0 + n * (a2 * t1 + a1 * t2)) % P
    if d == 0:                       # only possible if a == 0, which the caller already excluded
        raise ZeroDivisionError("norm is zero in GF(p^3) — element not invertible")
    di = F.inv(d)
    return ((t0 * di) % P, (t1 * di) % P, (t2 * di) % P)


def _inv_euclid(a):
    """Multiplicative inverse via the extended Euclidean algorithm on F_p[X], against the modulus X^D - N.
    Generic in D — the definition every fast path is checked against."""
    # r0 = modulus X^D - N, r1 = a ; track only the cofactor of a
    r0 = [(-NONRESIDUE) % P] + [0] * (DEGREE - 1) + [1]
    r1 = list(a)
    t0, t1 = [0], [1]

    def _deg(p_):
        d = len(p_) - 1
        while d > 0 and p_[d] == 0:
            d -= 1
        return d

    def _sub_scaled(p_, q_, c, shift):
        out = list(p_) + [0] * max(0, len(q_) + shift - len(p_))
        for i, qi in enumerate(q_):
            if qi:
                out[i + shift] = (out[i + shift] - c * qi) % P
        return out

    while True:
        d1 = _deg(r1)
        if d1 == 0:
            break
        d0 = _deg(r0)
        if d0 < d1:
            r0, r1 = r1, r0
            t0, t1 = t1, t0
            continue
        c = r0[d0] * F.inv(r1[d1]) % P
        r0 = _sub_scaled(r0, r1, c, d0 - d1)
        t0 = _sub_scaled(t0, t1, c, d0 - d1)
        if _deg(r0) >= d0 and r0[d0] != 0:      # defensive: degree must strictly drop
            raise ArithmeticError("extended Euclid failed to reduce — reducible modulus?")
    c = F.inv(r1[0])
    res = [(x * c) % P for x in t1] + [0] * DEGREE
    return tuple(res[:DEGREE])


def _check_inv_agreement():
    """The cubic fast path must agree with extended Euclid, and both must actually invert.

    Checked AT IMPORT on fixed vectors, because a wrong closed form is the quiet kind of wrong: it returns a
    well-formed field element that simply is not the inverse, every proof built on it is internally
    consistent, and the failure shows up as an unverifiable proof with nothing pointing at the field. The
    generic path is the definition; this pins the optimisation to it."""
    if DEGREE != 3:
        return
    for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (2, 3, 5), (P - 1, 7, 11),
              (123456789, 987654321, 555555555), (0, 0, NONRESIDUE), (NONRESIDUE, 0, 0)):
        fast, ref = _inv3(lift(v)), _inv_euclid(lift(v))
        if fast != ref:
            raise ValueError(f"GF(p^3) closed-form inverse disagrees with extended Euclid on {v}: "
                             f"{fast} != {ref}")
        if mul(v, fast) != ONE:
            raise ValueError(f"GF(p^3) inverse of {v} does not multiply to one")


_check_inv_agreement()


def div(u, v):
    return mul(u, inv(v))


def pw(u, e):
    """Square-and-multiply exponentiation."""
    if e < 0:
        return pw(inv(u), -e)
    r, b = ONE, lift(u)
    while e:
        if e & 1:
            r = mul(r, b)
        b = mul(b, b)
        e >>= 1
    return r


def eq(a, b):
    return lift(a) == lift(b)


def poly_eval(coeffs, z):
    """Horner evaluation of a polynomial with BASE or extension coefficients at an extension point."""
    acc = ZERO
    for c in reversed(coeffs):
        acc = add(mul(acc, z), c)
    return acc


# ---- TRACEABLE forms, for use inside AIR CONSTRAINTS ------------------------------------------------
# The functions above compute with % directly, which is right for witness generation and wrong inside a
# constraint: air_ir traces an AIR by monkeypatching the `field` MODULE and evaluating the constraints on
# symbolic cells, so anything doing raw modular arithmetic sees a _Sym and raises. These forms express the
# SAME arithmetic through field.add/sub/mul, so a tracer follows them and the constraint lowers into the SSA
# program that rowcomp_verify's in-circuit composition check needs.
#
# They are also correct on plain ints (F.mul IS modular multiplication), so an AIR uses one implementation
# everywhere and there is no second copy to drift.

def _limbs(v):
    """Symbolic-safe widening: a bare value (int OR _Sym) becomes (v, 0, ..., 0); a tuple is padded. Never
    uses % on the value itself, since _Sym.__mod__ returns self but arithmetic on it would not."""
    if type(v) is tuple:
        if len(v) > DEGREE:
            raise ValueError(f"element has {len(v)} limbs but the field is degree {DEGREE}")
        return tuple(list(v) + [0] * (DEGREE - len(v)))
    return tuple([v] + [0] * (DEGREE - 1))


def add_f(u, v):
    a, b = _limbs(u), _limbs(v)
    return tuple(F.add(a[i], b[i]) for i in range(DEGREE))


def sub_f(u, v):
    a, b = _limbs(u), _limbs(v)
    return tuple(F.sub(a[i], b[i]) for i in range(DEGREE))


def mul_f(u, v):
    """Same convolution as mul, through field ops only."""
    a, b = _limbs(u), _limbs(v)
    acc = [0] * (2 * DEGREE - 1)
    for i in range(DEGREE):
        for j in range(DEGREE):
            acc[i + j] = F.add(acc[i + j], F.mul(a[i], b[j]))
    out = list(acc[:DEGREE])
    for k in range(DEGREE, 2 * DEGREE - 1):
        out[k - DEGREE] = F.add(out[k - DEGREE], F.mul(NONRESIDUE, acc[k]))
    return tuple(out)


def scalar_mul_f(u, s):
    a = _limbs(u)
    return tuple(F.mul(a[i], s) for i in range(DEGREE))


def canon(v):
    """Normalise a value that may be BASE or EXTENSION: an int stays an int (reduced), a tuple is lifted to
    D normalised limbs.

    This exists because `int(v) % P` is the natural thing to write and is WRONG the moment v can be an
    extension element — it raises on a tuple. That bug has now appeared five separate times in this
    migration (compose_ext's challenges, rowcomp_verify's periodic fill, and three fields of
    rowcomp_verify._point_public), always in code that was correct when the value was base-only. Use canon()
    wherever a value's field is not statically known."""
    return lift(v) if type(v) is tuple else v % P


def flatten(vals):
    """[e0, e1, ...] -> [e0_0, ..., e0_{D-1}, e1_0, ...] — the wire/transcript form."""
    out = []
    for v in vals:
        out.extend(lift(v))
    return out


def unflatten(xs):
    """Inverse of flatten."""
    if len(xs) % DEGREE:
        raise ValueError(f"limb count {len(xs)} is not a multiple of the degree {DEGREE}")
    return [tuple(xs[i:i + DEGREE]) for i in range(0, len(xs), DEGREE)]
