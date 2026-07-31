"""
ML-DSA-44 — the ASSEMBLED SIGNATURE PROOF: every sub-circuit of one signature verification, proven and folded
into ONE heterogeneous recursion bundle (execnode/stark/recursive_verify_hetero).

WHY HETEROGENEOUS. The sub-circuits have genuinely different AIRs — the Keccak permutation is 6080 boolean
columns over 32 rows, the norm/decode/UseHint circuits are narrow range-check tables, the NTT butterfly is its
own shape. `recursive_verify.prove` requires one shared AIR shape, so a single homogeneous fold cannot bind
them; `recursive_verify_hetero.prove_hetero` folds proofs of DIFFERENT AIRs into one bundle (one FRI fold plus
one composition per distinct AIR), which is exactly this assembly.

WHAT THE BUNDLE ATTESTS. Each sub-proof is pinned to its own PUBLIC statement by boundaries (the decoded
coefficients, the range rows, the butterflies, the permutation states). The verifier rebuilds every one of
those statements from the PUBLIC (pk, msg, sig) via mldsa_verify — the same deterministic derivation the
reference performs — and then checks the single bundle against them. So the bundle proves the arithmetic while
the CHAINING (which value feeds which circuit) is verifier-derived and unforgeable, the same division of labour
the sponge uses.

SCOPE. `plan()` derives the full per-signature workload and the exact sub-proof list. `prove_signature()` proves
and folds a chosen SUBSET of that plan (`parts=`), because a full ML-DSA signature is 103 Keccak permutations —
minutes each — so the complete bundle is a proving-farm job, not a unit test. The subset path is the same code:
what changes with scale is time, not correctness. `verify_signature()` rebuilds the statements and verifies the
bundle.

Golden reference for every statement: mldsa_verify (which agrees with the native RustCrypto ml-dsa backend).
"""
from execnode.stark import (mldsa_params as P, mldsa_verify as MV, mldsa_norm_air as NORM,
                            mldsa_decode_air as DEC, mldsa_hint_air as HINT, mldsa_keccak_air as KEC,
                            mldsa_sponge_air as SP, mldsa_sample_air as SA, mldsa_butterfly_air as BF, mldsa_modq_air as MQ, stark,
                            recursive_verify as RV, recursive_verify_hetero as RVH, backend as B)

Q, N, K, L = P.Q, P.N, P.K, P.L

# the sub-circuit parts an assembled signature proof is made of, in verification order
PARTS = ("decode_z", "norm_z", "decode_t1", "usehint", "keccak")


def plan(pk, msg, sig):
    """The full statement + workload of ONE signature verification: what each sub-proof must cover.
    Everything here is derived from the PUBLIC (pk, msg, sig), so the verifier builds the identical plan."""
    up, us = MV.unpack_pk(pk), MV.unpack_sig(sig)
    if up is None or us is None:
        return None
    rho, t1 = up
    c_tilde, z, h = us
    z_bytes = sig[P.C_TILDE_BYTES:P.C_TILDE_BYTES + L * MV.Z_BYTES]
    t1_bytes = pk[32:]
    # the w' the UseHint rows are taken over (the same computation mldsa_verify performs)
    return {
        "rho": rho, "c_tilde": c_tilde,
        "z_chunks": [z_bytes[i * MV.Z_BYTES:(i + 1) * MV.Z_BYTES] for i in range(L)],
        "t1_chunks": [t1_bytes[i * MV.T1_BYTES:(i + 1) * MV.T1_BYTES] for i in range(K)],
        "z_coeffs": [c % Q for poly in z for c in poly],
        "hint_rows": _hint_rows(pk, msg, sig),
        "ntt_rows": ntt_rows(pk, msg, sig),
        "ntt_mul_rows": ntt_mul_rows(pk, msg, sig),
        "workload": MV.statement(pk, msg, sig),
    }


