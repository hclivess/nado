"""Off-chain end-to-end-encrypted message pool (doc/messaging.md).

A node-local, gossiped, EPHEMERAL store of opaque encrypted message envelopes — mirrors the transaction
mempool but is NEVER put in a block, never hashed into state, never validated by consensus. A node with a
corrupt/empty message pool is still a fully valid node. Messages carry a recipient DETECTION TAG (not a
cleartext recipient); a client lists tags since a cursor, matches its own, and fetches only its own bodies.

The pool does NOT decrypt anything — it stores/forwards ciphertext. It enforces only:
  - shape + size caps (a hard memory bound),
  - a fresh-enough timestamp,
  - a per-message proof-of-work (cheap for a human, painful for a flood),
  - REGISTERED sender + valid ML-DSA signature — injected by the node (chain + crypto live outside ops).

Pure and deterministic given (now, injected checks); unit-testable with stubbed checks. Thread-safety is the
caller's concern (the node holds it under the same lock discipline as the tx pool).
"""

import msgpack

from hashing import blake2b_hash

# --- off-chain messaging parameters (NOT consensus — safe to tune per release) -----------------------------
MSG_TTL_SECONDS   = 7 * 24 * 3600     # a message lives at most 7 days undelivered, then it is reaped
MSG_MAX_COUNT     = 100_000           # hard cap on pooled messages (oldest evicted first) — bounds memory
MSG_MAX_BYTES     = 16 * 1024         # max single envelope size (16 KiB) — ratchet header + body ciphertext
MSG_TS_SKEW       = 2 * 3600          # reject envelopes whose ts is >2 h in the future (clock-skew slack)
MSG_POW_BITS      = 12                # per-message hashcash difficulty (leading zero bits) — ~a few k hashes
PREKEY_MAX_BYTES  = 32 * 1024         # a prekey bundle (identity + signed prekey + one-time prekeys) cap

_ENVELOPE_FIELDS = ("v", "sender", "public_key", "tag", "hdr", "nonce", "ct", "ts", "pow", "sig")
_PREKEY_FIELDS   = ("address", "public_key", "ik_pub", "spk_pub", "spk_ts", "ts", "sig")


def pow_preimage(env: dict) -> list:
    """The canonical hashcash pre-image: everything the PoW commits to EXCEPT the pow nonce + signature."""
    return ["nado-msg-pow", env.get("sender", ""), env.get("tag", ""), env.get("ct", ""), env.get("ts", 0)]


def pow_ok(env: dict, bits: int = MSG_POW_BITS) -> bool:
    """A message's `pow` is valid iff blake2b(preimage + [pow]) has >= `bits` leading zero BITS.
    Deterministic + browser-reproducible (same blake2b_hash the rest of the chain uses)."""
    digest = blake2b_hash(pow_preimage(env) + [env.get("pow", "")])
    return _leading_zero_bits(digest) >= bits


def _leading_zero_bits(hexdigest: str) -> int:
    """leading zero BITS of a hex digest (nibble-walk, integer-only) — the hashcash difficulty measure"""
    n = 0
    for ch in hexdigest:
        v = int(ch, 16)
        if v == 0:
            n += 4
            continue
        # partial nibble: 8->0b1000 (0 leading), 4->1, 2->2, 1->3
        n += (3 - (v.bit_length() - 1))
        break
    return n


def message_id(env: dict) -> str:
    """Content id = blake2b over the whole envelope (all fields incl. sig). Dedup key + fetch handle."""
    return blake2b_hash([env.get(f, "") for f in _ENVELOPE_FIELDS])


_SIGNED_FIELDS = tuple(f for f in _ENVELOPE_FIELDS if f != "sig")


def signing_digest(env: dict) -> str:
    """The blake2b hash the sender's ML-DSA signature covers — every envelope field EXCEPT `sig` (so it
    binds the pow + content; pow is mined BEFORE signing, no circularity). The client signs unhex(this);
    the node verifies the same. Browser-reproducible (identical field order + canonical_bytes)."""
    return blake2b_hash([env.get(f, "") for f in _SIGNED_FIELDS])


