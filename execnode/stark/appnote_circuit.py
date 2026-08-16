"""
SHIELDED-CONTRACT transition circuit (doc/shielded-contracts.md) — the typed-note counterpart of
joinsplit_circuit, proving a 1-in/1-out private state transition in ONE zero-knowledge proof:

  owner   = hashn([DOM_OWNER, nsk])
  cm_in   = hashn([DOM_APPCM, cid, kind, arity, *fields_in,  owner,     rho_in ])   membership(cm_in) = root
  nf      = hashn([DOM_APPNF, nsk, cm_in])                                          (revealed)
  cm_out  = hashn([DOM_APPCM, cid, kind, arity, *fields_out, owner_out, rho_out])   (revealed)
  KIND_VALUE predicate: fields_in[0] + public_delta = fields_out[0], both in [0, 2^61)

WHAT IS ACTUALLY NEW HERE, relative to the join-split it is modelled on — the rest is deliberately the
same machinery, because a second hand-written sponge AIR is a second thing to get wrong:

  * THREE PUBLIC ABSORPTIONS per note (cid, kind, arity). They ride in a PERIODIC column (PUBMSG) gated by
    a selector (APUB), which is the same trick the round constants already use: both prover and verifier
    derive the column from the public statement, so a prover cannot substitute another contract's cid or
    relabel a note's kind. Putting them in a witness register instead would have let exactly that happen.
  * THE NULLIFIER ABSORBS THE COMMITMENT, not rho — the leak-closing change from shielded_state. cm is
    already captured in CARRY at COMMIT's end and is not overwritten until the first Merkle level, which
    is why this costs a selector (ACARRY) and no new register.
  * ARITY-PARAMETRIC GEOMETRY. A region absorbing m elements occupies m·R rows, so COMMIT and OUTPUT are
    (arity + 6)·R rather than a hardcoded 4·R. Depth D was already a runtime parameter of this geometry;
    arity follows the identical pattern, and both are recomputed by the verifier from the public statement.

BACKEND. prove() passes backend=alghash2 EXPLICITLY. stark.prove's native arena covers only the alghash2
and recursion backends; everything else reaches require_native_prover and refuses outside a build. All
three join-split modules omit the argument and therefore take blake2b, which is why the pool's Phase-2
prover cannot run on a node at all (measured 2026-08-16, tests/test_joinsplit_backend_gap.py). This circuit
does not inherit that.

STATUS: live. Two statements — a 1-in/1-out transition and a 0-in/1-out deposit — share this one AIR, and
shielded_state.verify_transition reaches both through its `proof["stark"]` branch. The state machine pins
the declared geometry (arity against the note kind, depth against the pool) before calling, and this module
bounds it again on its own account, because a verifier that allocates from numbers a stranger chose cannot
rely on its caller having checked them.
"""
from execnode.stark import field as F, alghash, stark

R = alghash.ROUNDS
RPL = 3 * R                                  # rows per Merkle level (two children + the node hash)
MAX_DEGREE = alghash.ALPHA

# Note-algebra domain tags. DEFINED HERE, at the bottom of the import graph, and imported by
# execnode/shielded_state.py — the state machine needs them and this circuit must not import the state
# machine back. alghash owns 1..4 (OWNER/CM/NF/NODE); these continue that append-only numbering.
DOM_APPCM, DOM_APPNF = 5, 6

# columns — identical to the join-split's, deliberately: cid/kind/arity are PUBLIC so they ride in periodic
# columns rather than registers, and the output opening rides in AB as free witness, so nothing new is needed
(S0, S1, AB, CARRY, SIB, DIR, NSK, RHO, OWN, NFREG, VIN, VOUT, CONS, ROOTREG,
 ACC, RB0, RB1, RB2, RB3) = range(19)
NCOLS = 19

# C-3 range gadget geometry (unchanged from the join-split — the wraparound it stops is the same one)
RNG_NIBBLES = 16
RNG_BLOCK = RNG_NIBBLES + 1
RNG_VALUES = 2
# HOW MANY TOP BITS THE GADGET PINS, and the value bound that follows from it. ONE number: c_rng_top sums
# exactly this many bit columns, and RANGE_BOUND is computed from it, so the constraint and the constant
# cannot say different things. They already did once — shielded_state.VALUE_MAX was 2^62, copied from
# joinsplit_circuit's module docstring, while the constraint pinned three bits and enforced 2^61. That made
# the transparent verifier LOOSER than the circuit it is supposed to specify. A constant that mirrors a
# constraint should be derived from it, not tested against it after the fact.
RNG_TOP_BITS = 3
RANGE_BOUND = 1 << (4 * RNG_NIBBLES - RNG_TOP_BITS)      # 2^61

OWN_END = 2 * R                              # OWNER = [DOM_OWNER, nsk]
NUL_ELEMS = 3                                # NULLIFIER = [DOM_APPNF, nsk, cm_in]

