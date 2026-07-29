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

auth_leaf_i = H_field(AUTH_DOMAIN, block_height, tx_index, txid_limbs, sender_limbs,
                      authorization_kind, signature_count)
auth_root   = the alghash2 fold over the ordered leaves (the same chain calls_commit uses, domain-separated)

THE LEAF CARRIES NO PUBLIC KEY, DELIBERATELY. It used to hash H(pubkey), and that was wrong the moment
auth_root entered the block hash preimage: under PUBKEY-ONCE a transaction MAY omit public_key, so resolving
it means reading as-of-parent account state, and the block hash would then depend on state. NADO already
enforces exactly one state-dependent header field (state_root) and treats a mismatch as fatal; adding a
second one buys nothing, because `sender` IS the address derived from the key and proof_sender() binds the
two natively on every single transaction. So the leaf is a pure function of IN-BLOCK data, the key stays the
native verifier's business, and a proof's public statement takes the pubkey the VERIFIER resolved — never one
the prover chose.

WIRED (alphanet-14): ops/block_ops.construct_block commits (auth_root, auth_count) inside the hash preimage
and core_loop.verify_block independently recomputes both from the block's own transactions and rejects on
mismatch. Evidence itself is DETACHED (see evidence_ok): raw signatures are what every block ships today, and
a stark envelope is accepted wherever a prover can supply one — same block hash either way.
"""
from execnode.stark import alghash, field as F

AUTH_DOMAIN = "nado-auth-v1"          # domain separator; a reroll-time constant
KIND_SINGLE_MLDSA44 = 1               # one ML-DSA-44 signature by the sender's own key
KIND_MULTISIG_MLDSA44 = 2             # a descriptor account: M member signatures over the same txid
AUTH_VERSION = 1


def _limbs(hex_or_str, n=4):
    """Split an identifier into field limbs (deterministic, collision-preserving under the leaf hash)."""
    b = hex_or_str.encode() if isinstance(hex_or_str, str) else bytes(hex_or_str)
    out, step = [], max(1, (len(b) + n - 1) // n)
    for i in range(n):
        chunk = b[i * step:(i + 1) * step]
        out.append(int.from_bytes(chunk, "little") % F.P if chunk else 0)
    return out


def auth_leaf(block_height, tx_index, txid, sender, kind=KIND_SINGLE_MLDSA44, sig_count=1):
    """One authorization entry's leaf — a pure function of the block's OWN committed data (no state read).
    See the module docstring for why the public key is deliberately absent."""
    from hashing import blake2b_hash
    payload = [AUTH_DOMAIN, AUTH_VERSION, int(block_height), int(tx_index),
               _limbs(txid), _limbs(sender), int(kind), int(sig_count)]
    return int(blake2b_hash(payload), 16) % F.P


def auth_entries(block):
    """The ordered authorization entries of a block: every transaction that requires a signature check.

    Derived from the block body alone, in the block's own transaction order — which construct_block has
    already canonicalised by txid, so two nodes holding the same tx set produce the same entries and hence
    the same root."""
    h = int(block.get("block_number", 0))
    out = []
    for idx, tx in enumerate(block.get("block_transactions", []) or []):
        sender = tx.get("sender")
        if not sender:
            continue
        if tx.get("multisig") is not None:
            # A descriptor account authorises with M member signatures over the same txid, so the entry
            # declares BOTH a different kind and the real check count. Counting it as one would let a block
            # commit K checks and require more, which is the whole thing auth_count exists to pin.
            sigs = tx.get("signature")
            kind, n = KIND_MULTISIG_MLDSA44, (len(sigs) if isinstance(sigs, list) else 0)
        else:
            kind, n = KIND_SINGLE_MLDSA44, 1
        out.append({"height": h, "index": idx, "txid": tx.get("txid", ""), "sender": sender,
                    "kind": kind, "sig_count": n})
    return out


def auth_root(entries):
    """Fold the ordered leaves into one field element — domain-separated from the calls commitment by starting
    the chain at merkle_node(IV, IV) with auth-prefixed leaves."""
    node = alghash.merkle_node(alghash.IV, alghash.IV)
    for e in entries:
        node = alghash.merkle_node(node, auth_leaf(e["height"], e["index"], e["txid"], e["sender"],
                                                   e["kind"], e["sig_count"]))
    return node


def auth_commitments(block):
    """(auth_root, auth_count) for a block — what the block CORE carries and the native verifier recomputes.

    auth_count is the number of authorization ENTRIES; the number of SIGNATURE CHECKS is sig_checks(), which
    differs once a multisig entry is present. The header pins the entry count because that is what indexes
    the root; the check count rides inside each leaf and so is pinned too."""
    entries = auth_entries(block)
    return auth_root(entries), len(entries)


def sig_checks(block):
    """Total ML-DSA verifications a block demands — the number an aggregate proof must cover."""
    return sum(int(e["sig_count"]) for e in auth_entries(block))


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
    root, count = auth_commitments(block)
    if int(block.get("auth_count", -1)) != count:
        return False, f"auth_count {block.get('auth_count')} != recomputed {count}"
    if int(block.get("auth_root", -1)) % F.P != root % F.P:
        return False, "auth_root does not match the block's own transactions"
    if evidence["type"] == "raw":
        entries = auth_entries(block)
        wits = evidence.get("witnesses") or []
        if len(wits) != len(entries):
            return False, f"raw evidence has {len(wits)} witnesses for {len(entries)} entries"
        if verify_sig is None:
            return True, "raw evidence shape ok (no verifier supplied)"
        for e, sig in zip(entries, wits):
            # The KEY comes from the verifier's own PUBKEY-ONCE resolution, never from the leaf and never
            # from the envelope — an envelope that could name its own key would verify against itself.
            pk = resolve_pubkey(e["sender"]) if resolve_pubkey else None
            if not verify_sig(sig, pk, e["txid"]):
                return False, f"signature {e['index']} invalid"
        return True, f"raw evidence ok ({len(wits)} signatures)"
    if verify_proof is None:
        return True, "stark evidence shape ok (no verifier supplied)"
    # The statement is built ENTIRELY from what the verifier derived: the recomputed root and count, the
    # block's own height and parent, the entries read out of the block body, and the keys OUR PUBKEY-ONCE
    # resolution produced. Nothing in it comes from the envelope. `witnesses` are the signatures the block
    # itself carries — the current sub-AIRs take the signature as a PUBLIC input, so an aggregate proof
    # offloads the verification ARITHMETIC rather than the signature BYTES; making the signature a witness
    # is what the byte-saving phase needs and it is an AIR change, not a wiring one.
    entries = auth_entries(block)
    txs = block.get("block_transactions") or []
    statement = {"auth_version": AUTH_VERSION, "auth_root": root, "auth_count": count,
                 "height": int(block.get("block_number", 0)),
                 "parent": block.get("parent_hash") or block.get("previous_hash"),
                 "entries": entries,
                 "pubkeys": [resolve_pubkey(e["sender"]) if resolve_pubkey else None for e in entries],
                 "witnesses": [txs[e["index"]].get("signature") for e in entries]}
    ok = verify_proof(evidence.get("circuit_id"), evidence.get("proof"), statement)
    return (True, f"stark evidence ok ({count} authorizations)") if ok else (False, "validity proof rejected")


def byte_saving(count, proof_bytes):
    """The size trade the rollout thresholds are set from: an ML-DSA-44 signature is 2420 B, so proof evidence
    pays off once 2420*K exceeds the proof. Returns (saved_bytes, crossover_K)."""
    saved = 2420 * int(count) - int(proof_bytes)
    crossover = -(-int(proof_bytes) // 2420)
    return saved, crossover
