"""
Constraint IR — trace an AIR's transition-constraint closures into a flat, hash-consed SSA program of field
operations, so the composition polynomial can be evaluated by a NATIVE (Rust) interpreter over the whole LDE
domain instead of by Python per point (the prover's dominant cost once hashing is native — see
doc/zk-recursion.md §3.2 / the native-prover task).

HOW: the constraints in vm_circuit/recursion are pure algebraic functions `con(cur, nxt, per, chal)` built out
of `field.add/sub/mul/pw` (+ constants). We call each ONCE with SYMBOLIC row/periodic/challenge inputs while
`field`'s arithmetic is monkeypatched to record an expression DAG instead of computing. Identical subexpressions
(the shared `_rs_val`, `_res_expr`, … across constraints) intern to the SAME node → global common-subexpression
elimination for free. The result is one SSA program whose N outputs are the N transition constraints, evaluated
in one topological pass per point.

The IR is a plain list of instructions `(op, a, b)`; leaves reference a trace column / periodic column /
challenge / constant; binary ops reference earlier instruction indices (SSA, operands always precede). A
POW's `b` is a small immediate exponent. Evaluation (Python here, Rust in native/starkcompose) is a mechanical
interpreter — and MUST be bit-identical to stark._composition (verified in tests). Nothing about soundness
changes: this only relocates the SAME field arithmetic off the Python interpreter.
"""
from execnode.stark import field as F

# opcodes (kept in sync with the native interpreter)
CUR, NXT, PER, CHAL, CONST, ADD, SUB, MUL, POW = range(9)


class _Builder:
    """Interning SSA builder. `ops[i] = (op, a, b)`; consts holds CONST values (a = index into consts)."""
    def __init__(self):
        self.ops = []
        self._intern = {}
        self.consts = []
        self._cintern = {}

    def _node(self, op, a, b):
        key = (op, a, b)
        i = self._intern.get(key)
        if i is None:
            i = len(self.ops)
            self.ops.append((op, a, b))
            self._intern[key] = i
        return i

    def leaf(self, op, idx):
        return self._node(op, idx, 0)

    def const(self, v):
        v = int(v) % F.P
        ci = self._cintern.get(v)
        if ci is None:
            ci = len(self.consts)
            self.consts.append(v)
            self._cintern[v] = ci
        return self._node(CONST, ci, 0)

    def binop(self, op, a, b):
        return self._node(op, a, b)

    def powop(self, a, e):
        return self._node(POW, a, int(e))


class _Sym:
    """A symbolic field value = (builder, node id). Arithmetic goes through the monkeypatched `field` fns."""
    __slots__ = ("b", "nid")

    def __init__(self, b, nid):
        self.b = b
        self.nid = nid

    # `v % F.P` appears in logup.combine — reduction is identity on an already-in-field symbolic value.
    def __mod__(self, other):
        return self

    def __rmod__(self, other):
        return self


def _coerce(b, x):
    return x.nid if isinstance(x, _Sym) else b.const(x)


class _tracing:
    """Context manager: monkeypatch field.add/sub/mul/pw/neg to build IR nodes when any operand is symbolic,
    else defer to the real field arithmetic (so constant folding on pure-int subexpressions stays exact)."""
    def __init__(self, b):
        self.b = b
        self._saved = {}

    def __enter__(self):
        b = self.b
        real = {n: getattr(F, n) for n in ("add", "sub", "mul", "pw", "neg")}
        self._saved = real

        def add(x, y):
            if isinstance(x, _Sym) or isinstance(y, _Sym):
                return _Sym(b, b.binop(ADD, _coerce(b, x), _coerce(b, y)))
            return real["add"](x, y)

        def sub(x, y):
            if isinstance(x, _Sym) or isinstance(y, _Sym):
                return _Sym(b, b.binop(SUB, _coerce(b, x), _coerce(b, y)))
            return real["sub"](x, y)

        def mul(x, y):
            if isinstance(x, _Sym) or isinstance(y, _Sym):
                return _Sym(b, b.binop(MUL, _coerce(b, x), _coerce(b, y)))
            return real["mul"](x, y)

        def pw(x, e):
            if isinstance(x, _Sym):
                if e < 0:
                    raise ValueError("IR trace: negative exponent in a constraint (unexpected)")
                return _Sym(b, b.powop(_coerce(b, x), e))
            return real["pw"](x, e)

        def neg(x):
            if isinstance(x, _Sym):
                return _Sym(b, b.binop(SUB, b.const(0), x.nid))
            return real["neg"](x)

        F.add, F.sub, F.mul, F.pw, F.neg = add, sub, mul, pw, neg
        return self

    def __exit__(self, *a):
        for n, fn in self._saved.items():
            setattr(F, n, fn)
        return False