# GEOMETRY BOUNDS, enforced HERE because this is where the geometry is CONSUMED. verify() reads arity and
# depth from the proof — attacker-supplied — and builds NPER periodic columns of length trace_len(arity, D)
# from them. Unbounded, a declared arity of 10^6 asks for a 67M-row trace and ~49 GB of columns; a declared
# depth of 10^6 asks for ~98 GB. Neither is reachable through private_call, because the state machine pins
# arity against KIND_ARITY and depth against TREE_DEPTH before calling — but that guard lives in the
# CALLER, and a verifier that allocates from numbers a stranger chose has to bound them itself. Any other
# caller of this module gets no protection from a check it does not run.
MAX_FIELDS = 16                              # arity ceiling; shielded_state imports this rather than
                                             # keeping a second copy (the domain-tag pattern)
MAX_DEPTH = 32                               # matches the pool's SHIELD_DEPTH — generous, and finite


def cm_elems(arity):
    """Elements a note-commitment sponge absorbs: DOM, cid, kind, arity, <arity fields>, owner, rho."""
    return arity + 6


def geometry(arity, D):
    """Every region boundary for (arity, depth), derived the same way by prover and verifier so a prover
    cannot relocate a region or an absorb slot. Returns a dict rather than globals because, unlike the
    join-split, two of these move with the note's shape."""
    ce = cm_elems(arity)
    com_end = OWN_END + ce * R
    nul_end = com_end + NUL_ELEMS * R
    out_start = nul_end + D * RPL
    out_end = out_start + ce * R
    return {"ce": ce, "own_end": OWN_END, "com_end": com_end, "nul_end": nul_end, "merk": nul_end,
            "out_start": out_start, "out_end": out_end,
            "total": out_end + RNG_VALUES * RNG_BLOCK}


def _next_pow2(x):
    p = 1
    while p < x:
        p <<= 1
    return p


def trace_len(arity, D):
    """The ONE honest trace length for (arity, D). The verifier pins T to this — a prover who pads to a
    different power of two is rejected before any constraint is evaluated (the join-split's H1 fix)."""
    return _next_pow2(geometry(arity, D)["total"] + 1)


# ---- reference evaluation (the ground truth the trace must reproduce) --------------------------------
def note_cm(cid_el, kind, fields, owner, rho):
    """cm = hashn([DOM_APPCM, cid, kind, arity, *fields, owner, rho]) — the field-native mirror of
    shielded_state.note_commitment, which folds the cid to an element before calling this shape."""
    return alghash.hashn([DOM_APPCM, cid_el % F.P, kind % F.P, len(fields),
                          *[f % F.P for f in fields], owner % F.P, rho % F.P])


def note_nf(nsk, cm):
    """nf = hashn([DOM_APPNF, nsk, cm])."""
    return alghash.hashn([DOM_APPNF, nsk % F.P, cm % F.P])


def transition(nsk, cid_el, kind, fields_in, rho_in, siblings, dirs, fields_out, owner_out, rho_out):
    """Non-ZK evaluation of the whole statement: (owner, cm_in, nf, root, cm_out). Tests and callers derive
    the public values a proof will be checked against from this, so the AIR and the state machine can be
    diffed against one shared reference."""
    from execnode.stark import membership as MB
    owner = alghash.owner_of(nsk % F.P)
    cm_in = note_cm(cid_el, kind, fields_in, owner, rho_in)
    nf = note_nf(nsk, cm_in)
    root = MB.merkle_root_from_path(cm_in, siblings, dirs)
    cm_out = note_cm(cid_el, kind, fields_out, owner_out, rho_out)
    return owner, cm_in, nf, root, cm_out


def _round(s0, s1, r):
    """One prover-side sponge round — the same map the transition constraints recompute in-circuit."""
    t0 = alghash.sbox(F.add(s0, alghash.RC[r % R][0]))
    t1 = alghash.sbox(F.add(s1, alghash.RC[r % R][1]))
    return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))


def _nibbles(v):
    return [(v >> (4 * (15 - k))) & 0xF for k in range(RNG_NIBBLES)]


def _range_fill(out_end, values):
    """row -> (acc, b0, b1, b2, b3): acc is the accumulator BEFORE this row's nibble, so the recurrence
    acc' = 16·acc + nibble has reconstructed the value by the block's bind row."""
    fill = {}
    for b, val in enumerate(values):
        acc = 0
        base = out_end + b * RNG_BLOCK
        for i, nib in enumerate(_nibbles(val)):
            fill[base + i] = (acc, (nib >> 3) & 1, (nib >> 2) & 1, (nib >> 1) & 1, nib & 1)
            acc = 16 * acc + nib
        fill[base + RNG_NIBBLES] = (acc, 0, 0, 0, 0)
    return fill


# ---- the absorb schedule ------------------------------------------------------------------------------
# ONE table, read by the trace builder AND by the periodic columns, so the two cannot disagree about which
# row absorbs what. Each entry is (row, source, value): `source` names the constraint that will bind it.
PUB, REG_NSK, REG_RHO, REG_OWN, REG_VIN, REG_VOUT, REG_CARRY, FREE = range(8)


