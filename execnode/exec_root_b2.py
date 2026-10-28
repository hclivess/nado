"""THE BLAKE2s EXEC ROOT (generation 29; Goldilocks retirement G2, doc/stwo-migration.md 9.2 and 9.5).

    state_root = BLAKE2s(KV_ROOT || RECORDS_ROOT, person=PERSON_ROOT)            64-hex

Both halves are compressed sparse trees (execnode/csmt.py; operator decision 2026-10-19, doc/stwo/g1-tree-shape.md).
This is today's execnode/exec_root.py with the Goldilocks parts replaced, leaf for leaf: the same two halves, the same
record tags, the same "zero / empty is absent" rules, so every fact the gen-28 root commits is committed here too
(tests/test_the_blake2s_exec_root_commits_every_leaf_the_old_root_does.py pins it against the old root's frozen leaves). What changes:
  * positions are BLAKE2s of canonical bytes, one personalization per kind, instead of alghash2 over 52-bit limbs;
  * values are EXACT integers (32 bytes, big-endian) instead of residues mod the Goldilocks prime — an amount is the
    amount, so the "a field residue is not a coin amount" exit check of 2026-09-24 has nothing left to guard;
  * a missing key, not a zero, is absence (the tree has keys, not a value-0 convention); zero amounts are still
    left out, exactly as the old projection's zero leaves vanished.

FROZEN AT THE REROLL with the tree: every personalization, encoding and tag below is part of the gen-29 genesis root,
and the Stwo settlement circuit (G4) recomputes these positions. APPEND-ONLY afterwards, like the old tags.
This is generation 29's exec root at every cursor (BLAKE_EXEC_HEIGHT, gen 28's gate, inlined in G9).
"""
import hashlib

from execnode import csmt
from hashing import blake2b_hash, canonical_bytes, outbox_leaf

# Leaf-digest domain tag (brand-carrying; renamed only at a CHAIN_GENERATION reroll).
DOMAIN_REC_DIGEST = b"rec-digest-v1"

# record tags (FROZEN — APPEND only; an existing tag's number is part of every settled root ever computed)
T_BRIDGE_BAL, T_DIV_BAL, T_BRIDGE_WD, T_DIV_WD, T_UNSHIELD_WD, T_DIGEST, T_KVX = 1, 2, 3, 4, 5, 6, 7
T_ASSET_BAL, T_ASSET_META = 8, 9   # (asset, holder) -> balance, and asset -> a digest of its metadata
T_ASSET_ALLOW = 10                 # (asset, owner, spender) -> allowance (delegated-spend authorization)
# 11/12 were the shielded-contract state's (cid, note root) and spent-set digest (deleted in G9 slice 5, never
# populated on generation 29). The numbers stay RESERVED: a tag is never reused for another record kind.
T_APP_ROOT, T_APP_NULL = 11, 12

# THE RETIRED FIELD POOL'S RECORDS (G9 slice 5). The Goldilocks field pool (and the wide pool and shielded-contract state
# that tags 11/12 served) are deleted: on generation 29 no entry point could add a note to them, so they were empty at
# every height. The empty field pool still projected two T_DIGEST records into every gen-29 root, so they are committed
# here BYTE-IDENTICALLY as constants — its root (a field element, as the decimal string it always was) and the digest of
# its empty spent set, blake2b_hash(["field_nfset"]). INVARIANT: every gen-29 root depends on these two; a reroll may
# drop them only together with a CHAIN_GENERATION bump (tests/test_the_retired_pools_commit_their_empty_digests.py).
RETIRED_FIELD_ROOT = "12068980620996700996"
RETIRED_FIELD_NFSET = "caeaaec45c69de5493ca19f3967f5706552b5840fa46f33a33681f97d0f72b37"


def leaf_digest(leaf_bytes):
    """64-hex digest of a canonical message-leaf's bytes — what a digest record commits in its position."""
    return hashlib.blake2b(DOMAIN_REC_DIGEST + leaf_bytes, digest_size=32).hexdigest()


def msg_outbox_leaf(msg):
    """Canonical bytes for one outbox message (shared with L1 xmsg verification via THIS module)."""
    return outbox_leaf(msg["seq"], msg["from"], msg["to_ns"], msg.get("data"))


def msg_inbox_leaf(i, msg):
    """Canonical bytes for one DELIVERED cross-domain message (index-tagged, append-only)."""
    return canonical_bytes(["inbox", int(i), msg.get("from_ns"), int(msg.get("seq", -1)), msg.get("data")])


