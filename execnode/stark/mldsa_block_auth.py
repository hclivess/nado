"""
Block AUTHORIZATION commitments + DETACHED EVIDENCE — the block-format half of validity-proof signature
aggregation (doc/zk-signature-aggregation.md).

THE LOAD-BEARING IDEA. A block's CORE carries its transactions with signatures STRIPPED, plus two commitment
fields:
    auth_root   a field-native commitment to the ordered authorization entries
    auth_count  the exact number K of signature checks the block requires
The signatures (or the STARK proof that replaces them) travel in a SEPARATE evidence envelope, exactly one of:
    {"type": "raw",   "witnesses": [...]}      every block can always ship this
    {"type": "stark", "circuit_id": ..., "proof": ...}
and the BLOCK HASH IS IDENTICAL either way, because the hash covers only the core. That decoupling is what
makes the scheme safe to roll out: a relay can build the canonical block for an offline winner from the signed
mempool without racing proof completion, and a missing or invalid proof can never change block identity when
valid alternate evidence exists.

NARROW SCOPE. The proof attests ONLY "every authorization entry carries a valid ML-DSA-44 signature over its
txid under the sender's resolved public key". Everything else stays in the native verifier — spending,
uniqueness, fee, target height, state root, PUBKEY-ONCE resolution — AND the native verifier INDEPENDENTLY
recomputes auth_root and auth_count from the block. So a prover cannot choose the statement: it is derived
from committed data.

auth_leaf_i = H_field(AUTH_DOMAIN, block_height, tx_index, txid_limbs, sender_limbs, H(pubkey),
                      authorization_kind, signature_count)
auth_root   = the alghash2 fold over the ordered leaves (the same chain calls_commit uses, domain-separated)

This module is DORMANT with respect to consensus: it computes and checks commitments, and nothing in block
validation calls it yet. Wiring it in is a block-format change that rides a reroll (see the doc's phased
Optional -> Mandatory rollout).
"""
from execnode.stark import alghash, field as F

AUTH_DOMAIN = "nado-auth-v1"          # domain separator; a reroll-time constant
KIND_SINGLE_MLDSA44 = 1               # version 1 supports exactly this authorization kind
AUTH_VERSION = 1


