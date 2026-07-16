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
from execnode.stark import field as F, stark, stark_native as SN, merkle, backend as B

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


if __name__ == "__main__":
    if not SN.available():
        print("SKIP  native/starkprove not built (cd native/starkprove && cargo build --release). "
              "Nothing depends on it yet.")
        sys.exit(0)
    check("native fused LDE is bit-identical to interpolate+coset_evaluate", t_lde_bit_identical)
    check("arena retains columns + reads back identically", t_arena_retains_and_reads)
    check("native arena Merkle (rleaf/rnode) bit-identical to merkle.commit(RECURSION)", t_merkle_col_bit_identical)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
