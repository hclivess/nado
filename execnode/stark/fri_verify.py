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
from execnode.stark.fri import (_expected_layers, _coset_interpolate, _coset_interpolate_ext,
                               GRIND_BITS, NUM_QUERIES)
from execnode.stark import extf as ext2
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
# GF(p^2) LAYOUT. The opened values, and therefore the fold carries, are extension elements when the inner
# proof is one. The HI limbs are APPENDED, so every index above keeps its meaning and simply denotes the LO
# limb — every carry/hold/select constraint is F_p-LINEAR and just duplicates per limb, and only the fold
# identity itself needs real extension arithmetic (alpha is the only ext-valued coefficient). Base is a strict
# prefix of ext, which keeps the diff, and the risk, confined to what genuinely differs.
_EXTRA0 = _W + _CAP + 5        # first appended limb column


def _carry(base, i):
    """Column holding limb `i` of carry `base` (_CLO / _CHI / _FOLD).

    Limb 0 IS the original base column, so the base-field layout is a strict prefix of the extension one and
    every pre-existing constraint keeps its meaning. Limbs 1.. are appended, grouped per carry. Derived from
    extf.DEGREE rather than named individually — a hand-written _CLO1/_CHI1/_FOLD1 block encodes the degree
    in its own length and silently stops covering the value when the degree moves."""
    if i == 0:
        return base
    which = (_CLO, _CHI, _FOLD).index(base)
    return _EXTRA0 + which * (ext2.DEGREE - 1) + (i - 1)


def _carry_all(base):
    return tuple(_carry(base, i) for i in range(ext2.DEGREE))


def _wtot(ext):
    return (_EXTRA0 + 3 * (ext2.DEGREE - 1)) if ext else _WTOT


# WHY a rejection is recorded rather than merely returned.
# _canonical_public answers "is this a valid foldable FRI proof" with a bare None, and that None conflates
# two completely different situations: the proof really is invalid (correct, expected), or OUR replay is
# broken (a bug in this file, a wrong challenge field, a mk_transcript that does not match how the proof was
# made). The caller cannot tell them apart, so prove_fold raised "an inner FRI proof failed native
# verification — refusing to fold it" — a message that points at the proof and is, when it is a replay bug,
# exactly backwards. That message cost hours: the actual cause was recursive_verify._fs defaulting to a
# base-field replay for extension proofs.
# The verdict is unchanged (None is still a refusal, and nothing decides anything on the reason string).
# Only the diagnosis is added.
LAST_REJECT = None


