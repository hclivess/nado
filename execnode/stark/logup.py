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
The prover-side builders here compute h, g, z with ONE batch inversion; the constraints themselves live in
each circuit (they are two lines each).
"""
from execnode.stark import field as F


def combine(vals, gamma):
    """Fold a tuple into one field element: Σ γ^k · v_k. Injective at a random γ (Schwartz–Zippel) — the
    standard way to look up multi-column rows through a single-value argument."""
    acc = 0
    g = 1
    for v in vals:
        acc = F.add(acc, F.mul(g, v % F.P))
        g = F.mul(g, gamma)
    return acc


def helper_column(active, fvals, beta):
    """h_i = active_i / (β + f_i), the per-row lookup term with the division hoisted into a witness column
    (the constraint h·(β+f) = active is degree 2). Zero on inactive rows. One batch inversion for the column."""
    dens = [F.add(beta, f % F.P) for f in fvals]
    if any(d == 0 for d in dens):
        raise ZeroDivisionError("β collides with a lookup value (re-prove; probability ~T/p)")
    invs = F.batch_inverse(dens)
    return [F.mul(a % F.P, iv) if a else 0 for a, iv in zip(active, invs)]


def running_sum(*term_cols):
    """z_i = Σ_{j<i} (Σ_k terms_k[j]) — the accumulator column. z[0] = 0 and, when the grand total is zero
    and the last row's terms are zero, z[T-1] = 0: exactly the two public boundary pins."""
    T = len(term_cols[0])
    z = [0] * T
    for i in range(1, T):
        s = z[i - 1]
        for col in term_cols:
            s = F.add(s, col[i - 1])
        z[i] = s
    return z


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
