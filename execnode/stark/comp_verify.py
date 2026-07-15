"""
Verifier-authoritative in-circuit COMPOSITION spot-check (doc/zk-recursion.md, doc/zk-glossary.md). It is the
trace-to-constraints half of an in-circuit STARK verifier — the companion to fri_verify.py's low-degree half.

Per spot-check point, it proves inside ONE recursion STARK that: the opened trace-column values at a query row
are Merkle-authenticated under the segment's committed column roots, AND the composition polynomial recomputed
from those openings (via the constraint-IR, air_ir) equals the PUBLIC composition value at that point. Binding
that value to a FRI layer-0 opening is what forces the low-degree polynomial FRI accepts to be the committed
trace actually satisfying the AIR — i.e. what makes a fold AUTHORITATIVE for a settled state root rather than a
proof of low-degree alone.

Verifier-authoritative, exactly as fri_verify.py:
  * The public statement is {column roots, per-point query geometry (cur/nxt indices), the periodic + challenge
    + alpha + invZ + boundary values at the point, and the layer-0 target}. All of it the settlement seam
    re-derives from the segment proof's roots + AIR — never taken on the prover's word.
  * From that public statement BOTH prover and verifier build the SAME recursion-AIR periodic + boundaries.
    Merkle SIBLINGS and path DIRECTION bits are WITNESS — the directions are pinned to the PUBLIC leaf index by
    the boolean + IACC bit-consumption constraints (see fri_verify.py; the argument is identical).
  * `verify_comp` rebuilds the schedule itself and verifies the recursion STARK against ITS schedule. The proof
    carries only the WITNESS (opened values, siblings, directions, sponge states).

SUCCINCT: every periodic column is STRUCTURED (stark._per_evaluator) — the 16-row hash-block pattern plus O(1)
sparse rows per opened column path / per check row — so verification does NO O(T) interpolation and is
independent of the recursion trace length.

K→1: each point may carry its own `roots` (the column roots of ITS inner proof), so one comp proof can span
spot-checks of MANY segment proofs — the composition half of collapsing K proofs into one bundle.

The composition recompute is a single check constraint that runs the air_ir SSA program (the SAME one
stark._composition evaluates) over the carried openings, so it is generic over the AIR: the x^2 demo AIR and the
W=106 execution AIR share this code path — only W and the program differ.
"""
from execnode.stark import alghash2 as a2, field as F, stark, backend
from execnode.stark.recursion import _permute_snapshots, _blocks_for, rmerkle_commit, rmerkle_path
from execnode.stark.fri_verify import _fill_block, _fill_path, _junk_absorb, _B
from execnode.stark.air_ir import CUR, NXT, PER, CHAL, CONST, ADD, SUB, MUL, POW

_W, _R, _RATE, _CAP = a2.WIDTH, a2.ROUNDS, a2.RATE, a2.DIGEST

# trace column layout: 12 sponge lanes | 4 witness sibling lanes | DIRW IACC | 2W carries (W cur, W nxt)
_SIBW = _W                       # 12..15
_DIRW, _IACC = _W + _CAP, _W + _CAP + 1
_CARRY = _W + _CAP + 2           # 18..18+2W-1


def _point_paths(point):
    """(cur_index, nxt_index) for a spot-check point — the PUBLIC query geometry (all columns of a row share the
    row index; each column lives in its own tree so the paths differ, but the leaf INDEX is common)."""
    return point["cur"][0][1], point["nxt"][0][1]


def _roots_of(point, col_roots):
    """The W column roots THIS point authenticates against: its own inner proof's roots when present (the K→1
    multi-proof case), else the shared `col_roots`."""
    return point.get("roots", col_roots)


def _layout(W, points):
    """Row landmarks for the concatenated openings. Per point: W cur-column paths then W nxt-column paths, then
    the check reads all 2W carries at the point's last row. Pure function of the PUBLIC path lengths."""
    segs, chk_rows, row = [], [], 0
    for point in points:
        opens = point["cur"] + point["nxt"]            # 2W (val, index, path)
        starts = []
        for (_v, _i, path) in opens:
            nblk = len(path) + 1
            starts.append((row, nblk))
            row += nblk * _B
        segs.append(starts)
        chk_rows.append(row - 1)                        # last filled row of this point
    n_used = row
    T = 1
    while T < n_used + 1:
        T <<= 1
    return segs, chk_rows, T, n_used


