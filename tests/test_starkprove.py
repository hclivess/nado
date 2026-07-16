"""
Holistic native prover — step 1: the PERSISTENT LDE ARENA (native/starkprove, execnode/stark/stark_native.py).

The invariant for the whole holistic-prover effort is BIT-IDENTITY: every stage must produce byte-for-byte the
same values as the current Python-orchestrated prover, so proofs stay valid and consensus is untouched. This
gates step 1: the arena's fused native LDE (sp_lde_column) reproduces stark._coset_evaluate(F.interpolate(col),
N, OFF) EXACTLY, field-for-field, and the retained buffer reads back identically at every position — across
several T, blowup, and random columns. If the .so isn't built the test SKIPS (nothing depends on it yet).

Run: python3 tests/test_starkprove.py   (build first: cd native/starkprove && cargo build --release)
"""
import os, sys, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import field as F, stark, stark_native as SN, merkle, backend as B, air_ir, fri
from execnode.stark.transcript import Transcript

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _py_lde(col, N):
    """The exact Python path stark.prove uses per column: interpolate then coset-evaluate over the OFF coset."""
    return stark._coset_evaluate(F.interpolate(list(col)), N, stark.OFF)


def t_lde_bit_identical():
    """sp_lde_column == _coset_evaluate(F.interpolate(col), N, OFF), field-for-field, over several geometries."""
    for T, blowup in [(8, 2), (16, 4), (64, 8), (256, 32), (1024, 16)]:
        N = T * blowup
        random.seed(1000 + T + blowup)
        for _ in range(3):
            col = [random.randrange(F.P) for _ in range(T)]
            want = _py_lde(col, N)
            SN.reset(T, N, stark.OFF)
            cid, got = SN.lde_column(col, N)
            assert cid == 0, f"first column id must be 0, got {cid}"
            assert len(got) == N, f"LDE length {len(got)} != N {N}"
            assert got == want, f"LDE mismatch at T={T} N={N}: first diff " + \
                str(next(((i, a, b) for i, (a, b) in enumerate(zip(got, want)) if a != b), None))


