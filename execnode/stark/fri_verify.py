"""
Verifier-authoritative in-circuit FRI verifier + fold (doc/zk-recursion.md, doc/zk-glossary.md). It proves,
inside ONE recursion STARK, that a batch of FRI low-degree proofs are all valid — with the VERIFIER, not the
prover, in control of the entire public statement. That control is what makes it sound.

  * The public statement is a FRI proof's small public part: {roots, N, offset, blowup, final, pow}.
  * `_canonical_public` recomputes, from that public part ALONE, everything native fri.verify derives — the FRI
    geometry, the Fiat-Shamir fold challenges α, the query indices (drawn from the transcript, never trusted
    from the proof), the grinding proof-of-work, and the final-layer LOW-DEGREE test. It returns None on any
    failed check, so the prover cannot influence α / query positions / the low-degree verdict.
  * From that canonical schedule BOTH prover and verifier build the SAME recursion-AIR periodic + boundaries
    (round constants, path direction bits, fold challenges, per-step selectors, roots-as-boundaries, finals-as-
    boundaries). The Merkle SIBLINGS are WITNESS columns, not periodic — the verifier never needs the prover's
    paths, and a prover cannot swap them without breaking the membership hash-to-root.
  * `verify_fold` re-derives the schedule from the roots, builds periodic+boundaries ITSELF, and verifies the
    recursion STARK against ITS schedule at protocol query strength. The proof carries only the WITNESS
    (openings, siblings, sponge states) — never the statement.

A prover controls only the witness; the entire public statement is verifier-derived and Fiat-Shamir-bound to
the committed roots. (Truly O(1) verification is a further optimization — the periodic is materialized O(T)
here; this module secures SOUNDNESS. Binding these FRI roots to a settled state root is the STARK composition
spot-check + the settlement seam, tracked separately.)
"""
from execnode.stark import alghash2 as a2, field as F, stark, backend
from execnode.stark.transcript import Transcript
from execnode.stark.fri import _expected_layers, _coset_interpolate, GRIND_BITS
from execnode.stark.recursion import _permute_snapshots, _blocks_for  # snapshot + path-block helpers

_W, _R, _RATE, _CAP = a2.WIDTH, a2.ROUNDS, a2.RATE, a2.DIGEST