# periodic column indices (all verifier-derivable + STRUCTURED; siblings and directions are witness)
def _per_layout(W, nt, nb, nper, nchal):
    RCL = 0; ACTR = _W; ACTA = _W + 1; SHOLDL = _W + 2; IHOLD = _W + 3; CHK = _W + 4; HOLD = _W + 5
    SEL = _W + 6                                        # 2W per-carry leaf selectors
    PINVZ = SEL + 2 * W
    PL0 = PINVZ + 1
    PALPHA = PL0 + 1                                    # nt+nb alphas
    PPER = PALPHA + nt + nb                             # nper periodic values at the point
    PCHAL = PPER + nper                                 # nchal challenge values
    PBVAL = PCHAL + nchal                               # nb boundary target values
    PBID = PBVAL + nb                                   # nb boundary 1/(x-pt) values
    NPER = PBID + nb
    return dict(RCL=RCL, ACTR=ACTR, ACTA=ACTA, SHOLDL=SHOLDL, IHOLD=IHOLD, CHK=CHK, HOLD=HOLD, SEL=SEL,
                PINVZ=PINVZ, PL0=PL0, PALPHA=PALPHA, PPER=PPER, PCHAL=PCHAL, PBVAL=PBVAL, PBID=PBID, NPER=NPER)


def _schedule(prog, W, boundaries, points, col_roots):
    """Build the recursion-AIR periodic + boundaries PURELY from the public statement (no witness). Prover and
    verifier both call this and MUST agree — that is what makes the verifier authoritative. Block anatomy and
    the structured-periodic representation are exactly fri_verify._schedule_periodic_boundaries's."""
    nt, nb = len(prog["outputs"]), len(boundaries)
    nper, nchal = prog["P"], prog["C"]
    L = _per_layout(W, nt, nb, nper, nchal)
    segs, chk_rows, T, n_used = _layout(W, points)

    rcl_base = [[a2.RC[r][lane] for r in range(_R)] + [0] * (_B - _R) for lane in range(_W)]
    actr_base = [1] * _R + [0] * (_B - _R)
    acta_base = [0] * _R + [1] + [0] * (_B - _R - 1)
    sholdl_base = [0] * (_R + 1) + [1] * (_B - _R - 1)
    ihold_base = [1] * _R + [0] + [1] * (_B - _R - 1)

    sup_link, sel = [], [[] for _ in range(2 * W)]
    chk_e, hold_rel = [], []
    pinvz, pl0 = [], []
    palpha = [[] for _ in range(nt + nb)]
    pper = [[] for _ in range(nper)]
    pchal = [[] for _ in range(nchal)]
    pbval = [[] for _ in range(nb)]
    pbid = [[] for _ in range(nb)]
    bnds = []

    for pi, point in enumerate(points):
        cur_idx, nxt_idx = _point_paths(point)
        roots = _roots_of(point, col_roots)
        starts = segs[pi]
        opens = point["cur"] + point["nxt"]
        for k, ((_v, _i, path), (start, nblk)) in enumerate(zip(opens, starts)):
            idx = cur_idx if k < W else nxt_idx
            col = k if k < W else k - W                  # which column's tree this path authenticates
            sup_link.append((start + nblk * _B - 1, 0))  # release the final block's row-15 link
            frow = start + (nblk - 1) * _B + _R          # the path's digest row
            sel[k].append((start, 1))                    # tie carry k to this path's leaf lane
            bnds.append((start, 0, a2.DOM_LEAF))         # rleaf frame of block 0
            for lane in range(2, _RATE):
                bnds.append((start, lane, 0))
            for lane in range(_CAP):
                bnds.append((start, _RATE + lane, a2.IV[lane]))
                bnds.append((frow, lane, int(roots[col][lane]) % F.P))   # final digest == column root
            bnds.append((start, _IACC, int(idx)))        # index accumulator: FS index in, fully consumed out
            bnds.append((frow, _IACC, 0))
        chk = chk_rows[pi]
        hold_rel.append((chk, 0))                        # carries released at the point boundary
        chk_e.append((chk, 1))
        pinvz.append((chk, int(point["invZ"]) % F.P))
        pl0.append((chk, int(point["layer0"]) % F.P))
        for j, a in enumerate(point["alphas"]):
            palpha[j].append((chk, int(a) % F.P))
        for j, v in enumerate(point["per"]):
            pper[j].append((chk, int(v) % F.P))
        for j, v in enumerate(point["chal"]):
            pchal[j].append((chk, int(v) % F.P))
        for j, (val, invd) in enumerate(point["bnd"]):
            pbval[j].append((chk, int(val) % F.P))
            pbid[j].append((chk, int(invd) % F.P))

    def P16(base, sparse=()):
        return {"period": _B, "base": base, "sparse": list(sparse)}

    def SP(entries):
        return {"period": 1, "base": [0], "sparse": list(entries)}

    per = [P16(rcl_base[lane]) for lane in range(_W)]
    per += [P16(actr_base), P16(acta_base), P16(sholdl_base, sup_link), P16(ihold_base, sup_link),
            SP(chk_e), {"period": 1, "base": [1], "sparse": hold_rel}]
    per += [SP(e) for e in sel]
    per += [SP(pinvz), SP(pl0)]
    per += [SP(e) for e in palpha] + [SP(e) for e in pper] + [SP(e) for e in pchal]
    per += [SP(e) for e in pbval] + [SP(e) for e in pbid]
    return per, bnds, T, segs, chk_rows, L


