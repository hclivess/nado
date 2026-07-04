"""Network-facing helpers shared by the HTTP API (nado.py): trusted-proxy client-IP resolution and a
size-bounded transaction deserializer. Kept SIDE-EFFECT-FREE and dependency-light so they can be unit-tested
without importing the node (which generates keys / touches the data dir at import time)."""
import json

import msgpack

# Belt-and-suspenders bounds for decoding an UNTRUSTED /submit_transaction body. The aiohttp app already caps
# the raw body (client_max_size, 1 MiB default), so these mainly bound the msgpack object-count blow-up — each
# tiny element becomes a ~50-byte Python object — and can't be hit by any legit tx: a blob payload is
# <= BLOB_MAX_BYTES (16 KiB) and the largest single field (ML-DSA pubkey/sig hex, PoSW proof) is a few KB.
MAX_TX_BODY = 1 << 20            # 1 MiB, matches aiohttp's default client_max_size
_MSGPACK_LIMITS = dict(max_str_len=MAX_TX_BODY, max_bin_len=MAX_TX_BODY, max_ext_len=MAX_TX_BODY,
                       max_array_len=131072, max_map_len=131072)


def unpack_tx(body, content_type):
    """Decode a submitted transaction body (msgpack or JSON) with explicit size bounds. Raises (rejected as a
    400/403 by the caller) on an oversized body or an over-large msgpack collection, instead of letting
    msgpack allocate unboundedly. Preserves the previous default of strict string map keys."""
    if body is None:
        raise ValueError("empty transaction body")
    if len(body) > MAX_TX_BODY:
        raise ValueError("transaction body too large")
    if "msgpack" in (content_type or ""):
        return msgpack.unpackb(body, raw=False, **_MSGPACK_LIMITS)
    return json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)


# --- CLIENT-side download bounds. When WE fetch from an untrusted peer we are the HTTP client, so aiohttp's
# server-side client_max_size does NOT apply — response.read() would buffer whatever the peer streams. A
# malicious donor (esp. a lone one under weak-subjectivity) could stream GiB and OOM us, and the sha256 /
# state_root checks that would reject bad content only run AFTER the whole body is in memory. So cap the read
# AND the msgpack object-count on every peer download. ---
MAX_PEER_BODY = 8 << 20            # /status, /peers, snapshot manifest, a single block — small control msgs
MAX_SNAPSHOT_TOTAL = 2 << 30      # absolute ceiling on a whole snapshot (sum of all chunk bytes)
MAX_SNAPSHOT_ACCOUNTS = 50_000_000


async def read_capped(response, cap):
    """Read up to `cap` bytes from an aiohttp response; raise if the peer streams more (anti-OOM).
    MUST LOOP: aiohttp's StreamReader.read(n) returns AT MOST n bytes and typically FEWER — just the first
    buffered TCP segment. A single `.read(cap+1)` therefore TRUNCATED any body that spanned more than one
    segment (an 867 KB snapshot chunk came back as its 32 KB first segment -> sha256 mismatch on import).
    Accumulate 64 KiB at a time until EOF, bailing the instant the running total exceeds the cap so we never
    buffer an unbounded body."""
    cap = int(cap)
    parts, total = [], 0
    while True:
        block = await response.content.read(65536)
        if not block:
            break
        total += len(block)
        if total > cap:
            raise IOError(f"peer response exceeds {cap}-byte cap")
        parts.append(block)
    return b"".join(parts)


def unpack_peer(body):
    """msgpack-decode a peer control message (status / peers / snapshot manifest / block) with the same
    object-count bounds used for untrusted tx bodies."""
    return msgpack.unpackb(body, raw=False, **_MSGPACK_LIMITS)


def client_ip_from(peer, xff_header, trusted):
    """Resolve the real client IP. By DEFAULT the raw socket peer — X-Forwarded-For is IGNORED so the per-IP
    rate limits + anti-Sybil registration cap can't be header-spoofed. ONLY when `peer` is itself a configured
    trusted reverse proxy (config 'trusted_proxies') do we consult X-Forwarded-For, walking right-to-left past
    any trusted-proxy hops to the first untrusted address (the real client). Pure function for testability.

    `trusted` is a set/frozenset of proxy IPs (empty -> XFF never trusted, the safe default)."""
    if not trusted or peer not in trusted:
        return peer
    for token in reversed((xff_header or "").split(",")):
        token = token.strip()
        if token and token not in trusted:
            return token
    return peer
