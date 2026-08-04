"""
Hash backends for the STARK stack (doc/zk-recursion.md). The FRI/STARK code (`merkle`, `transcript`, `fri`,
`stark`) is hash-agnostic — it needs a leaf/node commitment hash and a Fiat–Shamir transcript, nothing more.
A `Backend` supplies both. Two exist:

  · BLAKE2B (default) — byte-identical to the original hard-coded behaviour, so every existing proof
    (shielded pool, execution AIR, settlement) is unchanged.
  · ALGHASH2 — the wide-sponge algebraic hash (`alghash2`), so a proof's verification is expressible in
    field arithmetic and can therefore be verified INSIDE a STARK (recursion).

Digests are opaque to the callers: a hex string for blake2b, a CAPACITY-tuple of field elements for alghash2.
`==` works for both; `to_field_elements` flattens a digest to field lanes for the transcript / an in-circuit
verifier.
"""
from hashlib import blake2b as _blake2b
from hashing import blake2b_hash
from execnode.stark import field as F, alghash2

# The STARK's Merkle leaf/node hash is called MILLIONS of times per proof and is PURELY INTERNAL to a proof
# (prove + verify use it self-consistently; it is NOT the consensus state-root hash — that is
# hashing.merkle_root over canonical_bytes, untouched). So it skips json/canonical_bytes entirely and packs
# bytes directly: a field element is < P < 2^64 (8 LE bytes); a digest is 32 bytes. This removed ~18s of pure
# json.dumps overhead per execution-AIR proof (2.18M hashes). Domain-tagged so leaf/node spaces stay disjoint.
def _b2b32(*parts):
    return _blake2b(b"".join(parts), digest_size=32).hexdigest()


class _Blake2b:
    name = "blake2b"

    def leaf(self, x):
        return _b2b32(b"\x00", (int(x) % F.P).to_bytes(8, "little"))

    def node(self, a, b):
        return _b2b32(b"\x01", bytes.fromhex(a), bytes.fromhex(b))

    def leaf_ext(self, *limbs):
        """Extension leaf. Its own frame tag (\x02), so it can never collide with a base leaf (\x00) even
        when the trailing limbs are zero — see alghash2.rleaf_ext for why that distinctness matters."""
        return _b2b32(b"\x02", *[(int(x) % F.P).to_bytes(8, "little") for x in limbs])

    # transcript: state is a 32-byte hex string. Items are field ints, digest hex strings, or short labels;
    # each is encoded unambiguously (tag + bytes) so the absorb is injective — no json (hashlib is C-fast; the
    # json.dumps was the whole cost, incl. the 2^GRIND_BITS grind hashes). Internal to a proof, same both sides.
    def _enc(self, items):
        out = []
        for x in items:
            if isinstance(x, str) and len(x) == 64 and all(c in "0123456789abcdef" for c in x):
                out.append(b"H" + bytes.fromhex(x))                       # a digest
            elif isinstance(x, str):
                bs = x.encode(); out.append(b"S" + len(bs).to_bytes(2, "little") + bs)
            else:
                v = int(x) % F.P; out.append(b"I" + v.to_bytes(8, "little"))
        return b"".join(out)

    def t_init(self, label):
        return _b2b32(b"T", str(label).encode())

    def t_absorb(self, state, items):
        return _b2b32(b"A", bytes.fromhex(state), self._enc(items))

    def t_challenge(self, state):
        s = _b2b32(b"C", bytes.fromhex(state))
        return s, int(s, 16) % F.P

    def t_index(self, state, bound):
        s = _b2b32(b"X", bytes.fromhex(state))
        return s, int(s, 16) % bound

    def t_grind_hash(self, state, nonce):
        return int(_b2b32(b"G", bytes.fromhex(state), (int(nonce) % F.P).to_bytes(8, "little")), 16)

    def to_field_elements(self, digest):
        # a blake2b digest is a 256-bit hex string → four 64-bit field lanes (for uniformity only)
        v = int(digest, 16)
        return [(v >> (64 * i)) & 0xFFFFFFFFFFFFFFFF for i in range(4)]


