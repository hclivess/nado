"""
zk-STARK SHIELDED POOL — post-quantum confidential transactions (doc/privacy.md). Execution-layer feature.

WHAT THIS IS. The privacy-preserving state machine for a Zerocash-style shielded pool, plus a PLUGGABLE
proof-verifier seam. Notes are hiding+binding commitments in an append-only Merkle set; a spend reveals a
NULLIFIER (double-spend safe) and never its position/value; value is conserved across every transfer.

PHASED, like NADO's settlement (Phase-2a quorum -> Phase-2b STARK). The seam `verify_transfer(public, proof)`
takes ONLY public inputs + a proof:
  * PHASE 1 (this file): proof = the TRANSPARENT witness; the verifier re-checks Merkle membership + nullifier
    derivation + value conservation IN THE CLEAR. Result: fully SOUND (no double-spend, no forged value) but
    NOT yet private (the witness is visible). This lets the ENTIRE pool machinery + integration + tests be
    built and frozen now.
  * PHASE 2 (next): proof = a hash-based zk-STARK (FRI, post-quantum, no trusted setup) of the SAME statement.
    The verifier then checks the STARK against `public` alone, hiding the witness -> SOUND AND private. The
    state machine below does not change; only the verifier behind this seam does.

Everything here is deterministic + canonical-JSON (browser/full-node reproducible) and post-quantum (the only
assumption is a collision-resistant hash — BLAKE2b today; the eventual STARK circuit will use a STARK-friendly
hash internally, a documented Phase-2 decision, doc/privacy.md §hash).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hashing import blake2b_hash

SHIELD_DEPTH = 32                                  # Merkle depth -> up to 2**32 notes in the pool


def _h(*parts):
    """Domain-separated pool hash over canonical JSON (browser-reproducible)."""
    return blake2b_hash(["nado.shield", *[str(p) for p in parts]])


# --- empty-subtree roots (e[i] = root of an all-empty subtree of height i) -------------------------
def _empty_roots(depth):
    e = [_h("empty-leaf")]
    for _ in range(depth):
        e.append(_h("node", e[-1], e[-1]))
    return e


_EMPTY = _empty_roots(SHIELD_DEPTH)
EMPTY_ROOT = _EMPTY[SHIELD_DEPTH]


# --- note commitment + nullifier ------------------------------------------------------------------
def note_commitment(value: int, owner: str, rho: str) -> str:
    """Hiding+binding commitment to a note (value, owner-key id, randomness rho). rho (random) hides it;
    the hash binds it. Two notes with the same (value, owner) but fresh rho are unlinkable."""
    return _h("cm", int(value), owner, rho)


def owner_id(spend_secret: str) -> str:
    """Public owner identifier = H(spend_secret). You send a shielded note TO someone by committing to their
    owner_id; only the holder of spend_secret can produce the note's nullifier and spend it."""
    return _h("owner", spend_secret)


def note_nullifier(spend_secret: str, rho: str) -> str:
    """Deterministic, unlinkable spend tag. Binds the note's SECRET spend key + rho in a DIFFERENT domain than
    the commitment, so a revealed nullifier cannot be linked back to its commitment. Revealed once, on spend,
    to prevent double-spends."""
    return _h("nf", spend_secret, rho)


# --- fixed-depth Merkle commitment tree -----------------------------------------------------------
def merkle_root(leaves) -> str:
    if not leaves:
        return EMPTY_ROOT
    level = list(leaves)
    for d in range(SHIELD_DEPTH):
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else _EMPTY[d]
            nxt.append(_h("node", left, right))
        level = nxt
    return level[0]


def merkle_path(leaves, pos):
    """Authentication path (sibling hashes, bottom-up) for the leaf at `pos`."""
    path = []
    idx = pos
    level = list(leaves)
    for d in range(SHIELD_DEPTH):
        sib = idx ^ 1
        path.append(level[sib] if sib < len(level) else _EMPTY[d])
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else _EMPTY[d]
            nxt.append(_h("node", left, right))
        level = nxt
        idx //= 2
    return path


def verify_path(leaf, pos, path, root) -> bool:
    h = leaf
    idx = pos
    for d in range(SHIELD_DEPTH):
        sib = path[d]
        h = _h("node", h, sib) if idx % 2 == 0 else _h("node", sib, h)
        idx //= 2
    return h == root