# column layout: 12 sponge lanes | SIBW(4 witness sibling lanes) | CLO CHI FOLDED (per-step carries)
_SIBW = _W                      # 12..15
_CLO, _CHI, _FOLD = _W + _CAP, _W + _CAP + 1, _W + _CAP + 2
_WTOT = _W + _CAP + 3          # 19


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
        alphas, doms, o, n = [], [], off, N
        for r in roots:
            t.absorb(r); alphas.append(t.challenge()); doms.append(F.domain(n, o)); o = F.mul(o, o); n //= 2
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
                dom = doms[L]; nL = len(dom); half = nL // 2; a %= nL; lo = a % half
                plen = nL.bit_length() - 1              # rmerkle path length = log2(layer size)
                c2lo = True if L + 1 >= Lr else (lo < len(doms[L + 1]) // 2)
                steps.append((lo, plen, lo + half, plen, roots[L], dom[lo], alphas[L], c2lo))
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
    BR = _R + 1
    segs, query_end, row = [], [], 0
    for qi, steps in enumerate(schedule["queries"]):
        for j, st in enumerate(steps):
            n_lo, n_hi = st[1] + 1, st[3] + 1                    # rleaf block + one per path level
            lo_start = row; row += n_lo * BR
            hi_start = row; row += n_hi * BR
            fold_row = row - 1
            segs.append((lo_start, hi_start, fold_row, n_lo, n_hi))
            query_end.append(j == len(steps) - 1)
    n_used = row
    T = 1
    while T < n_used + 1:
        T <<= 1
    return segs, T, n_used, query_end


# periodic column indices (all verifier-derivable; NO siblings here — those are witness)
_RCL = 0; _ACTR = _W; _ACTA = _W + 1; _DIR = _W + 2
_SELLO = _W + 3; _SELHI = _W + 4; _HOLD = _W + 5; _FOLDAT = _W + 6
_PX = _W + 7; _PAL = _W + 8; _CHLO = _W + 9; _CHHI = _W + 10; _FINAT = _W + 11; _PFIN = _W + 12
_NPER = _W + 13


def _schedule_periodic_boundaries(schedule):
    """Build the recursion-AIR periodic + boundaries PURELY from the canonical schedule (no witness). Prover and
    verifier both call this and MUST get identical output — that is what makes the verifier authoritative."""
    BR = _R + 1
    segs, T, n_used, query_end = _layout(schedule)
    flat = [st for steps in schedule["queries"] for st in steps]
    flat_final = [schedule["finals"][qi] for qi, steps in enumerate(schedule["queries"]) for _ in steps]
    per = [[0] * T for _ in range(_NPER)]
    bnds = []

    def path_periodic(base, index, nblk):
        # direction bits come from the leaf INDEX (public) — bit k is the direction at level k
        idx = index
        for bblk in range(nblk):
            for rib in range(BR):
                i = base + bblk * BR + rib
                if rib < _R:
                    for lane in range(_W):
                        per[_RCL + lane][i] = a2.RC[rib][lane]
                    per[_ACTR][i] = 1
                elif bblk + 1 < nblk:
                    per[_ACTA][i] = 1
                    per[_DIR][i] = idx & 1
                    idx >>= 1

    for si, (lo_start, hi_start, fold_row, n_lo, n_hi) in enumerate(segs):
        st = flat[si]
        lo_pos, hi_pos, root, x, alpha, c2lo = st[0], st[2], st[4], st[5], st[6], st[7]
        path_periodic(lo_start, lo_pos, n_lo)
        path_periodic(hi_start, hi_pos, n_hi)
        per[_SELLO][lo_start] = 1
        per[_SELHI][hi_start] = 1
        per[_FOLDAT][fold_row] = 1
        per[_PX][fold_row] = int(x) % F.P
        per[_PAL][fold_row] = int(alpha) % F.P
        for i in range(lo_start, fold_row):
            per[_HOLD][i] = 1
        if query_end[si]:
            per[_FINAT][fold_row] = 1
            per[_PFIN][fold_row] = int(flat_final[si]) % F.P
        else:
            per[_CHLO if c2lo else _CHHI][fold_row] = 1
        # boundaries: each path's block-0 rleaf frame (leaf VALUE stays witness) + final digest == root
        for start in (lo_start, hi_start):
            bnds.append((start, 0, a2.DOM_LEAF))
            for lane in range(2, _RATE):
                bnds.append((start, lane, 0))
            for lane in range(_CAP):
                bnds.append((start, _RATE + lane, a2.IV[lane]))
        for last_start in (lo_start + (n_lo - 1) * BR, hi_start + (n_hi - 1) * BR):
            frow = last_start + _R
            for lane in range(_CAP):
                bnds.append((frow, lane, int(root[lane]) % F.P))
    return per, bnds, T, segs, query_end


def _fill_trace(pub_flat, wit_flat, T, segs):
    """PROVER side: fill the witness trace (sponge snapshots + witness siblings + carries). `pub_flat[si]` =
    (lo_pos, lo_len, hi_pos, hi_len, root, x, α, c2lo); `wit_flat[si]` = (lo_val, lo_path, hi_val, hi_path)."""
    BR = _R + 1
    rows = [[0] * _WTOT for _ in range(T)]
    INV2 = F.inv(2)
    for si, (lo_start, hi_start, fold_row, n_lo, n_hi) in enumerate(segs):
        lo_pos, _ll, hi_pos, _hl, root, x, alpha, _c2 = pub_flat[si]
        lo_val, lo_path, hi_val, hi_path = wit_flat[si]
        fv = F.add(F.mul(F.add(lo_val, hi_val), INV2),
                   F.mul(alpha, F.mul(F.sub(lo_val, hi_val), F.mul(INV2, F.inv(x)))))

        def fill_path(base, leaf_val, index, path):
            lb, sibs, _dirs, _cur = _blocks_for(leaf_val, index, path)
            for bblk, blk in enumerate(lb):
                for rib, s in enumerate(blk):
                    i = base + bblk * BR + rib
                    for lane in range(_W):
                        rows[i][lane] = int(s[lane]) % F.P
                    if rib == _R and bblk < len(sibs):     # sibling feeding the NEXT block's absorb
                        for lane in range(_CAP):
                            rows[i][_SIBW + lane] = int(sibs[bblk][lane]) % F.P

        fill_path(lo_start, lo_val, lo_pos, lo_path)
        fill_path(hi_start, hi_val, hi_pos, hi_path)
        for i in range(lo_start, fold_row + 1):
            rows[i][_CLO] = int(lo_val) % F.P
            rows[i][_CHI] = int(hi_val) % F.P
            rows[i][_FOLD] = fv % F.P
    n_used = segs[-1][2] + 1 if segs else 0
    for i in range(n_used, T):
        rows[i] = list(rows[n_used - 1]) if n_used else [0] * _WTOT
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

    # absorb-mux reads the sibling from the WITNESS columns cur[_SIBW+i], direction from periodic
    def a_left(i):
        def c(cur, nxt, per):
            d = per[_DIR]
            want = F.add(F.mul(F.sub(1, d), cur[i]), F.mul(d, cur[_SIBW + i]))
            return F.mul(per[_ACTA], F.sub(nxt[i], want))
        return c

    def a_right(i):
        def c(cur, nxt, per):
            d = per[_DIR]
            want = F.add(F.mul(F.sub(1, d), cur[_SIBW + i]), F.mul(d, cur[i]))
            return F.mul(per[_ACTA], F.sub(nxt[_CAP + i], want))
        return c

    def a_cap(i):
        def c(cur, nxt, per):
            return F.mul(per[_ACTA], F.sub(nxt[_RATE + i], a2.IV[i]))
        return c
    for i in range(_CAP):
        cons.append(a_left(i)); cons.append(a_right(i)); cons.append(a_cap(i))

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


def prove_fold(fri_proofs, num_queries_inner=None, num_queries_outer=64, mk_transcripts=None):
    """Fold REAL fri.prove(backend=RECURSION) proofs into ONE recursion proof. `num_queries_inner` must equal
    each inner proof's query count (defaults to len(queries) of the first). The outer proof is proven at
    `num_queries_outer` (protocol strength). `mk_transcripts[i]` (optional) rebuilds proof i's FRI-start
    transcript — needed when the inner FRI is embedded in a STARK; None = standalone (fresh 'fri' transcript).
    Returns (recursion_proof, publics)."""
    publics = [{"roots": p["roots"], "N": p["N"], "offset": p["offset"], "blowup": p["blowup"],
                "final": p["final"], "pow": p.get("pow")} for p in fri_proofs]
    if num_queries_inner is None:
        num_queries_inner = len(fri_proofs[0]["queries"])
    merged = {"queries": [], "finals": []}
    wit_flat = []
    for i, (p, pub) in enumerate(zip(fri_proofs, publics)):
        mk = mk_transcripts[i] if mk_transcripts else None
        c = _canonical_public(pub, num_queries_inner, mk)  # public schedule (same as the verifier's)
        w = _witness_of(p, num_queries_inner, mk)          # openings + paths, aligned to FS indices
        if c is None or w is None:
            raise ValueError("an inner FRI proof failed native verification — refusing to fold it")
        merged["queries"] += c["queries"]; merged["finals"] += c["finals"]
        for steps in w:
            wit_flat += steps
    per, bnds, T, segs, _qe = _schedule_periodic_boundaries(merged)
    pub_flat = [st for steps in merged["queries"] for st in steps]
    rows = _fill_trace(pub_flat, wit_flat, T, segs)
    proof = stark.prove(rows, _transitions(), bnds, periodic=per, max_degree=8,
                        num_queries=num_queries_outer, backend=backend.ALGHASH2)
    return proof, {"publics": publics, "num_queries_inner": num_queries_inner,
                   "num_queries_outer": num_queries_outer}


def verify_fold(recursion_proof, public, mk_transcripts=None):
    """SOUND verification. `public` = the {publics, num_queries_inner, num_queries_outer} from prove_fold.
    Re-derives the canonical schedule from each inner proof's PUBLIC part (recomputing FS challenges, checking
    grind + final-layer low-degree + geometry), builds periodic+boundaries ITSELF, and verifies the recursion
    STARK against ITS schedule. `mk_transcripts` as in prove_fold — the verifier must rebuild the same FRI-start
    transcripts (from the STARK proofs' public roots + AIR) for STARK-embedded FRI. Returns (ok, reason)."""
    try:
        nqi = public["num_queries_inner"]; nqo = public["num_queries_outer"]
        merged = {"queries": [], "finals": []}
        for i, pub in enumerate(public["publics"]):
            mk = mk_transcripts[i] if mk_transcripts else None
            c = _canonical_public(pub, nqi, mk)         # NATIVE checks + FS re-derivation, from public only
            if c is None:
                return False, "an inner proof's public statement failed native FRI verification"
            merged["queries"] += c["queries"]; merged["finals"] += c["finals"]
        per, bnds, _T, _segs, _qe = _schedule_periodic_boundaries(merged)   # VERIFIER builds the schedule
        return stark.verify(recursion_proof, _transitions(), bnds, periodic=per, max_degree=8,
                            num_queries=nqo, backend=backend.ALGHASH2)
    except Exception as e:
        return False, f"malformed recursion bundle: {e}"
