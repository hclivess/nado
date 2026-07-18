"""
Algebraic (STARK-friendly) hash over the Goldilocks field — the in-circuit hash for the shielded-pool STARK
(doc/privacy.md). BLAKE2b (used by the transparent pool) is byte-oriented and astronomically expensive to
express as field constraints; a STARK needs a hash built FROM field arithmetic. This is a small Poseidon-style
sponge: an x^7 S-box (7 is coprime to p-1, so it's a permutation over Goldilocks), round-constant addition,
and a 2×2 MDS mix, over a width-2 state whose second element is a never-absorbed CAPACITY (that capacity is
what makes the sponge binding — you can't freely invert to a chosen preimage).

ROUND COUNT. The digest is ONE field element, so this hash's generic security is capped by its output width:
~2^32 collision (birthday) / ~2^64 preimage — no round count lifts that ceiling (widen the digest for more, see
alghash2). What the round count MUST buy is that no ALGEBRAIC shortcut beats those generic bounds. An all-full-
round x^7 permutation has algebraic degree 7^ROUNDS; an interpolation/Gröbner inversion costs ~7^ROUNDS. To keep
that at or above the 2^64 preimage ceiling we need 7^ROUNDS ≥ 2^64 ⟹ ROUNDS ≥ 23 (64 / log2 7). ROUNDS = 27
(7^27 ≈ 2^76, a ~15% Poseidon-style margin) makes the algebraic attack strictly costlier than generic, so the
sponge delivers its full 64-bit-output strength. (8 rounds — the old "demonstration" value — gave degree only
7^8 ≈ 2^22.5, i.e. the permutation was interpolation-invertible far BELOW even the birthday bound: an
exploitable break of commit-reveal hiding and of any miner-biasable RNG seed.) The arithmetization technique is
identical for any round count; ROUNDS is a single source of truth consumed by the zkVM AIR, the interpreter, the
assembler, the shielded-pool joinsplit circuits, and the JS mirror.
"""
from hashing import blake2b_hash
from execnode.stark import field as F

ALPHA = 7                                        # S-box exponent (gcd(7, p-1) = 1 over Goldilocks)
ROUNDS = 27                                      # see ROUND COUNT above: 7^27 ≈ 2^76 ≥ the 2^64 output ceiling
MDS = [[2, 1], [1, 3]]                            # 2×2 MDS (all entries + determinant nonzero -> invertible/MDS)


def _c(*parts):
    """Nothing-up-my-sleeve constant: BLAKE2b of the labels, reduced into the field."""
    return int(blake2b_hash(["poseidon", *[str(p) for p in parts]]), 16) % F.P

RC = [[_c("rc", r, 0), _c("rc", r, 1)] for r in range(ROUNDS)]     # round constants
IV = _c("iv")                                                     # capacity initial value

# domain tags so commitment / nullifier / owner / tree-node hashes live in disjoint spaces
DOM_OWNER, DOM_CM, DOM_NF, DOM_NODE = 1, 2, 3, 4


def sbox(x):
    """x^ALPHA — a permutation of F_p since gcd(ALPHA, p-1) = 1."""
    return F.pw(x, ALPHA)


def permute(state):
    """One width-2 permutation: ROUNDS × (add round constants → x^7 → MDS mix)."""
    s0, s1 = state
    for r in range(ROUNDS):
        t0 = sbox(F.add(s0, RC[r][0]))
        t1 = sbox(F.add(s1, RC[r][1]))
        s0 = F.add(F.mul(MDS[0][0], t0), F.mul(MDS[0][1], t1))
        s1 = F.add(F.mul(MDS[1][0], t0), F.mul(MDS[1][1], t1))
    return [s0, s1]


def hashn(elements):
    """Sponge hash of a sequence of field elements (rate 1, capacity 1)."""
    s = [0, IV]
    for m in elements:
        s = permute([F.add(s[0], m % F.P), s[1]])       # absorb into the rate, then permute
    return s[0]


def compress(a, b):
    """2-to-1 Merkle-node compression, domain-separated with DOM_NODE."""
    return hashn([DOM_NODE, a, b])


# --- field-native note algebra (the STARK counterpart of execnode/shielded.py's BLAKE2b version) ---
def owner_of(nsk):
    """Spend-key binding: owner = hashn([DOM_OWNER, nsk])."""
    return hashn([DOM_OWNER, nsk % F.P])


def commit(value, owner, rho):
    """Note commitment cm = hashn([DOM_CM, value, owner, rho])."""
    return hashn([DOM_CM, value % F.P, owner % F.P, rho % F.P])


def nullifier(nsk, rho):
    """Nullifier nf = hashn([DOM_NF, nsk, rho]) — deterministic per note, unlinkable to cm without nsk."""
    return hashn([DOM_NF, nsk % F.P, rho % F.P])


def merkle_node(left, right):
    """Tree-node hash (alias of compress)."""
    return compress(left, right)
