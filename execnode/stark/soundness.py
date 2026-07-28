"""
Soundness calculator for NADO's FRI/STARK — what the parameters in fri.py ACTUALLY buy.

Run it:   python3 -m execnode.stark.soundness

WHY THIS FILE EXISTS
--------------------
The sizing comment in fri.py reads:

    320 queries · 0.4  +  18 grind  ≈  146 bits PROVABLE (Johnson)
    320 queries · 1.0  +  18 grind  ≈  338 bits CONJECTURED (list-decoding)

The query-phase arithmetic there is correct. But FRI soundness is a MINIMUM over
the query phase and the COMMIT phase, and that calculation has no commit-phase
term. The commit-phase error is ~n/|F| where |F| is the space the FOLDING
CHALLENGE is drawn from. fri.py originally folded with `alpha = t.challenge()`,
a BASE-field element, so |F| = 2^64 and the ceiling was

    64 - log2(n) = 64 - 18 = ~46-48 bits

irrespective of NUM_QUERIES and GRIND_BITS. Neither buys commit-phase bits:
grinding is a query-phase proof-of-work, and queries are what the commit phase
is independent of. The conjectured branch was capped by the same term, so 338
was equally unreachable.

THAT IS FIXED. fri.py now draws the folding challenge and the DEEP point from
GF(p^2) (EXT_CHALLENGES), and stark.py draws the constraint alphas from it too
(EXT_ALPHAS) — the alphas being the term that actually bound once FRI was lifted,
at log2(q) - log2(nc). The commit phase now binds at ~112, which is what Plonky2
and Miden get over this same base field. This file READS both flags rather than
assuming them (see _ext_alphas), so it reports what the code does, not what the
code was supposed to do.

STILL OPEN — the aux (LogUp) challenges. stark.py draws them with t.challenge(),
base field, for both prover and verifier. A LogUp argument's error is
(lookups + rows)/|challenge field|, so at 2^17 rows that term sits near 44 bits:
BELOW everything above, i.e. it is now the binding term for any circuit using
aux_spec (vm_circuit, logup_bind, and the settlement path). Lifting it is not a
one-line change — see alphas_bits/aux notes: the challenge can only be an
extension element if the aux COLUMNS and their transition constraints are
extension-valued too, which means representing each aux column as a pair of base
columns and mirroring the change in stark_native.py.

MODEL PROVENANCE
----------------
The regime formulas below are transcribed from Ethereum's `soundcalc`
(github.com/ethereum/soundcalc), the reference cross-zkVM calculator, and agree
with Plonky3's `p3-security` crate:

  UDR  proximity (1-rho)/2, list size 1, commit error (gamma*n + 1)/|F|
       -- soundcalc/proxgaps/unique_decoding.py, "Corollary 1.4 ... from BCHKS25"
  JBR  alpha = (1 + 1/(2m))*sqrt(rho), eta = sqrt(rho)/(2m),
       commit error ((2m'^5 + 3m'*gamma*rho)n/(3rho^{3/2}) + m'/sqrt(rho))/|F|
       -- soundcalc/proxgaps/johnson_bound.py, BCHKS25 Thm 1.5 Eq (1)

NOTE ON THE CONJECTURED BRANCH: the up-to-capacity conjectures (correlated
agreement, mutual correlated agreement, list-decodability) were DISPROVED in
late 2025 -- Crites-Stewart eprint 2025/2046, Diamond-Gruen eprint 2025/2010.
`s*log2(1/rho) + g` is therefore no longer a supported bound. The replacement
used here charges -log2(rho + eta) per query, per Plonky3's post-disproof
`conjectured_error` citing 2025/2010 section 1.5.
"""

import math

# ------------------------------------------------------ NADO's actual parameters

E_BASE = 64                 # log2 |Goldilocks|; the field alpha is drawn from today
E_EXT2 = 128                # log2 |GF(p^2)|
E_EXT3 = 192                # log2 |GF(p^3)|, for reference


def _params():
    """Read the live constants so this file cannot drift from fri.py/stark.py."""
    from execnode.stark import fri, stark
    R = int(math.log2(fri.FRI_BLOWUP))
    log_trace = int(math.log2(stark.MAX_TRACE_ROWS))
    ext = bool(getattr(fri, "EXT_CHALLENGES", False))
    return dict(R=R, s=fri.NUM_QUERIES, g=fri.GRIND_BITS,
                log_trace=log_trace, nu=log_trace + R,
                E=(E_EXT2 if ext else E_BASE), ext=ext)


# ---------------------------------------------------------------- regime terms

def yield_udr(R):
    """Bits per query in the unique-decoding regime: -log2((1+rho)/2)."""
    return -math.log2((1 + 2.0 ** -R) / 2)


