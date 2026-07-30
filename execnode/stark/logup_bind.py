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
from execnode.stark import field as F, stark, extf as ext2

# main columns: A tuple (3) | B tuple (3) ; aux (phase 2): inva, invb, accdiff
#
# EXTENSION-VALUED AUX. β and γ are drawn from GF(p^2) (see stark.ext_challenges_active): a LogUp argument's
# soundness error is (lookups + rows)/|challenge field|, so base-field challenges capped this circuit at ~44
# bits — below FRI's 112 and the alphas' 126, i.e. it was the binding term for the whole system. Once the
# challenges are extension elements every value derived from them is too: 1/(γ − rlc) lives in GF(p^2), and
# so does the running sum. A column can only hold base elements, so each LOGICAL aux column is carried as a
# PAIR of base columns (c0, c1) meaning c0 + c1·X, and the constraints read the pair back as one ext value.
# Under the RECURSION backend the challenges stay base-field (the in-circuit verifier cannot do ext), and the
# original 3 scalar aux columns are used unchanged — both layouts are live, chosen by the backend.
A0, A1, A2, B0, B1, B2 = range(6)
W_MAIN = 6
NUM_CHAL = 2                                    # ch[0]=β (rlc), ch[1]=γ (logup)

# BASE layout (recursion backend): three scalar aux columns.
INVA, INVB, ACC = 6, 7, 8
NUM_AUX_BASE = 3
# EXT layout: the same three logical columns, each split into extf.DEGREE limbs. The limb ids are DERIVED,
# not written out — an explicit INVA0/INVA1/... block silently encodes the degree in its own length, which is
# how NUM_AUX_EXT and the constraint reads drifted apart when the degree moved.
_LOG_INVA, _LOG_INVB, _LOG_ACC = 0, 1, 2          # logical aux column indices


def _aux(k, i=0):
    """Column id of limb `i` of logical aux column `k` under the extension layout."""
    return W_MAIN + k * ext2.DEGREE + i


def _rd(row, k):
    """Read logical aux column `k` back as one extension element."""
    return tuple(row[_aux(k, i)] for i in range(ext2.DEGREE))


NUM_AUX_EXT = NUM_AUX_BASE * ext2.DEGREE


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


def _rlc3(x0, x1, x2, beta):
    """β-folded random linear combination of a 3-tuple. β is base OR ext; the tuple entries are always base
    trace cells, so the ext form is scalar_mul (ext·base), never a full ext multiply."""
    if isinstance(beta, tuple):
        # x0 is a BASE trace cell; add_f widens it to the full limb count itself, so writing the embedding
        # out as a literal tuple here would hardcode the degree in the one place it must not be.
        b2 = ext2.mul_f(beta, beta)
        return ext2.add_f(ext2.add_f(x0, ext2.scalar_mul_f(beta, x1)), ext2.scalar_mul_f(b2, x2))
    return F.add(F.add(x0, F.mul(x1, beta)), F.mul(x2, F.mul(beta, beta)))


def _transitions_base():
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


def _transitions_ext():
    """The same three statements over GF(p^2), reading each aux column back from its (lo, hi) limb pair.

    Degree is UNCHANGED at 2: an aux limb is one column, (γ − rlc) is degree 1 in the main columns, and their
    ext product is still a degree-2 form — so max_degree=2 and the blowup stay exactly as they were. Only the
    arithmetic widens, which is the whole point: the argument's error now scales with |GF(p^2)|."""
    # The *_f forms go through field.* so air_ir can TRACE these constraints into its SSA program (the raw
    # ext2.mul computes with % directly and raises on a symbolic cell). Same arithmetic either way.
    def c_inva(c, n, p, ch):
        rlc = _rlc3(c[A0], c[A1], c[A2], ch[0])
        return ext2.sub_f(ext2.mul_f(_rd(c, _LOG_INVA), ext2.sub_f(ch[1], rlc)), ext2.ONE)
    def c_invb(c, n, p, ch):
        rlc = _rlc3(c[B0], c[B1], c[B2], ch[0])
        return ext2.sub_f(ext2.mul_f(_rd(c, _LOG_INVB), ext2.sub_f(ch[1], rlc)), ext2.ONE)
    def c_acc(c, n, p, ch):
        d = ext2.sub_f(_rd(n, _LOG_ACC), _rd(c, _LOG_ACC))
        return ext2.sub_f(d, ext2.sub_f(_rd(c, _LOG_INVA), _rd(c, _LOG_INVB)))
    return [c_inva, c_invb, c_acc]


