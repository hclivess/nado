"""
LogUp — the log-derivative lookup/permutation argument, the memory-checking machinery the VM execution
circuit stands on (doc/zk-execution-proofs.md). Proves multiset statements about COMMITTED trace columns:

  "every active row's value f_i appears in the table t"  ⟺  Σ_i active_i/(β + f_i) = Σ_j m_j/(β + t_j)

for SOME multiplicity column m — the two rational sums agree at a random β (drawn AFTER the trace is
committed, via the two-phase aux protocol in stark.prove) iff the multisets match, by unique factorization
of the denominators. With m fixed to 1 per public-log row it degenerates to exact multiset EQUALITY — the
form the VM's public I/O bus uses. Tuples (pc, opcode, args…) are first combined into one field element with
powers of a second challenge γ.

In-circuit shape (all divisions removed):
  helper columns   h·(β + f) = active      g·(β + t) = m          (degree 2)
  running sum      z' = z + h - g                                  (degree 1)
  boundaries       z[0] = 0,  z[T-1] = 0,  last row inactive on both sides (pinned by the circuit)
Each circuit builds its own h, g, z columns (one batch inversion) and carries the constraints (two lines each);
this module holds the shared pieces: tuple combination and the table-side multiplicities.
"""
from execnode.stark import field as F, extf as ext2


def combine(vals, gamma):
    """Fold a tuple into one field element: Σ γ^k · v_k. Injective at a random γ (Schwartz–Zippel) — the
    standard way to look up multi-column rows through a single-value argument.

    γ may be a BASE element or a GF(p^2) pair, and the result follows it. The values folded are always base
    (they are trace/periodic cells), so the extension path is scalar_mul — ext·base — and never a full ext
    multiply per term; only the γ power itself is squared up in the extension. Drawing γ from GF(p^2) is what
    takes the argument's Schwartz-Zippel error from ~2^-44 at 2^17 rows to the ~112-bit range everything else
    in the proof already sits at (see execnode/stark/soundness.py)."""
    if isinstance(gamma, tuple):
        # *_f forms: expressed through field.* so air_ir can trace a constraint that calls combine() with an
        # extension gamma into its SSA program. The raw ext2.mul computes with % directly and raises on a
        # symbolic cell — which is exactly where every base-field consumer of the exec AIR's IR broke.
        acc = ext2.ZERO
        g = ext2.ONE
        for v in vals:
            acc = ext2.add_f(acc, ext2.scalar_mul_f(g, v % F.P))
            g = ext2.mul_f(g, gamma)
        return acc
    acc = 0
    g = 1
    for v in vals:
        acc = F.add(acc, F.mul(g, v % F.P))
        g = F.mul(g, gamma)
    return acc


def multiplicities(values, table):
    """m_j for the table side: how many active lookups target table[j]. Duplicate table entries get all
    mass on their FIRST occurrence (any split verifies equally)."""
    first = {}
    for j, t in enumerate(table):
        first.setdefault(t % F.P, j)
    m = [0] * len(table)
    for v in values:
        j = first.get(v % F.P)
        if j is None:
            raise ValueError(f"lookup value {v} not in table")
        m[j] += 1
    return m