def build_program(transitions, W, num_periodic, num_chal):
    """Trace every transition constraint into ONE shared SSA program. Returns a dict:
      ops      : list of (op, a, b)         — the SSA (topological; a/b are earlier indices for binops)
      consts   : list of field values       — CONST leaves reference these by index
      outputs  : list of node ids           — output[t] = transition constraint t's value
      W, P, C  : geometry echoed back
    Raises if a constraint touches a challenge when num_chal == 0 (i.e. a one-phase AIR)."""
    b = _Builder()
    cur = [_Sym(b, b.leaf(CUR, i)) for i in range(W)]
    nxt = [_Sym(b, b.leaf(NXT, i)) for i in range(W)]
    per = [_Sym(b, b.leaf(PER, i)) for i in range(num_periodic)]
    chal = [_Sym(b, b.leaf(CHAL, i)) for i in range(num_chal)]
    outputs = []
    with _tracing(b):
        for con in transitions:
            r = con(cur, nxt, per, chal) if num_chal else con(cur, nxt, per)
            outputs.append(_coerce(b, r))          # a constraint with no row dependence folds to a CONST leaf
    return {"ops": b.ops, "consts": b.consts, "outputs": outputs,
            "W": W, "P": num_periodic, "C": num_chal}


import ctypes as _ct
import os as _os

_LIB = None
def _native():
    """Load libnado_starkcompose (native composition) once; None if unbuilt (→ pure-Python fallback)."""
    global _LIB
    if _LIB is not None:
        return _LIB or None
    try:
        from execnode.stark.native_guard import is_stale
        crate = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))),
                              "native", "starkcompose")
        so = _os.path.join(crate, "target", "release", "libnado_starkcompose.so")
        if is_stale(so, crate):                            # .so older than its sources (pulled without rebuild)
            raise OSError("native starkcompose .so is older than its sources — stale, using pure Python")
        lib = _ct.CDLL(so)
        u32, u64, sz = _ct.c_uint32, _ct.c_uint64, _ct.c_size_t
        Pu32, Pu64 = _ct.POINTER(u32), _ct.POINTER(u64)
        lib.compose.argtypes = [sz, Pu32, sz, Pu64, sz, Pu32, sz, sz, sz, sz, sz,
                                Pu64, Pu64, Pu64, Pu64, Pu64, sz, Pu32, Pu64, Pu64, Pu64]
        lib.compose.restype = _ct.c_int32
        _LIB = lib
        return lib
    except Exception:
        _LIB = False
        return None


def compose_native(prog, N, blowup, col_lde, per_lde, chals, alphas, invZ, boundaries, bnd_inv_dens):
    """Native composition (bit-identical to compose_python / stark._composition). Returns the cp list, or None
    if the native lib is unavailable OR rejects the program (caller then uses the Python path)."""
    lib = _native()
    if lib is None:
        return None
    u32, u64 = _ct.c_uint32, _ct.c_uint64
    ops = prog["ops"]; consts = prog["consts"]; outputs = prog["outputs"]
    W, nper = prog["W"], prog["P"]; nchal = len(chals)
    n_ops = len(ops); n_out = len(outputs); n_bnd = len(boundaries)

    ops_flat = (u32 * (n_ops * 3))()
    for i, (op, a, b) in enumerate(ops):
        ops_flat[i * 3] = op; ops_flat[i * 3 + 1] = a % (1 << 32); ops_flat[i * 3 + 2] = b % (1 << 32)
    # slice-assignment (arr[:] = list) marshals the big LDE arrays far faster than the (u64*n)(*list)
    # constructor unpack — the dominant setup cost at recursion scale (cols/per/binv are O((W+nper+n_bnd)·N)).
    def _arr(size, vals):
        m = max(1, size)
        a = (u64 * m)()
        vals = list(vals)
        if len(vals) < m:
            vals = vals + [0] * (m - len(vals))
        a[:] = vals[:m]
        return a
    consts_a = _arr(len(consts), consts)
    out_idx = (u32 * n_out)(); out_idx[:] = list(outputs)
    cols_a = _arr(W * N, [col_lde[c][j] for c in range(W) for j in range(N)])
    per_a = _arr(nper * N, [per_lde[c][j] for c in range(nper) for j in range(N)])
    chals_a = _arr(nchal, [int(x) % F.P for x in chals])
    alphas_a = _arr(n_out + n_bnd, list(alphas))
    invz_a = _arr(N, list(invZ))
    bcol = (u32 * max(1, n_bnd))(); bcol[:len(boundaries)] = [c for (_r, c, _v) in boundaries]
    bval = _arr(n_bnd, [v % F.P for (_r, _c, v) in boundaries])
    binv = _arr(n_bnd * N, [bnd_inv_dens[bi][j] for bi in range(n_bnd) for j in range(N)])
    out_a = (u64 * N)()

    rc = lib.compose(n_ops, ops_flat, len(consts), consts_a, n_out, out_idx, W, nper, nchal, N, blowup,
                     cols_a, per_a, chals_a, alphas_a, invz_a, n_bnd, bcol, bval, binv, out_a)
    if rc != 0:
        return None
    return list(out_a)


