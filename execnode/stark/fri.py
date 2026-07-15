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
from execnode.stark import field as F, merkle
from execnode.stark.transcript import Transcript
from execnode.stark import backend as _backend

INV2 = F.inv(2)

# Protocol-fixed FRI parameters. These are NOT read from the proof — a prover that under-declares the query
# count or drops folding layers was the C-1 total soundness bypass (an empty `queries`/`roots` list skipped
# every check). The verifier derives the whole FRI shape from N + FRI_BLOWUP and requires exactly NUM_QUERIES
# openings. stark.prove always calls fri.prove with fri_blowup == 2, so FRI_BLOWUP is fixed at 2.
#
# C-1 soundness sizing: at FRI_BLOWUP=2 (rate 1/2) each query contributes ~0.4 bit (provable) / ~1 bit
# (conjectured) of soundness, so 40 queries alone (~17-40 bits) fell short of the ~100-bit target. We raise the
# query count AND add GRIND_BITS of proof-of-work on the transcript (transcript.grind), which adds soundness
# UNCONDITIONALLY (a forger must redo 2^GRIND_BITS work per Fiat-Shamir attempt regardless of any FRI
# conjecture). 64 queries + 18 grind ≈ 82 bits (conjectured) / ~45 bits (provable) + 18 unconditional — a large
# lift over the prior config, at ~3s prover overhead (Python) / ~0.03s in the browser's WASM blake2b.
NUM_QUERIES = 64
FRI_BLOWUP = 2
GRIND_BITS = 18


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


def prove(evals, offset, blowup=4, num_queries=NUM_QUERIES, transcript=None, backend=None):
    """Prove deg(f) < len(evals)/blowup, where `evals` are f on the coset of size N=len(evals) with shift
    `offset`. Returns a proof dict. `blowup` (the Reed–Solomon rate denominator) sets both the claimed degree
    bound and the soundness per query."""
    b = backend or _backend.DEFAULT
    t = transcript or Transcript("fri", backend=b)
    N = len(evals)
    layers, roots = [], []
    cur, off = list(evals), offset
    dom = F.domain(N, off)
    while len(cur) > blowup:
        root, mlayers = merkle.commit(cur, b)
        roots.append(root); t.absorb(root)
        alpha = t.challenge()
        layers.append({"evals": cur, "mlayers": mlayers, "dom": dom, "off": off})
        cur = _fold(cur, dom, alpha)
        off = F.mul(off, off)
        dom = F.domain(len(cur), off)
    final = cur                                  # small -> sent in the clear
    t.absorb("final", *final)
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
            "pow": pow_nonce, "queries": queries}


def verify(proof, transcript=None, num_queries=None, expected_blowup=None, backend=None):
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
        alphas, offs, sizes = [], [], []
        off = offset
        n = N
        for r in roots:
            t.absorb(r)
            alphas.append(t.challenge())
            offs.append(off); sizes.append(n)
            off = F.mul(off, off); n //= 2
        t.absorb("final", *final)
        # C-1: the prover's proof-of-work must meet GRIND_BITS before the (transcript-derived) query positions
        # are drawn, so grinding the Fiat-Shamir queries costs 2^GRIND_BITS PER attempt. Same absorb order as
        # prove, so the query indices below match.
        if not t.check_grind(proof.get("pow"), GRIND_BITS):
            return False, "insufficient proof-of-work (grinding)"

        # the final layer must be genuinely low-degree: interpolate on its coset, high coeffs must vanish
        final_off = off
        coeffs = _coset_interpolate(final, final_off)
        deg_bound = max(1, len(final) // blowup)
        if any(c != 0 for c in coeffs[deg_bound:]):
            return False, "final layer is not low-degree"

        for q in queries:
            idx = t.challenge_index(N)
            if idx != q["idx"]:
                return False, "query index does not match transcript"
            a = idx
            for L, (root, alpha, step) in enumerate(zip(roots, alphas, q["steps"])):
                n = sizes[L]; half = n // 2
                a %= n
                lo = a % half
                # Merkle-check both opened points against this layer's root
                if not merkle.verify(root, lo, step["lo"], step["lo_path"], b):
                    return False, f"bad Merkle opening (lo) at layer {L}"
                if not merkle.verify(root, lo + half, step["hi"], step["hi_path"], b):
                    return False, f"bad Merkle opening (hi) at layer {L}"
                # the fold of this layer's pair must equal the NEXT layer's value at position `lo`
                x = F.mul(offs[L], F.pw(F.primitive_root_of_unity(n), lo))
                fe = F.mul(F.add(step["lo"], step["hi"]), INV2)
                fo = F.mul(F.sub(step["lo"], step["hi"]), F.mul(INV2, F.inv(x)))
                folded = F.add(fe, F.mul(alpha, fo))
                if L + 1 < len(roots):
                    nxt = q["steps"][L + 1]
                    nhalf = sizes[L + 1] // 2
                    # position `lo` in the next layer (size = half): it is the opened lo if lo<nhalf, else the hi
                    expected = nxt["lo"] if lo < nhalf else nxt["hi"]
                    if folded != expected:
                        return False, f"fold inconsistency at layer {L}"
                else:
                    # last folded layer -> its fold must match the public final layer at position `lo`
                    if folded != final[lo]:
                        return False, f"fold does not match final layer at layer {L}"
                a = lo
        return True, "ok"
    except Exception as e:
        return False, f"malformed proof: {e}"
