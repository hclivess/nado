"""
FRI — the Fast Reed–Solomon Interactive Oracle Proof of Proximity (doc/privacy.md). This is the engine of a
STARK: a succinct, POST-QUANTUM (hash-only) argument that a Merkle-committed vector of evaluations is (close
to) a polynomial of low degree. A STARK reduces "this execution trace satisfies the constraints" to "these
composed polynomials are low-degree", and FRI is what proves the latter cheaply.

How it works: repeatedly FOLD the polynomial in half using a Fiat–Shamir challenge — f(x) = f_e(x²) + x·f_o(x²),
folded g(x²) = f_e(x²) + α·f_o(x²) — halving the degree AND the domain each round, committing every layer's
Merkle root, until the polynomial is tiny (sent in the clear). The verifier spot-checks, at random points, that
each layer really is the fold of the previous one (with Merkle openings) and that the final layer is low-degree.

Soundness rests only on BLAKE2b collision-resistance (via the Merkle commitments + the transcript).
"""
from execnode.stark import field as F, merkle, extf as ext2, alghash2 as a2
from execnode.stark.transcript import Transcript
from execnode.stark import backend as _backend

INV2 = F.inv(2)

# Protocol-fixed FRI parameters. These are NOT read from the proof — a prover that under-declares the query
# count or drops folding layers was the C-1 total soundness bypass (an empty `queries`/`roots` list skipped
# every check). The verifier derives the whole FRI shape from N + FRI_BLOWUP and requires exactly NUM_QUERIES
# openings. stark.prove always calls fri.prove with fri_blowup == 2, so FRI_BLOWUP is fixed at 2.
#
# C-1 soundness sizing: at FRI_BLOWUP=2 (rate 1/2) each query contributes ~0.4 bit (provable / Johnson-bound) /
# ~1 bit (conjectured / list-decoding) of soundness, plus GRIND_BITS of transcript proof-of-work
# (transcript.grind) that adds soundness UNCONDITIONALLY (a forger redoes 2^GRIND_BITS work per Fiat-Shamir
# attempt, independent of any FRI conjecture). Sized to clear 128 bits on the PROVABLE (unconditional-modulo-
# collision-resistance) branch — not merely the conjectured branch that most STARK deployments settle for —
# BEFORE settlement ever trusts a proof:
#     320 queries · 0.4  +  18 grind  ≈  146 bits PROVABLE (Johnson),  and
#     320 queries · 1.0  +  18 grind  ≈  338 bits CONJECTURED (list-decoding).
# Raising NUM_QUERIES is the geometry-PRESERVING lever: it costs ~linear proof size (more Merkle openings) but
# does NOT change the FRI rate/fold shape — so it leaves the recursion subsystem, which arithmetizes the FRI
# fold geometry in-circuit (the fixed 16-row alghash2 block anatomy in recursion.py/fri_verify.py), untouched.
# The prover's dominant cost (the LDE + Merkle tree) is UNCHANGED by query count; only the opening set grows.
# GRIND_BITS stays 18 (EXPONENTIAL time; +10 bits ≈ 1000x grind) AND because the in-circuit recursion grind
# check is calibrated to it. FRI_BLOWUP stays 2 for the SAME reason: a lower rate gives more bits/query but
# changes the fold shape, which would ripple into every recursion AIR. Tests pass an explicit reduced count.
NUM_QUERIES = 320
FRI_BLOWUP = 2
GRIND_BITS = 18

# EXT_CHALLENGES: draw the FRI folding challenge from GF(p^2) instead of the base field.
# Commit-phase error is ~n/|challenge space|, so a base-field alpha pins PROVABLE
# soundness at 64 - log2(n) ~ 47 bits however the query budget is set. GF(p^D) lifts the
# ceiling to ~D*64 - log2(n); at D=3 the commit phase stops being the binding term at all
# and the bound passes to the query phase, which does not decay with trace size.
#   python3 -m execnode.stark.soundness
# Layer 0 stays base-field UNLESS the input is already extension-valued (a DEEP quotient --
# `ext0`); every layer after the first fold is extension-valued either way. This CHANGES THE
# PROOF FORMAT: ext layers commit a leaf digest over the whole limb tuple (alghash2.leaf_ext,
# ONE permutation, not one per limb), and `final` is a list of tuples.
# EVERYTHING IS PORTED: the arena (native/starkprove, degree-generic, handshake-checked against
# extf.DEGREE) and the in-circuit recursion AIRs (fri_verify, comp_verify, rowcomp_verify).
EXT_CHALLENGES = True


