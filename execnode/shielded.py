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
from Curve25519 import verify as mldsa_verify, unhex   # NADO's post-quantum ML-DSA-44 (module name is legacy)

SHIELD_DEPTH = 32                                  # Merkle depth -> up to 2**32 notes in the pool
ANCHOR_WINDOW = 128                                # recent roots a proof may target (bounded so the anchor set
                                                   # never grows without limit — clients prove against a fresh root)


def _h(*parts):
    """Domain-separated pool hash over canonical JSON (browser-reproducible)."""
    return blake2b_hash(["nado.shield", *[str(p) for p in parts]])


# --- empty-subtree roots (e[i] = root of an all-empty subtree of height i) -------------------------
def _empty_roots(depth):
    """Precompute e[i] = root of an all-empty subtree of height i (so e[depth] is the empty-tree root)."""
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


def owner_id(pubkey: str) -> str:
    """Public owner identifier = H(pubkey) of an ML-DSA-44 (post-quantum) SPEND KEY. You send a shielded note
    TO someone by committing to their owner_id; only the holder of the matching private key can AUTHORISE the
    spend (ML-DSA signature over the transfer, checked in verify_transfer)."""
    return _h("owner", pubkey)


def note_nullifier(pubkey: str, rho: str) -> str:
    """Deterministic, unlinkable spend tag = H(pubkey, rho), a DIFFERENT domain than the commitment so a
    revealed nullifier cannot be linked to its commitment. Revealed once on spend to prevent double-spends.
    (Note: the SENDER, who chose rho, can also compute this — a minor spend-detection leak that the Phase-2
    STARK closes with a Zcash-style nullifier-key tree; theft is impossible regardless, since SPENDING needs
    the ML-DSA private key, not just rho — doc/privacy.md.)"""
    return _h("nf", pubkey, rho)


def transfer_sighash(public: dict) -> str:
    """The message an input's owner ML-DSA-signs to authorise the spend: binds ALL public parts of the
    transfer (nullifiers, outputs, public value, fee, AND the unshield destination), so a signature can't be
    replayed onto a different transfer. Lists are sorted + '|'-joined (NOT passed as raw lists) so the hash is
    byte-identical in the browser port (Python str(list) is a non-reproducible repr) — every scalar is a plain
    string here.

    H-4: withdraw_addr is bound here too. Without it, an unshield's destination was UNSIGNED, so a front-runner
    could copy a victim's shielded_transfer blob, swap only withdraw_addr to their own address, and land it
    first — the signature still verified (the address wasn't in the message) and the exit was redirected. It is
    included unconditionally (empty string for a pure in-pool transfer that has no destination) so signer and
    verifier always agree on the bound message."""
    return _h("sighash", "|".join(sorted(public.get("nullifiers", []))),
              "|".join(sorted(public.get("out_commitments", []))),
              str(int(public.get("public_value", 0))), str(int(public.get("fee", 0))),
              str(public.get("withdraw_addr", "") or ""))


