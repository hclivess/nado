"""THE BLAKE2s EXEC ROOT (generation 29; Goldilocks retirement G2, doc/stwo-migration.md 9.2 and 9.5).

    state_root = BLAKE2s(KV_ROOT || RECORDS_ROOT, person=PERSON_ROOT)            64-hex

Both halves are compressed sparse trees (execnode/csmt.py; operator decision 2026-10-19, doc/stwo/g1-tree-shape.md).
This is today's execnode/exec_root.py with the Goldilocks parts replaced, leaf for leaf: the same two halves, the same
record tags, the same "zero / empty is absent" rules, so every fact the gen-28 root commits is committed here too
(tests/test_the_blake2s_exec_root_commits_every_leaf_the_old_root_does.py pins that while both exist). What changes:
  * positions are BLAKE2s of canonical bytes, one personalization per kind, instead of alghash2 over 52-bit limbs;
  * values are EXACT integers (32 bytes, big-endian) instead of residues mod the Goldilocks prime — an amount is the
    amount, so the "a field residue is not a coin amount" exit check of 2026-09-24 has nothing left to guard;
  * a missing key, not a zero, is absence (the tree has keys, not a value-0 convention); zero amounts are still
    left out, exactly as the old projection's zero leaves vanished.

FROZEN AT THE REROLL with the tree: every personalization, encoding and tag below is part of the gen-29 genesis root,
and the Stwo settlement circuit (G4) recomputes these positions. APPEND-ONLY afterwards, like the old tags.
Nothing imports this module on a consensus path until BLAKE_EXEC_HEIGHT (dormant on generation 28).
"""
import hashlib

from execnode import csmt
from execnode.exec_root import (T_BRIDGE_BAL, T_DIV_BAL, T_BRIDGE_WD, T_DIV_WD, T_UNSHIELD_WD, T_DIGEST, T_ASSET_BAL,
                                T_ASSET_META, T_ASSET_ALLOW, T_APP_ROOT, T_APP_NULL, asset_meta_digest, leaf_digest,
                                msg_outbox_leaf, msg_inbox_leaf)
from hashing import canonical_bytes, outbox_leaf

PERSON_SLOT = b"NADOkvS1"         # contract slot position
PERSON_CODE = b"NADOkvC1"         # contract code position
PERSON_META = b"NADOkvM1"         # contract meta (deployer, lock, runtime) position
PERSON_KVX = b"NADOkvX1"          # non-int storage, folded whole into the position
PERSON_REC = b"NADOrcK1"          # record position
PERSON_CODEV = b"NADOcdV1"        # the code commitment (a leaf VALUE: bounded, whatever the code's size)
PERSON_ROOT = b"NADOxR01"         # the two halves into the state root
ONE = b"\x01"                     # the value of a digest-in-position record


def _b2(data, person):
    return hashlib.blake2s(data, digest_size=32, person=person).digest()


def _id(cid) -> bytes:
    """a contract id as length-prefixed UTF-8 (cids are 32 hex or short fixed names like 'faucet'): the prefix keeps
    (cid, slot) from ever reading as another (cid', slot') with the bytes shifted between them"""
    b = str(cid).encode()
    if len(b) > 255:
        raise ValueError("contract id too long")
    return bytes([len(b)]) + b


def int_value(v) -> bytes:
    """an exact non-negative integer below 2^256 as 32 bytes big-endian; anything else (never produced by the exec
    rules) as tagged canonical bytes — a different length, so the two encodings can never collide, and never a raise
    on a consensus path"""
    if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < (1 << 256):
        return v.to_bytes(32, "big")
    return canonical_bytes(["int", repr(v)])


# ---- positions ---------------------------------------------------------------------------------------
def slot_key(cid, slot) -> bytes:
    return _b2(_id(cid) + int(slot).to_bytes(32, "big"), PERSON_SLOT)


def code_key(cid) -> bytes:
    return _b2(_id(cid), PERSON_CODE)


def meta_key(cid) -> bytes:
    return _b2(_id(cid), PERSON_META)


def kvx_key(cid, m, k, v) -> bytes:
    return _b2(canonical_bytes(["kvx", str(cid), str(m), str(k), v]), PERSON_KVX)


def record_key(tag, *parts) -> bytes:
    """the record position: canonical bytes of (tag, str(part)...) — str() as the old _limbs did, so a part means the
    same thing in both roots"""
    return _b2(canonical_bytes([int(tag), *[str(p) for p in parts]]), PERSON_REC)


def code_value(code) -> bytes:
    return _b2(canonical_bytes(code), PERSON_CODEV)