def yield_jbr(R, m):
    """Bits per query in the Johnson regime: -log2(sqrt(rho)(1 + 1/2m))."""
    a = math.sqrt(2.0 ** -R) * (1 + 0.5 / m)
    return -math.log2(a) if a < 1 else float("-inf")


def commit_udr(R, nu, E):
    """soundcalc UDR: (gamma*n + 1)/|F| with gamma = (1-rho)/2. No (m+1/2) factor."""
    gamma = (1 - 2.0 ** -R) / 2
    return E - math.log2(gamma * 2.0 ** nu + 1)


def commit_jbr(R, nu, E, m, folding=2):
    """BCHKS25 Thm 1.5 Eq (1), as shipped in soundcalc and Plonky3."""
    rho = 2.0 ** -R
    sr = math.sqrt(rho)
    mm = m + 0.5
    gamma = 1 - sr * (1 + 0.5 / m)
    if gamma <= 0:
        return float("-inf")
    n = 2.0 ** nu
    eps = ((2 * mm ** 5 + 3 * mm * gamma * rho) * n / (3 * rho * sr)
           + mm / sr) * max(folding - 1, 1)
    lin = E - math.log2(max(eps, 1.0))
    noq = (E - math.log2(folding) - math.log2(n + 1)
           - math.log2(2 * m + 1) + 0.5 * math.log2(rho))
    return min(lin, noq)


def deep_bits(E, log_degree):
    """DEEP / Schwartz-Zippel at one point: degree/|F|.

    NOTE: stark.prove does NOT run a DEEP/out-of-domain step. deep_eval.py is a
    separate subsystem (io_bind, bound_epoch_o1, state_io_tie,
    settlement_aggregate). For the MAIN STARK the analogous algebraic term is
    the constraint-combination alphas -- see alphas_bits below."""
    return E - log_degree


def _ext_alphas():
    """Whether stark.py draws the constraint alphas from GF(p^2) — READ, never assumed."""
    try:
        from execnode.stark import stark as _st
        return bool(getattr(_st, "EXT_ALPHAS", False))
    except Exception:
        return False


def alphas_bits(num_constraints=1, list_size=1.0, ext=None):
    """Soundness of the constraint-combination step, stark.py:298 and :421.

        alphas = [t.challenge() for _ in range(len(transitions) + len(boundaries))]

    The naive Schwartz-Zippel reading is that a random linear combination over a
    field of size q kills a nonzero constraint vector with probability 1/q, i.e.
    log2(q) bits. That IGNORES the union bound over constraints that the standard
    ALI analysis applies. Ethereum's soundcalc (circuits/deep_ali.py, Theorem 8
    of eprint 2022/1216) uses

        e_ALI = L_plus * num_constraints / |F|

    so the term is log2(q) - log2(L_plus * num_constraints). With L_plus = 1
    (unique decoding) and nc constraints that is log2(q) - log2(nc):

        nc =    1 -> 64.0      nc =  100 -> 57.4
        nc =   10 -> 60.7      nc = 3412 -> 52.3

    An earlier version of this function returned log2(q) flat, i.e. assumed
    nc = 1, and therefore OVERSTATED by log2(nc).

    The field these are drawn from is READ from stark.EXT_ALPHAS, never assumed:
    with base-field alphas this term caps the main STARK at ~63 bits however
    large the FRI challenge field becomes; with GF(p^2) alphas it lifts to ~127
    and the FRI commit term (112) binds instead."""
    from execnode.stark import field as F
    if ext is None:
        from execnode.stark import stark as _st
        ext = bool(getattr(_st, "EXT_ALPHAS", False))
    base = float(2 * (F.P.bit_length() - 1) if ext else (F.P.bit_length() - 1))
    return base - math.log2(max(list_size * num_constraints, 1.0))


def conjectured_bits(R, s, g, E):
    """Post-disproof random-words bound: s*(-log2(rho + eta)) + g."""
    rho = 2.0 ** -R
    eta = ((math.log2(math.e) + R) * rho) / E
    eff = rho + eta
    return s * (-math.log2(eff)) + g if 0 < eff < 1 else float(g)


def best_jbr(R, nu, E, s, g, m_lo=1.0, m_hi=1000.0, steps=3000):
    """Optimise the Johnson parameter m. commit falls / query rises in m, so the
    min is quasiconcave with a unique optimum."""
    best = (float("-inf"), None)
    ratio = (m_hi / m_lo) ** (1.0 / steps)
    m = m_lo
    for _ in range(steps + 1):
        y = yield_jbr(R, m)
        if y > 0:
            v = min(s * y + g, commit_jbr(R, nu, E, m))
            if v > best[0]:
                best = (v, m)
        m *= ratio
    return best