def _w_prime(pk, msg, sig, collect=False):
    """Recompute w' = NTT^-1(A.NTT(z) - NTT(c)*NTT(t1*2^d)) — the input to UseHint.

    `collect=True` also returns every butterfly this computation performs, in order. Those rows ARE the
    arithmetic that has never been in any circuit: today w' is handed to the usehint AIR as a PUBLIC input,
    so a verifier redoes this whole NTT matrix-vector product itself. Emitting them is what lets the "ntt"
    part attest it instead. The list is large by construction -- 9 forward NTTs and 4 inverse at 1024
    butterflies each, plus 5120 pointwise products, ~18432 rows per signature -- which is exactly why the
    row budget, not the field arithmetic, is what decides whether this is affordable.
    """
    from execnode.stark import mldsa_ntt_air as NTT
    rho, t1 = MV.unpack_pk(pk)
    c_tilde, z, h = MV.unpack_sig(sig)
    A = SA.expand_a(rho)
    c, _ = SA.sample_in_ball(c_tilde)
    # TWO ROW TYPES, NOT ONE. The NTT stages emit BUTTERFLIES (a, b, zeta) proven by mldsa_butterfly_air
    # (W=193), while the pointwise products emit (a, b) PAIRS proven by the mod-Q gadget mldsa_modq_air
    # (W=96). Collecting them into one list is wrong and only looked right because every slice up to 1024
    # rows lands inside the first forward NTT, before any pointwise pair appears -- the full 18432-row run
    # is what exposed it ("not enough values to unpack (expected 3, got 2)"). Per signature:
    # 13312 butterflies (9 forward + 4 inverse NTTs x 1024) and 5120 products (16 A.z + 4 c.t1, x 256).
    rows = {"bfs": [], "muls": []} if collect else None

    def _keep(pair, kind):
        val, emitted = pair
        if collect and emitted:
            rows[kind].extend(emitted)
        return val

    c_hat = _keep(NTT.apply_forward([x % Q for x in c]), "bfs")
    z_hat = [_keep(NTT.apply_forward([x % Q for x in poly]), "bfs") for poly in z]
    t1_hat = [_keep(NTT.apply_forward([(x << P.D) % Q for x in poly]), "bfs") for poly in t1]
    out = []
    for i in range(K):
        acc = [0] * N
        for j in range(L):
            prod = _keep(NTT.pointwise(A[i][j], z_hat[j]), "muls")
            acc = [(a + b) % Q for a, b in zip(acc, prod)]
        ct = _keep(NTT.pointwise(c_hat, t1_hat[i]), "muls")
        out.append(_keep(NTT.apply_inverse([(a - b) % Q for a, b in zip(acc, ct)]), "bfs"))
    return (out, h, rows) if collect else (out, h)


def _hint_rows(pk, msg, sig):
    """The (r, h) UseHint rows for the whole signature."""
    w, h = _w_prime(pk, msg, sig)
    return [(w[i][n], h[i][n]) for i in range(K) for n in range(N)]


NTT_ROWS = 64          # rows of the w' butterfly schedule this part attests (see prove_signature's docstring)


def ntt_rows(pk, msg, sig, limit=NTT_ROWS):
    """The first `limit` BUTTERFLIES of the w' computation (mldsa_butterfly_air rows)."""
    _w, _h, r = _w_prime(pk, msg, sig, collect=True)
    return r["bfs"][:limit]


def ntt_mul_rows(pk, msg, sig, limit=NTT_ROWS):
    """The first `limit` pointwise PRODUCTS of the w' computation (mldsa_modq_air rows)."""
    _w, _h, r = _w_prime(pk, msg, sig, collect=True)
    return r["muls"][:limit]