def meta_value(deployer, upgradable, runtime) -> bytes:
    return canonical_bytes(["meta", str(deployer if deployer is not None else ""), 1 if upgradable else 0,
                            str(runtime if runtime is not None else "")])


# ---- projections (one leaf per fact the old projections commit) ---------------------------------------
def kv_projection(contracts):
    """{key: value} over all contract storage, code and meta. A slot is a leaf when its value is an int in [1, 2^256);
    zero is absent; anything else is a KVX record, as in the old projection."""
    from execnode.stark import exec_state_bind as ESB      # contract_meta only: the defaults, one definition
    out = {}
    for cid in sorted(contracts):
        c = contracts[cid]
        out[meta_key(cid)] = meta_value(*ESB.contract_meta(c))
        if c.get("code") is not None:
            out[code_key(cid)] = code_value(c["code"])
        for m, kv in (c.get("storage") or {}).items():
            for k, v in kv.items():
                if m == "slots" and isinstance(v, int) and not isinstance(v, bool):
                    try:
                        s = int(k)
                    except (ValueError, TypeError):
                        s = None
                    if s is not None and 0 <= s < (1 << 256) and 0 <= v < (1 << 256):
                        if v:
                            out[slot_key(cid, s)] = int_value(v)
                        continue
                out[kvx_key(cid, m, k, v)] = ONE
    return out


def _amount(out, key, amt):
    v = int(amt)
    if v:                                                  # zero is absent, as the old tree's value-0 leaves were
        out[key] = int_value(v)


def records_projection(st):
    """{key: value} over the exec layer's non-contract state — exec_root.records_projection, record for record."""
    out = {}
    for addr, amt in st.bridge.items():
        _amount(out, record_key(T_BRIDGE_BAL, addr), amt)
    for addr, amt in st.dividend.items():
        _amount(out, record_key(T_DIV_BAL, addr), amt)
    for aid, row in getattr(st, "abal", {}).items():
        for holder, amt in row.items():
            _amount(out, record_key(T_ASSET_BAL, aid, holder), amt)
    for aid, meta in getattr(st, "assets", {}).items():
        out[record_key(T_ASSET_META, aid, asset_meta_digest(meta))] = ONE
    for aid, owners in getattr(st, "allow", {}).items():
        for owner, row in owners.items():
            for spender, amt in row.items():
                _amount(out, record_key(T_ASSET_ALLOW, aid, owner, spender), amt)
    for nonce, w in st.withdrawals.items():
        _amount(out, record_key(T_BRIDGE_WD, w["addr"], nonce), w["amount"])
    for nonce, w in st.dividend_withdrawals.items():
        _amount(out, record_key(T_DIV_WD, w["addr"], nonce), w["amount"])
    for nonce, w in st.unshield_withdrawals.items():
        _amount(out, record_key(T_UNSHIELD_WD, w["addr"], nonce), w["amount"])
    # the legacy pools must be EMPTY at the gen-29 carry (doc/stwo-migration.md 6.4b; the carry refuses otherwise), so
    # on generation 29 these two digests are the empty pools' — committed anyway, so the root still binds "empty"
    out[record_key(T_DIGEST, "shield_root", st.shielded.root())] = ONE
    out[record_key(T_DIGEST, "shield_nfset", st.shielded.nullifier_digest())] = ONE
    from execnode.stark import field as _F                  # the field pool's root is a field element by nature;
    out[record_key(T_DIGEST, "field_root", str(int(st.field_pool.root()) % _F.P))] = ONE   # same string as before
    from hashing import blake2b_hash
    out[record_key(T_DIGEST, "field_nfset",
                   blake2b_hash(["field_nfset", *sorted(str(n) for n in st.field_pool.nullifiers)]))] = ONE
    wp = getattr(st, "wide_pool", None)
    if wp is not None and (wp.commitments or wp.nullifiers):
        from execnode.stark import znote as _Z
        out[record_key(T_DIGEST, "wide_root", _Z.to_hex(wp.root()))] = ONE
        out[record_key(T_DIGEST, "wide_nfset", wp.nullifier_digest())] = ONE
    sp = getattr(st, "stwo_pool", None)
    if sp is not None and (sp.commitments or sp.nullifiers):
        out[record_key(T_DIGEST, "stwo_root", sp.root())] = ONE
        out[record_key(T_DIGEST, "stwo_nfset", sp.nullifier_digest())] = ONE
        if sp.marks:
            out[record_key(T_DIGEST, "stwo_marks", sp.marks_digest())] = ONE
    sv = int(getattr(st, "stwo_value", 0) or 0)
    if sv:
        out[record_key(T_DIGEST, "stwo_value", str(sv))] = ONE
    app = getattr(st, "app_state", None)
    if app is not None:
        for cid in sorted(app.trees):
            if not app.trees[cid]:
                continue
            out[record_key(T_APP_ROOT, cid, str(int(app.root(cid)) % _F.P))] = ONE
        if app.nullifiers:
            out[record_key(T_APP_NULL, app.nullifier_digest())] = ONE
    for _s, msg in st.outbox.items():
        out[record_key(T_DIGEST, "outbox", leaf_digest(msg_outbox_leaf(msg)))] = ONE
    for i, msg in enumerate(st.inbox):
        out[record_key(T_DIGEST, "inbox", leaf_digest(msg_inbox_leaf(i, msg)))] = ONE
    return out


