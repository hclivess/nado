"""
Verifier-authoritative in-circuit FRI verifier + fold (doc/zk-recursion.md, doc/zk-glossary.md). It proves,
inside ONE recursion STARK, that a batch of FRI low-degree proofs are all valid — with the VERIFIER, not the
prover, in control of the entire public statement. That control is what makes it sound.

  * The public statement is a FRI proof's small public part: {roots, N, offset, blowup, final, pow}.
  * `_canonical_public` recomputes, from that public part ALONE, everything native fri.verify derives — the FRI
    geometry, the Fiat-Shamir fold challenges α, the query indices (drawn from the transcript, never trusted
    from the proof), the grinding proof-of-work, and the final-layer LOW-DEGREE test. It returns None on any
    failed check, so the prover cannot influence α / query positions / the low-degree verdict.
  * From that canonical schedule BOTH prover and verifier build the SAME recursion-AIR periodic + boundaries.
    The Merkle SIBLINGS and the path DIRECTION BITS are WITNESS columns — the directions are forced to be the
    binary decomposition of the (verifier-derived) leaf index by an in-trace accumulator: IACC starts pinned to
    the index, every absorb step enforces IACC = 2·IACC' + d with d boolean, and after the path's log2(N) steps
    IACC is pinned to 0. Since Σ d_k·2^k < N < P the equality holds over the integers, so the bits are unique.
  * `verify_fold` re-derives the schedule from the roots, builds periodic+boundaries ITSELF, and verifies the
    recursion STARK against ITS schedule at protocol query strength. The proof carries only the WITNESS
    (openings, siblings, directions, sponge states) — never the statement.

SUCCINCT: every periodic column is STRUCTURED (stark._per_evaluator) — a fixed 16-row block pattern (hash
blocks are padded from R+1=9 to 16 rows so the pattern's period divides the power-of-two trace length) plus
O(1) sparse rows per Merkle path (fold-row publics, per-path link releases). The outer verifier therefore does
NO O(T) periodic interpolation: its cost is O(queries · layers), independent of the recursion trace length.
"""
from execnode.stark import alghash2 as a2, field as F, stark, backend
from execnode.stark.transcript import Transcript
from execnode.stark.fri import _expected_layers, _coset_interpolate, GRIND_BITS, NUM_QUERIES
from execnode.stark.recursion import _permute_snapshots, _blocks_for, _next_pow2  # snapshot + path-block helpers

_W, _R, _RATE, _CAP = a2.WIDTH, a2.ROUNDS, a2.RATE, a2.DIGEST
# rows per hash block: _R round rows + 1 absorb/digest row + ≥1 hold/link row, padded up to a POWER OF TWO so
# the block pattern is a true _B-periodic column (_B | T, the succinct-periodic requirement). Derived from
# ROUNDS (was a hardcoded 16 for the old 8-round hash: next_pow2(8+2)=16; at ROUNDS=54, next_pow2(56)=64).
_B = _next_pow2(_R + 2)

# witness column layout: 12 sponge lanes | SIBW(4 sibling lanes) | DIRW IACC | CLO CHI FOLDED (carries)
_SIBW = _W                      # 12..15
_DIRW, _IACC = _W + _CAP, _W + _CAP + 1
_CLO, _CHI, _FOLD = _W + _CAP + 2, _W + _CAP + 3, _W + _CAP + 4
_WTOT = _W + _CAP + 5          # 21