def _fill_trace(W, points, T, segs, chk_rows):
    """PROVER side: fill sponge snapshots + witness siblings/directions/index accumulators + the 2W opening
    carries. Carries are constant on each point's span and held (HOLD is only released at check rows) through
    whatever follows; padding rows are valid dummy hash blocks (the 16-periodic gates stay active there)."""
    WTOT = _CARRY + 2 * W
    rows = [[0] * WTOT for _ in range(T)]
    for pi, point in enumerate(points):
        opens = point["cur"] + point["nxt"]
        starts = segs[pi]
        vals = [int(o[0]) % F.P for o in opens]
        for k, ((val, index, path), (start, _nblk)) in enumerate(zip(opens, starts)):
            _fill_path(rows, start, val, index, path)
        for i in range(starts[0][0], chk_rows[pi] + 1):
            for k in range(2 * W):
                rows[i][_CARRY + k] = vals[k]
    n_used = chk_rows[-1] + 1 if chk_rows else 0
    state = [0] * _W
    for pb in range(n_used, T, _B):                      # padding: valid dummy chain from zeros
        snaps = _permute_snapshots(state)
        nxt = _junk_absorb(snaps[_R])
        _fill_block(rows, pb, snaps, nxt, (0,) * _CAP, 0, 0, 0)
        if n_used:                                       # carries stay constant through the padding
            for rib in range(_B):
                for k in range(2 * W):
                    rows[pb + rib][_CARRY + k] = rows[n_used - 1][_CARRY + k]
        state = nxt
    return rows