class _Alghash2:
    name = "alghash2"

    def leaf(self, x):
        return alghash2.leaf(x)

    def node(self, a, b):
        return alghash2.node(tuple(a), tuple(b))

    def leaf_ext(self, *limbs):
        return alghash2.leaf_ext(*limbs)

    # transcript: state is a CAPACITY-tuple of field elements
    def t_init(self, label):
        return alghash2.hashn([alghash2.DOM_ABSORB, sum(bytearray(str(label).encode())) % F.P])

    def _enc(self, items):
        """Flatten transcript items (ints, digest tuples/lists, strings) to field lanes.

        A LIST MUST ENCODE EXACTLY LIKE A TUPLE. Digests here are CAPACITY-tuples in memory, but a proof
        that is transmitted is JSON, and json.loads turns every tuple into a LIST. This checked
        `isinstance(x, tuple)` only, so a round-tripped digest fell through to the scalar branch and
        `int(<list>)` raised — meaning the Fiat-Shamir transcript could not even be built for any proof
        that had crossed the wire.

        The consequence was larger than one failed settle: the prover self-checks against its own
        IN-MEMORY proof (tuples) and passes, while a verifier on the receiving side works from JSON
        (lists) — so NO alghash2-backend proof could ever verify after transmission, which is the only
        thing a proof is for. It stayed invisible because a settle proof is ~118 MiB against an 8 MiB
        submit cap: every proof was refused for SIZE before a verifier ever ran. The first one to reach
        verification, once DA transport worked (2026-08-04, cursor 21298), failed here immediately:
            malformed proof: TypeError: int() argument must be ... not 'list'
            [backend.py:104 in _enc: out.append(int(x) % F.P)]

        Accepting both keeps the encoding byte-identical for the tuple case, so nothing that verified
        before changes — and in-memory and round-tripped proofs now hash to the SAME transcript, which is
        what makes a proof portable at all. The blake2b backend was never affected: its digests are hex
        strings, which survive JSON unchanged.
        """
        out = []
        for x in items:
            if isinstance(x, (tuple, list)):
                out.extend(int(e) % F.P for e in x)
            elif isinstance(x, (bytes, str)):
                out.append(sum(bytearray(str(x).encode())) % F.P)
            else:
                out.append(int(x) % F.P)
        return out

    def t_absorb(self, state, items):
        return alghash2.hashn([alghash2.DOM_ABSORB, *state, *self._enc(items)])

    def t_challenge(self, state):
        s = alghash2.hashn([alghash2.DOM_CHAL, *state])
        return s, int(s[0]) % F.P

    def t_index(self, state, bound):
        s = alghash2.hashn([alghash2.DOM_INDEX, *state])
        return s, int(s[0]) % bound

    def t_grind_hash(self, state, nonce):
        return alghash2.to_int(alghash2.hashn([alghash2.DOM_GRIND, *state, int(nonce) % F.P]))

    def grind_solve(self, state, bits):
        """Native fast-path for the transcript PoW: the whole nonce scan in Rust. Prefers the PARALLEL
        holistic-prover grind (all cores, deterministic round-minimum == the serial first-hit nonce), falling
        back to the serial native scan, then the generic Python loop. Byte-identical in every path (same
        DOM_GRIND hash, same smallest-valid-nonce answer)."""
        try:
            from execnode.stark import stark_native
            n = stark_native.grind(state, alghash2.DOM_GRIND, bits)
            if n is not None:
                return n
        except Exception:
            pass
        return alghash2.grind(state, alghash2.DOM_GRIND, bits)

    def to_field_elements(self, digest):
        return [int(e) % F.P for e in digest]


class _Recursion(_Alghash2):
    """The RECURSION-READY backend: alghash2 transcript (unchanged) but Merkle leaf/node = the FIXED-ARITY
    rleaf/rnode (ONE permutation per node — no length prefix). A proof committed with this backend has a Merkle
    tree the in-circuit membership AIR (execnode/stark/recursion.py) spends exactly one permutation block per
    level on — i.e. a proof `fri.prove(..., backend=RECURSION)` is directly verifiable INSIDE a recursion
    proof. (The plain ALGHASH2 backend uses the hashn sponge for Merkle too, which the in-VM verifier would pay
    two blocks per node for.)"""
    name = "recursion"

    def leaf(self, x):
        return alghash2.rleaf(x)

    def node(self, a, b):
        return alghash2.rnode(tuple(a), tuple(b))

    def leaf_ext(self, *limbs):
        """ONE permutation, same as leaf — which is what makes the in-circuit ext membership gadget cost the
        same as the base one (execnode/stark/fri_verify.py). Holds for degree <= 3."""
        return alghash2.rleaf_ext(*limbs)


BLAKE2B = _Blake2b()
ALGHASH2 = _Alghash2()
RECURSION = _Recursion()
DEFAULT = BLAKE2B


def get(name):
    return {"blake2b": BLAKE2B, "alghash2": ALGHASH2, "recursion": RECURSION}[name]
