"""Portable object codec — JSON body (compressed with zstd by the callers). REPLACES msgpack, which
cannot pack integers wider than 64 bits: a 256-bit value inside an opaque execution-layer blob payload
overflowed msgpack (`OverflowError: Integer value out of range`) and wedged block storage AND the peer
wire. JSON encodes arbitrary-precision integers natively, so any blob payload round-trips.

CONSENSUS-SENSITIVE: the packed bytes of a value stored in a SNAPSHOT_DB ARE hashed into the L1 state root
(snapshot_ops._leaf → merkle), so pack() must be byte-stable. Stability comes from every WRITER fixing dict
order at the source (kv_ops._normalize canonicalizes account docs; other stored docs are fixed-order
literals) — deliberately NOT from sort_keys here; see pack()'s docstring for why adding it forks the chain.
NaN/Infinity are kept out at the tx-admission gate (transaction_ops._has_float), not here. Bytes ride as
base64."""
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
    """Serialize any JSON-shaped object (dicts/lists/str/int[any width]/bool/None/bytes) to bytes.

    NOTE: this deliberately does NOT sort_keys. The state-row VALUE bytes it produces feed the L1 state
    root, so it must be byte-stable — but stability here comes from every writer fixing dict order at the
    source (kv_ops._normalize canonicalizes account docs; other stored docs are fixed-order literals), NOT
    from sort_keys. sort_keys was tried (gen-8) and REVERTED: it re-serialized existing account docs to a
    different byte string, changing the genesis state root and forking the fleet away from the un-updatable
    stranded nodes (which pack unsorted). Floats/NaN are kept out at the tx-admission gate
    (transaction_ops validate_transaction _has_float), which is the real defense; do not re-add sort_keys /
    allow_nan here without retiring the old-codec nodes first."""
    return json.dumps(obj, default=_default, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def unpack(raw):
    """Deserialize bytes produced by pack()."""
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8")
    return json.loads(raw, object_hook=_object_hook)
