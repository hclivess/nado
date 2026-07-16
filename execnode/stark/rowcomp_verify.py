"""
Verifier-authoritative in-circuit COMPOSITION spot-check for ROW-COMMITTED proofs (doc/zk-recursion.md §5).
The row-mode sibling of comp_verify.py: an inner proof built with `stark.prove(..., row_commit=True)` commits
each LDE row under ONE recursion-Merkle leaf (`alghash2.rrow` = hashn-style multi-chunk absorption of the whole
row), so authenticating an opened query row takes ONE path per tree instead of one per column — which is what
makes the W=106 execution AIR recursable (2 rows × 2 trees = 4 paths per spot-check point, not 2·106).

In-circuit, each path is: `nc = ⌈(Wg+2)/RATE⌉` LEAF-ABSORPTION blocks — block 0 starts from the pinned hashn
frame [Wg+1, DOM_LEAF, v0..v5, IV] with v-lanes tied to the carry columns, each further chunk is absorbed at
the block's absorb row (rate lanes += the next carries, capacity lanes carry over) — followed by `plen` NODE
blocks identical to comp_verify's (witness sibling + witness direction bit muxed in, direction pinned to the
PUBLIC row index by the boolean + IACC bit-consumption constraints), ending in the digest row pinned to the
row-tree root. The 2W carry columns hold the opened row values across the point's span and the composition
check constraint (the air_ir SSA program — generic over the AIR, including LogUp challenges via PCHAL) runs on
them at the point's check row against the public layer-0 target.

Verifier-authoritative and SUCCINCT exactly as comp_verify: the verifier builds the whole schedule from the
public statement (indices FS-derived upstream, roots, alphas/challenges/invZ/boundary values, layer-0 seam);
all periodic columns are STRUCTURED (16-row block pattern + O(1) sparse rows per path); the proof carries only
witness. Supports per-point roots (K→1 across proofs) and two-phase groups (main + aux trees).
"""
from execnode.stark import alghash2 as a2, field as F, stark, backend, air_ir
from execnode.stark.recursion import _permute_snapshots
from execnode.stark.fri_verify import _fill_block, _junk_absorb, _B
from execnode.stark.air_ir import CUR, NXT, PER, CHAL, CONST, ADD, SUB, MUL, POW

_W, _R, _RATE, _CAP = a2.WIDTH, a2.ROUNDS, a2.RATE, a2.DIGEST

# trace column layout: 12 sponge lanes | 4 witness sibling lanes | DIRW IACC | 2W carries (W cur, W nxt)
_SIBW = _W
_DIRW, _IACC = _W + _CAP, _W + _CAP + 1
_CARRY = _W + _CAP + 2


def _groups_of(W, n_aux):
    """Column groups, one per row tree: [(start, end)] — main columns, then aux columns (two-phase)."""
    w_main = W - n_aux
    return [(0, w_main)] + ([(w_main, W)] if n_aux else [])


def _nchunks(Wg):
    """hashn absorb chunks for a width-Wg row: els = [Wg+1, DOM_LEAF, v0..v_{Wg-1}] → ⌈(Wg+2)/RATE⌉."""
    return (Wg + 2 + _RATE - 1) // _RATE


def _path_shapes(W, n_aux, plens):
    """The per-point path list — (kind, group_index, carry_base, Wg, nc, plen) in fill/schedule order:
    cur paths for every group, then nxt paths. `plens[g]` = tree depth of group g's row tree."""
    groups = _groups_of(W, n_aux)
    shapes = []
    for kind in range(2):                                # 0 = cur row, 1 = nxt row
        for gi, (s, e) in enumerate(groups):
            Wg = e - s
            shapes.append((kind, gi, kind * W + s, Wg, _nchunks(Wg), plens[gi]))
    return shapes


def _layout(W, n_aux, points):
    """Row landmarks. Per point: one path per (kind, group), each (nc + plen) 16-row blocks; the check row is
    the point's last row. Pure function of the PUBLIC geometry."""
    segs, chk_rows, row = [], [], 0
    for point in points:
        shapes = _path_shapes(W, n_aux, point["path_lens"])
        starts = []
        for (_k, _g, _cb, _Wg, nc, plen) in shapes:
            starts.append((row, nc + plen))
            row += (nc + plen) * _B
        segs.append(starts)
        chk_rows.append(row - 1)
    n_used = row
    T = 1
    while T < n_used + 1:
        T <<= 1
    return segs, chk_rows, T, n_used