def achieved(R, nu, E, s, g, log_degree, num_constraints=1):
    """Provable soundness = min over binding terms, best regime."""
    u = min(s * yield_udr(R) + g, commit_udr(R, nu, E))
    j, m = best_jbr(R, nu, E, s, g)
    d = deep_bits(E, log_degree)
    a = alphas_bits(num_constraints)
    # `d` is REPORTED but must not BIND. deep_bits' own docstring says stark.prove runs no DEEP /
    # out-of-domain step — deep_eval.py is a separate subsystem (io_bind, bound_epoch_o1, state_io_tie,
    # settlement_aggregate) — and for the main STARK the analogous algebraic term is the constraint alphas,
    # which are accounted separately in `a`. Including it in the minimum meant the headline PROVABLE figure
    # was set by a term the file explicitly documents as inapplicable: it evaluated to 111.0 against a real
    # commit-phase bound of 112.0, so the report understated the main path by a bit and pointed at the wrong
    # term while doing it. Kept in the returned dict so the number stays visible for the paths that DO run a
    # DEEP step; simply no longer folded into the bound for the one that does not.
    total = min(max(u, j), a)
    return dict(udr=u, jbr=j, m=m, deep=d, alphas=a, total=total,
                regime="UDR" if u >= j else "JBR")


def saturation_queries(R, nu, E, g):
    """Query count past which no further security is bought."""
    ceil_ = max(commit_udr(R, nu, E), best_jbr(R, nu, E, 10 ** 6, g)[0])
    y = yield_udr(R)
    return max(0, math.ceil((ceil_ - g) / y))


# ---------------------------------------------------------------------- report

def report():
    p = _params()
    R, s, g, nu, E = p["R"], p["s"], p["g"], p["nu"], p["E"]
    print("=" * 78)
    print("NADO FRI SOUNDNESS")
    print("=" * 78)
    print(f"  blowup 2^{R}   queries {s}   grind {g}   trace 2^{p['log_trace']}"
          f"   FRI domain 2^{nu}")
    print(f"  challenge field: {'GF(p^2)' if p['ext'] else 'BASE Goldilocks'}"
          f"  ->  E = {E} bits")

    a = achieved(R, nu, E, s, g, p["log_trace"])
    print(f"\n  {'term':<26} {'bits':>9}")
    print("  " + "-" * 36)
    print(f"  {'query phase (UDR)':<26} {s * yield_udr(R) + g:>9.1f}")
    print(f"  {'commit phase (UDR)':<26} {commit_udr(R, nu, E):>9.1f}")
    print(f"  {'best Johnson (m=%.0f)' % a['m']:<26} {a['jbr']:>9.1f}")
    print(f"  {'DEEP / Schwartz-Zippel':<26} {a['deep']:>9.1f}   (not on the main path)")
    print(f"  {('constraint alphas (GF(p^2))' if _ext_alphas() else 'constraint alphas (BASE fld)'):<26} {a['alphas']:>9.1f}   <-- caps the main STARK")
    print(f"      (that is nc = 1; the term is log2(q) - log2(nc), so a circuit")
    print(f"       with 100 constraints sits at {alphas_bits(100):.1f} and one with")
    print(f"       3412 at {alphas_bits(3412):.1f}. Pass num_constraints to achieved().)")
    print("  " + "-" * 36)
    print(f"  {'PROVABLE (best regime: %s)' % a['regime']:<26} {a['total']:>9.1f}")
    print(f"  {'conjectured (repriced)':<26} "
          f"{min(conjectured_bits(R, s, g, E), a['alphas'], commit_udr(R, nu, E)):>9.1f}")

    sat = saturation_queries(R, nu, E, g)
    print(f"\n  soundness saturates at ~{sat} queries; {max(0, s - sat)} of the "
          f"{s} configured\n  queries add proof size and no security.")

    if not p["ext"]:
        print("\n  " + "!" * 62)
        print("  The folding challenge is a BASE-field element, so the commit phase")
        print("  caps this at ~%.0f bits whatever NUM_QUERIES says. fri.py's comment"
              % a["total"])
        print("  claims 146 provable / 338 conjectured; neither is reachable.")
        print("  Fix: fold with Transcript.challenge_ext() (ext2.py). Projection:")
        for label, EE in (("GF(p^2)", E_EXT2), ("GF(p^3)", E_EXT3)):
            aa = achieved(R, nu, EE, s, g, p["log_trace"])
            print(f"      {label}: {aa['total']:>6.1f} bits provable")
        print("  " + "!" * 62)


if __name__ == "__main__":
    report()
