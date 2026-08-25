"""ACCOUNT AUTHENTICATION AS STATE (doc/key-rotation.md, Roadmap Track H).

An address may carry an auth config — a list of ML-DSA authenticators, a SIGNING policy (who may spend / act
for the address) and a RECONFIG policy (who may change the config) — so keys rotate and a stolen hot key can
be recovered while the address and everything keyed by it (bond, ramp, fidelity, aliases, exec balances)
stays. An account WITHOUT a config is exactly today's account: one key, the one the address was derived
from (PUBKEY-ONCE stores it on first use), both policies ID(0). That implicit config is computed, never
stored, so existing accounts change nothing — not their doc, not the root.

    auth = {"v": <int>, "keys": [<pubkey hex>, ...], "sign": <policy>, "reconf": <policy>}
    policy = ["ID", i] | ["THRESHOLD", k, [policy, ...]]        (depth <= AUTH_POLICY_MAX_DEPTH)

Account doc fields (schemaless extras, all consensus state inside the root because `accounts` is):
    auth          the installed config (absent = legacy)
    auth_pending  {"cfg", "eff", "txid"} — one partial-policy change waiting out AUTH_DELAY; EFFECTIVE at
                  heights >= eff WITHOUT a write: every reader asks effective_config(acc, height), so a
                  matured pending config authorizes deterministically on every node with no promotion tx
    auth_freeze   height until which partial-policy changes are refused (set by a recovery-key cancel)

auth_history (DUPSORT, in the root): address -> (from_height, version, keys) for every config that ever
authorized the address, so EVIDENCE about a past height (an equivocation proof for a block signed under a
since-rotated key) verifies against the keys that were valid THEN. auth_revert (node-local): the txid-keyed
exact inverse of every `auth` tx, so rollback restores the doc byte-for-byte (the h4260 lesson).

The wire shape is the multisig one: a configured account signs with `signature` = a LIST of
{"public_key", "signature"} entries (each an ML-DSA signature over the txid); a plain string signature +
top-level public_key is the single-entry case and stays valid for single-key policies. Generation-keyed:
protocol.AUTH_ACTIVE is False on this chain (the `auth` recipient is refused, no account can hold a config)
and True from block 0 of the next generation — nothing to delete later.
"""
import protocol as P
from protocol import (AUTH_MAX_KEYS, AUTH_POLICY_MAX_DEPTH, AUTH_DELAY, AUTH_FREEZE, AUTH_HISTORY_KEEP, MIN_TX_FEE)
from ops import kv_ops
from ops.address_ops import make_address
from signatures import verify, unhex
from hashing import blake2b_hash


def pop_message(sender: str, cfg: dict) -> bytes:
    """What a NEW authenticator signs to prove possession: a domain-tagged digest of (chain, account, config).
    Not the txid — the proof rides INSIDE the tx data, which the txid commits, so it cannot sign the txid.
    Bound to the chain, the account and the exact config, so it cannot be replayed onto another account or
    a different policy; re-signing the same config for the same account is the same statement."""
    return unhex(blake2b_hash(["auth-pop-v1", P.CHAIN_ID, sender, cfg]))

PUBKEY_HEX = 2624          # ML-DSA-44 public key: 1312 bytes


# ---- policy language ----------------------------------------------------------------------------------
def _is_hex(s, n=None):
    return isinstance(s, str) and (n is None or len(s) == n) and all(c in "0123456789abcdef" for c in s)


def validate_policy(policy, nkeys: int, depth: int = 0):
    """Shape-check a policy tree against `nkeys` authenticators. Raises AssertionError."""
    assert isinstance(policy, list) and policy, "policy must be a non-empty list"
    if policy[0] == "ID":
        assert len(policy) == 2 and isinstance(policy[1], int) and not isinstance(policy[1], bool), "ID needs one index"
        assert 0 <= policy[1] < nkeys, "ID index out of range"
        return
    if policy[0] == "THRESHOLD":
        assert depth < AUTH_POLICY_MAX_DEPTH, "policy nesting too deep"
        assert len(policy) == 3 and isinstance(policy[1], int) and not isinstance(policy[1], bool), "THRESHOLD needs k and a list"
        subs = policy[2]
        assert isinstance(subs, list) and subs and len(subs) <= AUTH_MAX_KEYS, "THRESHOLD needs 1..AUTH_MAX_KEYS sub-policies"
        assert 1 <= policy[1] <= len(subs), "THRESHOLD k must be within 1..len(subs)"
        for sp in subs:
            validate_policy(sp, nkeys, depth + 1)
        return
    raise AssertionError("unknown policy operator")