def _per_layout(W, n_aux, nt, nb, nper, nchal):
    """Periodic column indices. LSEL[p] = first-block carry-tie gate per path shape p; LABS[p][c] = leaf-chunk-c
    absorb gate per path shape p (c = 1..nc-1) — flattened as LABS base + offsets."""
    shapes = _path_shapes(W, n_aux, [1] * len(_groups_of(W, n_aux)))   # plen irrelevant for the gate schema
    RCL = 0; ACTR = _W; ACTA = _W + 1; SHOLDL = _W + 2; IHOLD = _W + 3; CHK = _W + 4; HOLD = _W + 5
    LSEL = _W + 6
    n_shapes = len(shapes)
    labs_off, k = [], LSEL + n_shapes
    for (_k, _g, _cb, _Wg, nc, _pl) in shapes:
        labs_off.append(k); k += max(0, nc - 1)
    PINVZ = k
    PL0 = PINVZ + 1
    PALPHA = PL0 + 1
    PPER = PALPHA + nt + nb
    PCHAL = PPER + nper
    PBVAL = PCHAL + nchal
    PBID = PBVAL + nb
    NPER = PBID + nb
    return dict(RCL=RCL, ACTR=ACTR, ACTA=ACTA, SHOLDL=SHOLDL, IHOLD=IHOLD, CHK=CHK, HOLD=HOLD, LSEL=LSEL,
                LABS=labs_off, PINVZ=PINVZ, PL0=PL0, PALPHA=PALPHA, PPER=PPER, PCHAL=PCHAL, PBVAL=PBVAL,
                PBID=PBID, NPER=NPER)


def _schedule(prog, W, n_aux, boundaries, points):
    """Build periodic + boundaries PURELY from the public statement. Prover and verifier both call this and
    MUST agree. Every column is structured: 16-row base pattern + sparse rows."""
    nt, nb = len(prog["outputs"]), len(boundaries)
    nper, nchal = prog["P"], prog["C"]
    L = _per_layout(W, n_aux, nt, nb, nper, nchal)
    segs, chk_rows, T, n_used = _layout(W, n_aux, points)

    rcl_base = [[a2.RC[r][lane] for r in range(_R)] + [0] * (_B - _R) for lane in range(_W)]
    actr_base = [1] * _R + [0] * (_B - _R)
    acta_base = [0] * _R + [1] + [0] * (_B - _R - 1)
    sholdl_base = [0] * (_R + 1) + [1] * (_B - _R - 1)
    ihold_base = [1] * _R + [0] + [1] * (_B - _R - 1)

    n_shapes = len(_path_shapes(W, n_aux, [1] * len(_groups_of(W, n_aux))))
    sup_link, acta_del, ihold_add = [], [], []
    lsel = [[] for _ in range(n_shapes)]
    labs = [[] for _ in range(n_shapes)]                 # labs[p] = list of per-chunk entry lists
    chk_e, hold_rel, pinvz, pl0 = [], [], [], []
    palpha = [[] for _ in range(nt + nb)]
    pper = [[] for _ in range(nper)]
    pchal = [[] for _ in range(nchal)]
    pbval = [[] for _ in range(nb)]
    pbid = [[] for _ in range(nb)]
    bnds = []

    for pi, point in enumerate(points):
        shapes = _path_shapes(W, n_aux, point["path_lens"])
        starts = segs[pi]
        for p, ((kind, gi, cb, Wg, nc, plen), (start, nblk)) in enumerate(zip(shapes, starts)):
            idx = point["cur_index"] if kind == 0 else point["nxt_index"]
            root = point["roots"][gi]
            sup_link.append((start + nblk * _B - 1, 0))
            frow = start + (nblk - 1) * _B + _R
            # hashn frame of block 0: [Wg+1, DOM_LEAF, v0..v5, IV]; v-lanes tie to carries via LSEL
            bnds.append((start, 0, (Wg + 1) % F.P))
            bnds.append((start, 1, a2.DOM_LEAF))
            for lane in range(2 + min(Wg, _RATE - 2), _RATE):
                bnds.append((start, lane, 0))            # unused frame lanes of a narrow row
            for lane in range(_CAP):
                bnds.append((start, _RATE + lane, a2.IV[lane]))
                bnds.append((frow, lane, int(root[lane]) % F.P))
            bnds.append((start, _IACC, int(idx)))
            bnds.append((frow, _IACC, 0))
            lsel[p].append((start, 1))
            for c in range(1, nc):                       # leaf-chunk absorbs: gate on, node-mux off, IACC holds
                r8 = start + (c - 1) * _B + _R
                if len(labs[p]) < c:
                    labs[p].extend([[] for _ in range(c - len(labs[p]))])
                labs[p][c - 1].append((r8, 1))
                acta_del.append((r8, 0))
                ihold_add.append((r8, 1))
        chk = chk_rows[pi]
        hold_rel.append((chk, 0))
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

    per = [None] * L["NPER"]
    for lane in range(_W):
        per[L["RCL"] + lane] = P16(rcl_base[lane])
    per[L["ACTR"]] = P16(actr_base)
    per[L["ACTA"]] = P16(acta_base, acta_del)
    per[L["SHOLDL"]] = P16(sholdl_base, sup_link)
    per[L["IHOLD"]] = P16(ihold_base, ihold_add + sup_link)
    per[L["CHK"]] = SP(chk_e)
    per[L["HOLD"]] = {"period": 1, "base": [1], "sparse": hold_rel}
    shapes0 = _path_shapes(W, n_aux, [1] * len(_groups_of(W, n_aux)))
    for p in range(n_shapes):
        per[L["LSEL"] + p] = SP(lsel[p])
        nc = shapes0[p][4]
        for c in range(1, nc):
            ent = labs[p][c - 1] if c - 1 < len(labs[p]) else []
            per[L["LABS"][p] + (c - 1)] = SP(ent)
    per[L["PINVZ"]] = SP(pinvz); per[L["PL0"]] = SP(pl0)
    for j in range(nt + nb):
        per[L["PALPHA"] + j] = SP(palpha[j])
    for j in range(nper):
        per[L["PPER"] + j] = SP(pper[j])
    for j in range(nchal):
        per[L["PCHAL"] + j] = SP(pchal[j])
    for j in range(nb):
        per[L["PBVAL"] + j] = SP(pbval[j])
        per[L["PBID"] + j] = SP(pbid[j])
    return per, bnds, T, segs, chk_rows, L


