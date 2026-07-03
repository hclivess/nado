import json
import random
import string
from base64 import b64encode, b64decode
from hashlib import blake2b


def create_nonce(length: int = 8):
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


def base64encode(data: str) -> str:
    return b64encode(data.encode()).decode()


def base64decode(data: str) -> str:
    return b64decode(data).decode()


def canonical_bytes(data) -> bytes:
    """Deterministic, cross-platform encoding for all consensus hashing/signing.

    Replaces the previous repr()-based encoding (audit item M14), which varied across
    Python versions/implementations and could silently fork the network. Rules:
      - object keys are sorted, so dict insertion order is irrelevant;
      - compact separators, so whitespace is irrelevant;
      - inputs MUST be JSON primitives (str/int/list/dict/None) and contain NO floats.
    These rules are intentionally trivial to reproduce in a browser light-miner with a
    BigInt-aware serializer, so a phone can compute identical txids/hashes/signatures
    (Python's json emits ints exactly; JS must use BigInt to match for amounts > 2**53).
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def blake2b_hash(data, size: int = 32) -> str:
    return blake2b(canonical_bytes(data), digest_size=size).hexdigest()


def blake2b_hash_link(link_from, link_to, size: int = 32) -> str:
    # a 2-element list (not a tuple) so the encoding is JSON/browser-reproducible
    return blake2b(canonical_bytes([link_from, link_to]), digest_size=size).hexdigest()


# --- Merkle tree (execution-layer settlement + bridge, Phase 2) -----------------------------------
# Order-INDEPENDENT parent hashing (sorted pair), so a leaf's inclusion proof is just a list of sibling
# hashes — no left/right direction bits. Used by execnode.state for the settled state_root and by L1's
# `bridge_withdraw` to verify a withdrawal is in the bonded-quorum-settled root (the one bounded verifier).

def _mh(b: bytes) -> bytes:
    return blake2b(b, digest_size=32).digest()


def _mpair(a: bytes, b: bytes) -> bytes:
    return _mh(a + b) if a <= b else _mh(b + a)


def _leaf_hashes(leaves) -> list:
    return sorted(_mh(l) for l in leaves)          # leaves: list of raw leaf bytes


def _fold(level):
    return [_mpair(level[i], level[i + 1] if i + 1 < len(level) else level[i]) for i in range(0, len(level), 2)]


def merkle_root(leaves) -> str:
    cur = _leaf_hashes(leaves)
    if not cur:
        return _mh(b"nado-empty-merkle").hex()
    while len(cur) > 1:
        cur = _fold(cur)
    return cur[0].hex()


def merkle_proof(leaves, leaf):
    """Inclusion proof (list of sibling hashes, hex, bottom-up) for `leaf`; None if the leaf is absent."""
    cur = _leaf_hashes(leaves)
    target = _mh(leaf)
    if target not in cur:
        return None
    idx = cur.index(target)
    proof = []
    while len(cur) > 1:
        sib = idx ^ 1
        proof.append((cur[sib] if sib < len(cur) else cur[idx]).hex())
        cur = _fold(cur)
        idx //= 2
    return proof


def verify_merkle_proof(leaf, proof, root_hex: str) -> bool:
    h = _mh(leaf)
    for sib in (proof or []):
        h = _mpair(h, bytes.fromhex(sib))
    return h.hex() == root_hex


def withdrawal_leaf(addr, amount, nonce) -> bytes:
    """Canonical leaf bytes for a bridge withdrawal — identical on the execution node (which proves it)
    and on L1 (which verifies it against the settled root)."""
    return canonical_bytes(["bridge_withdrawal", addr, int(amount), nonce])


def dividend_leaf(addr, amount, nonce) -> bytes:
    """Canonical leaf bytes for a presence-dividend collection (distinct domain tag from bridge withdrawals
    so the two can never collide). Proven on L1 against the settled root to release DIVIDEND_POOL coins."""
    return canonical_bytes(["dividend_withdrawal", addr, int(amount), nonce])


def unshield_leaf(addr, amount, nonce) -> bytes:
    """Canonical leaf bytes for a shielded-pool UNSHIELD exit (distinct domain tag). Proven on L1 against the
    settled exec root to release SHIELD_ESCROW coins; `nonce` is the spent note's nullifier (one exit each)."""
    return canonical_bytes(["unshield_withdrawal", addr, int(amount), nonce])


def treasury_proposal_id(recipient, amount, memo, nonce, expiry) -> str:
    """Deterministic id of a treasury_spend proposal (doc/treasury.md). Bonded validators vote on this id and a
    treasury_execute pays it out once justified; binding the id to (recipient, amount, memo, nonce, expiry) means
    a vote approves EXACTLY that payout — the same recipient, amount, AND expiry block — and cannot be redirected
    or replayed past its deadline. `nonce` lets the same spend be re-proposed later; `expiry` is the last block at
    which it may execute. Domain-tagged ('treasury_spend') so it cannot collide with any other id/leaf."""
    return blake2b_hash(["treasury_spend", recipient, int(amount), memo, nonce, int(expiry)])


if __name__ == "__main__":
    blake2b_hash_link("test_old", "test_new")
    print(base64encode("b64test"))
    print(base64decode(base64encode("b64test")))