def policy_satisfied(policy, signers) -> bool:
    """True iff the set of authenticator indices `signers` satisfies `policy`. Pure."""
    if policy[0] == "ID":
        return policy[1] in signers
    k, subs = policy[1], policy[2]
    return sum(1 for sp in subs if policy_satisfied(sp, signers)) >= k


def policy_keys(policy) -> set:
    """Every authenticator index a policy mentions."""
    if policy[0] == "ID":
        return {policy[1]}
    out = set()
    for sp in policy[2]:
        out |= policy_keys(sp)
    return out


def validate_config(cfg):
    """Canonical-shape check of an auth config. Raises AssertionError. Returns (version, keys)."""
    assert isinstance(cfg, dict) and set(cfg.keys()) == {"v", "keys", "sign", "reconf"}, \
        "auth config must have exactly v, keys, sign, reconf"
    v = cfg["v"]
    assert isinstance(v, int) and not isinstance(v, bool) and v >= 1, "auth config version must be an int >= 1"
    keys = cfg["keys"]
    assert isinstance(keys, list) and 1 <= len(keys) <= AUTH_MAX_KEYS, f"auth config needs 1..{AUTH_MAX_KEYS} keys"
    assert all(_is_hex(k, PUBKEY_HEX) for k in keys), "every authenticator must be a 2624-hex ML-DSA-44 public key"
    assert len(set(keys)) == len(keys), "duplicate authenticator"
    validate_policy(cfg["sign"], len(keys))
    validate_policy(cfg["reconf"], len(keys))
    # every key must be reachable by SOME policy, else it is dead weight nobody can ever use to prove possession of
    assert policy_keys(cfg["sign"]) | policy_keys(cfg["reconf"]) == set(range(len(keys))), \
        "every authenticator must appear in the signing or the reconfig policy"
    return v, keys


# ---- effective config ---------------------------------------------------------------------------------
def implicit_config(address: str, acc) -> dict:
    """The config a legacy account behaves as: its one derived key (known once PUBKEY-ONCE stored it),
    both policies ID(0). `keys` is [] before the first transaction — the key then rides in that tx and is
    checked by derivation (make_address) instead of membership."""
    pk = (acc or {}).get("public_key")
    return {"v": 0, "keys": [pk] if pk else [], "sign": ["ID", 0], "reconf": ["ID", 0], "implicit": True}


def effective_config(address: str, acc, height) -> dict:
    """The config that authorizes `address` at `height`: a matured pending change (eff <= height), else the
    installed one, else the implicit legacy config. Pure function of (doc, height) — no write, so every
    node answers identically for the same committed state."""
    acc = acc or {}
    cfg = acc.get("auth")
    pend = acc.get("auth_pending")
    if pend and height is not None and int(pend["eff"]) <= int(height):
        return pend["cfg"]
    if cfg:
        return cfg
    return implicit_config(address, acc)


def is_configured(acc) -> bool:
    return bool(acc) and (acc.get("auth") is not None or acc.get("auth_pending") is not None)


def signer_index(pubkey: str, address: str, cfg: dict):
    """Which authenticator `pubkey` is under `cfg`, or None. An implicit config with no stored key yet
    accepts the key that DERIVES the address (the first-transaction case)."""
    keys = cfg.get("keys") or []
    if pubkey in keys:
        return keys.index(pubkey)
    if cfg.get("implicit") and not keys and make_address(pubkey) == address:
        return 0
    return None


def entries_of(transaction) -> list:
    """Normalise a tx's authentication material to [{"public_key", "signature"}, ...]. A string signature
    with a top-level public_key is one entry; `None` public_key is left for the caller to resolve."""
    sig = transaction.get("signature")
    if isinstance(sig, list):
        return sig
    return [{"public_key": transaction.get("public_key"), "signature": sig}]


def resolve_entries(transaction, cfg: dict) -> list:
    """entries_of, with a missing public_key filled in PUBKEY-ONCE style: when the config has exactly ONE
    authenticator that alone satisfies the signing policy, an entry that omits its key means that one. Any
    other omission stays None and fails verification (an ambiguous omission must never guess)."""
    entries = [dict(e) if isinstance(e, dict) else e for e in entries_of(transaction)]
    keys = cfg.get("keys") or []
    sole = [k for i, k in enumerate(keys) if policy_satisfied(cfg["sign"], {i})]
    for e in entries:
        if isinstance(e, dict) and e.get("public_key") is None and len(sole) == 1:
            e["public_key"] = sole[0]
    return entries