def _node_blocks(digest, index, path):
    """Permutation-snapshot blocks for the NODE chain from a starting digest up `path`. Mirrors
    recursion._blocks_for without the leaf block. Returns (blocks, sibs, dirs, final_digest)."""
    blocks, sibs, dirs = [], [], []
    cur = tuple(int(v) % F.P for v in digest)
    idx = index
    for sib in path:
        d = idx & 1
        left, right = (sib, cur) if d else (cur, sib)
        init = [int(v) % F.P for v in left] + [int(v) % F.P for v in right] + list(a2.IV)
        blocks.append(_permute_snapshots(init))
        sibs.append(tuple(int(v) % F.P for v in sib)); dirs.append(d)
        cur = tuple(blocks[-1][_R][:_CAP]); idx >>= 1
    return blocks, sibs, dirs, cur


def _fill_row_path(rows, base, values, Wg, index, path):
    """PROVER: one row path = the hashn leaf-absorption chain (nc blocks) then the node chain (plen blocks)."""
    els = [Wg + 1, a2.DOM_LEAF] + [int(v) % F.P for v in values]
    nc = _nchunks(Wg)
    state = [0] * _RATE + list(a2.IV)
    for i, m in enumerate(els[:_RATE]):
        state[i] = F.add(state[i], m)
    leaf_snaps = []
    for c in range(nc):
        snaps = _permute_snapshots(state)
        leaf_snaps.append(snaps)
        state = list(snaps[_R])
        if c + 1 < nc:
            for i, m in enumerate(els[(c + 1) * _RATE:(c + 2) * _RATE]):
                state[i] = F.add(state[i], m)
    digest = tuple(leaf_snaps[-1][_R][:_CAP])
    nb_blocks, sibs, dirs, final = _node_blocks(digest, index, path)
    acc = int(index)
    for c in range(nc):                                  # leaf blocks: IACC held, no sibling/direction
        if c + 1 < nc:
            # rate lanes absorb the next chunk, capacity lanes carry over — the hashn absorb, row-9 state
            nxt_state = [F.add(leaf_snaps[c][_R][i],
                               els[(c + 1) * _RATE + i] if i < _RATE and (c + 1) * _RATE + i < len(els) else 0)
                         for i in range(_W)]
        elif nb_blocks:
            nxt_state = nb_blocks[0][0]                  # the first node block's init (mux absorb of sibling 0)
        else:
            nxt_state = _junk_absorb(leaf_snaps[c][_R])
        _fill_block(rows, base + c * _B, leaf_snaps[c], nxt_state,
                    sibs[0] if (c + 1 == nc and nb_blocks) else (0,) * _CAP,
                    dirs[0] if (c + 1 == nc and nb_blocks) else 0, acc,
                    ((acc - dirs[0]) >> 1) if (c + 1 == nc and nb_blocks) else acc)
    if nb_blocks:
        acc = (acc - dirs[0]) >> 1
    for bi in range(len(nb_blocks)):
        b0 = base + (nc + bi) * _B
        if bi + 1 < len(nb_blocks):
            d = dirs[bi + 1]
            nxt_acc = (acc - d) >> 1
            _fill_block(rows, b0, nb_blocks[bi], nb_blocks[bi + 1][0], sibs[bi + 1], d, acc, nxt_acc)
            acc = nxt_acc
        else:
            _fill_block(rows, b0, nb_blocks[bi], _junk_absorb(nb_blocks[bi][_R]), (0,) * _CAP, 0, acc, acc)
    return final