def _limbs(hex_or_str, n=4):
    """Split an identifier into field limbs (deterministic, collision-preserving under the leaf hash)."""
    b = hex_or_str.encode() if isinstance(hex_or_str, str) else bytes(hex_or_str)
    out, step = [], max(1, (len(b) + n - 1) // n)
    for i in range(n):
        chunk = b[i * step:(i + 1) * step]
        out.append(int.from_bytes(chunk, "little") % F.P if chunk else 0)
    return out


def auth_leaf(block_height, tx_index, txid, sender, pubkey, kind=KIND_SINGLE_MLDSA44, sig_count=1):
    """One authorization entry's leaf — a pure function of COMMITTED public data."""
    from hashing import blake2b_hash
    # the pubkey enters as its HEX digest: blake2b_hash canonicalises via JSON, which cannot take raw bytes.
    pk_hex = (pubkey.hex() if isinstance(pubkey, (bytes, bytearray)) else str(pubkey or ""))
    payload = [AUTH_DOMAIN, int(block_height), int(tx_index), _limbs(txid), _limbs(sender),
               blake2b_hash(pk_hex), int(kind), int(sig_count)]
    return int(blake2b_hash(payload), 16) % F.P


def auth_entries(block, resolve_pubkey=None):
    """The ordered authorization entries of a block: every transaction that requires a signature check.
    `resolve_pubkey(sender)` supplies the PUBKEY-ONCE resolved key (the native verifier's own resolution)."""
    h = int(block.get("block_number", 0))
    out = []
    for idx, tx in enumerate(block.get("block_transactions", []) or []):
        sender = tx.get("sender")
        if not sender:
            continue
        pk = tx.get("public_key") or (resolve_pubkey(sender) if resolve_pubkey else None)
        out.append({"height": h, "index": idx, "txid": tx.get("txid", ""), "sender": sender,
                    "pubkey": pk or b"", "kind": KIND_SINGLE_MLDSA44, "sig_count": 1})
    return out


def auth_root(entries):
    """Fold the ordered leaves into one field element — domain-separated from the calls commitment by starting
    the chain at merkle_node(IV, IV) with auth-prefixed leaves."""
    node = alghash.merkle_node(alghash.IV, alghash.IV)
    for e in entries:
        node = alghash.merkle_node(node, auth_leaf(e["height"], e["index"], e["txid"], e["sender"],
                                                   e["pubkey"], e["kind"], e["sig_count"]))
    return node


def auth_commitments(block, resolve_pubkey=None):
    """(auth_root, auth_count) for a block — what the block CORE carries and the native verifier recomputes."""
    entries = auth_entries(block, resolve_pubkey)
    return auth_root(entries), len(entries)


# ---- detached evidence ------------------------------------------------------------------------------
def strip_signatures(block):
    """The signature-free block CORE: transactions keep everything the state machine needs (including a
    first-use public key) but drop the signature. The block HASH is taken over this core, so it is identical
    whether raw or proof evidence is shipped."""
    core = dict(block)
    txs = []
    for tx in block.get("block_transactions", []) or []:
        t = {k: v for k, v in tx.items() if k != "signature"}
        txs.append(t)
    core["block_transactions"] = txs
    return core


def raw_evidence(block):
    """The always-available evidence: the ordered signatures the core dropped."""
    return {"type": "raw",
            "witnesses": [tx.get("signature") for tx in (block.get("block_transactions") or [])
                          if tx.get("sender")]}


def stark_evidence(circuit_id, proof):
    return {"type": "stark", "circuit_id": circuit_id, "proof": proof}


def evidence_ok(evidence, block, resolve_pubkey=None, verify_sig=None, verify_proof=None):
    """Check ONE evidence envelope against a block core. Raw evidence is checked signature by signature
    (`verify_sig(sig, pubkey, txid)`); stark evidence is checked by `verify_proof(circuit_id, proof, statement)`
    where the statement is the verifier's OWN (auth_root, auth_count, height, ...) — never the prover's.
    Returns (ok, reason)."""
    if not isinstance(evidence, dict) or evidence.get("type") not in ("raw", "stark"):
        return False, "evidence must be exactly one of raw | stark"
    root, count = auth_commitments(block, resolve_pubkey)
    if int(block.get("auth_count", -1)) != count:
        return False, f"auth_count {block.get('auth_count')} != recomputed {count}"
    if int(block.get("auth_root", -1)) % F.P != root % F.P:
        return False, "auth_root does not match the block's own transactions"
    if evidence["type"] == "raw":
        entries = auth_entries(block, resolve_pubkey)
        wits = evidence.get("witnesses") or []
        if len(wits) != len(entries):
            return False, f"raw evidence has {len(wits)} witnesses for {len(entries)} entries"
        if verify_sig is None:
            return True, "raw evidence shape ok (no verifier supplied)"
        for e, sig in zip(entries, wits):
            if not verify_sig(sig, e["pubkey"], e["txid"]):
                return False, f"signature {e['index']} invalid"
        return True, f"raw evidence ok ({len(wits)} signatures)"
    if verify_proof is None:
        return True, "stark evidence shape ok (no verifier supplied)"
    statement = {"auth_version": AUTH_VERSION, "auth_root": root, "auth_count": count,
                 "height": int(block.get("block_number", 0)),
                 "parent": block.get("parent_hash") or block.get("previous_hash")}
    ok = verify_proof(evidence.get("circuit_id"), evidence.get("proof"), statement)
    return (True, f"stark evidence ok ({count} authorizations)") if ok else (False, "validity proof rejected")


def byte_saving(count, proof_bytes):
    """The size trade the rollout thresholds are set from: an ML-DSA-44 signature is 2420 B, so proof evidence
    pays off once 2420*K exceeds the proof. Returns (saved_bytes, crossover_K)."""
    saved = 2420 * int(count) - int(proof_bytes)
    crossover = -(-int(proof_bytes) // 2420)
    return saved, crossover