def _air_specs(plan_, parts, sizes):
    """The AIR DESCRIPTOR of each requested sub-circuit — transitions, boundaries and periodic columns — with
    NO proving. `sizes[i]` is that sub-proof's trace length T, which the verifier reads out of the bundle's
    published geometry.

    Split out of _items deliberately. The verifier needs exactly this and nothing else; calling _items would
    have re-PROVEN every sub-circuit to recover its boundaries, which is both absurdly expensive and a
    verifier doing the prover's job — the kind of mistake that looks like it works, because the answer comes
    out right.

    Every value here is derived from the PLAN, which is itself a pure function of the public (pk, msg, sig).
    So the statement a bundle is checked against is the verifier's own, and a bundle proved for a different
    signature cannot be replayed onto this one."""
    airs, i = [], 0

    def take():
        nonlocal i
        t = int(sizes[i]); i += 1
        return t

    if "decode_z" in parts:
        chunk = plan_["z_chunks"][0]
        coeffs = [(P.GAMMA_1 - w) for w in DEC.bit_unpack(chunk, DEC.BITS_Z)]
        airs.append({"transitions": DEC.transitions(DEC.BITS_Z, P.GAMMA_1),
                     "boundaries": DEC._boundaries(coeffs, take())})
    if "decode_t1" in parts:
        chunk = plan_["t1_chunks"][0]
        coeffs = list(DEC.bit_unpack(chunk, DEC.BITS_T1))
        airs.append({"transitions": DEC.transitions(DEC.BITS_T1, None),
                     "boundaries": DEC._boundaries(coeffs, take())})
    if "norm_z" in parts:
        zc = plan_["z_coeffs"][:64]
        airs.append({"transitions": NORM.transitions(), "boundaries": NORM._boundaries(zc, take())})
    if "usehint" in parts:
        rows = plan_["hint_rows"][:64]
        airs.append({"transitions": HINT.transitions(), "boundaries": HINT._boundaries(rows, take())})
    if "ntt" in parts:
        bfs = plan_["ntt_rows"]
        airs.append({"transitions": BF.transitions(), "boundaries": BF._boundaries(bfs, take())})
    if "ntt_mul" in parts:
        pairs = plan_["ntt_mul_rows"]
        airs.append({"transitions": MQ.transitions(), "boundaries": MQ._boundaries(pairs, take())})
    if "keccak" in parts:
        st = [0] * KEC.LANES
        out = KEC.keccak_f(list(st))
        T = take()
        airs.append({"transitions": KEC.transitions(), "boundaries": KEC._boundaries(st, out, T),
                     "periodic": KEC.periodic(T)})
    if i != len(sizes):
        raise ValueError(f"bundle declares {len(sizes)} sub-proofs but `parts` names {i}")
    return airs


def _items(plan_, parts, num_queries):
    """Prove each requested sub-circuit and return the hetero recursion items + their AIR descriptors."""
    bk = B.RECURSION
    items, airs = [], []

    def add(proof, transitions, boundaries, periodic=None):
        it = {"proof": proof, "transitions": transitions, "boundaries": boundaries}
        air = {"transitions": transitions, "boundaries": boundaries}
        if periodic is not None:
            it["periodic"] = periodic; air["periodic"] = periodic
        items.append(it); airs.append(air)

    if "decode_z" in parts:                                  # one z polynomial's bit-unpack
        chunk = plan_["z_chunks"][0]
        pr, coeffs = DEC.prove_field(chunk, "z", num_queries=num_queries, backend=bk)
        add(pr, DEC.transitions(DEC.BITS_Z, P.GAMMA_1), DEC._boundaries(coeffs, pr["T"]))
    if "decode_t1" in parts:
        chunk = plan_["t1_chunks"][0]
        pr, coeffs = DEC.prove_field(chunk, "t1", num_queries=num_queries, backend=bk)
        add(pr, DEC.transitions(DEC.BITS_T1, None), DEC._boundaries(coeffs, pr["T"]))
    if "norm_z" in parts:                                    # the ||z||inf bound over a slice of coefficients
        zc = plan_["z_coeffs"][:64]
        pr = NORM.prove(zc, num_queries=num_queries, backend=bk)
        add(pr, NORM.transitions(), NORM._boundaries(zc, pr["T"]))
    if "usehint" in parts:
        rows = plan_["hint_rows"][:64]
        pr = HINT.prove(rows, num_queries=num_queries, backend=bk)
        add(pr, HINT.transitions(), HINT._boundaries(rows, pr["T"]))
    if "ntt" in parts:                                       # butterflies of the w' NTT matrix-vector product
        bfs = plan_["ntt_rows"]
        pr = BF.prove(bfs, num_queries=num_queries, backend=bk)
        add(pr, BF.transitions(), BF._boundaries(bfs, pr["T"]))
    if "ntt_mul" in parts:                                   # pointwise products of the w' matrix-vector
        pairs = plan_["ntt_mul_rows"]
        pr = MQ.prove(pairs, num_queries=num_queries, backend=bk)
        add(pr, MQ.transitions(), MQ._boundaries(pairs, pr["T"]))
    if "keccak" in parts:                                    # one proven Keccak-f permutation
        st = [0] * KEC.LANES
        pr, out = KEC.prove_permutation(st, num_queries=num_queries, backend=bk)
        T = pr["T"]
        add(pr, KEC.transitions(), KEC._boundaries(st, out, T), KEC.periodic(T))
    return items, airs


