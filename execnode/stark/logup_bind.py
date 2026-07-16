"""
LogUp MULTISET-EQUALITY (in-circuit statement rebuild, doc/zk-recursion.md §5c(i)) — the binding primitive.

exec_state_bind binds the state transition to the epoch's writes NATIVELY (the verifier derives net-updates from
the io, O(#io)). To make that binding IN-CIRCUIT (so the verifier never processes the io — full O(1)), the
transition's updates and the exec proof's storage writes must be proven the SAME MULTISET inside a proof. This is
the standard LogUp argument: two lists of tuples are the same multiset iff Σ 1/(γ − rlc(A_i)) = Σ 1/(γ − rlc(B_j))
for a random γ, where rlc folds a tuple to one field element with a random β. Both challenges are drawn AFTER the
tuples are committed (the two-phase protocol), so a prover cannot rig them.

Self-contained + validated here; wiring it between the exec AIR (emit its storage writes on this bus) and the
transition AIR (emit its updates) — with the shared β/γ from folding both — is the succinctness integration.
"""
from execnode.stark import field as F, stark

# main columns: A tuple (3) | B tuple (3) ; aux (phase 2): inva, invb, accdiff
A0, A1, A2, B0, B1, B2, INVA, INVB, ACC = range(9)
W_MAIN = 6
NUM_AUX = 3
NUM_CHAL = 2                                    # ch[0]=β (rlc), ch[1]=γ (logup)


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


def _rlc3(x0, x1, x2, beta):
    return F.add(F.add(x0, F.mul(x1, beta)), F.mul(x2, F.mul(beta, beta)))


def _transitions():
    """(1) inv columns are the true inverses of (γ − rlc); (2) accdiff is the running prefix sum of (inva−invb),
    starting 0 and — with a guaranteed trailing dummy row — ending at the full multiset difference (pinned 0)."""
    def c_inva(c, n, p, ch):
        rlc = _rlc3(c[A0], c[A1], c[A2], ch[0])
        return F.sub(F.mul(c[INVA], F.sub(ch[1], rlc)), 1)
    def c_invb(c, n, p, ch):
        rlc = _rlc3(c[B0], c[B1], c[B2], ch[0])
        return F.sub(F.mul(c[INVB], F.sub(ch[1], rlc)), 1)
    def c_acc(c, n, p, ch):                      # accdiff[i+1] = accdiff[i] + (inva[i] − invb[i])
        return F.sub(F.sub(n[ACC], c[ACC]), F.sub(c[INVA], c[INVB]))
    return [c_inva, c_invb, c_acc]


def _build_aux(trace, chals):
    beta, gamma = chals[0], chals[1]
    inva, invb, acc = [], [], []
    running = 0
    for row in trace:
        acc.append(running)                      # EXCLUSIVE prefix sum (accdiff[0] = 0)
        ia = F.inv(F.sub(gamma, _rlc3(row[A0], row[A1], row[A2], beta)))
        ib = F.inv(F.sub(gamma, _rlc3(row[B0], row[B1], row[B2], beta)))
        inva.append(ia); invb.append(ib)
        running = F.add(running, F.sub(ia, ib))
    return [inva, invb, acc]


AUX_SPEC = {"num_challenges": NUM_CHAL, "num_aux": NUM_AUX, "build": _build_aux}
_DUMMY = (0, 0, 0)                                # padding tuple: identical on A and B ⇒ contributes 0 to accdiff


def _trace(A, B):
    if len(A) != len(B):
        raise ValueError("multiset-eq needs equal-length lists")
    n = len(A)
    T = _next_pow2(n + 1)                         # +1 guarantees a trailing dummy row (accdiff[T-1] = full diff)
    rows = []
    for i in range(T):
        a = A[i] if i < n else _DUMMY
        b = B[i] if i < n else _DUMMY
        rows.append([int(a[0]) % F.P, int(a[1]) % F.P, int(a[2]) % F.P,
                     int(b[0]) % F.P, int(b[1]) % F.P, int(b[2]) % F.P])
    return rows, T


def prove_multiset_eq(A, B, num_queries=stark.NUM_QUERIES, backend=None):
    """Prove multiset(A) == multiset(B), A/B lists of 3-field tuples. Two-phase LogUp; foldable under RECURSION.
    Returns the proof (proof['n'] = the common length, public)."""
    rows, T = _trace(A, B)
    bnd = [(0, ACC, 0), (T - 1, ACC, 0)]         # accdiff starts 0 and ends 0 ⇔ the multisets are equal
    proof = stark.prove(rows, _transitions(), bnd, max_degree=2, num_queries=num_queries, aux_spec=AUX_SPEC,
                        backend=backend)
    proof["n"] = len(A)
    return proof


def verify_multiset_eq(proof, expect_n=None, num_queries=stark.NUM_QUERIES, backend=None):
    """Verify a multiset-equality proof. `expect_n` (the verifier's expected common length) pins the geometry.
    Returns (ok, reason)."""
    try:
        n = proof.get("n")
        if not isinstance(n, int) or n < 0:
            return False, "bad length"
        if expect_n is not None and n != expect_n:
            return False, f"length {n} != expected {expect_n}"
        T = _next_pow2(n + 1)
        if proof.get("T") != T:
            return False, "bad trace geometry"
        bnd = [(0, ACC, 0), (T - 1, ACC, 0)]
        return stark.verify(proof, _transitions(), bnd, max_degree=2, num_queries=num_queries, aux_spec=AUX_SPEC,
                            backend=backend)
    except Exception as e:
        return False, f"malformed multiset-eq proof: {e}"