def _transitions(ext=False):
    return _transitions_ext() if ext else _transitions_base()


def _build_aux_base(trace, chals):
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


def _build_aux_ext(trace, chals):
    """Same computation in GF(p^2), emitted as limb pairs in the column order INVA0,INVA1,INVB0,INVB1,ACC0,ACC1.

    γ − rlc is invertible for all but a negligible fraction of γ (it vanishes only if γ happens to equal one of
    the ≤2T committed rlc values, and γ is drawn AFTER those are committed) — over GF(p^2) that probability is
    the ~112-bit term this migration buys. A hit would be an honest-prover liveness event, not a soundness one;
    ext2.inv raises rather than silently emitting a wrong column."""
    beta, gamma = chals[0], chals[1]
    D = ext2.DEGREE
    cols = [[] for _ in range(NUM_AUX_EXT)]      # limb-major: [INVA_0..D-1, INVB_0..D-1, ACC_0..D-1]
    running = ext2.ZERO
    for row in trace:
        for i in range(D):                                    # EXCLUSIVE prefix sum (accdiff[0] = 0)
            cols[_LOG_ACC * D + i].append(running[i])
        ia = ext2.inv(ext2.sub(gamma, _rlc3(row[A0], row[A1], row[A2], beta)))
        ib = ext2.inv(ext2.sub(gamma, _rlc3(row[B0], row[B1], row[B2], beta)))
        for i in range(D):
            cols[_LOG_INVA * D + i].append(ia[i])
            cols[_LOG_INVB * D + i].append(ib[i])
        running = ext2.add(running, ext2.sub(ia, ib))
    return cols


def _aux_spec(ext=False):
    return {"num_challenges": NUM_CHAL,
            "num_aux": NUM_AUX_EXT if ext else NUM_AUX_BASE,
            "build": _build_aux_ext if ext else _build_aux_base}


def _boundaries(T, ext=False):
    """accdiff starts 0 and ends 0 ⟺ the multisets are equal. Under ext that is a GF(p^2) zero, so BOTH limbs
    are pinned — dropping the hi limb would let a prover hide a non-zero difference in it."""
    if ext:
        # EVERY limb of the accumulator, at both ends. Pinning a subset lets a prover park an unbalanced bus
        # in the unpinned limbs and satisfy the boundary while the buses do not balance — the argument would
        # verify and prove nothing.
        return [(row, _aux(_LOG_ACC, i), 0) for row in (0, T - 1) for i in range(ext2.DEGREE)]
    return [(0, ACC, 0), (T - 1, ACC, 0)]
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
    # The layout follows the CHALLENGE FIELD, so prover and verifier must ask the same question of the same
    # backend — stark.ext_challenges_active is the one definition of that (see its docstring).
    _ext = stark.ext_challenges_active(backend)
    proof = stark.prove(rows, _transitions(_ext), _boundaries(T, _ext), max_degree=2,
                        num_queries=num_queries, aux_spec=_aux_spec(_ext), backend=backend)
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
        _ext = stark.ext_challenges_active(backend)
        return stark.verify(proof, _transitions(_ext), _boundaries(T, _ext), max_degree=2,
                            num_queries=num_queries, aux_spec=_aux_spec(_ext), backend=backend)
    except Exception as e:
        return False, f"malformed multiset-eq proof: {e}"