def _reject(reason):
    global LAST_REJECT
    LAST_REJECT = reason
    return None


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
    # GF(p^2) proofs are accepted now that the AIR carries extension arithmetic. The replay below MUST mirror
    # fri.verify exactly — same challenge field, same "final" absorption of the FLATTENED limbs, same
    # extension interpolation of the final layer — or the challenges diverge and every honest proof fails.
    # `ext0` says whether LAYER 0 is already extension-valued (a DEEP quotient) or still base; every later
    # layer is extension once folding starts, exactly as in fri.prove.
    _ext = bool(pub.get("ext")) if isinstance(pub, dict) else False
    _ext0 = bool(pub.get("ext0")) if isinstance(pub, dict) else False
    b = backend.RECURSION
    try:
        N, off, blowup = pub["N"], pub["offset"], pub["blowup"]
        roots, final = pub["roots"], pub["final"]
        if not isinstance(N, int) or N < 2 or (N & (N - 1)):
            return _reject(f"domain size N={N!r} is not a power of two >= 2")
        if not isinstance(blowup, int) or blowup < 2 or (blowup & (blowup - 1)):
            return _reject(f"blowup={blowup!r} is not a power of two >= 2")
        exp_layers = _expected_layers(N, blowup)
        if len(roots) != exp_layers or len(final) != (N >> exp_layers):
            return _reject(f"layer geometry: {len(roots)} roots (expected {exp_layers}) and "
                           f"{len(final)} final values (expected {N >> exp_layers})")
        t = mk_transcript() if mk_transcript is not None else Transcript("fri", backend=b)
        alphas, offs, sizes, o, n = [], [], [], off, N     # offsets+sizes only: points computed on demand as
        for r in roots:                                    # off·ω^pos, so NO O(N) domain is ever allocated
            t.absorb(r); alphas.append(t.challenge_ext() if _ext else t.challenge())
            offs.append(o); sizes.append(n)
            o = F.mul(o, o); n //= 2
        t.absorb("final", *(ext2.flatten(final) if _ext else final))
        if not t.check_grind(pub.get("pow"), GRIND_BITS):
            return _reject(f"grinding PoW failed at {GRIND_BITS} bits — usually means the transcript "
                           f"replay diverged before here (wrong challenge field, or a mk_transcript that "
                           f"does not match how the proof was produced), not that the nonce is wrong")
        coeffs = _coset_interpolate_ext(final, o) if _ext else _coset_interpolate(final, o)
        deg_bound = max(1, len(final) // blowup)
        _zero = ext2.ZERO if _ext else 0
        if any(c != _zero for c in coeffs[deg_bound:]):
            return _reject(f"final layer is not low-degree (bound {deg_bound} of {len(coeffs)})")
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
        return {"queries": out_queries, "finals": finals, "ext": _ext, "ext0": _ext0}
    except Exception as e:
        return _reject(f"{type(e).__name__}: {e}")


def _witness_of(fri_proof, num_queries, mk_transcript=None):
    """PROVER SIDE. Extract the WITNESS (opened values + Merkle sibling paths) aligned to the FS query indices,
    from a full FRI proof. Returns [[per-layer (lo_val, lo_path, hi_val, hi_path)]] (query-major) or None if the
    proof's declared indices disagree with Fiat-Shamir. `mk_transcript` as in _canonical_public."""
    b = backend.RECURSION
    N, off, blowup = fri_proof["N"], fri_proof["offset"], fri_proof["blowup"]
    roots, final, queries = fri_proof["roots"], fri_proof["final"], fri_proof["queries"]
    # The transcript must be replayed in the proof's OWN challenge field, exactly as _canonical_public and
    # fri.verify do — a base-field replay of an ext proof draws different challenges, so the FS query index
    # would not match the proof's and every honest witness extraction returned None.
    _ext = bool(fri_proof.get("ext", False))
    t = mk_transcript() if mk_transcript is not None else Transcript("fri", backend=b)
    o = off
    for r in roots:
        t.absorb(r); (t.challenge_ext() if _ext else t.challenge()); o = F.mul(o, o)
    t.absorb("final", *(ext2.flatten(final) if _ext else final))
    t.check_grind(fri_proof.get("pow"), GRIND_BITS)
    Lr = len(roots)
    out = []
    for _qi, q in enumerate(queries):
        idx = t.challenge_index(N)
        if idx != q.get("idx"):
            # Same reasoning as _reject above: the caller only sees None, and "the openings are for the
            # wrong rows" and "our transcript replay drifted" are indistinguishable from there.
            return _reject(f"query {_qi} opens index {q.get('idx')!r} but Fiat-Shamir derives {idx} — "
                           f"the witness does not align to the schedule")
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
# ext: alpha and the pinned final-layer value gain a HI limb, appended for the same prefix reason as above.
# ext: alpha and the pinned final-layer value each gain DEGREE-1 extra limb columns, appended.
_PAL_X0 = _W + 14                       # alpha limbs 1..D-1
def _pal(i):
    return _PAL if i == 0 else _PAL_X0 + (i - 1)


def _pfin(i):
    return _PFIN if i == 0 else _PAL_X0 + (ext2.DEGREE - 1) + (i - 1)


def _nper(ext):
    return (_W + 14 + 2 * (ext2.DEGREE - 1)) if ext else _NPER


def _schedule_periodic_boundaries(schedule, seam_lo0=None, ext=False, ext0=False):
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
    # WHICH LAYERS ARE EXTENSION-COMMITTED. fri.prove commits layer 0 with BASE leaves unless the values were
    # already ext (ext0 — a DEEP quotient); folding makes every LATER layer ext. So the leaf FRAME differs per
    # layer, and using the ext frame everywhere makes the in-circuit path digest disagree with the committed
    # root on layer 0 — which shows up as the "final digest == layer root" boundaries failing, not as a
    # constraint violation.
    flat_layer = [j for ln in qlens for j in range(ln)]
    def _leaf_ext(si):
        return bool(ext) and (flat_layer[si] > 0 or bool(ext0))

    sup_link, sello, selhi, hold_rel = [], [], [], []
    foldat, px, pal, chlo, chhi, finat, pfin = [], [], [], [], [], [], []
    pal_x = [[] for _ in range(ext2.DEGREE - 1)]             # ext: alpha limbs 1..D-1
    pfin_x = [[] for _ in range(ext2.DEGREE - 1)]            # ext: final-value limbs 1..D-1
    bnds = []
    for si, (lo_start, hi_start, fold_row, n_lo, n_hi) in enumerate(segs):
        st = flat[si]
        if seam_lo0 is not None and query_first[si]:
            _seam = seam_lo0[flat_qi[si]]
            if ext:
                # EVERY limb — the seam otherwise pins only part of the value the composition half is handed
                # and a prover is free to choose the rest.
                _sl = ext2.lift(_seam)
                for _i in range(ext2.DEGREE):
                    bnds.append((lo_start, _carry(_CLO, _i), int(_sl[_i]) % F.P))
            else:
                bnds.append((lo_start, _CLO, int(_seam) % F.P))
        lo_pos, hi_pos, root, x, alpha, c2lo = st[0], st[2], st[4], st[5], st[6], st[7]
        for start, nblk, pos in ((lo_start, n_lo, lo_pos), (hi_start, n_hi, hi_pos)):
            sup_link.append((start + nblk * _B - 1, 0))          # release the final block's row-15 link
            frow = start + (nblk - 1) * _B + _R                  # the path's digest row
            # leaf frame of block 0. An EXT leaf is (DOM_LEAF_EXT, lo, hi, 0, 0...): lane 1 carries the lo
            # limb and lane 2 the hi limb (both tied to the carries by SELLO/SELHI), so only lanes 3.. are
            # pinned to zero. Its own domain tag keeps it distinct from a base leaf with hi = 0.
            _lx = _leaf_ext(si)
            # Lane 0 is the domain tag; an extension leaf then occupies lanes 1..D, a base leaf only lane 1.
            # Everything above that is pinned to zero. The cut point is derived, not written: pinning lane D
            # to zero while the frame stores a limb there is a boundary violation on an HONEST trace, which
            # is how this surfaced (6 failures at lane 3 the moment the degree moved).
            bnds.append((start, 0, a2.DOM_LEAF_EXT if _lx else a2.DOM_LEAF))
            for lane in range((1 + ext2.DEGREE) if _lx else 2, _RATE):
                bnds.append((start, lane, 0))
            for lane in range(_CAP):
                bnds.append((start, _RATE + lane, a2.IV[lane]))
                bnds.append((frow, lane, int(root[lane]) % F.P))  # final digest == layer root
            bnds.append((start, _IACC, int(pos)))                # index accumulator: starts at the FS index...
            bnds.append((frow, _IACC, 0))                        # ...and is fully consumed — bits are unique
        sello.append((lo_start, 1)); selhi.append((hi_start, 1))
        hold_rel.append((fold_row, 0))
        foldat.append((fold_row, 1))
        px.append((fold_row, int(x) % F.P))
        if ext:
            _al = ext2.lift(alpha)
            pal.append((fold_row, int(_al[0]) % F.P))
            for _i in range(1, ext2.DEGREE):
                pal_x[_i - 1].append((fold_row, int(_al[_i]) % F.P))
        else:
            pal.append((fold_row, int(alpha) % F.P))
        if query_end[si]:
            finat.append((fold_row, 1))
            if ext:
                _fl = ext2.lift(flat_final[si])
                pfin.append((fold_row, int(_fl[0]) % F.P))
                for _i in range(1, ext2.DEGREE):
                    pfin_x[_i - 1].append((fold_row, int(_fl[_i]) % F.P))
            else:
                pfin.append((fold_row, int(flat_final[si]) % F.P))
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
    if ext:
        per += [SP(c) for c in pal_x] + [SP(c) for c in pfin_x]
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


def _fill_trace(pub_flat, wit_flat, T, segs, ext=False, ext0=False, query_end=None):
    """PROVER side: fill the witness trace (sponge snapshots + witness siblings/directions + index accumulators
    + carries). `pub_flat[si]` = (lo_pos, lo_len, hi_pos, hi_len, root, x, α, c2lo); `wit_flat[si]` =
    (lo_val, lo_path, hi_val, hi_path). Padding rows continue as inert dummy hash blocks (the 16-periodic round
    and absorb gates stay active through the padding, so it must be REAL permutation arithmetic)."""
    rows = [[0] * _wtot(ext) for _ in range(T)]
    INV2 = F.inv(2)
    # Which LAYER each segment belongs to, so the leaf FRAME matches how that layer was committed: layer 0 is
    # base-committed unless ext0, every later layer is ext (fri.prove's is_ext_layer). The CARRIES are ext
    # throughout — lifting a base opening just gives hi = 0 — but the frame tag and the lane-2 pin have to
    # follow the commitment, or the in-circuit path digest will not equal the layer root.
    # query_end[si] marks each query's LAST layer, so the counter resets exactly there.
    _seg_layer, _lay = [], 0
    for si in range(len(segs)):
        _seg_layer.append(_lay)
        _lay = 0 if (query_end and si < len(query_end) and query_end[si]) else _lay + 1
    for si, (lo_start, hi_start, fold_row, n_lo, n_hi) in enumerate(segs):
        lo_pos, _ll, hi_pos, _hl, root, x, alpha, _c2 = pub_flat[si]
        lo_val, lo_path, hi_val, hi_path = wit_flat[si]
        if ext:
            # Same fold, in GF(p^2). lo/hi may be base ints on an ext0=False layer 0, so lift before use;
            # x and INV2 stay base scalars, so only the single alpha multiply is a full extension product.
            _lx = bool(ext) and (_seg_layer[si] > 0 or bool(ext0))
            lo_e, hi_e = ext2.lift(lo_val), ext2.lift(hi_val)
            fe = ext2.scalar_mul(ext2.add(lo_e, hi_e), INV2)
            fo = ext2.scalar_mul(ext2.sub(lo_e, hi_e), F.mul(INV2, F.inv(x)))
            fv = ext2.add(fe, ext2.mul(ext2.lift(alpha), fo))
            # ext leaf frame only where that layer was ext-committed; otherwise the base frame with the
            # base value (its hi limb is zero anyway).
            _lf_lo = lo_e if _lx else lo_e[0]
            _lf_hi = hi_e if _lx else hi_e[0]
            _fill_path(rows, lo_start, _lf_lo, lo_pos, lo_path)
            _fill_path(rows, hi_start, _lf_hi, hi_pos, hi_path)
            for i in range(lo_start, fold_row + 1):
                for _k in range(ext2.DEGREE):
                    rows[i][_carry(_CLO, _k)] = lo_e[_k] % F.P
                    rows[i][_carry(_CHI, _k)] = hi_e[_k] % F.P
                    rows[i][_carry(_FOLD, _k)] = fv[_k] % F.P
            continue
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
                if ext:
                    for _k in range(1, ext2.DEGREE):
                        for _b in (_CLO, _CHI, _FOLD):
                            rows[pb + rib][_carry(_b, _k)] = rows[n_used - 1][_carry(_b, _k)]
        state = nxt
    return rows


def _transitions(ext=False):
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

    if not ext:
        def fold_c(c, n, p):
            lhs = F.mul(F.mul(2, p[_PX]), c[_FOLD])
            rhs = F.add(F.mul(p[_PX], F.add(c[_CLO], c[_CHI])), F.mul(p[_PAL], F.sub(c[_CLO], c[_CHI])))
            return F.mul(p[_FOLDAT], F.sub(lhs, rhs))
        cons.append(fold_c)
        cons.append(lambda c, n, p: F.mul(p[_CHLO], F.sub(n[_CLO], c[_FOLD])))
        cons.append(lambda c, n, p: F.mul(p[_CHHI], F.sub(n[_CHI], c[_FOLD])))
        cons.append(lambda c, n, p: F.mul(p[_FINAT], F.sub(c[_FOLD], p[_PFIN])))
        return cons

    # ---- GF(p^2) ----------------------------------------------------------------------------------
    # Every constraint above is F_p-LINEAR in the carries, so the HI limbs are exact duplicates against the
    # appended columns. The leaf select is the one that also changes shape: an extension leaf frames its lo
    # limb in lane 1 and its hi limb in lane 2 (see recursion._blocks_for), so SELLO/SELHI tie BOTH.
    # Every carry/hold/select/chain constraint is F_p-LINEAR, so limbs 1..D-1 are exact duplicates against
    # the appended columns. An extension leaf frames its limbs in lanes 1..D (see recursion._blocks_for), so
    # SELLO/SELHI tie limb k to lane k+1.
    D = ext2.DEGREE
    for _k in range(1, D):
        for _b in (_CLO, _CHI, _FOLD):
            cons.append((lambda bb, kk: lambda c, n, p:
                         F.mul(p[_HOLD], F.sub(n[_carry(bb, kk)], c[_carry(bb, kk)])))(_b, _k))
    for _k in range(1, D):
        cons.append((lambda kk: lambda c, n, p:
                     F.mul(p[_SELLO], F.sub(c[_carry(_CLO, kk)], c[kk + 1])))(_k))
        cons.append((lambda kk: lambda c, n, p:
                     F.mul(p[_SELHI], F.sub(c[_carry(_CHI, kk)], c[kk + 1])))(_k))

    # The fold identity 2x*FOLD = x*(CLO+CHI) + alpha*(CLO-CHI) over GF(p^D), one constraint per component.
    # x is a BASE domain point and stays a scalar; alpha is the only extension coefficient. Its product with
    # d = CLO-CHI reduces mod X^D - N as
    #     (alpha*d)_m = sum_{i+j=m} a_i d_j  +  N * sum_{i+j=m+D} a_i d_j
    # which is verified against extf.mul, and the whole identity against fri._fold_ext, before being wired.
    # A misplaced wrap term does NOT fail loudly here: the AIR stays low-degree and satisfiable, it just
    # proves a different fold.
    NR = ext2.NONRESIDUE

    def _fold_c(m):
        def c(cur, nxt, per):
            d = [F.sub(cur[_carry(_CLO, i)], cur[_carry(_CHI, i)]) for i in range(D)]
            acc = 0
            for i in range(D):
                for j in range(D):
                    if i + j == m:
                        acc = F.add(acc, F.mul(per[_pal(i)], d[j]))
                    elif i + j == m + D:
                        acc = F.add(acc, F.mul(NR, F.mul(per[_pal(i)], d[j])))
            lhs = F.mul(F.mul(2, per[_PX]), cur[_carry(_FOLD, m)])
            rhs = F.add(F.mul(per[_PX], F.add(cur[_carry(_CLO, m)], cur[_carry(_CHI, m)])), acc)
            return F.mul(per[_FOLDAT], F.sub(lhs, rhs))
        return c
    for _m in range(D):
        cons.append(_fold_c(_m))

    # the folded value becomes the next layer's opening, and the last layer is pinned to the public final
    # value — EVERY limb, or a prover can hide a discrepancy in the ones left unchecked.
    for _k in range(D):
        cons.append((lambda kk: lambda c, n, p:
                     F.mul(p[_CHLO], F.sub(n[_carry(_CLO, kk)], c[_carry(_FOLD, kk)])))(_k))
        cons.append((lambda kk: lambda c, n, p:
                     F.mul(p[_CHHI], F.sub(n[_carry(_CHI, kk)], c[_carry(_FOLD, kk)])))(_k))
        cons.append((lambda kk: lambda c, n, p:
                     F.mul(p[_FINAT], F.sub(c[_carry(_FOLD, kk)], p[_pfin(kk)])))(_k))
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
    # `ext`/`ext0` are part of the PUBLIC statement: they say which field the transcript replay draws in and
    # which column layout the AIR has. Omitting them made every ext proof replay as base-field, so the
    # Fiat-Shamir challenges diverged and the inner proof "failed native verification". They are safe to carry
    # from the proof because the verifier re-derives every challenge under them and a lie simply produces a
    # schedule the openings cannot satisfy.
    publics = [{"roots": p["roots"], "N": p["N"], "offset": p["offset"], "blowup": p["blowup"],
                "final": p["final"], "pow": p.get("pow"),
                "ext": bool(p.get("ext", False)), "ext0": bool(p.get("ext0", False))} for p in fri_proofs]
    if num_queries_inner is None:
        num_queries_inner = len(fri_proofs[0]["queries"])
    merged = {"queries": [], "finals": []}
    wit_flat, seam_lo0 = [], []
    for i, (p, pub) in enumerate(zip(fri_proofs, publics)):
        mk = mk_transcripts[i] if mk_transcripts else None
        c = _canonical_public(pub, num_queries_inner, mk)  # public schedule (same as the verifier's)
        w = _witness_of(p, num_queries_inner, mk)          # openings + paths, aligned to FS indices
        if c is None or w is None:
            _why = LAST_REJECT if c is None else "witness openings do not align to the Fiat-Shamir indices"
            raise ValueError(f"inner FRI proof {i} failed native verification — refusing to fold it: {_why}")
        merged["queries"] += c["queries"]; merged["finals"] += c["finals"]
        # One AIR proves the whole batch, so every inner proof must live in the SAME challenge field —
        # mixing them would need two column layouts in one trace.
        if merged.get("ext") is None:
            merged["ext"] = c["ext"]; merged["ext0"] = c["ext0"]
        elif merged["ext"] != c["ext"] or merged.get("ext0") != c["ext0"]:
            raise ValueError("cannot fold FRI proofs with different challenge-field layouts in one batch")
        for steps in w:
            wit_flat += steps
            seam_lo0.append(steps[0][0] if merged["ext"] else int(steps[0][0]) % F.P)
    _ext = bool(merged.get("ext"))
    _ext0 = bool(merged.get("ext0"))
    per, bnds, T, segs, _qe = _schedule_periodic_boundaries(merged, seam_lo0, ext=_ext, ext0=_ext0)
    pub_flat = [st for steps in merged["queries"] for st in steps]
    rows = _fill_trace(pub_flat, wit_flat, T, segs, ext=_ext, ext0=_ext0, query_end=_qe)
    proof = stark.prove(rows, _transitions(_ext), bnds, periodic=per, max_degree=8,
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
            raise ValueError(f"inner FRI public statement {i} failed native verification: {LAST_REJECT}")
        merged["queries"] += c["queries"]; merged["finals"] += c["finals"]
        if merged.get("ext") is None:
            merged["ext"] = c["ext"]; merged["ext0"] = c["ext0"]
        elif merged["ext"] != c["ext"] or merged.get("ext0") != c["ext0"]:
            raise ValueError("mixed challenge fields across the folded proofs")
    seam = public.get("seam_lo0")
    if seam is not None and len(seam) != len(merged["queries"]):
        raise ValueError("seam value count != query count")
    _ext = bool(merged.get("ext"))
    per, bnds, _T, _segs, _qe = _schedule_periodic_boundaries(
        merged, seam, ext=_ext, ext0=bool(merged.get("ext0")))
    return _transitions(_ext), bnds, per


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
            if merged.get("ext") is None:
                merged["ext"] = c["ext"]; merged["ext0"] = c["ext0"]
            elif merged["ext"] != c["ext"] or merged.get("ext0") != c["ext0"]:
                return False, "mixed challenge fields across the folded proofs"
        seam = public.get("seam_lo0")                   # layer-0 seam values: in-circuit membership validates
        if seam is not None and len(seam) != len(merged["queries"]):        # them, so a lie cannot verify
            return False, "seam value count != query count"
        # The layout is derived from the INNER proofs' public parts, never from the fold prover — so a prover
        # cannot present an ext batch and have it checked under the cheaper base-field AIR. That much was
        # already true, and it is only HALF the property: it stops an extension batch being checked cheaply,
        # and does nothing to stop a BASE-FIELD batch being presented in the first place. Pin the field to
        # the protocol, exactly as stark.verify does with expected_ext, or a prover simply produces its inner
        # proofs base-field and has the fold attest them at ~47 bits instead of ~156.
        _ext = bool(merged.get("ext"))
        _want_ext = stark.ext_challenges_active(backend.RECURSION)
        if _ext != _want_ext:
            return False, (f"inner FRI proofs declare ext={_ext} but this chain pins ext={_want_ext} — "
                           f"the challenge field is not the prover's to choose")
        per, bnds, _T, _segs, _qe = _schedule_periodic_boundaries(
            merged, seam, ext=_ext, ext0=bool(merged.get("ext0")))
        return stark.verify(recursion_proof, _transitions(_ext), bnds, periodic=per, max_degree=8,
                            num_queries=nqo, backend=out_backend or backend.ALGHASH2)
    except Exception as e:
        return False, f"malformed recursion bundle: {e}"