def _canonical_public(pub, num_queries, mk_transcript=None):
    """VERIFIER SIDE. From a FRI proof's PUBLIC part only — {roots, N, offset, blowup, final, pow} — recompute
    the whole statement native fri.verify derives: geometry, the Fiat-Shamir fold challenges α, the query
    INDICES (drawn from the transcript, NOT trusted from the proof), the grinding PoW, and the final-layer
    LOW-DEGREE test. NO openings are read. Returns {queries:[[per-layer public...]], finals:[...]} or None if
    any native check fails. Each per-layer public tuple is (lo_pos, lo_len, hi_pos, hi_len, root, x, α, c2lo)
    with path LENGTHS derived from the (public) layer sizes.

    `mk_transcript` returns the transcript positioned exactly where fri.prove began. For a STANDALONE FRI proof
    that is a fresh Transcript('fri') (the default). For a FRI embedded in a STARK, fri.prove was handed the
    STARK's transcript (already absorbed the trace-column roots + drew the constraint challenges), so the caller
    must reconstruct THAT — verifier-authoritatively, from the STARK proof's public roots + AIR — and pass it."""
    b = backend.RECURSION
    try:
        N, off, blowup = pub["N"], pub["offset"], pub["blowup"]
        roots, final = pub["roots"], pub["final"]
        if not isinstance(N, int) or N < 2 or (N & (N - 1)):
            return None
        if not isinstance(blowup, int) or blowup < 2 or (blowup & (blowup - 1)):
            return None
        exp_layers = _expected_layers(N, blowup)
        if len(roots) != exp_layers or len(final) != (N >> exp_layers):
            return None
        t = mk_transcript() if mk_transcript is not None else Transcript("fri", backend=b)
        alphas, offs, sizes, o, n = [], [], [], off, N     # offsets+sizes only: points computed on demand as
        for r in roots:                                    # off·ω^pos, so NO O(N) domain is ever allocated
            t.absorb(r); alphas.append(t.challenge()); offs.append(o); sizes.append(n)
            o = F.mul(o, o); n //= 2
        t.absorb("final", *final)
        if not t.check_grind(pub.get("pow"), GRIND_BITS):
            return None
        coeffs = _coset_interpolate(final, o)
        deg_bound = max(1, len(final) // blowup)
        if any(c != 0 for c in coeffs[deg_bound:]):
            return None
        Lr = len(roots)
        out_queries, finals = [], []
        for _q in range(num_queries):
            idx = t.challenge_index(N)                  # FS-derived query index — the verifier chooses it
            a, steps, last_lo = idx, [], 0
            for L in range(Lr):
                nL = sizes[L]; half = nL // 2; a %= nL; lo = a % half
                plen = nL.bit_length() - 1              # rmerkle path length = log2(layer size)
                c2lo = True if L + 1 >= Lr else (lo < sizes[L + 1] // 2)
                x = F.mul(offs[L], F.pw(F.primitive_root_of_unity(nL), lo))
                steps.append((lo, plen, lo + half, plen, roots[L], x, alphas[L], c2lo))
                last_lo = lo; a = lo
            out_queries.append(steps); finals.append(final[last_lo])
        return {"queries": out_queries, "finals": finals}
    except Exception:
        return None


def _witness_of(fri_proof, num_queries, mk_transcript=None):
    """PROVER SIDE. Extract the WITNESS (opened values + Merkle sibling paths) aligned to the FS query indices,
    from a full FRI proof. Returns [[per-layer (lo_val, lo_path, hi_val, hi_path)]] (query-major) or None if the
    proof's declared indices disagree with Fiat-Shamir. `mk_transcript` as in _canonical_public."""
    b = backend.RECURSION
    N, off, blowup = fri_proof["N"], fri_proof["offset"], fri_proof["blowup"]
    roots, final, queries = fri_proof["roots"], fri_proof["final"], fri_proof["queries"]
    t = mk_transcript() if mk_transcript is not None else Transcript("fri", backend=b)
    o = off
    for r in roots:
        t.absorb(r); t.challenge(); o = F.mul(o, o)
    t.absorb("final", *final)
    t.check_grind(fri_proof.get("pow"), GRIND_BITS)
    Lr = len(roots)
    out = []
    for q in queries:
        idx = t.challenge_index(N)
        if idx != q.get("idx"):
            return None
        steps = []
        for L in range(Lr):
            s = q["steps"][L]
            steps.append((s["lo"], s["lo_path"], s["hi"], s["hi_path"]))
        out.append(steps)
    return out


def _layout(schedule):
    """Row landmarks for the concatenated per-query, per-layer, two-path (lo,hi) trace — a pure function of the
    PUBLIC path lengths, so prover and verifier agree. Public step = (lo_pos, lo_len, hi_pos, hi_len, root, x,
    α, c2lo). Returns (segments, T, n_used, query_end); segment = (lo_start, hi_start, fold_row, n_lo, n_hi)."""
    segs, query_end, row = [], [], 0
    for qi, steps in enumerate(schedule["queries"]):
        for j, st in enumerate(steps):
            n_lo, n_hi = st[1] + 1, st[3] + 1                    # rleaf block + one per path level
            lo_start = row; row += n_lo * _B
            hi_start = row; row += n_hi * _B
            fold_row = row - 1
            segs.append((lo_start, hi_start, fold_row, n_lo, n_hi))
            query_end.append(j == len(steps) - 1)
    n_used = row
    T = 1
    while T < n_used + 1:
        T <<= 1
    return segs, T, n_used, query_end


# periodic column indices (all verifier-derivable, all STRUCTURED; siblings + directions are WITNESS)
_RCL = 0; _ACTR = _W; _ACTA = _W + 1; _SHOLDL = _W + 2; _IHOLD = _W + 3
_SELLO = _W + 4; _SELHI = _W + 5; _HOLD = _W + 6; _FOLDAT = _W + 7
_PX = _W + 8; _PAL = _W + 9; _CHLO = _W + 10; _CHHI = _W + 11; _FINAT = _W + 12; _PFIN = _W + 13
_NPER = _W + 14


def _schedule_periodic_boundaries(schedule, seam_lo0=None):
    """Build the recursion-AIR periodic + boundaries PURELY from the canonical schedule (no witness). Prover and
    verifier both call this and MUST get identical output — that is what makes the verifier authoritative.

    `seam_lo0` (one value per query, in schedule order) pins each query's LAYER-0 lo opening as a public
    boundary on the CLO carry. SELLO already ties CLO to the authenticated leaf, so this forces the pinned
    value to BE the committed layer-0 value — the seam that lets a caller (recursive_verify) hand the same
    value to the composition half knowing a lie cannot satisfy the in-circuit membership. Callers that only
    want the low-degree statement pass None (no extra boundaries).

    Block anatomy (16 rows): rows 0..7 rounds (ACTR), row 8 = permuted digest + ABSORB into row 9 (ACTA, using
    the witness sibling + witness direction bit), rows 9..14 sponge hold, row 15 links to the next block — the
    link (SHOLDL sponge lanes, IHOLD the index accumulator) is sparse-RELEASED at each path's final block so
    paths don't bleed into each other. Every column is a structured {period:16 or 1, base, sparse} dict, so the
    verifier evaluates it in O(1) per query point — no O(T) interpolation anywhere."""
    segs, T, n_used, query_end = _layout(schedule)
    flat = [st for steps in schedule["queries"] for st in steps]
    flat_final = [schedule["finals"][qi] for qi, steps in enumerate(schedule["queries"]) for _ in steps]

    rcl_base = [[a2.RC[r][lane] for r in range(_R)] + [0] * (_B - _R) for lane in range(_W)]
    actr_base = [1] * _R + [0] * (_B - _R)
    acta_base = [0] * _R + [1] + [0] * (_B - _R - 1)
    sholdl_base = [0] * (_R + 1) + [1] * (_B - _R - 1)           # rows 9..15 (15 = the inter-block link)
    ihold_base = [1] * _R + [0] + [1] * (_B - _R - 1)            # everywhere but the absorb row 8

    qlens = [len(steps) for steps in schedule["queries"]]
    query_first = []                                             # segment si is a query's LAYER-0 segment?
    for ln in qlens:
        query_first += [True] + [False] * (ln - 1)
    flat_qi = [q for q, ln in enumerate(qlens) for _ in range(ln)]

    sup_link, sello, selhi, hold_rel = [], [], [], []
    foldat, px, pal, chlo, chhi, finat, pfin = [], [], [], [], [], [], []
    bnds = []
    for si, (lo_start, hi_start, fold_row, n_lo, n_hi) in enumerate(segs):
        st = flat[si]
        if seam_lo0 is not None and query_first[si]:
            bnds.append((lo_start, _CLO, int(seam_lo0[flat_qi[si]]) % F.P))
        lo_pos, hi_pos, root, x, alpha, c2lo = st[0], st[2], st[4], st[5], st[6], st[7]
        for start, nblk, pos in ((lo_start, n_lo, lo_pos), (hi_start, n_hi, hi_pos)):
            sup_link.append((start + nblk * _B - 1, 0))          # release the final block's row-15 link
            frow = start + (nblk - 1) * _B + _R                  # the path's digest row
            bnds.append((start, 0, a2.DOM_LEAF))                 # rleaf frame of block 0
            for lane in range(2, _RATE):
                bnds.append((start, lane, 0))
            for lane in range(_CAP):
                bnds.append((start, _RATE + lane, a2.IV[lane]))
                bnds.append((frow, lane, int(root[lane]) % F.P))  # final digest == layer root
            bnds.append((start, _IACC, int(pos)))                # index accumulator: starts at the FS index...
            bnds.append((frow, _IACC, 0))                        # ...and is fully consumed — bits are unique
        sello.append((lo_start, 1)); selhi.append((hi_start, 1))
        hold_rel.append((fold_row, 0))
        foldat.append((fold_row, 1))
        px.append((fold_row, int(x) % F.P)); pal.append((fold_row, int(alpha) % F.P))
        if query_end[si]:
            finat.append((fold_row, 1)); pfin.append((fold_row, int(flat_final[si]) % F.P))
        else:
            (chlo if c2lo else chhi).append((fold_row, 1))

    def P16(base, sparse=()):
        return {"period": _B, "base": base, "sparse": list(sparse)}

    def SP(entries):
        return {"period": 1, "base": [0], "sparse": list(entries)}

    per = [P16(rcl_base[lane]) for lane in range(_W)]
    per += [P16(actr_base), P16(acta_base), P16(sholdl_base, sup_link), P16(ihold_base, sup_link),
            SP(sello), SP(selhi), {"period": 1, "base": [1], "sparse": hold_rel}, SP(foldat),
            SP(px), SP(pal), SP(chlo), SP(chhi), SP(finat), SP(pfin)]
    return per, bnds, T, segs, query_end


def _fill_block(rows, base, snaps, nxt_state, sib, d, acc_in, acc_out):
    """Write one 16-row hash block: 9 permutation snapshots, the witness sibling + direction at the absorb row,
    then the absorbed state held through rows 9..15. IACC carries acc_in through row 8 and acc_out after."""
    for rib in range(_R + 1):
        i = base + rib
        for lane in range(_W):
            rows[i][lane] = int(snaps[rib][lane]) % F.P
        rows[i][_IACC] = acc_in
    r8 = base + _R
    for lane in range(_CAP):
        rows[r8][_SIBW + lane] = int(sib[lane]) % F.P
    rows[r8][_DIRW] = d
    for rib in range(_R + 1, _B):
        i = base + rib
        for lane in range(_W):
            rows[i][lane] = int(nxt_state[lane]) % F.P
        rows[i][_IACC] = acc_out


def _junk_absorb(state):
    """The absorbed state after a zero-sibling, direction-0 absorb — what a path's FINAL block (and padding
    blocks) hold on rows 9..15: [digest lanes, zeros, IV]. Dead lanes; the row-15 link is released there."""
    return [int(state[i]) % F.P for i in range(_CAP)] + [0] * _CAP + list(a2.IV)


def _fill_path(rows, base, leaf_val, index, path):
    """PROVER: one Merkle path = len(path)+1 blocks. Directions/IACC follow the REAL index bits (the schedule's
    boundaries pin IACC to the index at the start and 0 at the digest row, forcing exactly these bits)."""
    lb, sibs, dirs, _cur = _blocks_for(leaf_val, index, path)
    nblk = len(lb)
    acc = int(index)
    for bblk in range(nblk):
        if bblk + 1 < nblk:
            d = dirs[bblk]
            nxt_acc = (acc - d) >> 1
            _fill_block(rows, base + bblk * _B, lb[bblk], lb[bblk + 1][0], sibs[bblk], d, acc, nxt_acc)
            acc = nxt_acc
        else:
            _fill_block(rows, base + bblk * _B, lb[bblk], _junk_absorb(lb[bblk][_R]), (0,) * _CAP, 0, acc, acc)


def _fill_trace(pub_flat, wit_flat, T, segs):
    """PROVER side: fill the witness trace (sponge snapshots + witness siblings/directions + index accumulators
    + carries). `pub_flat[si]` = (lo_pos, lo_len, hi_pos, hi_len, root, x, α, c2lo); `wit_flat[si]` =
    (lo_val, lo_path, hi_val, hi_path). Padding rows continue as inert dummy hash blocks (the 16-periodic round
    and absorb gates stay active through the padding, so it must be REAL permutation arithmetic)."""
    rows = [[0] * _WTOT for _ in range(T)]
    INV2 = F.inv(2)
    for si, (lo_start, hi_start, fold_row, n_lo, n_hi) in enumerate(segs):
        lo_pos, _ll, hi_pos, _hl, root, x, alpha, _c2 = pub_flat[si]
        lo_val, lo_path, hi_val, hi_path = wit_flat[si]
        fv = F.add(F.mul(F.add(lo_val, hi_val), INV2),
                   F.mul(alpha, F.mul(F.sub(lo_val, hi_val), F.mul(INV2, F.inv(x)))))
        _fill_path(rows, lo_start, lo_val, lo_pos, lo_path)
        _fill_path(rows, hi_start, hi_val, hi_pos, hi_path)
        for i in range(lo_start, fold_row + 1):
            rows[i][_CLO] = int(lo_val) % F.P
            rows[i][_CHI] = int(hi_val) % F.P
            rows[i][_FOLD] = fv % F.P
    n_used = segs[-1][2] + 1 if segs else 0
    state = [0] * _W
    for pb in range(n_used, T, _B):                              # padding: valid dummy chain from zeros
        snaps = _permute_snapshots(state)
        nxt = _junk_absorb(snaps[_R])
        _fill_block(rows, pb, snaps, nxt, (0,) * _CAP, 0, 0, 0)
        if n_used:                                               # carries stay constant through the padding
            for rib in range(_B):
                rows[pb + rib][_CLO] = rows[n_used - 1][_CLO]
                rows[pb + rib][_CHI] = rows[n_used - 1][_CHI]
                rows[pb + rib][_FOLD] = rows[n_used - 1][_FOLD]
        state = nxt
    return rows


def _transitions():
    cons = []

    def round_c(i):
        def c(cur, nxt, per):
            t = [F.pw(F.add(cur[j], per[_RCL + j]), a2.ALPHA) for j in range(_W)]
            mixed = 0
            for j in range(_W):
                mixed = F.add(mixed, F.mul(a2._MDS[i][j], t[j]))
            return F.mul(per[_ACTR], F.sub(nxt[i], mixed))
        return c
    for i in range(_W):
        cons.append(round_c(i))

    # absorb-mux reads the sibling AND the direction bit from WITNESS columns; the direction is forced to the
    # index's binary decomposition by the boolean + accumulator constraints below
    def a_left(i):
        def c(cur, nxt, per):
            d = cur[_DIRW]
            want = F.add(F.mul(F.sub(1, d), cur[i]), F.mul(d, cur[_SIBW + i]))
            return F.mul(per[_ACTA], F.sub(nxt[i], want))
        return c

    def a_right(i):
        def c(cur, nxt, per):
            d = cur[_DIRW]
            want = F.add(F.mul(F.sub(1, d), cur[_SIBW + i]), F.mul(d, cur[i]))
            return F.mul(per[_ACTA], F.sub(nxt[_CAP + i], want))
        return c

    def a_cap(i):
        def c(cur, nxt, per):
            return F.mul(per[_ACTA], F.sub(nxt[_RATE + i], a2.IV[i]))
        return c
    for i in range(_CAP):
        cons.append(a_left(i)); cons.append(a_right(i)); cons.append(a_cap(i))

    # direction bit boolean + index-accumulator bit consumption: IACC = 2·IACC' + d at every absorb
    cons.append(lambda c, n, p: F.mul(p[_ACTA], F.mul(c[_DIRW], F.sub(c[_DIRW], 1))))
    cons.append(lambda c, n, p: F.mul(p[_ACTA], F.sub(c[_IACC], F.add(F.mul(2, n[_IACC]), c[_DIRW]))))

    # sponge lanes hold rows 9..15 (row 15 = the inter-block link, released at path-final blocks); IACC holds
    # everywhere except the absorb row (same release)
    def s_hold(i):
        def c(cur, nxt, per):
            return F.mul(per[_SHOLDL], F.sub(nxt[i], cur[i]))
        return c
    for i in range(_W):
        cons.append(s_hold(i))
    cons.append(lambda c, n, p: F.mul(p[_IHOLD], F.sub(n[_IACC], c[_IACC])))

    cons.append(lambda c, n, p: F.mul(p[_HOLD], F.sub(n[_CLO], c[_CLO])))
    cons.append(lambda c, n, p: F.mul(p[_HOLD], F.sub(n[_CHI], c[_CHI])))
    cons.append(lambda c, n, p: F.mul(p[_HOLD], F.sub(n[_FOLD], c[_FOLD])))
    cons.append(lambda c, n, p: F.mul(p[_SELLO], F.sub(c[_CLO], c[1])))
    cons.append(lambda c, n, p: F.mul(p[_SELHI], F.sub(c[_CHI], c[1])))

    def fold_c(c, n, p):
        lhs = F.mul(F.mul(2, p[_PX]), c[_FOLD])
        rhs = F.add(F.mul(p[_PX], F.add(c[_CLO], c[_CHI])), F.mul(p[_PAL], F.sub(c[_CLO], c[_CHI])))
        return F.mul(p[_FOLDAT], F.sub(lhs, rhs))
    cons.append(fold_c)
    cons.append(lambda c, n, p: F.mul(p[_CHLO], F.sub(n[_CLO], c[_FOLD])))
    cons.append(lambda c, n, p: F.mul(p[_CHHI], F.sub(n[_CHI], c[_FOLD])))
    cons.append(lambda c, n, p: F.mul(p[_FINAT], F.sub(c[_FOLD], p[_PFIN])))
    return cons


def prove_fold(fri_proofs, num_queries_inner=None, num_queries_outer=64, mk_transcripts=None, out_backend=None):
    """Fold REAL fri.prove(backend=RECURSION) proofs into ONE recursion proof. `num_queries_inner` must equal
    each inner proof's query count (defaults to len(queries) of the first). The outer proof is proven at
    `num_queries_outer` (protocol strength). `mk_transcripts[i]` (optional) rebuilds proof i's FRI-start
    transcript — needed when the inner FRI is embedded in a STARK; None = standalone (fresh 'fri' transcript).

    `out_backend` sets the HASH the fold's OWN proof commits under (default ALGHASH2). Pass backend.RECURSION
    to make the fold proof itself rleaf/rnode-committed — i.e. DEPTH-READY: its own FRI is then exactly the
    shape prove_fold folds, so this proof can be an inner proof of ANOTHER fold (recursion_depth.fold_tree).
    Returns (recursion_proof, publics)."""
    publics = [{"roots": p["roots"], "N": p["N"], "offset": p["offset"], "blowup": p["blowup"],
                "final": p["final"], "pow": p.get("pow")} for p in fri_proofs]
    if num_queries_inner is None:
        num_queries_inner = len(fri_proofs[0]["queries"])
    merged = {"queries": [], "finals": []}
    wit_flat, seam_lo0 = [], []
    for i, (p, pub) in enumerate(zip(fri_proofs, publics)):
        mk = mk_transcripts[i] if mk_transcripts else None
        c = _canonical_public(pub, num_queries_inner, mk)  # public schedule (same as the verifier's)
        w = _witness_of(p, num_queries_inner, mk)          # openings + paths, aligned to FS indices
        if c is None or w is None:
            raise ValueError("an inner FRI proof failed native verification — refusing to fold it")
        merged["queries"] += c["queries"]; merged["finals"] += c["finals"]
        for steps in w:
            wit_flat += steps
            seam_lo0.append(int(steps[0][0]) % F.P)        # each query's layer-0 lo opening (the seam value)
    per, bnds, T, segs, _qe = _schedule_periodic_boundaries(merged, seam_lo0)
    pub_flat = [st for steps in merged["queries"] for st in steps]
    rows = _fill_trace(pub_flat, wit_flat, T, segs)
    proof = stark.prove(rows, _transitions(), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries_outer, backend=out_backend or backend.ALGHASH2)
    return proof, {"publics": publics, "num_queries_inner": num_queries_inner,
                   "num_queries_outer": num_queries_outer, "seam_lo0": seam_lo0}


def fold_air(public, mk_transcripts=None, expect_inner=None):
    """Reconstruct the fold proof's AIR — (transitions, boundaries, periodic) — from its PUBLIC statement alone,
    exactly as verify_fold rebuilds it (verifier-authoritative: the schedule comes from the inner proofs' public
    parts + Fiat-Shamir, never the prover's word). This is what lets a DEPTH level authoritatively RE-VERIFY the
    fold proof via recursive_verify (recursion_authdepth): fold proof + this AIR → recursive_verify.prove.
    Returns (transitions, boundaries, periodic) or raises. Max_degree is the fixed fold-AIR 8."""
    nqi = expect_inner if expect_inner is not None else NUM_QUERIES
    merged = {"queries": [], "finals": []}
    for i, pub in enumerate(public["publics"]):
        mk = mk_transcripts[i] if mk_transcripts else None
        c = _canonical_public(pub, nqi, mk)
        if c is None:
            raise ValueError("an inner FRI public statement failed native verification")
        merged["queries"] += c["queries"]; merged["finals"] += c["finals"]
    seam = public.get("seam_lo0")
    if seam is not None and len(seam) != len(merged["queries"]):
        raise ValueError("seam value count != query count")
    per, bnds, _T, _segs, _qe = _schedule_periodic_boundaries(merged, seam)
    return _transitions(), bnds, per


def verify_fold(recursion_proof, public, mk_transcripts=None, expect_inner=None, expect_outer=None,
                out_backend=None):
    """SOUND verification. `public` = the {publics, num_queries_inner, num_queries_outer} from prove_fold.
    Re-derives the canonical schedule from each inner proof's PUBLIC part (recomputing FS challenges, checking
    grind + final-layer low-degree + geometry), builds periodic+boundaries ITSELF, and verifies the recursion
    STARK against ITS schedule. `mk_transcripts` as in prove_fold.

    The number of FRI spot-checks IS the soundness, so the query strength is the VERIFIER'S policy, never read
    from the prover's bundle: `expect_inner`/`expect_outer` default to the protocol constant (fri.NUM_QUERIES)
    and drive BOTH the schedule reconstruction and stark.verify. A prover that folded at a weaker count fails
    because the verifier rebuilds the schedule at full strength and the committed trace cannot match; the
    bundle's declared counts are cross-checked only for a clearer early error. A count < 1 is always rejected.
    A caller with a non-default policy (e.g. a fast test, or the settlement seam pinning to its segment count)
    passes it explicitly. Returns (ok, reason)."""
    try:
        nqi = expect_inner if expect_inner is not None else NUM_QUERIES
        nqo = expect_outer if expect_outer is not None else NUM_QUERIES
        if not isinstance(nqi, int) or not isinstance(nqo, int) or nqi < 1 or nqo < 1:
            return False, "fold query count must be a positive integer"
        dnqi, dnqo = public.get("num_queries_inner"), public.get("num_queries_outer")
        if dnqi is not None and dnqi != nqi:
            return False, f"declared inner query count {dnqi} != verifier policy {nqi}"
        if dnqo is not None and dnqo != nqo:
            return False, f"declared outer query count {dnqo} != verifier policy {nqo}"
        merged = {"queries": [], "finals": []}
        for i, pub in enumerate(public["publics"]):
            mk = mk_transcripts[i] if mk_transcripts else None
            c = _canonical_public(pub, nqi, mk)         # NATIVE checks + FS re-derivation, from public only
            if c is None:
                return False, "an inner proof's public statement failed native FRI verification"
            merged["queries"] += c["queries"]; merged["finals"] += c["finals"]
        seam = public.get("seam_lo0")                   # layer-0 seam values: in-circuit membership validates
        if seam is not None and len(seam) != len(merged["queries"]):        # them, so a lie cannot verify
            return False, "seam value count != query count"
        per, bnds, _T, _segs, _qe = _schedule_periodic_boundaries(merged, seam)  # VERIFIER builds the schedule
        return stark.verify(recursion_proof, _transitions(), bnds, periodic=per, max_degree=8,
                            num_queries=nqo, backend=out_backend or backend.ALGHASH2)
    except Exception as e:
        return False, f"malformed recursion bundle: {e}"