# ---- the root -----------------------------------------------------------------------------------------
def full_root(kv_root: bytes, rec_root: bytes) -> bytes:
    return _b2(kv_root + rec_root, PERSON_ROOT)


def state_root_hex(contracts, st) -> str:
    """cold computation from scratch (genesis, tools, tests); a node keeps the two csmt.Tree objects and updates them"""
    return full_root(csmt.root_of(kv_projection(contracts)), csmt.root_of(records_projection(st))).hex()


# ---- exit proofs (prove exec-side, verify on L1 — both through THIS module) ---------------------------
def record_proof(kv_tree: "csmt.Tree", rec_tree: "csmt.Tree", key: bytes) -> dict:
    """{"kv": 64-hex kv half-root, "s": [64-hex siblings, root first], "t": terminal} — the gen-29 exit wire format"""
    sibs, term = rec_tree.prove(key)
    t = ["empty"] if term[0] == "empty" else ["leaf", term[1].hex(), term[2].hex()]
    return {"kv": kv_tree.root().hex(), "s": [s.hex() for s in sibs], "t": t}


def verify_record(settled_hex, key: bytes, value, proof) -> bool:
    """L1's exit verifier: the record `key` holds `value` (bytes; None = absent) in the records half, composed with the
    claimed KV half into the settled root. False — never raises — on anything malformed."""
    try:
        if not isinstance(proof, dict) or not isinstance(settled_hex, str):
            return False
        kv = bytes.fromhex(proof["kv"])
        sibs = [bytes.fromhex(x) for x in proof["s"]]
        t = proof["t"]
        term = ("empty",) if t == ["empty"] else ("leaf", bytes.fromhex(t[1]), bytes.fromhex(t[2])) if (
            isinstance(t, list) and len(t) == 3 and t[0] == "leaf") else None
        if term is None or len(kv) != 32 or len(sibs) > csmt.MAX_DEPTH:
            return False
        # the records half's root, recomputed from the path, then composed: a correct path to a WRONG kv half fails
        rec_root = _fold(key, value, sibs, term)
        return rec_root is not None and full_root(kv, rec_root).hex() == settled_hex
    except Exception:
        return False


def _fold(key, value, sibs, term):
    """the records half's root this proof implies, or None if the proof is not a valid csmt proof for (key, value)"""
    # csmt.verify checks shape and claim against a GIVEN root; here the root is the unknown, so recompute it the same
    # way verify does and let verify confirm the shape against what we computed
    if term[0] == "leaf":
        h = csmt.leaf_hash(term[1], term[2])
    else:
        h = csmt.EMPTY
    for i in range(len(sibs) - 1, -1, -1):
        h = csmt.node_hash(sibs[i], h) if csmt.bit(key, i) else csmt.node_hash(h, sibs[i])
    return h if csmt.verify(h, key, value, (sibs, term)) else None


def verify_withdrawal(settled_hex, addr, amount, nonce, proof):
    return verify_record(settled_hex, record_key(T_BRIDGE_WD, addr, nonce), int_value(int(amount)), proof)


def verify_dividend(settled_hex, addr, amount, nonce, proof):
    return verify_record(settled_hex, record_key(T_DIV_WD, addr, nonce), int_value(int(amount)), proof)


def verify_unshield(settled_hex, addr, amount, nonce, proof):
    return verify_record(settled_hex, record_key(T_UNSHIELD_WD, addr, nonce), int_value(int(amount)), proof)


def verify_outbox_msg(settled_hex, seq, sender, to_ns, data, proof):
    dg = leaf_digest(outbox_leaf(seq, sender, to_ns, data))
    return verify_record(settled_hex, record_key(T_DIGEST, "outbox", dg), ONE, proof)
