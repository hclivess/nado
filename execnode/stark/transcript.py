"""
Fiat–Shamir transcript — turns the interactive STARK/FRI protocol NON-interactive (doc/privacy.md). Every
challenge is a BLAKE2b hash of everything absorbed so far, so a cheating prover cannot pick data to suit a
challenge it hasn't seen. Post-quantum (hash-only) and byte-reproducible on any verifier.
"""
from hashing import blake2b_hash
from execnode.stark.field import P


class Transcript:
    def __init__(self, label="nado-stark"):
        self.state = blake2b_hash(["transcript", label])

    def absorb(self, *items):
        self.state = blake2b_hash(["absorb", self.state, *[str(x) for x in items]])

    def challenge(self):
        """A uniform field element derived from the transcript."""
        self.state = blake2b_hash(["challenge", self.state])
        return int(self.state, 16) % P

    def challenge_index(self, bound):
        """A uniform index in [0, bound)."""
        self.state = blake2b_hash(["index", self.state])
        return int(self.state, 16) % bound