def _transitions(prog, W, boundaries, L):
    """Round + absorb-mux (membership, witness directions) + index-accumulator + holds + per-carry leaf selector
    + the generic composition check."""
    ops, consts, outputs = prog["ops"], prog["consts"], prog["outputs"]
    nt, nb = len(outputs), len(boundaries)
    nper, nchal = prog["P"], prog["C"]
    cons = []

    def round_c(i):
        def c(cur, nxt, per):
            t = [F.pw(F.add(cur[j], per[L["RCL"] + j]), a2.ALPHA) for j in range(_W)]
            mixed = 0
            for j in range(_W):
                mixed = F.add(mixed, F.mul(a2._MDS[i][j], t[j]))
            return F.mul(per[L["ACTR"]], F.sub(nxt[i], mixed))
        return c
    for i in range(_W):
        cons.append(round_c(i))

    def a_left(i):
        def c(cur, nxt, per):
            d = cur[_DIRW]
            want = F.add(F.mul(F.sub(1, d), cur[i]), F.mul(d, cur[_SIBW + i]))
            return F.mul(per[L["ACTA"]], F.sub(nxt[i], want))
        return c

    def a_right(i):
        def c(cur, nxt, per):
            d = cur[_DIRW]
            want = F.add(F.mul(F.sub(1, d), cur[_SIBW + i]), F.mul(d, cur[i]))
            return F.mul(per[L["ACTA"]], F.sub(nxt[_CAP + i], want))
        return c

    def a_cap(i):
        def c(cur, nxt, per):
            return F.mul(per[L["ACTA"]], F.sub(nxt[_RATE + i], a2.IV[i]))
        return c
    for i in range(_CAP):
        cons.append(a_left(i)); cons.append(a_right(i)); cons.append(a_cap(i))

    # direction bit boolean + IACC = 2·IACC' + d at every absorb (bits unique — see fri_verify)
    cons.append(lambda c, n, p: F.mul(p[L["ACTA"]], F.mul(c[_DIRW], F.sub(c[_DIRW], 1))))
    cons.append(lambda c, n, p: F.mul(p[L["ACTA"]], F.sub(c[_IACC], F.add(F.mul(2, n[_IACC]), c[_DIRW]))))

    def s_hold(i):
        def c(cur, nxt, per):
            return F.mul(per[L["SHOLDL"]], F.sub(nxt[i], cur[i]))
        return c
    for i in range(_W):
        cons.append(s_hold(i))
    cons.append(lambda c, n, p: F.mul(p[L["IHOLD"]], F.sub(n[_IACC], c[_IACC])))

    # carries held constant (HOLD released only at check rows)
    for k in range(2 * W):
        cons.append((lambda kk: lambda c, n, p: F.mul(p[L["HOLD"]], F.sub(n[_CARRY + kk], c[_CARRY + kk])))(k))
    # each carry equals its path's authenticated leaf value (lane 1 of the leaf block's row 0)
    for k in range(2 * W):
        cons.append((lambda kk: lambda c, n, p: F.mul(p[L["SEL"] + kk], F.sub(c[_CARRY + kk], c[1])))(k))

    def check_c(cur, nxt, per):
        cvals = [cur[_CARRY + k] for k in range(W)]
        nvals = [cur[_CARRY + W + k] for k in range(W)]
        pvals = [per[L["PPER"] + i] for i in range(nper)]
        chvals = [per[L["PCHAL"] + i] for i in range(nchal)]
        t = [0] * len(ops)
        for i, (op, a, bb) in enumerate(ops):
            if op == CUR:
                t[i] = cvals[a]
            elif op == NXT:
                t[i] = nvals[a]
            elif op == PER:
                t[i] = pvals[a]
            elif op == CHAL:
                t[i] = chvals[a]
            elif op == CONST:
                t[i] = consts[a]
            elif op == ADD:
                t[i] = F.add(t[a], t[bb])
            elif op == SUB:
                t[i] = F.sub(t[a], t[bb])
            elif op == MUL:
                t[i] = F.mul(t[a], t[bb])
            else:  # POW
                t[i] = F.pw(t[a], bb)
        acc = 0
        for tt in range(nt):
            acc = F.add(acc, F.mul(per[L["PALPHA"] + tt], t[outputs[tt]]))
        cp = F.mul(acc, per[L["PINVZ"]])
        for bi, (_row, col, _val) in enumerate(boundaries):
            term = F.mul(F.mul(per[L["PALPHA"] + nt + bi], F.sub(cvals[col], per[L["PBVAL"] + bi])),
                         per[L["PBID"] + bi])
            cp = F.add(cp, term)
        return F.mul(per[L["CHK"]], F.sub(cp, per[L["PL0"]]))
    cons.append(check_c)
    return cons