def _expected_layers(N, blowup):
    """Number of fold layers stark/fri produces for a size-N domain: fold while size > blowup."""
    layers, n = 0, N
    while n > blowup:
        n //= 2
        layers += 1
    return layers


def _fold(evals, dom, alpha):
    """One FRI fold: evals of f on coset `dom` (size n) -> evals of g on the squared coset (size n/2), where
    g(x²) = (f(x)+f(-x))/2 + α·(f(x)-f(-x))/(2x). The pair (x, -x) sits at indices (i, i+n/2)."""
    half = len(evals) // 2
    out = [0] * half
    for i in range(half):
        fx, fmx, x = evals[i], evals[i + half], dom[i]
        fe = F.mul(F.add(fx, fmx), INV2)
        fo = F.mul(F.sub(fx, fmx), F.mul(INV2, F.inv(x)))
        out[i] = F.add(fe, F.mul(alpha, fo))
    return out


def _fold_ext(evals, dom, alpha):
    """One FRI fold with a GF(p^2) challenge. Same identity as _fold. `evals` may be base
    ints (layer 0) or ext pairs; `dom` is base-field; `alpha` is an ext pair. fe/fo scale
    by BASE constants, so only the single alpha*fo is a full extension multiply."""
    half = len(evals) // 2
    out = [None] * half
    for i in range(half):
        fx, fmx, x = ext2.lift(evals[i]), ext2.lift(evals[i + half]), dom[i]
        fe = ext2.scalar_mul(ext2.add(fx, fmx), INV2)
        fo = ext2.scalar_mul(ext2.sub(fx, fmx), F.mul(INV2, F.inv(x)))
        out[i] = ext2.add(fe, ext2.mul(alpha, fo))
    return out


def _ext_leaf(b, v):
    """Leaf digest for a GF(p^2) value — ONE hash of the frame (tag, lo, hi).

    Was node(leaf(a0), leaf(a1)), which needed no new backend opcode but cost THREE hashes. Affordable
    natively, ruinous IN-CIRCUIT: the recursion membership AIR spends one permutation block per hash, so an
    ext leaf tripled the leaf stage — and the compression's second input is the previous block's DIGEST, a
    value the path machinery supplies as a free witness sibling and would now have to constrain equal to a
    computed digest. That linkage does not exist in the AIR, and it is what kept the recursion path pinned to
    base-field arithmetic (hence ~47 bits) after FRI, DEEP and the alphas had all been lifted.

    b.leaf_ext packs both limbs into the single existing frame — alghash2's rleaf already leaves lanes 2..3
    unused — so the in-circuit gadget differs from the base one only by pinning one more lane. It carries its
    OWN domain tag, so an ext leaf and a base leaf stay distinct frames even when the hi limb is zero."""
    return b.leaf_ext(*ext2.lift(v))


def _commit_ext(values, b):
    """Merkle-commit a layer of EXTENSION values.

    Tries the native whole-tree build first. Without it this loop ran n leaf permutations plus n-1 node
    permutations in PYTHON on every folded layer — the dominant cost of an extension proof, and it lands on
    the settlement fold, which is what the extension migration exists to make sound.

    The native build is selected by BACKEND, not guessed: the recursion backend commits with one permutation
    per node (rleaf_ext/rnode) and the sponge backend with hashn frames, and using the wrong one produces a
    well-formed tree with the wrong root. Anything unexpected — no lib, unknown backend, a degree the frame
    cannot hold — falls back to the identical Python path rather than to an approximation."""
    limbs = [ext2.lift(v) for v in values]
    name = getattr(b, "name", "")
    _nat = None
    if name == "recursion":
        _nat = a2.rmerkle_commit_ext(limbs)
    elif name == "alghash2":
        _nat = a2.merkle_commit_ext(limbs)
    if _nat is not None:
        return _nat
    return merkle.commit_digests([_ext_leaf(b, v) for v in values], b)


def _coset_interpolate_ext(evals, offset):
    """Interpolation is F_p-LINEAR and GF(p^D) is a rank-D F_p-module, so the LIMBS interpolate separately
    and recombine exactly. No extension NTT needed — which is why the degree can move without touching the
    NTT at all."""
    lim = [ext2.lift(v) for v in evals]
    per_limb = [_coset_interpolate([e[k] for e in lim], offset) for k in range(ext2.DEGREE)]
    return [tuple(per_limb[k][i] for k in range(ext2.DEGREE)) for i in range(len(per_limb[0]))]