def asset_meta_digest(meta):
    """The digest an asset's T_ASSET_META leaf is positioned by. ONE encoding, shared by records_projection and
    records_bind's asset derivation: the settle verifier authenticates a prover-supplied metadata preimage by
    finding THIS leaf in the pinned projection, and a second copy of the encoding would drift from the first."""
    return blake2b_hash(["asset", meta["issuer"], int(meta["seed"]), meta["name"], meta["sym"], int(meta["dec"]),
                         int(meta["supply"]), bool(meta["mintable"]), meta.get("uri", "")])


PERSON_SLOT = b"NADOkvS1"         # contract slot position
PERSON_CODE = b"NADOkvC1"         # contract code position
PERSON_META = b"NADOkvM1"         # contract meta (deployer, lock, runtime) position
PERSON_KVX = b"NADOkvX1"          # non-int storage, folded whole into the position
PERSON_REC = b"NADOrcK1"          # record position
PERSON_CODEV = b"NADOcdV1"        # the code commitment (a leaf VALUE: bounded, whatever the code's size)
PERSON_ROOT = b"NADOxR01"         # the two halves into the state root
ONE = b"\x01"                     # the value of a digest-in-position record

# THE COUNTERS (G4, 2026-10-20) — a record tag that exists only in this root. A withdrawal record's POSITION includes a
# nonce from an exec-state counter (wd_nonce for bridge_withdraw, dw_nonce for collect_dividend, uw_nonce for unshield
# exits) and outbox_seq numbers emitted messages; the gen-28 root commits none of them, so a settlement proof could not
# authenticate where a new withdrawal leaf goes — the reason collect_dividend made 17 of 22 settle-proof spans
# unprovable (doc/stwo-migration.md 9.3). Committed here, a proof reads the nonce from the pinned pre-state. Zero is
# absent, like every other record. FROZEN at the reroll with the rest of the root.
T_COUNTER = 13
COUNTERS = ("wd_nonce", "dw_nonce", "uw_nonce", "outbox_seq")

# THE DIGEST REGISTRY (protocol.EXEC_ADDR_ROOT_HEIGHT, G4 2026-10-27): one record per ExecState.zk_addrs entry, positioned
# by the digest (its decimal string, the registry's own key) and valued by the address. A PAY to a digest the registry
# lacks reverts, so the registry decides outcomes; committed, a settlement proof reads it from the pre-state like any
# other record (execnode/settle_b2.py). From the gate's cursor only, so every root before it is unchanged.
T_ADDR = 14


def addr_root_at(cursor) -> bool:
    """Whether the root AT `cursor` commits the digest registry (protocol.EXEC_ADDR_ROOT_HEIGHT). ONE predicate for the
    exec node's root and the settlement replay."""
    from protocol import EXEC_ADDR_ROOT_HEIGHT as H
    return bool(H) and int(cursor) >= H


def addr_value(addr) -> bytes:
    return str(addr).encode()


# THE DIVIDEND CARRY (protocol.EXEC_CARRY_ROOT_HEIGHT, 2026-10-28): ExecState.div_carry, the undistributed remainder every
# dividend accrual reads, as one more T_COUNTER record. A NAME in the counter family, not a new tag: its position is
# record_key(T_COUNTER, "div_carry"), disjoint from the four COUNTERS by its part, and its value is the exact integer
# (zero absent, like every counter). COUNTERS itself stays frozen: the carry joins the projection only from the gate's
# cursor, so every root before it is unchanged. A settlement replay reads it from the span's pre root (settle_b2), which
# is what lets a span cross an epoch boundary without L1 keeping the carry in exec summaries (measured broken at 10860).
CARRY_COUNTER = "div_carry"


def carry_root_at(cursor) -> bool:
    """Whether the root AT `cursor` commits the dividend carry (protocol.EXEC_CARRY_ROOT_HEIGHT). ONE predicate for the
    exec node's root, the settlement replay, the exec node's prover and L1's span check."""
    from protocol import EXEC_CARRY_ROOT_HEIGHT as H
    return bool(H) and int(cursor) >= H


def projection_gate_at(cursor) -> bool:
    """Whether the projection's SHAPE changes at exactly `cursor` with no state mutation (a cursor-gated record kind
    starts there). The exec node memoises its root on mutations (ExecState._touch), so block_apply.close touches the state
    at this cursor; without it a block that mutates nothing at the gate keeps the previous cursor's root, which a cold
    projection (a restarted node, a stash check, the prover) computes WITH the new record — two roots for one state.
    INVARIANT: every cursor-gated record kind added to records_projection is named here. (EXEC_ADDR_ROOT_HEIGHT predates
    this and is already behind the live tip; it is deliberately not named, so no replay of its blocks moves.)"""
    from protocol import EXEC_CARRY_ROOT_HEIGHT as H
    return bool(H) and int(cursor) == H


