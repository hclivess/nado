import json
import random
import string
from base64 import b64encode, b64decode
from hashlib import blake2b


def create_nonce(length: int = 8):
    """Random lowercase-ASCII string for node-local identifiers (and the config server_key at
    length 64). Uses `random`, NOT a CSPRNG — fine for nonces/ids, not for key material."""
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


def base64encode(data: str) -> str:
    """str -> base64 str (utf-8); trivial transport-encoding helper, no consensus role."""
    return b64encode(data.encode()).decode()


def base64decode(data: str) -> str:
    """base64 str -> original str (inverse of base64encode)."""
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
    """The chain's general-purpose hash: blake2b (32 B default) over canonical_bytes(data), hex.
    CONSENSUS-CRITICAL — txids, pool hashes and ids all derive from it, and it is byte-exact across
    Python versions AND the browser light-miner precisely because canonical_bytes (not repr) feeds it."""
    return blake2b(canonical_bytes(data), digest_size=size).hexdigest()


def blake2b_hash_link(link_from, link_to, size: int = 32) -> str:
    """Hash of an ORDERED (from, to) pair — the chain-link primitive (e.g. block hash =
    link(timestamp, transactions)). ORDER MATTERS: the pair is encoded as a 2-element JSON list,
    so link(a, b) != link(b, a); swapping arguments forks the chain. Consensus-critical like
    blake2b_hash, and equally browser-reproducible via canonical_bytes."""
    # a 2-element list (not a tuple) so the encoding is JSON/browser-reproducible
    return blake2b(canonical_bytes([link_from, link_to]), digest_size=size).hexdigest()


# --- Merkle tree (execution-layer settlement + bridge, Phase 2) -----------------------------------
# Order-INDEPENDENT parent hashing (sorted pair), so a leaf's inclusion proof is just a list of sibling
# hashes — no left/right direction bits. Used by execnode.state for the settled state_root and by L1's
# `bridge_withdraw` to verify a withdrawal is in the bonded-quorum-settled root (the one bounded verifier).

def _mh(b: bytes) -> bytes:
    """Merkle-internal blake2b-256 over RAW bytes — no canonical_bytes wrapping, because leaves are
    already canonical (the *_leaf builders below emit canonical_bytes) and tree nodes are digests."""
    return blake2b(b, digest_size=32).digest()


def _mpair(a: bytes, b: bytes) -> bytes:
    """Parent = hash of the two children concatenated in SORTED byte order. This one rule is what
    makes proofs direction-free (no left/right bits to carry or get wrong on either side of the
    bridge) — both the exec-layer prover and L1's verifier depend on it byte-for-byte."""
    return _mh(a + b) if a <= b else _mh(b + a)


def _leaf_hashes(leaves) -> list:
    """Hash every raw leaf, then SORT (byte order) — the canonical bottom level. Sorting here, with
    _mpair's sorted parents, is what makes the whole tree independent of caller leaf order."""
    return sorted(_mh(l) for l in leaves)          # leaves: list of raw leaf bytes


def _fold(level):
    """One level up the tree: pair adjacent nodes, DUPLICATING the last node when the level is odd
    (duplicate-last-leaf rule). merkle_proof mirrors the same rule when emitting siblings — prover
    and verifier folding must match exactly or every odd-width tree's root diverges."""
    return [_mpair(level[i], level[i + 1] if i + 1 < len(level) else level[i]) for i in range(0, len(level), 2)]


def merkle_root(leaves) -> str:
    """Merkle root (hex) over raw leaf bytes — order-INDEPENDENT thanks to the sorted leaf level +
    sorted-pair parents, so prover and verifier need not agree on leaf ordering, only on leaf
    CONTENT (the canonical_bytes leaf encoders below). The empty set hashes a fixed domain tag so
    'no leaves' has a distinct, unforgeable root instead of an error/sentinel. CONSENSUS-CRITICAL:
    this is the settled exec-layer state_root that L1 withdrawal verification anchors to."""
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
    """Recompute the root from `leaf` (raw bytes) and its sibling list (hex, bottom-up) and compare
    to `root_hex`. No left/right direction bits are needed — _mpair sorts each pair, so the fold is
    position-free. An empty/None proof asserts the single-leaf tree (root == _mh(leaf)). This is
    L1's ONE bounded verifier: bridge/dividend/unshield exits all release coins through it, so its
    hashing rules must stay byte-identical to the prover's (merkle_proof above)."""
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


def outbox_leaf(seq, sender, to_ns, data) -> bytes:
    """Canonical leaf bytes for a cross-domain OUTBOX message — identical on the execution node (which commits
    it in state_root and proves it) and on L1 (which verifies an `xmsg` delivery against the SETTLED root of
    the sending namespace). Distinct domain tag ('outbox') so it can never collide with a bridge/dividend
    leaf. `data` is committed via canonical json so any structure hashes deterministically."""
    return canonical_bytes(["outbox", int(seq), sender, to_ns, json.dumps(data, sort_keys=True)])


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
