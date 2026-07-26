"""Portable object codec — JSON body (compressed with zstd by the callers). REPLACES msgpack, which
cannot pack integers wider than 64 bits: a 256-bit value inside an opaque execution-layer blob payload
overflowed msgpack (`OverflowError: Integer value out of range`) and wedged block storage AND the peer
wire. JSON encodes arbitrary-precision integers natively, so any blob payload round-trips.

CANONICAL: the packed bytes of a value stored in a SNAPSHOT_DB ARE hashed into the L1 state root
(snapshot_ops._leaf → merkle), so pack() MUST be deterministic — `sort_keys=True` normalizes dict key
order (a stored doc built by merging caller-ordered `data` must not inherit the sender's key order into the
root) and `allow_nan=False` rejects NaN/Infinity (their JSON tokens are non-standard and not browser-
reproducible). Bytes ride as base64."""
import json
import base64


def _default(o):
    if isinstance(o, (bytes, bytearray)):
        return {"__b64__": base64.b64encode(bytes(o)).decode("ascii")}
    raise TypeError(f"codec: not JSON-serializable: {type(o).__name__}")


def _object_hook(d):
    if len(d) == 1 and "__b64__" in d:
        return base64.b64decode(d["__b64__"])
    return d


def pack(obj) -> bytes:
    """Serialize any JSON-shaped object (dicts/lists/str/int[any width]/bool/None/bytes) to CANONICAL bytes:
    sorted keys + no NaN/Infinity, so two nodes serialize an equal value to identical bytes (it feeds the
    state root)."""
    return json.dumps(obj, default=_default, separators=(",", ":"), ensure_ascii=False,
                      sort_keys=True, allow_nan=False).encode("utf-8")


def unpack(raw):
    """Deserialize bytes produced by pack()."""
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8")
    return json.loads(raw, object_hook=_object_hook)