def t_arena_retains_and_reads():
    """Multiple columns retained in the arena; sp_read returns the SAME values sp_lde_column produced (this is
    what later stages — Merkle, composition, openings — will read instead of Python lists)."""
    T, blowup = 128, 8; N = T * blowup
    random.seed(77)
    cols = [[random.randrange(F.P) for _ in range(T)] for _ in range(5)]
    SN.reset(T, N, stark.OFF)
    ldes = []
    for k, col in enumerate(cols):
        cid, got = SN.lde_column(col, N)
        assert cid == k, f"column id {cid} != insertion order {k}"
        ldes.append(got)
    assert SN.num_cols() == len(cols), "arena must retain every column"
    # spot-read every column at several positions — must equal both the returned buffer and the Python path
    for k, col in enumerate(cols):
        want = _py_lde(col, N)
        for pos in (0, 1, N // 2, N - 1, 12345 % N):
            assert SN.read(k, pos) == ldes[k][pos] == want[pos], f"read mismatch col {k} pos {pos}"
    SN.free()
    assert SN.num_cols() == -1, "sp_free must release the arena"


def t_merkle_col_bit_identical():
    """sp_commit_col (RECURSION-backend rleaf/rnode tree, built straight from the retained arena column) gives
    the SAME root and the SAME authentication paths as merkle.commit(col_lde, backend.RECURSION) +
    merkle.open_at — so the arena's Merkle stage never marshals the column back to Python."""
    for T, blowup in [(8, 2), (64, 8), (256, 32)]:
        N = T * blowup
        random.seed(4000 + T + blowup)
        col = [random.randrange(F.P) for _ in range(T)]
        py_lde = _py_lde(col, N)
        want_root, want_layers = merkle.commit(py_lde, B.RECURSION)
        SN.reset(T, N, stark.OFF)
        cid, _ = SN.lde_column(col, N, want_out=False)
        tid, got_root = SN.commit_col(cid)
        assert got_root == tuple(want_root), f"root mismatch T={T}: {got_root} != {tuple(want_root)}"
        path_len = N.bit_length() - 1
        for pos in (0, 1, N // 2, N - 1, 98765 % N):
            got_path = SN.open_at(tid, pos, path_len)
            want_path = merkle.open_at(want_layers, pos)
            assert [tuple(d) for d in got_path] == [tuple(d) for d in want_path], \
                f"path mismatch T={T} pos={pos}"
            # and the path a verifier would check actually re-roots (defense in depth)
            assert merkle.verify(want_root, pos, py_lde[pos], want_path, B.RECURSION)
    SN.free()


def _compose_case(W, T, transitions, boundaries, periodic, num_challenges, chals, seed):
    """Compute cp both ways for one AIR/trace and assert byte-identity. col/per LDEs built the Python way;
    the arena adds the same columns then runs sp_compose; alphas are shared."""
    max_degree = 2
    blowup = stark._blowup(max_degree); N = blowup * T
    gT = F.primitive_root_of_unity(T)
    random.seed(seed)
    trace = [[random.randrange(F.P) for _ in range(W)] for _ in range(T)]
    prog = air_ir.build_program(transitions, W, len(periodic), num_challenges)
    alphas = [random.randrange(F.P) for _ in range(len(transitions) + len(boundaries))]
    col_lde = [stark._coset_evaluate(F.interpolate([trace[i][c] for i in range(T)]), N, stark.OFF)
               for c in range(W)]
    per_lde = [stark._coset_evaluate(F.interpolate(stark._per_expand(pc, T)), N, stark.OFF) for pc in periodic]
    x_lde = F.domain(N, stark.OFF)
    cp_py = stark._composition(T, W, N, blowup, gT, col_lde, per_lde, x_lde, transitions, boundaries,
                               alphas, chals if num_challenges else None)
    SN.reset(T, N, stark.OFF)
    for c in range(W):
        SN.lde_column([trace[i][c] for i in range(T)], N, want_out=False)
    for pc in periodic:
        SN.lde_column(stark._per_expand(pc, T), N, want_out=False)
    _, cp_native = SN.compose(prog, boundaries, alphas, chals if num_challenges else [], T, N, blowup)
    assert cp_native == cp_py, "composition mismatch: first diff " + \
        str(next(((i, a, b) for i, (a, b) in enumerate(zip(cp_native, cp_py)) if a != b), None))
    SN.free()


def t_compose_single_phase():
    """Composition from the arena == stark._composition, single-phase, with a structured periodic + boundaries."""
    PER0 = {"period": 4, "base": [3, 1, 4, 1]}
    TRANS = [lambda c, n, p: F.sub(n[0], F.add(F.mul(c[0], c[0]), p[0])),
             lambda c, n, p: F.sub(c[1], F.mul(c[0], c[0]))]
    BND = [(0, 0, 12345), (0, 1, 6789), (3, 0, 42)]
    for T in (8, 64, 256):
        _compose_case(2, T, TRANS, BND, [PER0], 0, [], seed=500 + T)


def t_compose_with_challenge():
    """Exercise the CHAL opcode: a constraint reads a challenge γ; cp matches with challenges passed through."""
    PER0 = {"period": 4, "base": [3, 1, 4, 1]}
    TRANS = [lambda c, n, p, ch: F.sub(n[0], F.add(F.mul(c[0], c[0]), p[0])),
             lambda c, n, p, ch: F.sub(n[2], F.add(c[2], F.mul(ch[0], n[0])))]   # aux-style, γ-weighted
    BND = [(0, 0, 111), (0, 2, 0)]
    for T in (8, 64):
        _compose_case(3, T, TRANS, BND, [PER0], 1, [F.GENERATOR + 7], seed=900 + T)


def t_fri_bit_identical():
    """stark_native.fri_prove (fold + Merkle + openings from the arena; transcript in Python) produces the
    IDENTICAL FRI proof to fri.prove over the RECURSION backend — roots, final, pow nonce, and every query
    step (values + paths) field-for-field — over a real low-degree evals vector."""
    for T, DEG, blowup, NQ in [(64, 8, 4, 3), (256, 16, 2, 5), (512, 64, 4, 8)]:
        N = T
        random.seed(3000 + T + DEG)
        # a genuinely low-degree poly on the coset (so FRI's final layer really is low-degree)
        coeffs = [random.randrange(F.P) for _ in range(N // blowup)] + [0] * (N - N // blowup)
        off = F.GENERATOR
        evals = [F.poly_eval(coeffs, x) for x in F.domain(N, off)]
        proof_py = fri.prove(evals, off, blowup=blowup, num_queries=NQ,
                             transcript=Transcript("fri", backend=B.RECURSION), backend=B.RECURSION)
        SN.reset(1, N, off)
        cid = SN.load_col(evals)
        proof_nat = SN.fri_prove(cid, off, blowup, NQ, Transcript("fri", backend=B.RECURSION))
        for k in ("N", "offset", "blowup", "pow"):
            assert proof_nat[k] == proof_py[k], f"FRI {k} mismatch: {proof_nat[k]} != {proof_py[k]}"
        assert [tuple(r) for r in proof_nat["roots"]] == [tuple(r) for r in proof_py["roots"]], "FRI roots mismatch"
        assert list(proof_nat["final"]) == list(proof_py["final"]), "FRI final mismatch"
        assert len(proof_nat["queries"]) == len(proof_py["queries"]) == NQ
        for qn, qp in zip(proof_nat["queries"], proof_py["queries"]):
            assert qn["idx"] == qp["idx"], "FRI query idx mismatch"
            assert len(qn["steps"]) == len(qp["steps"])
            for sn, sp in zip(qn["steps"], qp["steps"]):
                assert sn["lo"] == sp["lo"] and sn["hi"] == sp["hi"], "FRI step value mismatch"
                assert [tuple(d) for d in sn["lo_path"]] == [tuple(d) for d in sp["lo_path"]], "FRI lo_path mismatch"
                assert [tuple(d) for d in sn["hi_path"]] == [tuple(d) for d in sp["hi_path"]], "FRI hi_path mismatch"
        # and the native proof VERIFIES under the real verifier (defense in depth)
        ok, why = fri.verify(proof_nat, transcript=Transcript("fri", backend=B.RECURSION),
                             num_queries=NQ, expected_blowup=blowup, backend=B.RECURSION)
        assert ok, f"native FRI proof must verify: {why}"
        SN.free()


def _proofs_equal(a, b, path="proof"):
    """Deep byte-equality of two proof dicts (tuples vs lists normalized)."""
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        assert len(a) == len(b), f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            _proofs_equal(x, y, f"{path}[{i}]")
    elif isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), f"{path}: keys {set(a)} != {set(b)}"
        for k in a:
            _proofs_equal(a[k], b[k], f"{path}.{k}")
    else:
        assert a == b, f"{path}: {a} != {b}"


def t_prove_end_to_end():
    """HOLISTIC prove == stark.prove, single-phase column mode, RECURSION backend — the WHOLE proof dict
    field-for-field (col_roots, fri roots/final/pow/queries, and every opening path), and the native proof
    verifies under the real stark.verify."""
    PER0 = {"period": 4, "base": [3, 1, 4, 1]}
    TRANS = [lambda c, n, p: F.sub(n[0], F.add(F.mul(c[0], c[0]), p[0])),
             lambda c, n, p: F.sub(c[1], F.mul(c[0], c[0]))]
    for T, NQ in [(8, 3), (64, 8)]:
        random.seed(6000 + T)
        # a trace that actually satisfies the AIR (col0 evolves by col0^2+per0; col1 = col0^2) so it verifies
        PER0_DENSE = [PER0["base"][i % 4] for i in range(T)]
        col0 = [random.randrange(F.P)]
        for i in range(T - 1):
            col0.append(F.add(F.mul(col0[-1], col0[-1]), PER0_DENSE[i]))
        trace = [[v, F.mul(v, v)] for v in col0]
        BND = [(0, 0, col0[0]), (0, 1, F.mul(col0[0], col0[0]))]
        want = stark.prove(trace, TRANS, BND, periodic=[PER0], max_degree=2, num_queries=NQ, backend=B.RECURSION)
        got = SN.prove(trace, TRANS, BND, periodic=[PER0], max_degree=2, num_queries=NQ)
        _proofs_equal(got, want)
        ok, why = stark.verify(got, TRANS, BND, periodic=[PER0], max_degree=2, num_queries=NQ, backend=B.RECURSION)
        assert ok, f"holistic-proved proof must verify under stark.verify: {why}"


def t_prove_row_commit():
    """HOLISTIC prove == stark.prove in ROW-COMMIT mode (ONE row tree; openings authenticate a whole row with
    one path), byte-identical + verifies."""
    PER0 = {"period": 4, "base": [3, 1, 4, 1]}
    TRANS = [lambda c, n, p: F.sub(n[0], F.add(F.mul(c[0], c[0]), p[0])),
             lambda c, n, p: F.sub(c[1], F.mul(c[0], c[0]))]
    for T, NQ in [(8, 3), (64, 6)]:
        random.seed(7000 + T)
        PD = [PER0["base"][i % 4] for i in range(T)]
        col0 = [random.randrange(F.P)]
        for i in range(T - 1):
            col0.append(F.add(F.mul(col0[-1], col0[-1]), PD[i]))
        trace = [[v, F.mul(v, v)] for v in col0]
        BND = [(0, 0, col0[0]), (0, 1, F.mul(col0[0], col0[0]))]
        want = stark.prove(trace, TRANS, BND, periodic=[PER0], max_degree=2, num_queries=NQ,
                           backend=B.RECURSION, row_commit=True)
        got = SN.prove(trace, TRANS, BND, periodic=[PER0], max_degree=2, num_queries=NQ, row_commit=True)
        _proofs_equal(got, want)
        ok, why = stark.verify(got, TRANS, BND, periodic=[PER0], max_degree=2, num_queries=NQ,
                               backend=B.RECURSION, row_commit=True)
        assert ok, f"row-committed holistic proof must verify: {why}"


def t_prove_two_phase():
    """HOLISTIC prove == stark.prove for a TWO-PHASE (LogUp-style) AIR: main commit → challenge γ → aux
    running-sum column → composition with γ. The aux BUILDER stays in Python (small T-length columns); the
    LDEs/commit/compose/FRI stay in the arena. Byte-identical + verifies. This is the execution/segment shape."""
    PER0 = {"period": 4, "base": [3, 1, 4, 1]}
    TRANS = [lambda c, n, p, ch: F.sub(n[0], F.add(F.mul(c[0], c[0]), p[0])),
             lambda c, n, p, ch: F.sub(c[1], F.mul(c[0], c[0])),
             lambda c, n, p, ch: F.sub(n[2], F.add(c[2], F.mul(ch[0], n[0])))]

    def build_aux(trace, chals):
        g = chals[0]; acc = 0; out = []
        for i, row in enumerate(trace):
            if i > 0:
                acc = F.add(acc, F.mul(g, row[0]))
            out.append(acc)
        return [out]
    SPEC = {"num_challenges": 1, "num_aux": 1, "build": build_aux}
    for T, NQ in [(8, 3), (64, 6)]:
        random.seed(8000 + T)
        PD = [PER0["base"][i % 4] for i in range(T)]
        col0 = [random.randrange(F.P)]
        for i in range(T - 1):
            col0.append(F.add(F.mul(col0[-1], col0[-1]), PD[i]))
        trace = [[v, F.mul(v, v)] for v in col0]
        BND = [(0, 0, col0[0]), (0, 2, 0)]
        want = stark.prove(trace, TRANS, BND, periodic=[PER0], max_degree=2, num_queries=NQ,
                           aux_spec=SPEC, backend=B.RECURSION, row_commit=True)
        got = SN.prove(trace, TRANS, BND, periodic=[PER0], max_degree=2, num_queries=NQ,
                       aux_spec=SPEC, row_commit=True)
        _proofs_equal(got, want)
        ok, why = stark.verify(got, TRANS, BND, periodic=[PER0], max_degree=2, num_queries=NQ,
                               aux_spec=SPEC, backend=B.RECURSION, row_commit=True)
        assert ok, f"two-phase holistic proof must verify: {why}"


if __name__ == "__main__":
    if not SN.available():
        print("SKIP  native/starkprove not built (cd native/starkprove && cargo build --release). "
              "Nothing depends on it yet.")
        sys.exit(0)
    check("native fused LDE is bit-identical to interpolate+coset_evaluate", t_lde_bit_identical)
    check("arena retains columns + reads back identically", t_arena_retains_and_reads)
    check("native arena Merkle (rleaf/rnode) bit-identical to merkle.commit(RECURSION)", t_merkle_col_bit_identical)
    check("native arena composition bit-identical to stark._composition (single-phase)", t_compose_single_phase)
    check("native arena composition bit-identical with a challenge (CHAL opcode)", t_compose_with_challenge)
    check("native arena FRI bit-identical to fri.prove (fold+commit+open+queries)", t_fri_bit_identical)
    check("HOLISTIC prove == stark.prove end-to-end (single-phase column, verifies)", t_prove_end_to_end)
    check("HOLISTIC prove == stark.prove (row-commit, verifies)", t_prove_row_commit)
    check("HOLISTIC prove == stark.prove (two-phase LogUp, verifies)", t_prove_two_phase)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