_PREKEY_SIGNED_FIELDS = tuple(f for f in _PREKEY_FIELDS if f != "sig")


def prekey_signing_digest(bundle: dict) -> str:
    """The blake2b hash a prekey bundle's ML-DSA self-signature covers (every field except `sig`)."""
    return blake2b_hash([bundle.get(f, "") for f in _PREKEY_SIGNED_FIELDS])


class MessagePool:
    def __init__(self, ttl_seconds=MSG_TTL_SECONDS, max_count=MSG_MAX_COUNT,
                 max_bytes=MSG_MAX_BYTES, pow_bits=MSG_POW_BITS):
        """Every cap/difficulty is injectable so tests run with tiny limits and cheap PoW; production
        uses the module defaults. Nothing here is consensus — two nodes with different knobs still agree
        on the chain."""
        self.ttl = ttl_seconds
        self.max_count = max_count
        self.max_bytes = max_bytes
        self.pow_bits = pow_bits
        self._seq = 0                 # monotonic cursor; every accepted message gets the next seq
        self.messages = {}            # msg_id -> {"env": envelope, "recv": ts, "seq": n}
        self.prekeys = {}             # address -> {"bundle": bundle, "ts": spk_ts-or-ts}

    # ---- messages -----------------------------------------------------------------------------------------
    def add_message(self, env, now, is_registered, verify_sig) -> tuple:
        """Validate + insert an envelope. Returns (ok: bool, reason: str, msg_id: str|None).
        `is_registered(addr) -> bool` and `verify_sig(public_key, sender, env) -> bool` are injected by the
        node (chain state + ML-DSA verification). Idempotent: re-adding a known msg_id is a benign no-op."""
        if not isinstance(env, dict):
            return False, "not a dict", None
        if any(f not in env for f in _ENVELOPE_FIELDS):
            return False, "missing field", None
        if _rough_size(env) > self.max_bytes:
            return False, "too big", None
        ts = env.get("ts")
        if not isinstance(ts, int):
            return False, "bad ts", None
        if ts > now + MSG_TS_SKEW:
            return False, "ts in the future", None
        if ts < now - self.ttl:
            return False, "ts too old", None
        if not pow_ok(env, self.pow_bits):
            return False, "insufficient pow", None
        mid = message_id(env)
        if mid in self.messages:
            return True, "duplicate", mid            # already have it — benign
        # crypto/chain gates last (most expensive): registered sender + valid signature
        if not is_registered(env["sender"]):
            return False, "sender not registered", None
        if not verify_sig(env["public_key"], env["sender"], env):
            return False, "bad signature", None
        self._seq += 1
        self.messages[mid] = {"env": env, "recv": now, "seq": self._seq}
        self._evict_over_cap()
        return True, "ok", mid

    def get_message(self, msg_id):
        """Fetch one envelope by content id, or None if unknown/expired/evicted. Recipients call this
        only for the tags they matched in list_tags, so the node never learns which tags are theirs
        beyond the fetch pattern itself."""
        row = self.messages.get(msg_id)
        return row["env"] if row else None

    def list_tags(self, since_seq=0, limit=5000) -> list:
        """Ordered [{"seq", "tag", "id"}] for seq > since_seq — the recipient scans these, matches its own
        tags, then fetches only its own bodies. `next` cursor = the max seq returned."""
        rows = [r for r in self.messages.values() if r["seq"] > since_seq]
        rows.sort(key=lambda r: r["seq"])
        return [{"seq": r["seq"], "tag": r["env"]["tag"], "id": message_id(r["env"])} for r in rows[:limit]]

    def cursor(self) -> int:
        """current max seq — the since_seq a client resumes list_tags from to see only new arrivals"""
        return self._seq

    def drop(self, msg_id) -> bool:
        """Explicit removal (e.g. on a delivery ack). Returns True if it was present."""
        return self.messages.pop(msg_id, None) is not None

    # ---- prekey bundles (the off-chain directory) -------------------------------------------------------
    def add_prekey(self, bundle, is_registered, verify_sig) -> tuple:
        """Publish/replace an address's signed prekey bundle. Newest (by spk_ts/ts) wins."""
        if not isinstance(bundle, dict) or any(f not in bundle for f in _PREKEY_FIELDS):
            return False, "bad bundle"
        if _rough_size(bundle) > PREKEY_MAX_BYTES:
            return False, "too big"
        addr = bundle["address"]
        if not is_registered(addr):
            return False, "not registered"
        if not verify_sig(bundle["public_key"], addr, bundle):
            return False, "bad signature"
        new_ts = bundle.get("spk_ts") or bundle.get("ts") or 0
        cur = self.prekeys.get(addr)
        if cur and cur["ts"] >= new_ts:
            return True, "stale"                     # keep the newer one already held
        self.prekeys[addr] = {"bundle": bundle, "ts": new_ts}
        return True, "ok"

    def get_prekey(self, address):
        """newest published prekey bundle for an address, or None — verified at add_prekey time,
        returned as-is"""
        row = self.prekeys.get(address)
        return row["bundle"] if row else None

    # ---- housekeeping -----------------------------------------------------------------------------------
    def gc(self, now) -> int:
        """Reap TTL-expired messages. Returns how many were removed. Call periodically (per epoch tick)."""
        dead = [mid for mid, r in self.messages.items() if now - r["recv"] > self.ttl]
        for mid in dead:
            del self.messages[mid]
        return len(dead)

    def _evict_over_cap(self):
        """Enforce max_count by evicting the LOWEST-seq (oldest-accepted) messages first — the pool's
        hard memory bound. A flood can therefore only displace old traffic, never grow the pool, and
        each displacing message still costs its own PoW (DoS floor)."""
        if len(self.messages) <= self.max_count:
            return
        # evict the oldest by seq until back under the cap
        surplus = len(self.messages) - self.max_count
        oldest = sorted(self.messages.items(), key=lambda kv: kv[1]["seq"])[:surplus]
        for mid, _ in oldest:
            del self.messages[mid]

    def stats(self) -> dict:
        """pool counters for the node's status/monitoring surface"""
        return {"messages": len(self.messages), "prekeys": len(self.prekeys), "cursor": self._seq}

    # ---- persistence: survive a node RESTART (the pool is otherwise in-memory, so a restart silently
    #      dropped every undelivered DM + published prekey). Opaque encrypted envelopes, so this is just bytes.
    def save(self, path) -> bool:
        """Atomically persist messages + prekeys + cursor to `path` (tmp + fsync + os.replace)."""
        import os
        blob = msgpack.packb({"seq": self._seq, "messages": self.messages, "prekeys": self.prekeys})
        tmp = f"{path}.tmp"
        with open(tmp, "wb") as f:
            f.write(blob); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        return True

    def load(self, path, now) -> int:
        """Load a persisted pool on boot, dropping TTL-expired messages. Returns messages kept. No-op if
        the file is missing/corrupt (a fresh/empty pool is always valid)."""
        import os
        if not os.path.isfile(path):
            return 0
        try:
            with open(path, "rb") as f:
                data = msgpack.unpackb(f.read(), raw=False)
        except Exception:
            return 0
        self._seq = int(data.get("seq", 0) or 0)
        self.messages = {k: v for k, v in (data.get("messages") or {}).items()
                         if isinstance(v, dict) and now - int(v.get("recv", 0)) <= self.ttl}
        self.prekeys = dict(data.get("prekeys") or {})
        return len(self.messages)


def _rough_size(obj) -> int:
    """Cheap upper-bound on the wire size of a str-keyed dict of str/int values (no msgpack dependency)."""
    total = 0
    for k, v in obj.items():
        total += len(k) + (len(v) if isinstance(v, str) else 8)
    return total