def verify_entries(transaction, address: str, cfg: dict) -> set:
    """Verify every signature entry of `transaction` under `cfg` and return the set of authenticator indices
    that signed. Every entry must be valid (deterministic accept/reject; verification work bounded by
    AUTH_MAX_KEYS). Raises AssertionError."""
    entries = resolve_entries(transaction, cfg)
    assert entries and len(entries) <= AUTH_MAX_KEYS, "signature entries must be 1..AUTH_MAX_KEYS"
    message = unhex(transaction["txid"])
    signers = set()
    for e in entries:
        assert isinstance(e, dict), "signature entry must be an object"
        pk, sig = e.get("public_key"), e.get("signature")
        assert _is_hex(pk, PUBKEY_HEX) and isinstance(sig, str), "signature entry needs public_key + signature hex"
        i = signer_index(pk, address, cfg)
        assert i is not None, "signature by a key that does not authorize this account"
        assert i not in signers, "duplicate signature by the same authenticator"
        assert verify(signed=sig, public_key=pk, message=message), "invalid signature"
        signers.add(i)
    return signers


def signer_indices(transaction, address: str, cfg: dict) -> set:
    """The authenticator indices a tx's entries name — NO crypto (reflect trusts validate). Same mapping
    as verify_entries, so apply and validate agree on which policy the tx satisfied."""
    out = set()
    for e in resolve_entries(transaction, cfg):
        i = signer_index(e.get("public_key"), address, cfg)
        if i is not None:
            out.add(i)
    return out


def key_authorized(pubkey: str, address: str, height=None, acc=None) -> bool:
    """May `pubkey`, signing ALONE, act for `address` (block signatures, status attestations, messaging,
    forum login — every single-key check that used to be proof_sender)? Legacy: the key derives the
    address. Configured: it is an authenticator that alone satisfies the SIGNING policy."""
    if acc is None:
        acc = kv_ops.get_account(address) if P.AUTH_ACTIVE else None
    if not P.AUTH_ACTIVE or not is_configured(acc):
        return make_address(pubkey) == address
    cfg = effective_config(address, acc, height)
    i = signer_index(pubkey, address, cfg)
    return i is not None and policy_satisfied(cfg["sign"], {i})


def key_valid_at(pubkey: str, address: str, height: int) -> bool:
    """EVIDENCE check: was `pubkey` an authenticator of `address` at `height`? Answered from auth_history
    (the config with the greatest from_height <= height); before any history row the derived key is the
    only valid one. A rotated-away key's past double-signs therefore stay slashable."""
    if not P.AUTH_ACTIVE:
        return make_address(pubkey) == address
    rows = [r for r in kv_ops.auth_history(address) if r[0] <= int(height)]
    if not rows:
        return make_address(pubkey) == address
    return blake2b_hash(pubkey) in rows[-1][2]


# ---- the `auth` transaction ---------------------------------------------------------------------------
def validate_auth_tx(transaction, block_height: int, signers: set):
    """Consensus validation of an `auth` tx (data = {"op": "set", "cfg", "pop"} | {"op": "cancel"}), given
    the verified signer set. Raises AssertionError. Pure read of committed state."""
    assert P.AUTH_ACTIVE, "account authentication is not active on this chain generation"
    assert transaction["amount"] == 0, "auth tx must have zero amount"
    assert transaction["fee"] >= MIN_TX_FEE, "auth tx fee below minimum"
    assert transaction.get("multisig") is None, "a multisig account has no auth config"
    d = transaction.get("data")
    assert isinstance(d, dict), "auth tx needs a data object"
    address = transaction["sender"]
    acc = kv_ops.get_account(address) or {}
    cur = effective_config(address, acc, block_height)
    pend = acc.get("auth_pending")
    pend_live = bool(pend) and int(pend["eff"]) <= int(block_height)
    op = d.get("op")
    if op == "cancel":
        assert set(d.keys()) == {"op"}, "cancel carries no other fields"
        assert pend and not pend_live, "nothing pending to cancel"
        allowed = policy_satisfied(cur["sign"], signers) or (signers & (policy_keys(cur["reconf"]) - policy_keys(cur["sign"])))
        assert allowed, "cancel needs the signing policy or a reconfig-only authenticator"
        return
    assert op == "set", "auth op must be set or cancel"
    assert set(d.keys()) == {"op", "cfg", "pop"}, "set carries exactly cfg and pop"
    v, keys = validate_config(d["cfg"])
    assert v == int(cur.get("v", 0)) + 1, "auth config version must be current + 1"
    full = policy_satisfied(cur["reconf"], signers)
    partial = (not full) and policy_satisfied(cur["sign"], signers)
    assert full or partial, "auth set needs the reconfig policy (immediate) or the signing policy (pending)"
    if partial:
        assert not (pend and not pend_live), "a change is already pending"
        assert int(block_height) >= int(acc.get("auth_freeze", 0) or 0), "partial-policy changes are frozen"
    # proof of possession for every NEW key: its own signature over the txid. An unsatisfiable or
    # mistyped config can never be installed.
    pop = d["pop"]
    assert isinstance(pop, dict), "pop must map new public keys to signatures"
    have = set(cur.get("keys") or [])
    message = pop_message(address, d["cfg"])
    new = [k for k in keys if k not in have]
    assert set(pop.keys()) == set(new), "pop must cover exactly the new authenticators"
    for k in new:
        assert isinstance(pop[k], str) and verify(signed=pop[k], public_key=k, message=message), \
            "proof of possession failed"