def prove_signature(pk, msg, sig, parts=("decode_z", "norm_z", "usehint"),
                    num_queries=2, num_queries_outer=2):
    """Prove the requested sub-circuits of this signature and FOLD them into ONE heterogeneous bundle.
    Returns (bundle, publics, airs) or None if the signature does not verify natively (never prove a lie)."""
    if not MV.verify(pk, msg, sig):
        return None
    pl = plan(pk, msg, sig)
    if pl is None:
        return None
    items, airs = _items(pl, parts, num_queries)
    bundle = RVH.prove_hetero(items, num_queries_outer=num_queries_outer)
    publics = [RV.public_part(it["proof"]) for it in items]
    return bundle, publics, airs


def verify_signature(bundle, publics, airs, num_queries=2, num_queries_outer=2):
    """Verify the folded bundle. The AIR descriptors carry each sub-circuit's public statement (its
    boundaries), which the caller rebuilds from the public (pk, msg, sig) — so a bundle cannot be replayed
    against a different signature. Returns (ok, reason)."""
    return RVH.verify_hetero(publics, airs, bundle, num_queries_outer=num_queries_outer,
                             num_queries_inner=num_queries)


# ---- BLOCK-LEVEL AGGREGATION --------------------------------------------------------------------------
# What ops/block_ops.verify_auth_proof calls when a block ships a stark authorization envelope. The
# statement is built by mldsa_block_auth from the VERIFIER's own recomputation — the envelope contributes
# only the proof itself, so a prover cannot choose what it is proving.
#
# WHAT THIS BUYS TODAY, PRECISELY: the sub-circuit statements are rebuilt from the public (pk, msg, sig),
# so the signature is a PUBLIC input and the block still carries it. The envelope therefore replaces the
# VERIFICATION ARITHMETIC of K signatures with one bundle check, not their bytes. Moving the signature into
# the witness (so the block can drop it) is an AIR change — every sub-circuit that currently pins a
# sig-derived value as a boundary must instead bind it in-circuit — and it is the next phase, not a
# configuration flag. Saying so here rather than in a design doc, because the gap is invisible from the
# call site: an envelope that "verifies" looks like aggregation whether or not it saves anything.

BLOCK_AUTH_CIRCUIT_V1 = "mldsa44-block-auth-v1"


def verify_block_authorizations(circuit_id, proof, statement):
    """Verify one aggregate authorization envelope against a verifier-derived statement.

    `proof` = {"bundles": [ {"publics": ..., "airs": ...}, ... ]} — one entry per authorization, in the
    statement's own entry order. Returns True only if EVERY entry is covered and every bundle verifies
    against the statement this verifier built. False on anything unexpected: an envelope that cannot be
    checked is not evidence."""
    if circuit_id != BLOCK_AUTH_CIRCUIT_V1:
        return False
    if not isinstance(proof, dict) or not isinstance(statement, dict):
        return False
    entries = statement.get("entries") or []
    pubkeys = statement.get("pubkeys") or []
    wits = statement.get("witnesses") or []
    if not (len(entries) == len(pubkeys) == len(wits) == int(statement.get("auth_count", -1))):
        return False
    bundles = proof.get("bundles")
    if not isinstance(bundles, list) or len(bundles) != len(entries):
        return False            # one bundle per authorization — a short list would leave checks unproven
    for e, pk, sig, b in zip(entries, pubkeys, wits, bundles):
        if not pk or not sig:
            return False        # unresolved key or missing signature: nothing to have proven
        if not isinstance(b, dict):
            return False
        # The AIR descriptors ARE the statement: they are rebuilt here from (pk, txid, sig) so a bundle
        # proved against a different signature cannot be replayed onto this entry.
        try:
            msg = bytes.fromhex(e["txid"]) if isinstance(e["txid"], str) else bytes(e["txid"])
            pkb = bytes.fromhex(pk) if isinstance(pk, str) else bytes(pk)
            sgb = bytes.fromhex(sig) if isinstance(sig, str) else bytes(sig)
        except Exception:
            return False
        pl = plan(pkb, msg, sgb)
        if pl is None:
            return False
        parts = tuple(b.get("parts") or ())
        if not parts:
            return False        # a bundle covering nothing proves nothing
        pubs = b.get("publics")
        if not isinstance(pubs, list) or not pubs:
            return False
        try:
            airs = _air_specs(pl, parts, [int(x["T"]) for x in pubs])
        except Exception:
            return False
        ok, _why = verify_signature(b.get("bundle"), pubs, airs,
                                    num_queries=int(b.get("num_queries", 2)),
                                    num_queries_outer=int(b.get("num_queries_outer", 2)))
        if not ok:
            return False
    return True
