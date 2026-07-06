"""
Fiat–Shamir transcript — turns the interactive STARK/FRI protocol NON-interactive (doc/privacy.md). Every
challenge is a BLAKE2b hash of everything absorbed so far, so a cheating prover cannot pick data to suit a
challenge it hasn't seen. Post-quantum (hash-only) and byte-reproducible on any verifier.
"""
from hashing import blake2b_hash
from execnode.stark.field import P


class Transcript:
    def __init__(self, label="nado-stark"):
        """Fresh transcript, domain-separated by `label`."""
        self.state = blake2b_hash(["transcript", label])

    def absorb(self, *items):
        """Fold items into the transcript state — every later challenge depends on them."""
        self.state = blake2b_hash(["absorb", self.state, *[str(x) for x in items]])

    def challenge(self):
        """A uniform field element derived from the transcript."""
        self.state = blake2b_hash(["challenge", self.state])
        return int(self.state, 16) % P

    def challenge_index(self, bound):
        """A uniform index in [0, bound)."""
        self.state = blake2b_hash(["index", self.state])
        return int(self.state, 16) % bound

    def _grind_ok(self, nonce, bits):
        """True iff the PoW hash of (current state, nonce) has `bits` leading zero bits."""
        # PoW over the CURRENT transcript state: the hash must have `bits` leading zero bits. Uses the same
        # blake2b_hash as every other transcript op, so the browser prover (which mirrors it byte-for-byte)
        # agrees. 64-hex digest -> 256 bits total.
        h = int(blake2b_hash(["grind", self.state, str(nonce)]), 16)   # str(nonce): JSON string, matches JS String(nonce)
        return (h >> (256 - bits)) == 0

    def grind(self, bits):
        """Find a nonce whose PoW hash has `bits` leading zeros, fold it into the transcript, return it. This
        multiplies a forger's cost by 2^bits UNCONDITIONALLY (independent of the FRI soundness conjecture),
        the cheap way to raise soundness beyond what the query count alone gives (C-1)."""
        nonce = 0
        while not self._grind_ok(nonce, bits):
            nonce += 1
        self.absorb("grind", nonce)
        return nonce

    def check_grind(self, nonce, bits):
        """Verifier side: the nonce must be a non-negative int meeting the PoW, then fold it in identically."""
        if not (isinstance(nonce, int) and nonce >= 0 and self._grind_ok(nonce, bits)):
            return False
        self.absorb("grind", nonce)
        return True