def absorb_schedule(arity, D, cid_el, kind):
    """{row: (source, value)} for every absorbed message. value is meaningful only for PUB rows (it becomes
    the PUBMSG periodic column); for register/free rows the constraint reads the column instead."""
    g = geometry(arity, D)
    sched = {R - 1: (REG_NSK, 0)}                                   # OWNER: nsk
    # COMMIT: cid, kind, arity (public) · fields (secret registers) · owner · rho
    head = [(PUB, cid_el), (PUB, kind), (PUB, arity)]
    # ONLY FIELD 0 TAKES A REGISTER. There is one value-register pair (VIN/VOUT) because conservation is a
    # linear check over field 0; every further field is FREE WITNESS, which is not a weakening — an INPUT
    # note's extra fields are pinned by cm_in's membership in the tree, and an OUTPUT note's are the
    # prover's to choose, exactly as owner and rho are. Whether they mean anything is the kind predicate's
    # business, which is the whole point of typed notes.
    body = [(REG_VIN, 0)] + [(FREE, 0)] * (arity - 1)
    tail = [(REG_OWN, 0), (REG_RHO, 0)]
    for i, ent in enumerate(head + body + tail, start=1):
        sched[g["own_end"] + i * R - 1] = ent
    # NULLIFIER: nsk, then the COMMITMENT still sitting in CARRY
    sched[g["com_end"] + 1 * R - 1] = (REG_NSK, 0)
    sched[g["com_end"] + 2 * R - 1] = (REG_CARRY, 0)
    # OUTPUT: the same public head, then the output opening as FREE witness (the zero-knowledge part)
    out_body = [(REG_VOUT, 0)] + [(FREE, 0)] * (arity - 1)
    for i, ent in enumerate(head + out_body + [(FREE, 0), (FREE, 0)], start=1):
        sched[g["out_start"] + i * R - 1] = ent
    return sched


def build_trace(nsk, cid_el, kind, fields_in, rho_in, siblings, dirs, fields_out, owner_out, rho_out):
    """The honest witness trace. Same five-region shape as the join-split, with the public head absorbed
    from the periodic column and the nullifier absorbing CARRY. Returns (trace, T, D, root, nf, cm_out)."""
    arity = len(fields_in)
    if len(fields_out) != arity:
        raise ValueError("input and output notes must have the same arity")
    D = len(siblings)
    g = geometry(arity, D)
    T = trace_len(arity, D)
    nsk, rho_in, rho_out = nsk % F.P, rho_in % F.P, rho_out % F.P
    owner_out = owner_out % F.P
    v_in, v_out = fields_in[0] % F.P, fields_out[0] % F.P
    sched = absorb_schedule(arity, D, cid_el, kind)

    cons = F.sub(v_in, v_out)
    rfill = _range_fill(g["out_end"], (fields_in[0], fields_out[0]))
    tr = []
    s0, s1, ab = alghash.DOM_OWNER, alghash.IV, alghash.DOM_OWNER
    carry = sib = dr = own = nfreg = rootreg = 0
    lvl = 0
    # The FREE lane is consumed in row order: COMMIT's extra input fields, then OUTPUT's extra output
    # fields, then the output opening. Keep this list in the same order as absorb_schedule emits FREE.
    free_msgs = ([f % F.P for f in fields_in[1:]] + [f % F.P for f in fields_out[1:]]
                 + [owner_out, rho_out])
    free_i = 0
    for r in range(T):
        acc, rb0, rb1, rb2, rb3 = rfill.get(r, (0, 0, 0, 0, 0))
        tr.append([s0, s1, ab, carry, sib, dr, nsk, rho_in, own, nfreg, v_in, v_out, cons, rootreg,
                   acc, rb0, rb1, rb2, rb3])
        r0, r1 = _round(s0, s1, r)
        if r == g["own_end"] - 1:                       # OWNER done -> capture owner, open COMMIT
            own = r0
            s0, s1, ab = DOM_APPCM, alghash.IV, DOM_APPCM
        elif r == g["com_end"] - 1:                     # COMMIT done -> capture cm, open NULLIFIER
            carry = r0
            s0, s1, ab = DOM_APPNF, alghash.IV, DOM_APPNF
        elif r == g["nul_end"] - 1:                     # NULLIFIER done -> capture nf, open MEMBERSHIP
            nfreg = r0
            sib, dr = siblings[0] % F.P, dirs[0] % F.P
            s0, s1, ab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
        elif g["merk"] <= r < g["out_start"]:           # MEMBERSHIP
            pos = (r - g["merk"]) % RPL
            block, last = pos // R, (pos % R == R - 1)
            if last and block == 0:
                left = F.add(carry, F.mul(dr, F.sub(sib, carry)))
                s0, s1, ab = F.add(r0, left), r1, left
            elif last and block == 1:
                right = F.add(sib, F.mul(dr, F.sub(carry, sib)))
                s0, s1, ab = F.add(r0, right), r1, right
            elif last and block == 2:
                lvl += 1
                if lvl < D:
                    carry, sib, dr = r0, siblings[lvl] % F.P, dirs[lvl] % F.P
                    s0, s1, ab = alghash.DOM_NODE, alghash.IV, alghash.DOM_NODE
                else:                                   # last level -> capture root, open OUTPUT
                    rootreg = r0
                    s0, s1, ab = DOM_APPCM, alghash.IV, DOM_APPCM
            else:
                s0, s1 = r0, r1
        elif r in sched and r < g["out_end"] - 1:       # a scheduled absorption
            src, val = sched[r]
            if src == PUB:
                msg = val % F.P
            elif src == REG_NSK:
                msg = nsk
            elif src == REG_RHO:
                msg = rho_in
            elif src == REG_OWN:
                msg = own
            elif src == REG_VIN:
                msg = v_in
            elif src == REG_VOUT:
                msg = v_out
            elif src == REG_CARRY:
                msg = carry
            else:                                       # FREE — the secret output opening
                msg = free_msgs[free_i]
                free_i += 1
            s0, s1, ab = F.add(r0, msg), r1, msg
        else:                                           # plain round, range region, or padding
            s0, s1 = r0, r1
    _, _, nf, root, cm_out = transition(nsk, cid_el, kind, fields_in, rho_in, siblings, dirs,
                                        fields_out, owner_out, rho_out)
    return tr, T, D, root, nf, cm_out