def key_digests(keys) -> list:
    """auth_history stores blake2b digests of the authenticators, not the 1312-byte keys: LMDB caps a
    DUPSORT value at 511 bytes, and evidence only needs MEMBERSHIP (was this key valid then?), which a
    digest answers exactly as well."""
    return [blake2b_hash(k) for k in keys]


def _hist_row(from_height, cfg):
    return [int(from_height), int(cfg["v"]), key_digests(cfg["keys"])]


def apply_auth_tx(transaction, block_height: int, logger, revert=False):
    """Apply / exactly revert an `auth` tx. Validation already ran; this only mutates. Journals the prior
    (auth, auth_pending, auth_freeze) triple and every auth_history row it adds or removes."""
    address, txid = transaction["sender"], transaction["txid"]
    if revert:
        found, prev_auth, prev_pend, prev_freeze, hist = kv_ops.auth_revert_pop(txid)
        if not found:
            return
        for op, row in reversed(hist or []):
            if op == "add":
                kv_ops.auth_history_del(address, *row)
            else:
                kv_ops.auth_history_put(address, *row)
        for field, val in (("auth", prev_auth), ("auth_pending", prev_pend), ("auth_freeze", prev_freeze)):
            if val is None:
                kv_ops.account_del_field(address, field)
            else:
                kv_ops.account_set_field(address, field, val)
        return
    acc = kv_ops.get_account(address) or {}
    prev = (acc.get("auth"), acc.get("auth_pending"), acc.get("auth_freeze"))
    cur = effective_config(address, acc, block_height)
    pend = acc.get("auth_pending")
    hist = []
    new_auth, new_pend, new_freeze = acc.get("auth"), pend, acc.get("auth_freeze")
    # a matured pending config IS the live one: materialise it (no history change — its row exists)
    if pend and int(pend["eff"]) <= int(block_height):
        new_auth, new_pend = pend["cfg"], None
    d = transaction["data"]
    signers = signer_indices(transaction, address, cur)
    if d["op"] == "cancel":
        row = _hist_row(new_pend["eff"], new_pend["cfg"])
        kv_ops.auth_history_del(address, *row); hist.append(["del", row])
        by_recovery_only = bool(signers & (policy_keys(cur["reconf"]) - policy_keys(cur["sign"]))) \
            and not policy_satisfied(cur["sign"], signers)
        new_pend = None
        if by_recovery_only:
            new_freeze = int(block_height) + AUTH_FREEZE
    else:
        cfg = d["cfg"]
        if policy_satisfied(cur["reconf"], signers):
            if new_pend:                                   # an un-matured pending change is superseded
                row = _hist_row(new_pend["eff"], new_pend["cfg"])
                kv_ops.auth_history_del(address, *row); hist.append(["del", row])
                new_pend = None
            new_auth = cfg
            row = _hist_row(block_height, cfg)
            kv_ops.auth_history_put(address, *row); hist.append(["add", row])
        else:
            eff = int(block_height) + AUTH_DELAY
            new_pend = {"cfg": cfg, "eff": eff, "txid": txid}
            row = _hist_row(eff, cfg)
            kv_ops.auth_history_put(address, *row); hist.append(["add", row])
    # bounded history: prune the oldest rows beyond AUTH_HISTORY_KEEP (journaled, so revert restores them)
    rows = kv_ops.auth_history(address)
    for r in rows[:max(0, len(rows) - AUTH_HISTORY_KEEP)]:
        row = [r[0], r[1], list(r[2])]
        kv_ops.auth_history_del(address, *row); hist.append(["del", row])
    kv_ops.auth_revert_put(txid, prev[0], prev[1], prev[2], hist)
    for field, val in (("auth", new_auth), ("auth_pending", new_pend), ("auth_freeze", new_freeze)):
        if val is None:
            kv_ops.account_del_field(address, field)
        else:
            kv_ops.account_set_field(address, field, val)
    return True