def _fill_trace(W, n_aux, points, T, segs, chk_rows):
    """PROVER side: sponge snapshots + witness siblings/directions/IACC + the 2W carries."""
    WTOT = _CARRY + 2 * W
    rows = [[0] * WTOT for _ in range(T)]
    groups = _groups_of(W, n_aux)
    for pi, point in enumerate(points):
        shapes = _path_shapes(W, n_aux, point["path_lens"])
        starts = segs[pi]
        vals = [int(v) % F.P for v in point["cur"]] + [int(v) % F.P for v in point["nxt"]]
        for (kind, gi, cb, Wg, nc, plen), (start, _nblk) in zip(shapes, starts):
            s, e = groups[gi]
            rowvals = (point["cur"] if kind == 0 else point["nxt"])[s:e]
            idx = point["cur_index"] if kind == 0 else point["nxt_index"]
            path = (point["cur_paths"] if kind == 0 else point["nxt_paths"])[gi]
            _fill_row_path(rows, start, rowvals, Wg, idx, path)
        for i in range(starts[0][0], chk_rows[pi] + 1):
            for k in range(2 * W):
                rows[i][_CARRY + k] = vals[k]
    n_used = chk_rows[-1] + 1 if chk_rows else 0
    state = [0] * _W
    for pb in range(n_used, T, _B):
        snaps = _permute_snapshots(state)
        nxt = _junk_absorb(snaps[_R])
        _fill_block(rows, pb, snaps, nxt, (0,) * _CAP, 0, 0, 0)
        if n_used:
            for rib in range(_B):
                for k in range(2 * W):
                    rows[pb + rib][_CARRY + k] = rows[n_used - 1][_CARRY + k]
        state = nxt
    return rows