# ---- periodic (public) columns -----------------------------------------------------------------------
(RC0, RC1, ANSK, ARHO, AOWN, AVIN, AVOUT, AFREE, ACARRY, APUB, PUBMSG, B0, B1,
 RCM, RNF, RNODE, ROUT, CAPOWN, CAPCARRY, CAPNF, CAPROOT, INMERK,
 RNG_ACC, RNG_START, RBIND_VIN, RBIND_VOUT) = range(26)
NPER = 26


def periodic(T, arity, D, cid_el, kind):
    """The public selector columns, fully determined by (T, arity, D, cid, kind).

    EVERY absorb selector is derived from absorb_schedule(), the same table the trace builder reads, so the
    two cannot drift apart — a hand-maintained second copy of the schedule is precisely how an AIR ends up
    describing a different statement than the trace it validates. PUBMSG carries cid/kind/arity as column
    VALUES: the verifier rebuilds it from the public statement, so a prover cannot swap in another
    contract's cid or relabel the note's kind, which a witness register would have allowed."""
    g = geometry(arity, D)
    sched = absorb_schedule(arity, D, cid_el, kind)
    merk, out_start, out_end, total = g["merk"], g["out_start"], g["out_end"], g["total"]

    def col(fn):
        return [1 if fn(r) else 0 for r in range(T)]

    def src_is(*want):
        return col(lambda r: r in sched and sched[r][0] in want and r < out_end - 1)

    lvl_end = lambda r, upto: (merk <= r < out_start and (r - merk) % RPL == RPL - 1
                               and 0 <= (r - merk) // RPL < upto)
    rng = lambda r: out_end <= r < total

    p = [None] * NPER
    p[RC0] = [alghash.RC[r % R][0] for r in range(T)]
    p[RC1] = [alghash.RC[r % R][1] for r in range(T)]
    p[ANSK] = src_is(REG_NSK)
    p[ARHO] = src_is(REG_RHO)
    p[AOWN] = src_is(REG_OWN)
    p[AVIN] = src_is(REG_VIN)
    p[AVOUT] = src_is(REG_VOUT)
    p[ACARRY] = src_is(REG_CARRY)
    p[AFREE] = src_is(FREE)
    p[APUB] = src_is(PUB)
    p[PUBMSG] = [(sched[r][1] % F.P) if (r in sched and sched[r][0] == PUB and r < out_end - 1) else 0
                 for r in range(T)]
    p[B0] = col(lambda r: merk <= r < out_start and (r - merk) % RPL == R - 1)
    p[B1] = col(lambda r: merk <= r < out_start and (r - merk) % RPL == 2 * R - 1)
    p[RCM] = col(lambda r: r == g["own_end"] - 1)
    p[RNF] = col(lambda r: r == g["com_end"] - 1)
    p[RNODE] = col(lambda r: r == g["nul_end"] - 1 or lvl_end(r, D - 1))
    p[ROUT] = col(lambda r: r == out_start - 1)
    p[CAPOWN] = col(lambda r: r == g["own_end"] - 1)
    p[CAPCARRY] = col(lambda r: r == g["com_end"] - 1 or lvl_end(r, D - 1))
    p[CAPNF] = col(lambda r: r == g["nul_end"] - 1)
    p[CAPROOT] = col(lambda r: r == out_start - 1)
    p[INMERK] = col(lambda r: merk <= r < out_start)
    p[RNG_ACC] = col(lambda r: rng(r) and (r - out_end) % RNG_BLOCK < RNG_NIBBLES)
    p[RNG_START] = col(lambda r: rng(r) and (r - out_end) % RNG_BLOCK == 0)
    p[RBIND_VIN] = col(lambda r: r == out_end + 0 * RNG_BLOCK + RNG_NIBBLES)
    p[RBIND_VOUT] = col(lambda r: r == out_end + 1 * RNG_BLOCK + RNG_NIBBLES)
    return p


# ---- the AIR ------------------------------------------------------------------------------------------
def transitions():
    """The transition polynomials, each gated to its region by the periodic selectors. Structurally the
    join-split's set plus two absorb sources (APUB, ACARRY); the sponge, capture, Merkle and range groups
    are unchanged, which is the point — one audited shape, two statements."""
    A = alghash

    def rnd(cur, per):
        t0 = F.pw(F.add(cur[S0], per[RC0]), A.ALPHA)
        t1 = F.pw(F.add(cur[S1], per[RC1]), A.ALPHA)
        return F.add(F.mul(2, t0), t1), F.add(t0, F.mul(3, t1))

    def parts(cur, per):
        left = F.add(cur[CARRY], F.mul(cur[DIR], F.sub(cur[SIB], cur[CARRY])))
        right = F.add(cur[SIB], F.mul(cur[DIR], F.sub(cur[CARRY], cur[SIB])))
        reset = F.add(F.add(per[RCM], per[RNF]), F.add(per[RNODE], per[ROUT]))
        reset_dom = F.add(F.add(F.mul(per[RCM], DOM_APPCM), F.mul(per[RNF], DOM_APPNF)),
                          F.add(F.mul(per[RNODE], A.DOM_NODE), F.mul(per[ROUT], DOM_APPCM)))
        return left, right, reset, reset_dom

    def c_s1(cur, nxt, per):
        """Capacity lane: follows the permutation, restarting from IV at a region reset."""
        _, r1 = rnd(cur, per)
        _, _, reset, _ = parts(cur, per)
        return F.sub(nxt[S1], F.add(F.mul(reset, A.IV), F.mul(F.sub(1, reset), r1)))

    def c_s0(cur, nxt, per):
        """Rate lane: permutation plus whichever message the schedule injects — a register, the PUBLIC
        periodic value, the captured commitment, free witness, or a Merkle child. This single constraint is
        what binds the entire hash-chain structure of the statement to its intended sources."""
        r0, _ = rnd(cur, per)
        left, right, reset, reset_dom = parts(cur, per)
        absorbed = F.add(
            F.add(F.add(F.mul(per[ANSK], cur[NSK]), F.mul(per[ARHO], cur[RHO])),
                  F.add(F.mul(per[AOWN], cur[OWN]), F.mul(per[AVIN], cur[VIN]))),
            F.add(F.add(F.mul(per[AVOUT], cur[VOUT]), F.mul(per[AFREE], nxt[AB])),
                  F.add(F.add(F.mul(per[ACARRY], cur[CARRY]), F.mul(per[APUB], per[PUBMSG])),
                        F.add(F.mul(per[B0], left), F.mul(per[B1], right)))))
        return F.sub(nxt[S0], F.add(reset_dom, F.mul(F.sub(1, reset), F.add(r0, absorbed))))

    def c_ab(cur, nxt, per):
        """AB discipline: at each scheduled row AB' equals the scheduled message; on AFREE rows it is free
        witness (the secret output opening — the zero-knowledge part); otherwise it holds."""
        left, right, _, _ = parts(cur, per)
        setm = F.add(F.add(F.add(per[RCM], per[RNF]), F.add(per[RNODE], per[ROUT])),
                     F.add(F.add(F.add(per[ANSK], per[ARHO]), F.add(per[AOWN], per[AVIN])),
                           F.add(F.add(per[AVOUT], per[ACARRY]),
                                 F.add(per[APUB], F.add(per[B0], per[B1])))))
        hold = F.sub(F.sub(1, setm), per[AFREE])
        terms = [
            F.mul(per[RCM], F.sub(nxt[AB], DOM_APPCM)), F.mul(per[RNF], F.sub(nxt[AB], DOM_APPNF)),
            F.mul(per[RNODE], F.sub(nxt[AB], A.DOM_NODE)), F.mul(per[ROUT], F.sub(nxt[AB], DOM_APPCM)),
            F.mul(per[ANSK], F.sub(nxt[AB], cur[NSK])), F.mul(per[ARHO], F.sub(nxt[AB], cur[RHO])),
            F.mul(per[AOWN], F.sub(nxt[AB], cur[OWN])), F.mul(per[AVIN], F.sub(nxt[AB], cur[VIN])),
            F.mul(per[AVOUT], F.sub(nxt[AB], cur[VOUT])),
            F.mul(per[ACARRY], F.sub(nxt[AB], cur[CARRY])),
            F.mul(per[APUB], F.sub(nxt[AB], per[PUBMSG])),
            F.mul(per[B0], F.sub(nxt[AB], left)), F.mul(per[B1], F.sub(nxt[AB], right)),
            F.mul(hold, F.sub(nxt[AB], cur[AB])),
        ]
        acc = 0
        for t in terms:
            acc = F.add(acc, t)
        return acc

    def _cap(cur, nxt, per, reg, sel):
        r0, _ = rnd(cur, per)
        return F.sub(nxt[reg], F.add(F.mul(per[sel], r0), F.mul(F.sub(1, per[sel]), cur[reg])))

    def c_carry(cur, nxt, per):
        """cm_in at COMMIT's end, then each intermediate Merkle node. The gap between those two is exactly
        where the NULLIFIER region reads it — which is why nf can bind cm at no extra register cost."""
        return _cap(cur, nxt, per, CARRY, CAPCARRY)

    def c_own(cur, nxt, per):
        return _cap(cur, nxt, per, OWN, CAPOWN)

    def c_nf(cur, nxt, per):
        return _cap(cur, nxt, per, NFREG, CAPNF)

    def c_root(cur, nxt, per):
        return _cap(cur, nxt, per, ROOTREG, CAPROOT)

    def c_hold(reg):
        """reg is constant over the trace, so every region reads the SAME secret value."""
        return lambda cur, nxt, per: F.sub(nxt[reg], cur[reg])

    def c_sib(cur, nxt, per):
        return F.mul(F.sub(1, per[RNODE]), F.sub(nxt[SIB], cur[SIB]))

    def c_dir(cur, nxt, per):
        return F.mul(F.sub(1, per[RNODE]), F.sub(nxt[DIR], cur[DIR]))

    def c_dirbit(cur, nxt, per):
        """DIR boolean inside membership — the child-selection interpolation is a swap only for DIR ∈ {0,1}."""
        return F.mul(per[INMERK], F.mul(cur[DIR], F.sub(1, cur[DIR])))

    def c_cons(cur, nxt, per):
        """The KIND_VALUE predicate, in-circuit: CONS = VIN - VOUT on every row, with the boundary pinning
        CONS to -public_delta. Integer-exact only together with the range gadget below."""
        return F.sub(cur[CONS], F.sub(cur[VIN], cur[VOUT]))

    def _nib(cur):
        return F.add(F.add(F.mul(8, cur[RB0]), F.mul(4, cur[RB1])), F.add(F.mul(2, cur[RB2]), cur[RB3]))

    def c_rng_acc(cur, nxt, per):
        return F.mul(per[RNG_ACC], F.sub(nxt[ACC], F.add(F.mul(16, cur[ACC]), _nib(cur))))

    def c_rng_reset(cur, nxt, per):
        return F.mul(per[RNG_START], cur[ACC])

    def c_rng_top(cur, nxt, per):
        """The MSB nibble's top RNG_TOP_BITS bits pinned to 0 → each bound value < RANGE_BOUND, the margin
        that makes the mod-P conservation equation coincide with integer conservation. Summed from the same
        constant RANGE_BOUND is computed from, so the two cannot disagree."""
        acc = 0
        for reg in (RB0, RB1, RB2, RB3)[:RNG_TOP_BITS]:
            acc = F.add(acc, cur[reg])
        return F.mul(per[RNG_START], acc)

    def c_bit(reg):
        return lambda cur, nxt, per: F.mul(per[RNG_ACC], F.mul(cur[reg], F.sub(1, cur[reg])))

    def c_bind(sel, val):
        return lambda cur, nxt, per: F.mul(per[sel], F.sub(cur[ACC], cur[val]))

    # ORDER MUST MATCH TRANSITION_NAMES. The names exist so a test can assert WHICH constraint catches a
    # given tamper, not merely that something did — without that, every constraint here could be deleted
    # one at a time with the suite still green, because the remaining ones cover for whichever is missing.
    # Measured: before the names, all eight constraints probed were individually removable in silence.
    return [c_s1, c_s0, c_ab, c_carry, c_own, c_nf, c_root,
            c_hold(NSK), c_hold(RHO), c_hold(VIN), c_hold(VOUT),
            c_sib, c_dir, c_dirbit, c_cons,
            c_rng_acc, c_rng_reset, c_rng_top,
            c_bit(RB0), c_bit(RB1), c_bit(RB2), c_bit(RB3),
            c_bind(RBIND_VIN, VIN), c_bind(RBIND_VOUT, VOUT)]


TRANSITION_NAMES = ("c_s1", "c_s0", "c_ab", "c_carry", "c_own", "c_nf", "c_root",
                    "hold_NSK", "hold_RHO", "hold_VIN", "hold_VOUT",
                    "c_sib", "c_dir", "c_dirbit", "c_cons",
                    "rng_acc", "rng_reset", "rng_top",
                    "bit_RB0", "bit_RB1", "bit_RB2", "bit_RB3",
                    "bind_VIN", "bind_VOUT")


# ---- prove / verify -----------------------------------------------------------------------------------
# BACKEND, stated once and passed explicitly at both ends. stark.prove's native arena covers only the
# alghash2 and recursion backends; anything else reaches require_native_prover and refuses on a node. The
# three join-split modules omit the argument, take backend.DEFAULT (blake2b), and are therefore unprovable
# in production — measured 2026-08-16, pinned by tests/test_joinsplit_backend_gap.py. Naming it here is the
# whole fix for this circuit, and it must be the SAME backend on both sides or the transcript diverges.
BACKEND = "alghash2"


def _boundaries(g, root, nf, cm_out, public_delta):
    """The public pins. CONS = v_in - v_out is pinned to -public_delta: that is the KIND_VALUE predicate
    itself, enforced in-circuit over the SECRET amounts, and it is integer-exact only because the range
    gadget bounds both values well below P."""
    return [(0, S0, alghash.DOM_OWNER), (0, S1, alghash.IV), (0, AB, alghash.DOM_OWNER),
            (0, CONS, F.sub(0, public_delta % F.P)),
            (g["out_end"], ROOTREG, root % F.P),
            (g["out_end"], NFREG, nf % F.P),
            (g["out_end"], S0, cm_out % F.P)]


def prove(nsk, cid_el, kind, fields_in, rho_in, siblings, dirs, fields_out, owner_out, rho_out,
          public_delta=0, num_queries=stark.NUM_QUERIES, aux=None):
    """Prove one private state transition. Returns (proof, root, nf, cm_out) — the proof plus exactly the
    public values it will be checked against. `aux` binds extra public data into the Fiat–Shamir transcript
    (the withdrawal destination, so an exit cannot be redirected — the pool's H-4 lesson)."""
    from execnode.stark import backend as BK
    arity = len(fields_in)
    tr, T, D, root, nf, cm_out = build_trace(nsk, cid_el, kind, fields_in, rho_in, siblings, dirs,
                                             fields_out, owner_out, rho_out)
    g = geometry(arity, D)
    proof = stark.prove(tr, transitions(), _boundaries(g, root, nf, cm_out, public_delta),
                        periodic=periodic(T, arity, D, cid_el, kind), max_degree=MAX_DEGREE,
                        num_queries=num_queries, aux=aux, backend=BK.get(BACKEND))
    proof["D"], proof["arity"] = D, arity
    return proof, root, nf, cm_out


def verify(proof, cid_el, kind, root, nf, cm_out, public_delta, root_is_known, aux=None):
    """Verify against the public statement alone. Returns (ok, reason).

    GEOMETRY IS PINNED, not read. D and arity come from the proof, but T is recomputed from them and
    compared — a prover who pads to a different power of two would otherwise present a trace the periodic
    columns do not describe (the join-split's H1 fix, inherited). cid and kind go into the periodic columns
    the verifier builds itself, so a proof cannot be re-presented as another contract's or another kind's."""
    from execnode.stark import backend as BK
    try:
        D, arity = int(proof["D"]), int(proof["arity"])
    except (KeyError, TypeError, ValueError):
        return False, "proof does not declare its geometry"
    if not (1 <= arity <= MAX_FIELDS) or not (1 <= D <= MAX_DEPTH):
        return False, (f"geometry out of range (arity 1..{MAX_FIELDS}, depth 1..{MAX_DEPTH}) — refused "
                       f"before building any column")
    if int(proof.get("T", -1)) != trace_len(arity, D):
        return False, "trace length does not match the declared geometry"
    if not root_is_known(root):
        return False, "unknown anchor root"
    g = geometry(arity, D)
    # stark.verify already returns (ok, reason) — return it straight through rather than re-wrapping, or
    # a falsy tuple gets nested inside another and every failure reads as the same opaque rejection.
    return stark.verify(proof, transitions(), _boundaries(g, root, nf, cm_out, public_delta),
                        periodic=periodic(int(proof["T"]), arity, D, cid_el, kind),
                        max_degree=MAX_DEGREE, aux=aux, backend=BK.get(BACKEND))


# =======================================================================================================
# THE DEPOSIT STATEMENT (0-in / 1-out) — how private state comes into existence at all.
#
# The transition above spends a note and creates a note. A DEPOSIT has nothing to spend: public coins
# become the FIRST private note. Without it, a chain with CONSENSUS_ALLOW_TRANSPARENT off can never create
# a note, so the whole feature cannot bootstrap — found by trying to write the worked example, which is
# what worked examples are for.
#
# WHY A PROOF IS NEEDED AT ALL when the amount is public. The deposited value IS public (it equals
# public_delta — the coins visibly left the ledger). What must stay hidden is WHO the note belongs to, so
# the opening cannot simply be published: revealing owner and rho would let anyone recompute cm and follow
# that note forever. The proof therefore attests one thing — this commitment commits to exactly the value
# that was escrowed — while hiding the owner. That is precisely Zcash's shielding property: the amount
# entering is public, the recipient is not.
#
# ONE AIR, TWO STATEMENTS. This deliberately reuses transitions() unchanged rather than adding a second
# constraint set. Every constraint the deposit does not need is satisfied trivially: the unused absorb and
# capture selectors are zero columns, so the capture registers hold at 0 and c_cons still reads
# CONS = VIN - VOUT with VIN = 0. A second AIR would be a second thing to audit, and the reason this one
# generalised so cleanly is that a deposit is a transition with its input regions selected out.
# =======================================================================================================

def deposit_geometry(arity):
    """Only the OUTPUT region and the range blocks — no OWNER, COMMIT, NULLIFIER or MEMBERSHIP. Row 0
    starts the sponge directly from the boundary (the same way the transition trace starts OWNER), so no
    reset row is needed ahead of it."""
    ce = cm_elems(arity)
    out_end = ce * R
    return {"ce": ce, "out_start": 0, "out_end": out_end,
            "total": out_end + RNG_VALUES * RNG_BLOCK}


def deposit_trace_len(arity):
    return _next_pow2(deposit_geometry(arity)["total"] + 1)


def deposit_absorb_schedule(arity, cid_el, kind):
    """{row: (source, value)} — the public head, the value, then the opening as free witness."""
    head = [(PUB, cid_el), (PUB, kind), (PUB, arity)]
    body = [(REG_VOUT, 0)] + [(FREE, 0)] * (arity - 1)
    return {i * R - 1: ent for i, ent in enumerate(head + body + [(FREE, 0), (FREE, 0)], start=1)}


def deposit_periodic(T, arity, cid_el, kind):
    """The same 26 columns; every selector the deposit does not use is a zero column, which is what lets
    transitions() be reused verbatim."""
    g = deposit_geometry(arity)
    sched = deposit_absorb_schedule(arity, cid_el, kind)
    out_end, total = g["out_end"], g["total"]

    def col(fn):
        return [1 if fn(r) else 0 for r in range(T)]

    def src_is(*want):
        return col(lambda r: r in sched and sched[r][0] in want and r < out_end - 1)

    rng = lambda r: out_end <= r < total
    p = [[0] * T for _ in range(NPER)]
    p[RC0] = [alghash.RC[r % R][0] for r in range(T)]
    p[RC1] = [alghash.RC[r % R][1] for r in range(T)]
    p[AVOUT] = src_is(REG_VOUT)
    p[AFREE] = src_is(FREE)
    p[APUB] = src_is(PUB)
    p[PUBMSG] = [(sched[r][1] % F.P) if (r in sched and sched[r][0] == PUB and r < out_end - 1) else 0
                 for r in range(T)]
    p[RNG_ACC] = col(lambda r: rng(r) and (r - out_end) % RNG_BLOCK < RNG_NIBBLES)
    p[RNG_START] = col(lambda r: rng(r) and (r - out_end) % RNG_BLOCK == 0)
    p[RBIND_VIN] = col(lambda r: r == out_end + 0 * RNG_BLOCK + RNG_NIBBLES)
    p[RBIND_VOUT] = col(lambda r: r == out_end + 1 * RNG_BLOCK + RNG_NIBBLES)
    return p


def build_deposit_trace(cid_el, kind, fields_out, owner_out, rho_out):
    """The honest deposit witness. VIN stays 0 throughout, so c_cons reads CONS = -v_out and the boundary
    pins it to -public_delta exactly as it does for a transition."""
    arity = len(fields_out)
    g = deposit_geometry(arity)
    T = deposit_trace_len(arity)
    owner_out, rho_out = owner_out % F.P, rho_out % F.P
    v_out = fields_out[0] % F.P
    sched = deposit_absorb_schedule(arity, cid_el, kind)
    cons = F.sub(0, v_out)
    rfill = _range_fill(g["out_end"], (0, fields_out[0]))
    tr = []
    s0, s1, ab = DOM_APPCM, alghash.IV, DOM_APPCM
    free_msgs = [f % F.P for f in fields_out[1:]] + [owner_out, rho_out]
    free_i = 0
    for r in range(T):
        acc, rb0, rb1, rb2, rb3 = rfill.get(r, (0, 0, 0, 0, 0))
        tr.append([s0, s1, ab, 0, 0, 0, 0, 0, 0, 0, 0, v_out, cons, 0,
                   acc, rb0, rb1, rb2, rb3])
        r0, r1 = _round(s0, s1, r)
        if r in sched and r < g["out_end"] - 1:
            src, val = sched[r]
            if src == PUB:
                msg = val % F.P
            elif src == REG_VOUT:
                msg = v_out
            else:
                msg = free_msgs[free_i]
                free_i += 1
            s0, s1, ab = F.add(r0, msg), r1, msg
        else:
            s0, s1 = r0, r1
    return tr, T, note_cm(cid_el, kind, fields_out, owner_out, rho_out)


def _deposit_boundaries(g, cm_out, public_delta):
    """Row 0 opens the OUTPUT sponge directly. ROOTREG and NFREG are pinned to 0 — a deposit proves no
    membership and reveals no nullifier, and pinning them is what stops a transition proof being presented
    as a deposit or the reverse."""
    return [(0, S0, DOM_APPCM), (0, S1, alghash.IV), (0, AB, DOM_APPCM),
            (0, CONS, F.sub(0, public_delta % F.P)),
            (g["out_end"], ROOTREG, 0),
            (g["out_end"], NFREG, 0),
            (g["out_end"], S0, cm_out % F.P)]


def prove_deposit(cid_el, kind, fields_out, owner_out, rho_out, public_delta,
                  num_queries=stark.NUM_QUERIES, aux=None):
    """Prove that `cm_out` commits to exactly the escrowed value, hiding its owner. Returns (proof, cm_out)."""
    from execnode.stark import backend as BK
    arity = len(fields_out)
    tr, T, cm_out = build_deposit_trace(cid_el, kind, fields_out, owner_out, rho_out)
    g = deposit_geometry(arity)
    proof = stark.prove(tr, transitions(), _deposit_boundaries(g, cm_out, public_delta),
                        periodic=deposit_periodic(T, arity, cid_el, kind), max_degree=MAX_DEGREE,
                        num_queries=num_queries, aux=aux, backend=BK.get(BACKEND))
    proof["arity"], proof["deposit"] = arity, True
    return proof, cm_out


def verify_deposit(proof, cid_el, kind, cm_out, public_delta, aux=None):
    """Verify a deposit against its public statement. Returns (ok, reason)."""
    from execnode.stark import backend as BK
    if not proof.get("deposit"):
        return False, "not a deposit proof"
    try:
        arity = int(proof["arity"])
    except (KeyError, TypeError, ValueError):
        return False, "proof does not declare its geometry"
    if not (1 <= arity <= MAX_FIELDS):
        return False, (f"geometry out of range (arity 1..{MAX_FIELDS}) — refused before building any "
                       f"column")
    if int(proof.get("T", -1)) != deposit_trace_len(arity):
        return False, "trace length does not match the declared geometry"
    if int(public_delta) <= 0:
        return False, "a deposit must bring value in"
    g = deposit_geometry(arity)
    return stark.verify(proof, transitions(), _deposit_boundaries(g, cm_out, public_delta),
                        periodic=deposit_periodic(int(proof["T"]), arity, cid_el, kind),
                        max_degree=MAX_DEGREE, aux=aux, backend=BK.get(BACKEND))
