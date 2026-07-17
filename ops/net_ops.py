"""Network-facing helpers shared by the HTTP API (nado.py): trusted-proxy client-IP resolution and a
size-bounded transaction deserializer. Kept SIDE-EFFECT-FREE and dependency-light so they can be unit-tested
without importing the node (which generates keys / touches the data dir at import time)."""
from ops import codec
import zstandard

# Belt-and-suspenders bound for decoding an UNTRUSTED /submit_transaction body. The aiohttp app already caps
# the raw body (client_max_size, 1 MiB default); this second explicit cap bounds the JSON-codec (ops/codec.py)
# object blow-up — each tiny element becomes a ~50-byte Python object — and can't be hit by any legit tx: a
# blob payload is <= BLOB_MAX_BYTES (16 KiB) and the largest single field (ML-DSA pubkey/sig hex, PoSW proof)
# is a few KB.
MAX_TX_BODY = 1 << 20            # 1 MiB, matches aiohttp's default client_max_size
def unpack_tx(body):
    """Decode a submitted transaction body (the JSON codec wire — see ops/codec.py) with an explicit
    size bound. Raises (rejected as a 400/403 by the caller) on an empty or oversized body."""
    if body is None:
        raise ValueError("empty transaction body")
    if len(body) > MAX_TX_BODY:
        raise ValueError("transaction body too large")
    return codec.unpack(body)


# --- CLIENT-side download bounds. When WE fetch from an untrusted peer we are the HTTP client, so aiohttp's
# server-side client_max_size does NOT apply — response.read() would buffer whatever the peer streams. A
# malicious donor (esp. a lone one under weak-subjectivity) could stream GiB and OOM us, and the sha256 /
# state_root checks that would reject bad content only run AFTER the whole body is in memory. So cap the read
# (and the decompressed size, via bounded_zstd_decompress) on every peer download. ---
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
    """Decode a peer control message (status / peers / snapshot manifest / block) via the JSON codec
    (ops/codec.py). The caller is responsible for bounding `body` first (read_capped / MAX_PEER_BODY)."""
    return codec.unpack(body)


def bounded_zstd_decompress(body, cap):
    """Decompress a zstd frame to AT MOST `cap` bytes, raising if it would exceed it — the anti-bomb
    primitive for every untrusted zstd download.

    Why not ZstdDecompressor().decompress(body, max_output_size=cap): that arg is IGNORED whenever the
    frame DECLARES its content size in the header (which nado's one-shot compressor does). zstandard
    then allocates the DECLARED size up front — a ~16 KB frame declaring 512 MB is decompressed in full,
    OOMing us before msgpack's element bounds ever run. Streaming avoids that: we pull fixed-size chunks
    and abort the instant the running total crosses `cap`, so peak allocation is bounded regardless of
    the header's claim. A fresh decompressor per call (instances aren't safe for concurrent reuse)."""
    cap = int(cap)
    dctx = zstandard.ZstdDecompressor()
    parts, total = [], 0
    with dctx.stream_reader(body) as reader:
        while True:
            chunk = reader.read(65536)
            if not chunk:
                break
            total += len(chunk)
            if total > cap:
                raise IOError(f"zstd frame expands past {cap}-byte cap")
            parts.append(chunk)
    return b"".join(parts)


def unpack_zstd_peer(body, cap=MAX_PEER_BODY):
    """decode a peer's zstd(msgpack) control payload — the ?compress=zstd wire (nado.py serialize()).
    read_capped already bounds the COMPRESSED body; bounded_zstd_decompress bounds the DECOMPRESSED
    output against a bomb (parity with the old raw-msgpack wire: same cap either way)."""
    return codec.unpack(bounded_zstd_decompress(body, cap))


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
