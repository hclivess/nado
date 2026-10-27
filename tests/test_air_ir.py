"""
Constraint-IR bit-identity (execnode/stark/air_ir.py + native/starkcompose). Guards the ONE thing that
matters about the native prover: the IR — and its native Rust evaluator — must produce EXACTLY the same
composition polynomial as the pure-Python stark._composition, for a real AIR. Any divergence is a soundness
bug (a proof that verifies one way and not the other), so this test compares field-element-for-field-element.

The AIR is the join-split (execnode/stark/joinsplit_circuit.py), the legacy shielded pool's withdraw proof that
stark.py still proves. It used to be the two-phase execution AIR (vm_circuit), which G9 deleted with the
Goldilocks settle proof; no two-phase AIR is left, so the IR is exercised here with zero challenges — the only
shape any remaining caller hands it. Run: python3 tests/test_air_ir.py
"""
import os, sys, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import joinsplit_circuit as JC, field as F, air_ir, stark

import _harness
_report = _harness.Report()
check = _report.run

# tests/test_stark_joinsplit_circuit.py's canonical 900-in / 850-out + 50-fee transfer
NSK, VIN, RHO = 0xCAFE, 900, 0x9999
SIBS, DIRS = [111, 222, 333, 444], [0, 1, 0, 1]
VOUT, OWN_OUT, RHO_OUT = 850, 0xABC, 0x5555
PUB, FEE = 0, 50

_CAP = {}


def _capture_composition():
    """Prove the join-split, intercepting stark._composition to grab its exact inputs + output (once)."""
    if _CAP:
        return _CAP
    cap = _CAP
    real = stark._composition
    def spy(T, W, N, blowup, gT, col_lde, per_lde, x_lde, transitions, boundaries, alphas,
            challenges=None, ext_alphas=False):
        # ext_alphas is forwarded, not dropped: with GF(p^2) alphas the composition is extension-valued and
        # this test compares it against the IR interpreter, so silently proving under the base-field path
        # would compare two different quantities and pass for the wrong reason.
        out = real(T, W, N, blowup, gT, col_lde, per_lde, x_lde, transitions, boundaries, alphas,
                   challenges, ext_alphas=ext_alphas)
        cap.update(T=T, W=W, N=N, blowup=blowup, gT=gT, col_lde=col_lde, per_lde=per_lde, x_lde=x_lde,
                   transitions=transitions, boundaries=boundaries, alphas=alphas, challenges=challenges,
                   ext_alphas=ext_alphas, out=list(out))   # a COPY: stark.prove adds the P1 trace batch into this
                                                            # list in place afterwards, so a reference compared a
                                                            # mutated value (broken since PROOF_TRACE_LDT_HEIGHT)
        return out
    stark._composition = spy
    try:
        JC.prove_transfer(NSK, VIN, RHO, SIBS, DIRS, VOUT, OWN_OUT, RHO_OUT, PUB, FEE, num_queries=6)
    finally:
        stark._composition = real
    assert cap, "stark.prove never reached _composition"
    return cap


def t_ir_matches_closures():
    """eval_program_point == the constraint closures, at random points of the real proof's LDE (next row is
    j+blowup there, exactly as stark._composition reads it)."""
    c = _capture_composition()
    W, N, bl, trans = c["W"], c["N"], c["blowup"], c["transitions"]
    nper = len(c["per_lde"])
    chal = list(c["challenges"] or [])
    prog = air_ir.build_program(trans, W, nper, len(chal))
    random.seed(1)
    for _ in range(30):
        j = random.randrange(N)
        cur = [c["col_lde"][k][j] for k in range(W)]
        nxt = [c["col_lde"][k][(j + bl) % N] for k in range(W)]
        per = [c["per_lde"][k][j] for k in range(nper)]
        ir = air_ir.eval_program_point(prog, cur, nxt, per, chal)
        direct = [(con(cur, nxt, per, chal) if chal else con(cur, nxt, per)) % F.P for con in trans]
        assert ir == direct, f"point {j}: IR != closures"


def _ivz_bnd(c):
    T, N, gT, x = c["T"], c["N"], c["gT"], c["x_lde"]
    last = F.pw(gT, T - 1)
    inv_xTm1 = F.batch_inverse([F.sub(F.pw(x[j], T), 1) for j in range(N)])
    invZ = [F.mul(F.sub(x[j], last), inv_xTm1[j]) for j in range(N)]
    bnd = [F.batch_inverse([F.sub(x[j], F.pw(gT, row)) for j in range(N)]) for (row, _c, _v) in c["boundaries"]]
    return invZ, bnd


def t_python_ir_composition():
    """The IR composition must reproduce stark._composition EXACTLY — including under GF(p^2) alphas, where
    both are extension-valued and an extension constraint contributes a limb PAIR of outputs."""
    c = _capture_composition()
    invZ, bnd = _ivz_bnd(c)
    ext = bool(c.get("ext_alphas"))
    prog = air_ir.build_program(c["transitions"], c["W"], len(c["per_lde"]), len(c["challenges"] or []),
                                ext_chal=ext)
    chals = list(c["challenges"] or [])
    if ext:                                  # the IR takes challenges as FLAT limbs, one CHAL leaf each
        chals = [limb for ch in (c["challenges"] or []) for limb in (ch if isinstance(ch, tuple) else (ch, 0))]
    got = air_ir.compose_python(prog, c["N"], c["blowup"], c["col_lde"], c["per_lde"], chals,
                                c["alphas"], invZ, c["boundaries"], bnd)
    assert got == c["out"], "python-IR composition != stark._composition"


def t_native_composition():
    """The Rust arena multiplies by a BASE-field alpha, so it cannot carry GF(p^2) alphas — stark._composition
    deliberately takes the Python path when they are in use. Comparing against it under ext would be comparing
    a path that never runs, so this check applies to the base-field composition only."""
    c = _capture_composition()
    if c.get("ext_alphas"):
        print("      (GF(p^2) alphas in use — the native arena is base-field by design; check N/A)")
        return
    invZ, bnd = _ivz_bnd(c)
    prog = air_ir.build_program(c["transitions"], c["W"], len(c["per_lde"]), len(c["challenges"] or []))
    got = air_ir.compose_native(prog, c["N"], c["blowup"], c["col_lde"], c["per_lde"], list(c["challenges"] or []),
                                c["alphas"], invZ, c["boundaries"], bnd)
    if got is None:
        print("      (native lib unbuilt — skipping native check; Python path is the fallback)")
        return
    assert got == c["out"], "NATIVE composition != stark._composition (soundness bug!)"


if __name__ == "__main__":
    check("IR interpreter == constraint closures (join-split AIR)", t_ir_matches_closures)
    check("python-IR composition == stark._composition", t_python_ir_composition)
    check("native composition == stark._composition (bit-identical)", t_native_composition)
    print("ALL PASS" if not _report.fails else f"{_report.fails} FAILED")
    sys.exit(1 if _report.fails else 0)
