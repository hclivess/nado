"""
Fiat–Shamir transcript — turns the interactive STARK/FRI protocol NON-interactive (doc/privacy.md). Every
challenge derives from a hash of everything absorbed so far, so a cheating prover cannot pick data to suit a
challenge it hasn't seen. The hash is supplied by a BACKEND (execnode/stark/backend.py): BLAKE2b by default
(byte-identical to the original — existing proofs unchanged), or the wide-sponge `alghash2` for the
recursion layer (doc/zk-recursion.md). Post-quantum (hash-only) and byte-reproducible.
"""
from execnode.stark import backend as _backend


# The Fiat-Shamir domain label every NADO proof binds. Brand-carrying: renamed only at a
# CHAIN_GENERATION reroll (doc/address-format.md). JS mirror: static/stark/transcript.js.
DOMAIN_STARK = "stark-v1"


class Transcript:
    def __init__(self, label=None, backend=None):
        if label is None:
            label = DOMAIN_STARK
        """Fresh transcript, domain-separated by `label`."""
        self.b = backend or _backend.DEFAULT
        self.state = self.b.t_init(label)

    def absorb(self, *items):
        """Fold items into the transcript state — every later challenge depends on them."""
        self.state = self.b.t_absorb(self.state, items)

    def challenge(self):
        """A uniform field element derived from the transcript."""
        self.state, v = self.b.t_challenge(self.state)
        return v

    def challenge_index(self, bound):
        """A uniform index in [0, bound)."""
        self.state, v = self.b.t_index(self.state, bound)
        return v

    def _grind_ok(self, nonce, bits):
        """True iff the PoW hash of (current state, nonce) has `bits` leading zero bits."""
        h = self.b.t_grind_hash(self.state, nonce)
        return (h >> (256 - bits)) == 0

    def grind(self, bits):
        """Find a nonce whose PoW hash has `bits` leading zeros, fold it in, return it. Multiplies a forger's
        cost by 2^bits UNCONDITIONALLY (independent of the FRI soundness conjecture). If the backend exposes a
        native `grind_solve` (alghash2's Rust loop), use it — the whole 2^bits scan runs in native code, the
        recursion/fold hot path — else scan in Python. Both find the SMALLEST hit, so the nonce is identical."""
        nonce = None
        solve = getattr(self.b, "grind_solve", None)
        if solve is not None:
            nonce = solve(self.state, bits)
        if nonce is None:
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