def genesis_canary() -> str:
    """The empty exec layer's root in THIS generation's format: protocol.EXEC_GENESIS_ROOT_B2. INVARIANT: every runtime
    reader of the genesis root goes through here — the exec node's start-up canary and L1's pre-settlement header
    sentinel both read the alghash constant directly until 2026-10-19, which on generation 29 would have refused every
    exec node's start."""
    # BLAKE_EXEC_HEIGHT (gen 28's gate, 1 from gen 29, inlined in G9; it was exec_root_b2.blake_exec_at, deleted with
    # it): the exec root is this module's at every cursor, genesis cursors -1 and 0 included, so the canary is the
    # BLAKE2s one. (protocol.EXEC_GENESIS_ROOT, the Goldilocks root, went with execnode/exec_root.py in G9 slice 4.)
    import protocol
    return protocol.EXEC_GENESIS_ROOT_B2


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


def contract_meta(c):
    """(deployer, upgradable, runtime) of a contract record, with the defaults the exec layer applies: a legacy record
    with no flag is upgradable; no runtime is the default runtime. The ONE definition of those defaults (it lived in
    execnode/stark/exec_state_bind.py until G9 slice 4): the meta leaf below and settle_b2's witness leaves both read
    it, so a default changed in one place cannot make the two roots disagree."""
    return (c.get("deployer", ""), c.get("upgradable", True) is not False, c.get("runtime", "zkvm"))


def meta_value(deployer, upgradable, runtime) -> bytes:
    return canonical_bytes(["meta", str(deployer if deployer is not None else ""), 1 if upgradable else 0,
                            str(runtime if runtime is not None else "")])


# ---- projections (one leaf per fact the old projections commit) ---------------------------------------
def kv_projection(contracts):
    """{key: value} over all contract storage, code and meta. A slot is a leaf when its value is an int in [1, 2^256);
    zero is absent; anything else is a KVX record, as in the old projection."""
    out = {}
    for cid in sorted(contracts):
        c = contracts[cid]
        out[meta_key(cid)] = meta_value(*contract_meta(c))
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
    # the LEGACY BLAKE2b pool is empty at the gen-29 carry (doc/stwo-migration.md 6.4b) but still LIVE for zero-value
    # notes (ExecState "shielded_transfer"), so its two digests are computed from the pool, never pinned
    out[record_key(T_DIGEST, "shield_root", st.shielded.root())] = ONE
    out[record_key(T_DIGEST, "shield_nfset", st.shielded.nullifier_digest())] = ONE
    # THE DELETED FIELD POOL'S TWO RECORDS, as the constants they were on every gen-29 state (see RETIRED_FIELD_ROOT)
    out[record_key(T_DIGEST, "field_root", RETIRED_FIELD_ROOT)] = ONE
    out[record_key(T_DIGEST, "field_nfset", RETIRED_FIELD_NFSET)] = ONE
    # (the deleted wide pool and shielded-contract state were empty on every gen-29 state, and empty projected nothing)
    sp = getattr(st, "stwo_pool", None)
    if sp is not None and (sp.commitments or sp.nullifiers):
        out[record_key(T_DIGEST, "stwo_root", sp.root())] = ONE
        out[record_key(T_DIGEST, "stwo_nfset", sp.nullifier_digest())] = ONE
        if sp.marks:
            out[record_key(T_DIGEST, "stwo_marks", sp.marks_digest())] = ONE
    sv = int(getattr(st, "stwo_value", 0) or 0)
    if sv:
        out[record_key(T_DIGEST, "stwo_value", str(sv))] = ONE
    for name in COUNTERS:                                  # the nonces new records are positioned by (T_COUNTER)
        _amount(out, record_key(T_COUNTER, name), getattr(st, name, 0) or 0)
    if addr_root_at(getattr(st, "cursor", -1)):            # the digest registry (T_ADDR), from its gate
        for d, a in (getattr(st, "zk_addrs", None) or {}).items():
            out[record_key(T_ADDR, d)] = addr_value(a)
    if carry_root_at(getattr(st, "cursor", -1)):           # the dividend carry (T_COUNTER "div_carry"), from its gate
        _amount(out, record_key(T_COUNTER, CARRY_COUNTER), getattr(st, "div_carry", 0) or 0)
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
def record_proof(kv_root: bytes, rec_tree: "csmt.Tree", key: bytes) -> dict:
    """{"kv": 64-hex kv half-root, "s": [64-hex siblings, root first], "t": terminal} — the gen-29 exit wire format"""
    sibs, term = rec_tree.prove(key)
    t = ["empty"] if term[0] == "empty" else ["leaf", term[1].hex(), term[2].hex()]
    return {"kv": bytes(kv_root).hex(), "s": [s.hex() for s in sibs], "t": t}


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
