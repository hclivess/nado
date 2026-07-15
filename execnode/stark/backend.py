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


BLAKE2B = _Blake2b()
ALGHASH2 = _Alghash2()
RECURSION = _Recursion()
DEFAULT = BLAKE2B


def get(name):
    return {"blake2b": BLAKE2B, "alghash2": ALGHASH2, "recursion": RECURSION}[name]