def _coset_interpolate(evals, offset):
    """Coefficients of f, given its evaluations on the coset {offset·ω^i}. Interpolate g(y)=f(offset·y) on the
    subgroup via iNTT, then rescale: f_j = g_j · offset^-j."""
    g = F.interpolate(evals)                     # g_j : g(ω^i) = evals[i]
    inv_off = F.inv(offset)
    scale = 1
    coeffs = []
    for gj in g:
        coeffs.append(F.mul(gj, scale))
        scale = F.mul(scale, inv_off)
    return coeffs


def prove(evals, offset, blowup=4, num_queries=NUM_QUERIES, transcript=None, backend=None,
          ext=None):
    """Prove deg(f) < len(evals)/blowup, where `evals` are f on the coset of size N=len(evals) with shift
    `offset`. Returns a proof dict. `blowup` (the Reed–Solomon rate denominator) sets both the claimed degree
    bound and the soundness per query."""
    from execnode.stark.native_guard import require_native_prover
    require_native_prover("fri.py:prove")
    b = backend or _backend.DEFAULT
    t = transcript or Transcript("fri", backend=b)
    use_ext = EXT_CHALLENGES if ext is None else bool(ext)
    N = len(evals)
    layers, roots = [], []
    cur, off = list(evals), offset
    dom = F.domain(N, off)
    # LAYER-0 EXT-NESS IS DATA-DRIVEN, not positional. For stark's composition the layer-0 evaluations are
    # base-field, but a DEEP quotient (P-v)/(x-z) with an EXT point z is ext-valued from layer 0 onward, and
    # committing those as base ints would corrupt the leaves. Decide from the values themselves and record it,
    # so the verifier hashes the same leaves; a prover that lies here simply fails its own Merkle openings.
    ext0 = bool(use_ext and cur and not isinstance(cur[0], int))
    depth = 0
    while len(cur) > blowup:
        is_ext_layer = use_ext and (depth > 0 or ext0)
        root, mlayers = (_commit_ext(cur, b) if is_ext_layer else merkle.commit(cur, b))
        roots.append(root); t.absorb(root)
        layers.append({"evals": cur, "mlayers": mlayers, "dom": dom, "off": off})
        if use_ext:
            cur = _fold_ext(cur, dom, t.challenge_ext())
        else:
            cur = _fold(cur, dom, t.challenge())
        off = F.mul(off, off)
        dom = F.domain(len(cur), off)
        depth += 1
    final = cur                                  # small -> sent in the clear
    t.absorb("final", *(ext2.flatten(final) if use_ext else final))
    pow_nonce = t.grind(GRIND_BITS)              # C-1: proof-of-work before query derivation (unconditional bits)

    queries = []
    for _ in range(num_queries):
        idx = t.challenge_index(N)               # a position in the layer-0 domain
        steps = []
        a = idx
        for L in layers:
            n = len(L["evals"]); half = n // 2
            a %= n
            lo = a % half                        # the pair is (lo, lo+half)
            steps.append({
                "lo": L["evals"][lo], "lo_path": merkle.open_at(L["mlayers"], lo),
                "hi": L["evals"][lo + half], "hi_path": merkle.open_at(L["mlayers"], lo + half),
            })
            a = lo
        queries.append({"idx": idx, "steps": steps})

    return {"N": N, "offset": offset, "blowup": blowup, "roots": roots, "final": final,
            "pow": pow_nonce, "queries": queries, "ext": use_ext, "ext0": ext0}