def prove_comp(prog, W, boundaries, points, col_roots, num_queries=stark.NUM_QUERIES):
    """Prove a batch of composition spot-checks. `prog` = air_ir.build_program(transitions, W, nper, nchal);
    `boundaries` = [(row, col, val)]; each `points[i]` carries the opened columns (val,index,path) at the cur and
    nxt rows plus the PUBLIC per/chal/alpha/invZ/boundary/layer0 values at that point — and optionally its own
    `roots` (K→1: points from different inner proofs authenticate against different column roots). `col_roots`
    is the shared/default root set. Returns (proof, public)."""
    per, bnds, T, segs, _chk, L = _schedule(prog, W, boundaries, points, col_roots)
    rows = _fill_trace(W, points, T, segs, _chk)
    proof = stark.prove(rows, _transitions(prog, W, boundaries, L), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries, backend=backend.ALGHASH2)
    public = {"col_roots": [[int(v) % F.P for v in r] for r in col_roots] if col_roots else None,
              "points_public": [_point_public(p, W) for p in points], "num_queries": num_queries,
              "path_len": len(points[0]["cur"][0][2]) if points else 0}
    return proof, public


def _point_public(point, W):
    """The PUBLIC half of a spot-check point — everything except the witness openings/paths."""
    pp = {"cur_index": point["cur"][0][1], "nxt_index": point["nxt"][0][1],
          "per": [int(v) % F.P for v in point["per"]], "chal": [int(v) % F.P for v in point["chal"]],
          "alphas": [int(v) % F.P for v in point["alphas"]], "invZ": int(point["invZ"]) % F.P,
          "bnd": [(int(v) % F.P, int(d) % F.P) for (v, d) in point["bnd"]],
          "layer0": int(point["layer0"]) % F.P,
          "path_len": len(point["cur"][0][2])}
    if "roots" in point:
        pp["roots"] = [[int(v) % F.P for v in r] for r in point["roots"]]
    return pp


def public_from_point_publics(points_public, col_roots, path_len, num_queries=stark.NUM_QUERIES):
    """Assemble a comp_verify `public` bundle a VERIFIER builds itself (no proving, no witness). `points_public`
    are `_point_public`-shaped dicts the verifier derived from an inner proof + Fiat-Shamir; `path_len` is the
    default tree depth (log2 of the committed leaf count) for points that don't carry their own. verify_comp
    against this bundle checks the recursion proof against the VERIFIER's schedule, so nothing in the
    composition statement is taken on the prover's word."""
    return {"col_roots": [[int(v) % F.P for v in r] for r in col_roots] if col_roots else None,
            "points_public": points_public, "num_queries": num_queries, "path_len": path_len}


def verify_comp(proof, prog, W, boundaries, public):
    """SOUND verification. Rebuilds the recursion-AIR schedule from the PUBLIC statement only (column roots +
    each point's public geometry/values), then verifies the recursion STARK against ITS schedule. The proof
    supplies only witness (openings, siblings, directions, sponge states). Returns (ok, reason)."""
    try:
        col_roots = public["col_roots"]
        # reconstruct the schedule-shaping "points" from the public halves (paths are witness -> length is fixed
        # by the tree depth = log2 of the leaf count, which is pinned by the committed geometry the verifier
        # already knows; carried per point, with the bundle-level path_len as the fallback).
        pts = []
        for pp in public["points_public"]:
            plen = pp.get("path_len", public.get("path_len"))
            cur = [(0, pp["cur_index"], [0] * plen) for _ in range(W)]
            nxt = [(0, pp["nxt_index"], [0] * plen) for _ in range(W)]
            pt = {"cur": cur, "nxt": nxt, "per": pp["per"], "chal": pp["chal"],
                  "alphas": pp["alphas"], "invZ": pp["invZ"], "bnd": pp["bnd"], "layer0": pp["layer0"]}
            if "roots" in pp:
                pt["roots"] = pp["roots"]
            pts.append(pt)
        per, bnds, _T, _segs, _chk, L = _schedule(prog, W, boundaries, pts, col_roots)
        return stark.verify(proof, _transitions(prog, W, boundaries, L), bnds, periodic=per, max_degree=8,
                            num_queries=public["num_queries"], backend=backend.ALGHASH2)
    except Exception as e:
        return False, f"malformed composition bundle: {e}"
