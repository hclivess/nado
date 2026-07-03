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