def compose_python(prog, N, blowup, col_lde, per_lde, chals, alphas, invZ, boundaries, bnd_inv_dens):
    """Evaluate the FULL composition polynomial over the size-N LDE via the IR — the reference the native
    interpreter must match, and itself a drop-in for stark._composition. `boundaries` = [(row, col, val)],
    `bnd_inv_dens[b]` = the size-N 1/(x-pt) vector for boundary b (computed exactly as stark._composition does).
    alphas has one entry per transition then one per boundary. Bit-identical arithmetic to _composition."""
    P = F.P
    W, nper = prog["W"], prog["P"]
    nt = len(prog["outputs"])
    cp = [0] * N
    for j in range(N):
        cur = [col_lde[c][j] for c in range(W)]
        nxt = [col_lde[c][(j + blowup) % N] for c in range(W)]
        per = [per_lde[c][j] for c in range(nper)]
        outs = eval_program_point(prog, cur, nxt, per, chals)
        acc = 0
        for t in range(nt):
            acc = (acc + alphas[t] * outs[t]) % P
        v = acc * invZ[j] % P
        for bi, (_row, col, val) in enumerate(boundaries):
            a = alphas[nt + bi]
            v = (v + a * ((col_lde[col][j] - val) % P) * bnd_inv_dens[bi][j]) % P
        cp[j] = v
    return cp


def program_degree(prog):
    """The polynomial DEGREE (in trace columns) of the AIR's highest-degree transition constraint, computed by
    propagating degrees through the SSA: CUR/NXT are degree-1 columns; PER/CHAL/CONST are degree 0 (public);
    ADD/SUB take the max; MUL adds; POW multiplies by the exponent. The composition gadgets need this to pick
    a `max_degree` with enough headroom — a composition gadget RE-EVALUATES this program and then GATES the
    result (check-row selector · alpha · invZ), which adds degree, so a gadget proving the recompute of a
    degree-D inner AIR must give itself deg_bound > (D+1)·T or its own composition isn't low-degree."""
    ops = prog["ops"]
    deg = [0] * len(ops)
    for i, (op, a, b) in enumerate(ops):
        if op in (CUR, NXT):
            deg[i] = 1
        elif op in (PER, CHAL, CONST):
            deg[i] = 0
        elif op in (ADD, SUB):
            deg[i] = max(deg[a], deg[b])
        elif op == MUL:
            deg[i] = deg[a] + deg[b]
        else:  # POW
            deg[i] = deg[a] * b
    return max((deg[o] for o in prog["outputs"]), default=0)


def gadget_max_degree(prog, floor=8):
    """The `max_degree` a composition gadget must prove at so its gated recompute of `prog` stays low-degree.
    The check constraint reaches ≈ (program_degree + 1)·T, so pick the smallest max_degree whose deg_bound
    (next_pow2(max_degree)·T) strictly exceeds that — floored at `floor` (the gadget's own round/mux
    constraints are degree ≤ 8, and prover+verifier both derive this from the SAME program so they agree)."""
    from execnode.stark.stark import _next_pow2
    need = program_degree(prog) + 2         # deg_bound (in T units) must exceed check_c ≈ program_degree+1
    md = floor
    while _next_pow2(md) < need:
        md = _next_pow2(md) + 1
    return md


def eval_program_point(prog, cur_row, nxt_row, per_row, chals):
    """Pure-Python interpreter: evaluate all outputs at ONE point given the row/periodic/challenge values.
    Returns a list (one value per output). Reference for the native interpreter's bit-identity test."""
    ops, consts = prog["ops"], prog["consts"]
    t = [0] * len(ops)
    for i, (op, a, bb) in enumerate(ops):
        if op == CUR:
            t[i] = cur_row[a]
        elif op == NXT:
            t[i] = nxt_row[a]
        elif op == PER:
            t[i] = per_row[a]
        elif op == CHAL:
            t[i] = chals[a]
        elif op == CONST:
            t[i] = consts[a]
        elif op == ADD:
            t[i] = (t[a] + t[bb]) % F.P
        elif op == SUB:
            t[i] = (t[a] - t[bb]) % F.P
        elif op == MUL:
            t[i] = (t[a] * t[bb]) % F.P
        else:  # POW
            t[i] = pow(t[a], bb, F.P)
    return [t[o] for o in prog["outputs"]]
