"""Portable object codec — JSON body (compressed with zstd by the callers). REPLACES msgpack, which
cannot pack integers wider than 64 bits: a 256-bit value inside an opaque execution-layer blob payload
overflowed msgpack (`OverflowError: Integer value out of range`) and wedged block storage AND the peer
wire. JSON encodes arbitrary-precision integers natively, so any blob payload round-trips.

Non-consensus: consensus hashing uses canonical_bytes (JSON) elsewhere; this is only the storage/wire
container. Bytes ride as base64."""
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
    """Serialize any JSON-shaped object (dicts/lists/str/int[any width]/float/bool/None/bytes) to bytes."""
    return json.dumps(obj, default=_default, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def unpack(raw):
    """Deserialize bytes produced by pack()."""
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8")
    return json.loads(raw, object_hook=_object_hook)
