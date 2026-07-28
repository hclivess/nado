"""
Quadratic extension GF(p²) of the Goldilocks field, p = 2^64 - 2^32 + 1.

WHY THIS EXISTS
---------------
FRI soundness is a MINIMUM over two terms: the query phase and the commit phase.
`fri.NUM_QUERIES` buys query-phase bits. NOTHING buys commit-phase bits except a
bigger field — not queries, not grinding. The commit-phase error is ~ n/|F| where
|F| is the space the FOLDING CHALLENGE is drawn from, so folding with base-field
challenges caps PROVABLE soundness at

    64 - log2(n)  =  64 - 18  =  ~46-48 bits

no matter how large NUM_QUERIES or GRIND_BITS are. See soundness.py for the
computation against this repo's actual parameters.

Drawing the folding challenge from GF(p²) lifts that ceiling to ~112 bits. This
is what Plonky2 and Miden do over this same base field; Venus and ZisK use a
cubic extension for ~176.

REPRESENTATION
--------------
GF(p²) = F_p[X] / (X² - 7).  7 is a quadratic non-residue mod p (checked:
7^((p-1)/2) = p-1), so X² - 7 is irreducible. Same modulus Plonky2 uses for its
Goldilocks quadratic extension.

An element is a 2-tuple (a, b) meaning a + b·X. Base elements embed as (a, 0).
Every function accepts either a tuple or a bare int (treated as a base element)
and always returns a tuple.
"""

from execnode.stark import field as F

P = F.P
NONRESIDUE = 7          # X² - 7 is irreducible over F_p

ZERO = (0, 0)
ONE = (1, 0)
X = (0, 1)


def lift(v):
    """Accept an int (base element) or a tuple; always return a normalised tuple."""
    if type(v) is tuple:
        a, b = v
        return (a % P, b % P)
    return (v % P, 0)


def is_base(v):
    """True iff the element lies in the base field F_p."""
    return lift(v)[1] == 0


def to_base(v):
    """The base-field element, or None if v has a nonzero X component."""
    a, b = lift(v)
    return a if b == 0 else None


def add(u, v):
    (a, b), (c, d) = lift(u), lift(v)
    return ((a + c) % P, (b + d) % P)


def sub(u, v):
    (a, b), (c, d) = lift(u), lift(v)
    return ((a - c) % P, (b - d) % P)


def neg(u):
    a, b = lift(u)
    return ((-a) % P, (-b) % P)


def mul(u, v):
    """(a + bX)(c + dX) = (ac + 7bd) + (ad + bc)X, using X² = 7."""
    (a, b), (c, d) = lift(u), lift(v)
    return ((a * c + NONRESIDUE * b * d) % P, (a * d + b * c) % P)


def scalar_mul(u, s):
    """Multiply by a BASE-field scalar — two mults instead of four."""
    a, b = lift(u)
    s %= P
    return (a * s % P, b * s % P)


def square(u):
    a, b = lift(u)
    return ((a * a + NONRESIDUE * b * b) % P, (2 * a * b) % P)


def norm(u):
    """N(a + bX) = a² - 7b², an element of the BASE field. Zero iff u == 0."""
    a, b = lift(u)
    return (a * a - NONRESIDUE * b * b) % P


def conj(u):
    """The Frobenius conjugate a - bX (= u^p)."""
    a, b = lift(u)
    return (a % P, (-b) % P)


def inv(u):
    """u^-1 = conj(u)/N(u)."""
    n = norm(u)
    if n == 0:
        raise ZeroDivisionError("ext2: inverse of zero")
    ninv = F.inv(n)
    a, b = lift(u)
    return (a * ninv % P, (-b) * ninv % P)


def div(u, v):
    return mul(u, inv(v))


def pw(u, e):
    """Square-and-multiply by a (possibly negative) integer exponent."""
    if e < 0:
        return pw(inv(u), -e)
    r, base = ONE, lift(u)
    while e:
        if e & 1:
            r = mul(r, base)
        base = square(base)
        e >>= 1
    return r


def eq(u, v):
    return lift(u) == lift(v)


def poly_eval(coeffs, z):
    """Horner evaluation of a BASE-field coefficient list at an EXTENSION point.

    This is the shape the DEEP check needs: the polynomial stays over F_p, only
    the challenge point moves to GF(p²)."""
    acc = ZERO
    for c in reversed(coeffs):
        acc = add(mul(acc, z), lift(c))
    return acc


# ---------------------------------------------------------------- encoding

# ---- TRACEABLE forms, for use inside AIR CONSTRAINTS ------------------------------------------------
# The functions above do raw modular arithmetic on ints, which is right for witness generation and wrong
# inside a constraint: air_ir traces an AIR by monkeypatching the `field` MODULE and evaluating the
# constraints on symbolic cells, so anything that computes with `%` directly sees a _Sym and raises. These
# forms express the SAME arithmetic through field.add/sub/mul, so a tracer follows them and the constraint
# lowers into the SSA program that rowcomp_verify's in-circuit composition check needs.
#
# They are also correct on plain ints (F.mul IS modular multiplication), so an AIR can use them everywhere
# and stay traceable — there is no second implementation to keep in step.

def add_f(u, v):
    return F.add(u[0], v[0]), F.add(u[1], v[1])


def sub_f(u, v):
    return F.sub(u[0], v[0]), F.sub(u[1], v[1])


def mul_f(u, v):
    """(a0 + a1·X)(b0 + b1·X) mod (X² − NONRESIDUE), through field ops only."""
    a0, a1 = u
    b0, b1 = v
    lo = F.add(F.mul(a0, b0), F.mul(NONRESIDUE, F.mul(a1, b1)))
    hi = F.add(F.mul(a0, b1), F.mul(a1, b0))
    return lo, hi


def scalar_mul_f(u, s):
    """Extension element times a BASE scalar — one multiply per limb, no cross terms."""
    return F.mul(u[0], s), F.mul(u[1], s)


def flatten(vals):
    """[(a0,b0), (a1,b1), ...] -> [a0, b0, a1, b1, ...] for hashing/absorbing."""
    out = []
    for v in vals:
        a, b = lift(v)
        out.append(a)
        out.append(b)
    return out


def unflatten(xs):
    """Inverse of flatten."""
    return [(xs[i] % P, xs[i + 1] % P) for i in range(0, len(xs), 2)]