def verify(proof, transcript=None, num_queries=None, expected_blowup=None, backend=None,
           expected_ext=None):
    """Verify a FRI proof. Returns (ok, reason).

    C-1: `num_queries` and `expected_blowup`, when given, are the caller's PROTOCOL values — the verifier
    refuses a proof that declares anything else. stark.verify always passes them (fixed query count +
    fri_blowup==2), so a prover can't drop folding layers, shrink the query set, or inflate `final` to make
    the low-degree test vacuous (all of which the old verifier accepted — an empty proof returned True). The
    FRI geometry (layer count, final-layer size) is always derived from N + blowup and enforced for
    self-consistency; the standalone primitive tests call this without the protocol values.
    """
    try:
        N, offset, blowup = proof["N"], proof["offset"], proof["blowup"]
        roots, final, queries = proof["roots"], proof["final"], proof["queries"]

        if not isinstance(N, int) or N < 2 or (N & (N - 1)) != 0:
            return False, "bad FRI domain size"
        if not isinstance(blowup, int) or blowup < 2 or (blowup & (blowup - 1)) != 0:
            return False, "bad FRI blowup"
        if expected_blowup is not None and blowup != expected_blowup:
            return False, "unexpected FRI blowup"
        exp_layers = _expected_layers(N, blowup)
        if len(roots) != exp_layers:
            return False, "wrong FRI layer count"
        if len(final) != (N >> exp_layers):
            return False, "wrong FRI final-layer size"
        if num_queries is not None and len(queries) != num_queries:
            return False, "wrong FRI query count"

        b = backend or _backend.DEFAULT
        t = transcript or Transcript("fri", backend=b)

        # replay the transcript to recover the same folding challenges + query positions. Only layer OFFSETS and
        # SIZES are kept — domain points are computed on demand as off·ω^pos, so verification never allocates an
        # O(N) domain (a per-query pw instead; the succinct-verifier requirement).
        # C-1: the challenge field is a PROTOCOL constant, not a prover choice. A proof
        # declaring base-field when the protocol says GF(p^2) would be checked under the
        # weaker commit bound (~47 bits instead of ~112), so the declaration is pinned
        # whenever the caller supplies its protocol values.
        use_ext = bool(proof.get("ext", False))
        ext0 = bool(proof.get("ext0", False))     # layer-0 values are ext (a DEEP quotient), see prove
        if expected_ext is None and (num_queries is not None or expected_blowup is not None):
            expected_ext = EXT_CHALLENGES
        if expected_ext is not None and use_ext != bool(expected_ext):
            return False, "unexpected FRI challenge field"

        alphas, offs, sizes = [], [], []
        off = offset
        n = N
        for r in roots:
            t.absorb(r)
            alphas.append(t.challenge_ext() if use_ext else t.challenge())
            offs.append(off); sizes.append(n)
            off = F.mul(off, off); n //= 2
        t.absorb("final", *(ext2.flatten(final) if use_ext else final))
        # C-1: the prover's proof-of-work must meet GRIND_BITS before the (transcript-derived) query positions
        # are drawn, so grinding the Fiat-Shamir queries costs 2^GRIND_BITS PER attempt. Same absorb order as
        # prove, so the query indices below match.
        if not t.check_grind(proof.get("pow"), GRIND_BITS):
            return False, "insufficient proof-of-work (grinding)"

        # the final layer must be genuinely low-degree: interpolate on its coset, high coeffs must vanish
        final_off = off
        deg_bound = max(1, len(final) // blowup)
        if use_ext:
            coeffs = _coset_interpolate_ext(final, final_off)
            if any(c != ext2.ZERO for c in coeffs[deg_bound:]):
                return False, "final layer is not low-degree"
        else:
            coeffs = _coset_interpolate(final, final_off)
            if any(c != 0 for c in coeffs[deg_bound:]):
                return False, "final layer is not low-degree"

        # ONE NATIVE CROSSING PER LAYER, INSTEAD OF A PYTHON CLIMB PER OPENING.
        #
        # Each query opens two paths per layer and merkle.verify/verify_digest walked them in PYTHON,
        # calling a native permute per LEVEL — one ctypes crossing each. Measured on the live 118.57 MiB
        # settle proof this was the largest Python cost left in verification: 57,600 alghash2.node calls,
        # 4.35 s, all of it arriving through merkle.verify_digest from this loop while the trace openings
        # next door were already batched. Same Python-loop-around-a-native-kernel shape the prover port
        # removed; doc/rust-only-proving.md says move the LOOP.
        #
        # BATCHED PER LAYER because one native batch must share a single path length, and the tree halves
        # every layer. Within a layer the shape is uniform: same root, same plen, and ext-ness is fixed by
        # `use_ext and (L > 0 or ext0)`, so a layer is exactly one call.
        #
        # The pre-pass uses the CLAIMED q["idx"]; the loop below still checks it against the transcript and
        # returns before reading any of these answers if it disagrees.
        _lb = None
        if getattr(b, "name", "") in ("recursion", "alghash2") and queries:
            from execnode.stark import alghash2 as _a2f
            if all(len(_q.get("steps") or ()) >= len(roots) for _q in queries):
                _lb = {}
                for _L in range(len(roots)):
                    _n = sizes[_L]; _half = _n // 2
                    _is_ext = use_ext and (_L > 0 or ext0)
                    _items = []
                    for _q in queries:
                        _st = _q["steps"][_L]
                        _lo = (int(_q["idx"]) % _n) % _half
                        _llo = _ext_leaf(b, _st["lo"]) if _is_ext else _st["lo"]
                        _lhi = _ext_leaf(b, _st["hi"]) if _is_ext else _st["hi"]
                        _items.append((roots[_L], _lo, _llo, _st["lo_path"]))
                        _items.append((roots[_L], _lo + _half, _lhi, _st["hi_path"]))
                    # A ragged/!CAPACITY batch is a MALFORMED PROOF, not a missing library — reject it here
                    # rather than letting merkle_verify_paths return None and be read as "no native lib".
                    if len({len(_it[3]) for _it in _items}) != 1:
                        return False, f"bad Merkle opening at layer {_L}"
                    if _is_ext and any(len(_it[2]) != _a2f.CAPACITY for _it in _items):
                        return False, f"bad Merkle opening at layer {_L}"
                    _r = _a2f.merkle_verify_paths(_items, getattr(b, "name", ""), digest=_is_ext)
                    if _r is None:
                        # NO SILENT PYTHON WALK — falling back is what hid this cost for the feature's
                        # whole life. A missing export means a stale crate, which gets rebuilt, not routed
                        # around.
                        raise RuntimeError(
                            "alghash2 native merkle_verify_paths unavailable — the native crate is stale. "
                            "Rebuild with `cargo build --release` in native/alghash2.")
                    _lb[_L] = _r

        for _qi, q in enumerate(queries):
            idx = t.challenge_index(N)
            if idx != q["idx"]:
                return False, "query index does not match transcript"
            a = idx
            for L, (root, alpha, step) in enumerate(zip(roots, alphas, q["steps"])):
                n = sizes[L]; half = n // 2
                a %= n
                lo = a % half
                # Merkle-check both opened points against this layer's root
                is_ext_layer = use_ext and (L > 0 or ext0)
                if _lb is not None:
                    # answers from this layer's single native crossing, in the order they were queued
                    if not _lb[L][2 * _qi]:
                        return False, f"bad Merkle opening (lo) at layer {L}"
                    if not _lb[L][2 * _qi + 1]:
                        return False, f"bad Merkle opening (hi) at layer {L}"
                elif is_ext_layer:
                    # only reached for a backend the native crate does not implement (blake2b, tests)
                    if not merkle.verify_digest(root, lo, _ext_leaf(b, step["lo"]),
                                                step["lo_path"], b):
                        return False, f"bad Merkle opening (lo) at layer {L}"
                    if not merkle.verify_digest(root, lo + half, _ext_leaf(b, step["hi"]),
                                                step["hi_path"], b):
                        return False, f"bad Merkle opening (hi) at layer {L}"
                elif not merkle.verify(root, lo, step["lo"], step["lo_path"], b):
                    return False, f"bad Merkle opening (lo) at layer {L}"
                elif not merkle.verify(root, lo + half, step["hi"], step["hi_path"], b):
                    return False, f"bad Merkle opening (hi) at layer {L}"
                # the fold of this layer's pair must equal the NEXT layer's value at position `lo`
                x = F.mul(offs[L], F.pw(F.primitive_root_of_unity(n), lo))
                if use_ext:
                    flo, fhi = ext2.lift(step["lo"]), ext2.lift(step["hi"])
                    fe = ext2.scalar_mul(ext2.add(flo, fhi), INV2)
                    fo = ext2.scalar_mul(ext2.sub(flo, fhi), F.mul(INV2, F.inv(x)))
                    folded = ext2.add(fe, ext2.mul(alpha, fo))
                else:
                    fe = F.mul(F.add(step["lo"], step["hi"]), INV2)
                    fo = F.mul(F.sub(step["lo"], step["hi"]), F.mul(INV2, F.inv(x)))
                    folded = F.add(fe, F.mul(alpha, fo))
                if L + 1 < len(roots):
                    nxt = q["steps"][L + 1]
                    nhalf = sizes[L + 1] // 2
                    # position `lo` in the next layer (size = half): it is the opened lo if lo<nhalf, else the hi
                    expected = nxt["lo"] if lo < nhalf else nxt["hi"]
                    if (ext2.lift(expected) if use_ext else expected) != folded:
                        return False, f"fold inconsistency at layer {L}"
                else:
                    # last folded layer -> its fold must match the public final layer at position `lo`
                    if (ext2.lift(final[lo]) if use_ext else final[lo]) != folded:
                        return False, f"fold does not match final layer at layer {L}"
                a = lo
        return True, "ok"
    except Exception as e:
        # SAY WHERE. This returned only the exception's text, which for a TypeError deep in the verifier
        # ("int() argument must be ... not 'list'") names neither the file, the line, nor the value — and a
        # settle proof is ~118 MiB of nested structure, so "somewhere in there" is not a starting point.
        # Observed live 2026-08-04: the first settle proof ever to REACH verification (every earlier one was
        # refused for size before the verifier ran) failed with exactly that text and nothing else.
        import traceback as _tb
        _f = _tb.extract_tb(e.__traceback__)[-1]
        return False, (f"malformed proof: {type(e).__name__}: {e} "
                       f"[{_f.filename.rsplit('/', 1)[-1]}:{_f.lineno} in {_f.name}: {_f.line}]")
