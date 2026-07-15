"""
Constraint-IR bit-identity (execnode/stark/air_ir.py + native/starkcompose). Guards the ONE thing that
matters about the native prover: the IR — and its native Rust evaluator — must produce EXACTLY the same
composition polynomial as the pure-Python stark._composition, for a real two-phase execution AIR. Any
divergence is a soundness bug (a proof that verifies one way and not the other), so this test compares
field-element-for-field-element. Run: python3 tests/test_air_ir.py
"""
import os, sys, random, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.stark import vm_circuit as V, field as F, air_ir, stark
from execnode import runtimes

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _real_trace():
    """A real dice-bet execution-AIR trace + its periodic and (phase-2) aux columns."""
    code = __import__("execnode.games.dice", fromlist=["build"]).build()
    cf, fa = runtimes.zkvm_statement("ndoX" + "x" * 44, [88, 3, 50], {})
    S = lambda f, k: f * (1 << 32) + k
    slots = {S(1, 3): runtimes.zkvm_addr_digest("ndoA" + "a" * 44), S(2, 3): 50_000_000, S(3, 3): 50_000_000}
    call = V._norm_call({"code": code, "method": "bet", "caller_f": cf, "args_f": [a % F.P for a in fa],
                         "caller": "x", "args": [88, 3, 50], "value": 100_000, "cursor": 100, "timestamp": 0,
                         "beacons": None, "block_hashes": None, "slots": slots})
    trace, T, blocks, progs, epoch_io, _pc = V.build_epoch_trace([call])
    periodic = V.build_periodic(blocks, progs, epoch_io, T)
    beta, gamma = 111111, 222222
    aux = V.make_aux_builder(periodic)(trace, (beta, gamma))
    full = [trace[i] + [aux[c][i] for c in range(V.NUM_AUX)] for i in range(T)]
    return full, periodic, T, (beta, gamma)


def t_ir_matches_closures():
    """eval_program_point == the constraint closures, at random rows."""
    full, periodic, T, chal = _real_trace()
    trans = V.transitions()
    prog = air_ir.build_program(trans, V.W_TOTAL, V.NUM_PERIODIC, 2)
    random.seed(1)
    for _ in range(30):
        j = random.randrange(T)
        cur, nxt = full[j], full[(j + 1) % T]
        per = [periodic[c][j] for c in range(V.NUM_PERIODIC)]
        ir = air_ir.eval_program_point(prog, cur, nxt, per, list(chal))
        direct = [con(cur, nxt, per, chal) % F.P for con in trans]
        assert ir == direct, f"row {j}: IR != closures"


def _capture_composition():
    """Prove a dice bet, intercepting stark._composition to grab its exact inputs + output."""
    cap = {}
    real = stark._composition
    def spy(T, W, N, blowup, gT, col_lde, per_lde, x_lde, transitions, boundaries, alphas, challenges=None):
        out = real(T, W, N, blowup, gT, col_lde, per_lde, x_lde, transitions, boundaries, alphas, challenges)
        cap.update(T=T, W=W, N=N, blowup=blowup, gT=gT, col_lde=col_lde, per_lde=per_lde, x_lde=x_lde,
                   transitions=transitions, boundaries=boundaries, alphas=alphas, challenges=challenges, out=out)
        return out
    stark._composition = spy
    try:
        code = __import__("execnode.games.dice", fromlist=["build"]).build()
        cf, fa = runtimes.zkvm_statement("ndoX" + "x" * 44, [88, 3, 50], {})
        S = lambda f, k: f * (1 << 32) + k
        slots = {S(1, 3): runtimes.zkvm_addr_digest("ndoA" + "a" * 44), S(2, 3): 50_000_000, S(3, 3): 50_000_000}
        V.prove_call(code, "bet", cf, fa, slots, value=100_000, cursor=100, num_queries=6)
    finally:
        stark._composition = real
    return cap


def _ivz_bnd(c):
    T, N, gT, x = c["T"], c["N"], c["gT"], c["x_lde"]
    last = F.pw(gT, T - 1)
    inv_xTm1 = F.batch_inverse([F.sub(F.pw(x[j], T), 1) for j in range(N)])
    invZ = [F.mul(F.sub(x[j], last), inv_xTm1[j]) for j in range(N)]
    bnd = [F.batch_inverse([F.sub(x[j], F.pw(gT, row)) for j in range(N)]) for (row, _c, _v) in c["boundaries"]]
    return invZ, bnd


def t_python_ir_composition():
    c = _capture_composition()
    invZ, bnd = _ivz_bnd(c)
    prog = air_ir.build_program(c["transitions"], c["W"], V.NUM_PERIODIC, 2)
    got = air_ir.compose_python(prog, c["N"], c["blowup"], c["col_lde"], c["per_lde"], c["challenges"],
                                c["alphas"], invZ, c["boundaries"], bnd)
    assert got == c["out"], "python-IR composition != stark._composition"


def t_native_composition():
    c = _capture_composition()
    invZ, bnd = _ivz_bnd(c)
    prog = air_ir.build_program(c["transitions"], c["W"], V.NUM_PERIODIC, 2)
    got = air_ir.compose_native(prog, c["N"], c["blowup"], c["col_lde"], c["per_lde"], list(c["challenges"]),
                                c["alphas"], invZ, c["boundaries"], bnd)
    if got is None:
        print("      (native lib unbuilt — skipping native check; Python path is the fallback)")
        return
    assert got == c["out"], "NATIVE composition != stark._composition (soundness bug!)"


if __name__ == "__main__":
    check("IR interpreter == constraint closures (execution AIR)", t_ir_matches_closures)
    check("python-IR composition == stark._composition", t_python_ir_composition)
    check("native composition == stark._composition (bit-identical)", t_native_composition)
    print("ALL PASS" if not fails else f"{fails} FAILED")
    sys.exit(1 if fails else 0)