def _transitions(prog, W, n_aux, boundaries, L):
    """Rounds + node-mux absorb + direction/IACC + holds + leaf-absorption ties + the composition check."""
    ops, consts, outputs = prog["ops"], prog["consts"], prog["outputs"]
    nt, nb = len(outputs), len(boundaries)
    nper, nchal = prog["P"], prog["C"]
    shapes = _path_shapes(W, n_aux, [1] * len(_groups_of(W, n_aux)))
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

    cons.append(lambda c, n, p: F.mul(p[L["ACTA"]], F.mul(c[_DIRW], F.sub(c[_DIRW], 1))))
    cons.append(lambda c, n, p: F.mul(p[L["ACTA"]], F.sub(c[_IACC], F.add(F.mul(2, n[_IACC]), c[_DIRW]))))

    def s_hold(i):
        def c(cur, nxt, per):
            return F.mul(per[L["SHOLDL"]], F.sub(nxt[i], cur[i]))
        return c
    for i in range(_W):
        cons.append(s_hold(i))
    cons.append(lambda c, n, p: F.mul(p[L["IHOLD"]], F.sub(n[_IACC], c[_IACC])))

    # first leaf block: frame v-lanes (2..7) == the path's carries
    for p, (kind, gi, cb, Wg, nc, _pl) in enumerate(shapes):
        for i in range(min(Wg, _RATE - 2)):
            cons.append((lambda pp, ii, base: lambda c, n, per:
                         F.mul(per[L["LSEL"] + pp], F.sub(c[2 + ii], c[_CARRY + base + ii])))(p, i, cb))
    # further chunks: rate lanes absorb the next carries (or nothing, past the row's width); capacity carries
    for p, (kind, gi, cb, Wg, nc, _pl) in enumerate(shapes):
        for c_i in range(1, nc):
            gate = L["LABS"][p] + (c_i - 1)
            for lane in range(_RATE):
                k = c_i * _RATE + lane - 2               # els index -> value index v_k
                if 0 <= k < Wg:
                    cons.append((lambda g, ll, base, kk: lambda c, n, per:
                                 F.mul(per[g], F.sub(n[ll], F.add(c[ll], c[_CARRY + base + kk]))))
                                (gate, lane, cb, k))
                else:
                    cons.append((lambda g, ll: lambda c, n, per:
                                 F.mul(per[g], F.sub(n[ll], c[ll])))(gate, lane))
            for i in range(_CAP):
                cons.append((lambda g, ii: lambda c, n, per:
                             F.mul(per[g], F.sub(n[_RATE + ii], c[_RATE + ii])))(gate, i))

    for k in range(2 * W):
        cons.append((lambda kk: lambda c, n, p: F.mul(p[L["HOLD"]], F.sub(n[_CARRY + kk], c[_CARRY + kk])))(k))

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
            else:
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


def prove_comp(prog, W, n_aux, boundaries, points, num_queries=stark.NUM_QUERIES):
    """Prove a batch of row-mode composition spot-checks. Each `points[i]` carries the opened cur/nxt ROWS
    (full W values), one Merkle path per row tree (`cur_paths`/`nxt_paths`), the public indices, the row-tree
    roots, path lengths, and the public per/chal/alpha/invZ/boundary/layer0 values. Returns (proof, public)."""
    per, bnds, T, segs, chk, L = _schedule(prog, W, n_aux, boundaries, points)
    rows = _fill_trace(W, n_aux, points, T, segs, chk)
    md = air_ir.gadget_max_degree(prog)   # headroom for the gated recompute of a degree-D inner AIR (W=106 → 16)
    proof = stark.prove(rows, _transitions(prog, W, n_aux, boundaries, L), bnds, periodic=per, max_degree=md,
                        num_queries=num_queries, backend=backend.ALGHASH2)
    public = {"points_public": [_point_public(p) for p in points], "num_queries": num_queries}
    return proof, public


def _point_public(point):
    """The PUBLIC half of a row-mode spot-check point — everything except the row values and paths."""
    return {"cur_index": point["cur_index"], "nxt_index": point["nxt_index"],
            "roots": [[int(v) % F.P for v in r] for r in point["roots"]],
            "path_lens": list(point["path_lens"]),
            "per": [int(v) % F.P for v in point["per"]], "chal": [int(v) % F.P for v in point["chal"]],
            "alphas": [int(v) % F.P for v in point["alphas"]], "invZ": int(point["invZ"]) % F.P,
            "bnd": [(int(v) % F.P, int(d) % F.P) for (v, d) in point["bnd"]],
            "layer0": int(point["layer0"]) % F.P}


def verify_comp(proof, prog, W, n_aux, boundaries, public):
    """SOUND verification. Rebuilds the schedule from the PUBLIC statement only, then verifies the recursion
    STARK against ITS schedule. Returns (ok, reason)."""
    try:
        pts = []
        for pp in public["points_public"]:
            pts.append({"cur_index": pp["cur_index"], "nxt_index": pp["nxt_index"], "roots": pp["roots"],
                        "path_lens": pp["path_lens"], "per": pp["per"], "chal": pp["chal"],
                        "alphas": pp["alphas"], "invZ": pp["invZ"], "bnd": pp["bnd"], "layer0": pp["layer0"]})
        per, bnds, _T, _segs, _chk, L = _schedule(prog, W, n_aux, boundaries, pts)
        md = air_ir.gadget_max_degree(prog)   # verifier derives the SAME max_degree from the same program
        return stark.verify(proof, _transitions(prog, W, n_aux, boundaries, L), bnds, periodic=per,
                            max_degree=md, num_queries=public["num_queries"], backend=backend.ALGHASH2)
    except Exception as e:
        return False, f"malformed row-composition bundle: {e}"
