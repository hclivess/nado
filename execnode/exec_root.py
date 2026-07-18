"""
THE settled execution-layer state root (alphanet-6, FROZEN SCHEME — doc/zk-recursion.md §5c deployment).

    state_root = alghash2.rnode( KV_ROOT , RECORDS_ROOT )         serialized 64-hex (storage_tree.digest_hex)

Both halves are depth-256 sparse alghash2 Merkle trees (storage_tree.SparseStore) — depth 256 saturates the
hash's own 128-bit collision resistance, so the scheme never needs a depth bump; alghash2 positions keep every
half arithmetization-friendly, so extending validity proofs over MORE of the root later (records half, exits)
is forward-compatible work on the SAME tree — no future genesis reroll, no hard fork, for any vision.md feature.

  KV half — contract storage. position = exec_state_bind.slot_key(cid, slot) (alghash2, in-circuit provable —
  the O(1) settlement machinery binds THIS half today: merkle_update / io_replay / settlement_aggregate).
  Non-"slots"/non-int storage is committed via a KVX digest record (completeness net; zkvm only writes slots).

  RECORDS half — everything else the exec layer must agree on and L1 exits must verify:
    * amounts as VALUES at alghash2-derived positions:   bridge/dividend balances, bridge/dividend/unshield
      withdrawal records (position binds (addr, nonce) at 256 bits; value = amount; a zero amount == absent,
      consistent with L1 exits asserting amount > 0).
    * digests IN THE POSITION (value = 1): shielded-pool root/nullifier set, field pool root/nullifier set,
      outbox + inbox messages — the 256-bit position IS the commitment, so a 64-bit value never bounds binding.

  record positions: alghash2.hashn([DOM_REC, tag, …parts]) where every part is blake2b-folded to 5×52-bit field
  limbs (the cid_limbs pattern: the fold is native over PUBLIC data; the hashn is the part a future in-circuit
  record proof arithmetizes — one more reason nothing here ever needs to change).

An exit proof is {"kv": 64-hex kv-root, "path": packed records path}: L1 recomputes the record position from the
tx's public fields, folds the packed path (storage_tree.unpack_path — ~1KB, only non-empty siblings), and checks
rnode(kv, folded) == the settled root. One settled root serves execution AND exits.
"""
import hashlib
from hashing import blake2b_hash, canonical_bytes, outbox_leaf
from execnode.stark import field as F, alghash2 as A2, storage_tree as ST, exec_state_bind as ESB

# Leaf-digest domain tag (brand-carrying; renamed only at a CHAIN_GENERATION reroll).
DOMAIN_REC_DIGEST = b"rec-digest-v1"

DEPTH = 256                       # FROZEN: the full digest — position security = the hash's own strength
DOM_REC = 8                       # record-position domain (exec_state_bind DOM_KVPOS = 7)

# record tags (FROZEN)
T_BRIDGE_BAL, T_DIV_BAL, T_BRIDGE_WD, T_DIV_WD, T_UNSHIELD_WD, T_DIGEST, T_KVX = 1, 2, 3, 4, 5, 6, 7


def _limbs(part):
    """Any public value → 5×52-bit field limbs via a blake2b fold (native, over public data — the same
    cid_limbs pattern the in-circuit slot_key derivation consumes)."""
    n = int(blake2b_hash(["rec", str(part)]), 16)
    return [(n >> (52 * i)) & ((1 << 52) - 1) for i in range(5)]


def record_key(tag, *parts):
    """The FROZEN record position: alghash2.hashn([DOM_REC, tag, …limbs(part)…]) packed big-endian to 256 bits."""
    els = [DOM_REC, int(tag)]
    for p in parts:
        els.extend(_limbs(p))
    acc = 0
    for lane in A2.hashn(els):
        acc = (acc << 64) | int(lane)
    return acc & ((1 << DEPTH) - 1)


def leaf_digest(leaf_bytes):
    """64-hex digest of a canonical message-leaf's bytes — what a digest record commits in its position."""
    return hashlib.blake2b(DOMAIN_REC_DIGEST + leaf_bytes, digest_size=32).hexdigest()


def msg_outbox_leaf(msg):
    """Canonical bytes for one outbox message (shared with L1 xmsg verification via THIS module)."""
    return outbox_leaf(msg["seq"], msg["from"], msg["to_ns"], msg.get("data"))


def msg_inbox_leaf(i, msg):
    """Canonical bytes for one DELIVERED cross-domain message (index-tagged, append-only)."""
    return canonical_bytes(["inbox", int(i), msg.get("from_ns"), int(msg.get("seq", -1)), msg.get("data")])


def kvx_key(cid, m, k, v):
    """Completeness net for storage OUTSIDE the int-valued 'slots' map: the whole (cid, map, key, value) is
    folded into the position (value = 1). zkvm writes only int slots, so this is normally empty — but nothing
    a runtime could ever store escapes the committed root."""
    n = blake2b_hash(["kvx", str(cid), str(m), str(k), v])
    return record_key(T_KVX, n)