# --- the shielded pool ----------------------------------------------------------------------------
class ShieldedPool:
    """Append-only commitment set + spent-nullifier set. Built deterministically by replaying shielded txs
    from FINALIZED L1 blobs in order (no reorgs at the exec cursor), so no rollback bookkeeping is needed."""

    def __init__(self, commitments=None, nullifiers=None, anchors=None):
        self.commitments = list(commitments or [])     # leaves, in insertion order (pos = index)
        self.nullifiers = set(nullifiers or [])         # spent nullifiers
        # ANCHOR SET: every root the pool has ever held. A transfer may prove against ANY past root (the tree
        # keeps growing between building a proof and it landing), so we accept a proof whose `root` is in here.
        self.anchors = set(anchors or [])
        self.anchors.add(self.root())

    # -- state ----
    def root(self):
        return merkle_root(self.commitments)

    def size(self):
        return len(self.commitments)

    def has_nullifier(self, nf):
        return nf in self.nullifiers

    def knows_root(self, root):
        return root in self.anchors

    def to_dict(self):
        return {"commitments": self.commitments, "nullifiers": sorted(self.nullifiers),
                "anchors": sorted(self.anchors), "root": self.root()}

    @classmethod
    def from_dict(cls, d):
        return cls(d.get("commitments"), d.get("nullifiers"), d.get("anchors"))


# --- transfer statement + verifier seam -----------------------------------------------------------
# A transfer is a join-split: spend `inputs` notes, create `outputs` notes, with a signed public value.
#   public = {
#     "root":            Merkle root the inputs are proven against (must be a root the pool has held),
#     "nullifiers":      [nf, ...]      # one per input, revealed
#     "out_commitments": [cm, ...]      # commitments of the new notes
#     "public_value":    int           # >0 coins ENTER the pool (shield deposit), <0 LEAVE (unshield), 0 = private transfer
#     "fee":             int           # pool/L1 fee (burned)
#   }
#   proof (PHASE 1, transparent) = {
#     "inputs":  [{"value","spend_secret","rho","pos","path"}, ...]   # opening + membership witness per input
#     "outputs": [{"value","owner","rho"}, ...]                        # opening per output note
#   }
# INVARIANT proven: every input commitment is in the tree at `root`; each nullifier = H(spend_secret,rho) and
# matches its input; each out_commitment = H(value,owner,rho); and  sum(inputs)+public_value == sum(outputs)+fee.

def verify_transfer(public: dict, proof: dict, root_is_known) -> tuple:
    """Verify a shielded transfer. `root_is_known(root)` -> bool tells us the `root` is one the pool actually
    held (anchor freshness). Returns (ok, reason). Phase 2 will replace the transparent re-check below with a
    single STARK verification against `public` — the signature of THIS function does not change."""
    try:
        root = public["root"]
        nfs = public["nullifiers"]
        out_cms = public["out_commitments"]
        pub_val = int(public["public_value"])
        fee = int(public["fee"])
        ins = proof["inputs"]
        outs = proof["outputs"]
    except (KeyError, TypeError, ValueError):
        return False, "malformed transfer"

    if not root_is_known(root):
        return False, "unknown anchor root"
    if len(nfs) != len(ins) or len(out_cms) != len(outs):
        return False, "public/witness length mismatch"
    if fee < 0:
        return False, "negative fee"
    if len(set(nfs)) != len(nfs):
        return False, "duplicate nullifier within the transfer"

    in_sum = 0
    for i, w in enumerate(ins):
        try:
            v = int(w["value"]); ss = w["spend_secret"]; rho = w["rho"]; pos = int(w["pos"]); path = w["path"]
        except (KeyError, TypeError, ValueError):
            return False, "malformed input witness"
        if v < 0:
            return False, "negative input value"
        cm = note_commitment(v, owner_id(ss), rho)                 # reconstruct the input commitment
        if not verify_path(cm, pos, path, root):
            return False, f"input {i} not in the tree at root"
        if note_nullifier(ss, rho) != nfs[i]:
            return False, f"input {i} nullifier does not match the note"
        in_sum += v

    out_sum = 0
    for j, w in enumerate(outs):
        try:
            v = int(w["value"]); owner = w["owner"]; rho = w["rho"]
        except (KeyError, TypeError, ValueError):
            return False, "malformed output note"
        if v < 0:
            return False, "negative output value"
        if note_commitment(v, owner, rho) != out_cms[j]:
            return False, f"output {j} commitment does not match the note"
        out_sum += v

    if in_sum + pub_val != out_sum + fee:
        return False, "value not conserved"
    return True, "ok"


def apply_transfer(pool: ShieldedPool, public: dict, proof: dict, root_is_known) -> tuple:
    """Verify then MUTATE the pool for a shielded transfer: reject if any revealed nullifier is already spent
    (double-spend), else record the nullifiers and append the output commitments. Returns (ok, reason)."""
    ok, reason = verify_transfer(public, proof, root_is_known)
    if not ok:
        return False, reason
    for nf in public["nullifiers"]:
        if pool.has_nullifier(nf):
            return False, "nullifier already spent (double-spend)"
    pool.nullifiers.update(public["nullifiers"])
    for cm in public["out_commitments"]:
        pool.commitments.append(cm)
    pool.anchors.add(pool.root())                                  # the new state root becomes a valid anchor
    return True, "ok"
