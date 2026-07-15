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
from hashing import blake2b_hash
from execnode.stark import field as F, alghash2


class _Blake2b:
    name = "blake2b"

    def leaf(self, x):
        return blake2b_hash(["stark-leaf", str(int(x))])

    def node(self, a, b):
        return blake2b_hash(["stark-node", a, b])

    # transcript: state is a hex string
    def t_init(self, label):
        return blake2b_hash(["transcript", label])

    def t_absorb(self, state, items):
        return blake2b_hash(["absorb", state, *[str(x) for x in items]])

    def t_challenge(self, state):
        s = blake2b_hash(["challenge", state])
        return s, int(s, 16) % F.P

    def t_index(self, state, bound):
        s = blake2b_hash(["index", state])
        return s, int(s, 16) % bound

    def t_grind_hash(self, state, nonce):
        return int(blake2b_hash(["grind", state, str(nonce)]), 16)

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

    # transcript: state is a CAPACITY-tuple of field elements
    def t_init(self, label):
        return alghash2.hashn([alghash2.DOM_ABSORB, sum(bytearray(str(label).encode())) % F.P])

    def _enc(self, items):
        """Flatten transcript items (ints, digest-tuples, strings) to field lanes."""
        out = []
        for x in items:
            if isinstance(x, tuple):
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
        """Native fast-path for the transcript PoW: the whole nonce scan in Rust. Returns the nonce, or None to
        fall back to the generic Python loop. Byte-identical (same DOM_GRIND hash, same 0,1,2,… scan)."""
        return alghash2.grind(state, alghash2.DOM_GRIND, bits)

    def to_field_elements(self, digest):
        return [int(e) % F.P for e in digest]


BLAKE2B = _Blake2b()
ALGHASH2 = _Alghash2()
DEFAULT = BLAKE2B


def get(name):
    return {"blake2b": BLAKE2B, "alghash2": ALGHASH2}[name]
