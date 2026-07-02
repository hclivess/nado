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

INV2 = F.inv(2)


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


def prove(evals, offset, blowup=4, num_queries=32, transcript=None):
    """Prove deg(f) < len(evals)/blowup, where `evals` are f on the coset of size N=len(evals) with shift
    `offset`. Returns a proof dict. `blowup` (the Reed–Solomon rate denominator) sets both the claimed degree
    bound and the soundness per query."""
    t = transcript or Transcript("fri")
    N = len(evals)
    layers, roots = [], []
    cur, off = list(evals), offset
    dom = F.domain(N, off)
    while len(cur) > blowup:
        root, mlayers = merkle.commit(cur)
        roots.append(root); t.absorb(root)
        alpha = t.challenge()
        layers.append({"evals": cur, "mlayers": mlayers, "dom": dom, "off": off})
        cur = _fold(cur, dom, alpha)
        off = F.mul(off, off)
        dom = F.domain(len(cur), off)
    final = cur                                  # small -> sent in the clear
    t.absorb("final", *final)

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

    return {"N": N, "offset": offset, "blowup": blowup, "roots": roots, "final": final, "queries": queries}


def verify(proof, transcript=None):
    """Verify a FRI proof. Returns (ok, reason)."""
    try:
        N, offset, blowup = proof["N"], proof["offset"], proof["blowup"]
        roots, final, queries = proof["roots"], proof["final"], proof["queries"]
        t = transcript or Transcript("fri")

        # replay the transcript to recover the same folding challenges + query positions
        alphas, offs, doms = [], [], []
        off = offset
        n = N
        for r in roots:
            t.absorb(r)
            alphas.append(t.challenge())
            offs.append(off); doms.append(F.domain(n, off))
            off = F.mul(off, off); n //= 2
        t.absorb("final", *final)

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
            for L, (root, alpha, dom, step) in enumerate(zip(roots, alphas, doms, q["steps"])):
                n = len(dom); half = n // 2
                a %= n
                lo = a % half
                # Merkle-check both opened points against this layer's root
                if not merkle.verify(root, lo, step["lo"], step["lo_path"]):
                    return False, f"bad Merkle opening (lo) at layer {L}"
                if not merkle.verify(root, lo + half, step["hi"], step["hi_path"]):
                    return False, f"bad Merkle opening (hi) at layer {L}"
                # the fold of this layer's pair must equal the NEXT layer's value at position `lo`
                x = dom[lo]
                fe = F.mul(F.add(step["lo"], step["hi"]), INV2)
                fo = F.mul(F.sub(step["lo"], step["hi"]), F.mul(INV2, F.inv(x)))
                folded = F.add(fe, F.mul(alpha, fo))
                if L + 1 < len(roots):
                    nxt = q["steps"][L + 1]
                    nhalf = len(doms[L + 1]) // 2
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