# ---- projections -------------------------------------------------------------------------------------
def kv_projection(contracts):
    """{position: value} over ALL contract storage: int-valued 'slots' at slot_key(cid, slot) (the in-circuit
    positions the settlement machinery proves), anything else as a KVX digest record."""
    out = {}
    for cid in sorted(contracts):
        for m, kv in ((contracts[cid].get("storage") or {})).items():
            for k, v in kv.items():
                if m == "slots" and isinstance(v, int):
                    try:
                        out[ESB.slot_key(cid, int(k), DEPTH)] = int(v) % F.P
                        continue
                    except (ValueError, TypeError):
                        pass
                out[kvx_key(cid, m, k, v)] = 1
    return out


def records_projection(st):
    """{position: value} over the exec layer's non-contract state. `st` is duck-typed (an ExecState or anything
    exposing .bridge/.dividend/.withdrawals/.dividend_withdrawals/.unshield_withdrawals/.shielded/.field_pool/
    .outbox/.inbox)."""
    out = {}
    for addr, amt in st.bridge.items():
        out[record_key(T_BRIDGE_BAL, addr)] = int(amt) % F.P
    for addr, amt in st.dividend.items():
        out[record_key(T_DIV_BAL, addr)] = int(amt) % F.P
    for nonce, w in st.withdrawals.items():
        out[record_key(T_BRIDGE_WD, w["addr"], nonce)] = int(w["amount"]) % F.P
    for nonce, w in st.dividend_withdrawals.items():
        out[record_key(T_DIV_WD, w["addr"], nonce)] = int(w["amount"]) % F.P
    for nonce, w in st.unshield_withdrawals.items():
        out[record_key(T_UNSHIELD_WD, w["addr"], nonce)] = int(w["amount"]) % F.P
    out[record_key(T_DIGEST, "shield_root", st.shielded.root())] = 1
    out[record_key(T_DIGEST, "shield_nfset", st.shielded.nullifier_digest())] = 1
    out[record_key(T_DIGEST, "field_root", str(int(st.field_pool.root()) % F.P))] = 1
    out[record_key(T_DIGEST, "field_nfset",
                   blake2b_hash(["field_nfset", *sorted(str(n) for n in st.field_pool.nullifiers)]))] = 1
    for _s, msg in st.outbox.items():
        out[record_key(T_DIGEST, "outbox", leaf_digest(msg_outbox_leaf(msg)))] = 1
    for i, msg in enumerate(st.inbox):
        out[record_key(T_DIGEST, "inbox", leaf_digest(msg_inbox_leaf(i, msg)))] = 1
    return out


def apply_projection(store, projection):
    """Diff-apply a fresh projection onto a persistent SparseStore: delete what vanished, write what changed —
    O(changed · depth) hashing instead of a cold rebuild. The store's root is then THE half-root."""
    for k in [k for k in store.values if k not in projection]:
        store.set(k, 0)
    for k, v in projection.items():
        if store.values.get(k) != v:
            store.set(k, v)


# ---- the root ----------------------------------------------------------------------------------------
def full_root_hex(kv_root, rec_root):
    """state_root = rnode(kv, records), 64-hex."""
    return ST.digest_hex(A2.rnode(kv_root, rec_root))


def state_root_hex(contracts, st):
    """Cold computation of the settled root from scratch (genesis/tools/tests; the node itself goes through
    persistent stores + apply_projection)."""
    kv = ST.SparseStore(DEPTH, kv_projection(contracts))
    rec = ST.SparseStore(DEPTH, records_projection(st))
    return full_root_hex(kv.root(), rec.root())


# ---- exit proofs (prove exec-side, verify on L1 — both through THIS module) ---------------------------
def record_proof(kv_root, rec_store, pos):
    """{"kv": 64-hex kv half-root, "path": packed records path for `pos`} — the exit proof wire format."""
    return {"kv": ST.digest_hex(kv_root), "path": ST.pack_path(rec_store.path(pos), DEPTH)}


def verify_record(settled_hex, pos, value, proof):
    """L1's ONE bounded exit verifier: fold `value` at `pos` through the packed records path, compose with the
    claimed kv half, compare to the settled 64-hex root. False (never raises) on anything malformed."""
    try:
        if not isinstance(proof, dict):
            return False
        sibs = ST.unpack_path(proof.get("path"), DEPTH)
        if sibs is None:
            return False
        kv = ST.digest_from_hex(proof.get("kv"))
        rec = ST.fold(int(value) % F.P, int(pos), sibs)
        return full_root_hex(kv, rec) == settled_hex
    except Exception:
        return False


def verify_withdrawal(settled_hex, addr, amount, nonce, proof):
    return verify_record(settled_hex, record_key(T_BRIDGE_WD, addr, nonce), int(amount), proof)


def verify_dividend(settled_hex, addr, amount, nonce, proof):
    return verify_record(settled_hex, record_key(T_DIV_WD, addr, nonce), int(amount), proof)


def verify_unshield(settled_hex, addr, amount, nonce, proof):
    return verify_record(settled_hex, record_key(T_UNSHIELD_WD, addr, nonce), int(amount), proof)


def verify_outbox_msg(settled_hex, seq, sender, to_ns, data, proof):
    dg = leaf_digest(outbox_leaf(seq, sender, to_ns, data))
    return verify_record(settled_hex, record_key(T_DIGEST, "outbox", dg), 1, proof)