# --- fixed-depth Merkle commitment tree -----------------------------------------------------------
def merkle_root(leaves) -> str:
    """Root of the fixed-depth (SHIELD_DEPTH) tree over `leaves`, padding odd/short levels with the
    empty-subtree root of that height — so the root is stable as the pool grows leaf by leaf."""
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
    """Fold `leaf` up the tree with the sibling `path` (bottom-up; pos bits pick left/right) and check the
    result equals `root`."""
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
        """Rebuild the pool from persisted lists (all optional -> empty pool) and re-register the current
        root as an anchor so a freshly-loaded pool immediately accepts proofs against its own root."""
        self.commitments = list(commitments or [])     # leaves, in insertion order (pos = index)
        self.nullifiers = set(nullifiers or [])         # spent nullifiers
        # ANCHOR WINDOW (oldest-first, BOUNDED): the recent roots a proof may target. A transfer may prove
        # against a slightly stale root (the tree grows between proof-build and landing), but we keep only the
        # last ANCHOR_WINDOW so the set can't grow forever — deterministic across nodes (same append order).
        self._cached_root = None
        self.anchor_list = list(anchors or [])
        self._remember_anchor(self.root())

    # -- state ----
    def root(self):
        """Current commitment-tree root (cached; recomputed only after an append)."""
        # SCALING: cache the O(n) root; invalidated on append. (An incremental frontier tree makes this
        # O(depth) per append — the documented next scaling step, doc/privacy.md §scaling.)
        if self._cached_root is None:
            self._cached_root = merkle_root(self.commitments)
        return self._cached_root

    def _append_commitment(self, cm):
        """Append a note leaf and invalidate the cached root."""
        self.commitments.append(cm)
        self._cached_root = None

    def _remember_anchor(self, root):
        """Record `root` in the anchor window (deduped; trimmed to the newest ANCHOR_WINDOW entries)."""
        if self.anchor_list and self.anchor_list[-1] == root:
            return
        if root in self.anchor_list:
            return
        self.anchor_list.append(root)
        if len(self.anchor_list) > ANCHOR_WINDOW:
            del self.anchor_list[:-ANCHOR_WINDOW]

    def size(self):
        """Number of notes (commitments) ever added to the pool."""
        return len(self.commitments)

    def has_nullifier(self, nf):
        """True if `nf` was already revealed by a spend (double-spend check)."""
        return nf in self.nullifiers

    def knows_root(self, root):
        """Anchor freshness: is `root` one this pool actually held recently (within ANCHOR_WINDOW)?"""
        return root in self.anchor_list

    def nullifier_digest(self):
        """One compact commitment to the WHOLE spent set (so the exec state_root binds it without one leaf per
        nullifier). SCALING: an incremental accumulator replaces this O(n) digest at large scale."""
        return _h("nfset", *sorted(self.nullifiers))

    def to_dict(self):
        """JSON-safe snapshot (nullifiers sorted for determinism); root included for inspection only —
        from_dict recomputes it."""
        return {"commitments": self.commitments, "nullifiers": sorted(self.nullifiers),
                "anchors": self.anchor_list, "root": self.root()}

    @classmethod
    def from_dict(cls, d):
        """Rebuild a pool from a to_dict snapshot."""
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
    held (anchor freshness). Returns (ok, reason).

    PHASE-2 SEAM (doc/privacy.md): if `proof` carries a "stark" bundle it routes to the zk-STARK verifier
    (execnode/stark/joinsplit_transfer) instead of re-checking the transparent witness in the clear. The
    join-split hash gadget is arithmetised + proven in ZK today; composing the FULL statement (membership +
    value conservation + nullifier) into one circuit is the remaining Phase-2 work, so the transparent path
    below stays authoritative for real spends until then. The signature of THIS function does not change."""
    if isinstance(proof, dict) and proof.get("stark"):
        from execnode.stark import joinsplit_transfer
        return joinsplit_transfer.verify_transfer(public, proof, root_is_known)
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

    if ins and not root_is_known(root):
        return False, "unknown anchor root"                        # only spends need a valid anchor (shields have no inputs)
    if len(nfs) != len(ins) or len(out_cms) != len(outs):
        return False, "public/witness length mismatch"
    if fee < 0:
        return False, "negative fee"
    if len(set(nfs)) != len(nfs):
        return False, "duplicate nullifier within the transfer"

    sighash = transfer_sighash(public)
    in_sum = 0
    for i, w in enumerate(ins):
        try:
            v = int(w["value"]); pk = w["pubkey"]; rho = w["rho"]; pos = int(w["pos"]); path = w["path"]; sig = w["sig"]
        except (KeyError, TypeError, ValueError):
            return False, "malformed input witness"
        if v < 0:
            return False, "negative input value"
        cm = note_commitment(v, owner_id(pk), rho)                 # reconstruct the input commitment
        if not verify_path(cm, pos, path, root):
            return False, f"input {i} not in the tree at root"
        if note_nullifier(pk, rho) != nfs[i]:
            return False, f"input {i} nullifier does not match the note"
        # SPEND AUTHORISATION: the input's owner must ML-DSA-sign the transfer. Knowing the note opening
        # (value, pubkey, rho) is NOT enough to spend — only the private key can produce this signature.
        try:
            authorised = mldsa_verify(signed=sig, message=unhex(sighash), public_key=pk)
        except Exception:
            authorised = False
        if not authorised:
            return False, f"input {i} spend authorisation (ML-DSA signature) invalid"
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
        pool._append_commitment(cm)
    pool._remember_anchor(pool.root())                             # the new state root becomes a valid anchor
    return True, "ok"
