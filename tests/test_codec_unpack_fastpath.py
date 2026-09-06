"""codec.unpack skips the per-object hook when no "__b64__" (or \\u escape) is present — the result must be
byte-for-byte identical to the hooked decode in every case, including a key spelled with a \\u escape."""
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import codec


def _ref(raw):
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8")
    return json.loads(raw, object_hook=codec._object_hook)


def main():
    cases = [
        codec.pack({"a": 1, "b": [1, 2, {"c": "x"}], "n": 2 ** 70, "s": "žluťoučký"}),
        codec.pack({"blob": b"\x00\x01\xff" * 10, "list": [b"q", {"k": b""}]}),
        b'{"\\u005f_b64__":"QUJD"}',                 # escaped key still reaches the hook -> bytes
        b'{"x":{"__b64__":"QUJD","extra":1}}',       # two keys: hook must NOT convert
        b'{"t":"has __b64__ in a string"}',           # marker inside a value: slow path, same result
        '{"plain":"str input"}',
        b'[]', b'{}', b'"s"',
    ]
    for raw in cases:
        got, ref = codec.unpack(raw), _ref(raw)
        assert got == ref and type(got) is type(ref), (raw, got, ref)
    assert codec.unpack(b'{"\\u005f_b64__":"QUJD"}') == b"ABC"
    assert codec.unpack(codec.pack({"z": b"hi"})) == {"z": b"hi"}
    # the fast path really is taken for hook-free input (round-trips through plain json.loads)
    assert codec._B64_MARK not in codec.pack({"a": [1, 2, 3]})
    print("ALL OK")


if __name__ == "__main__":
    main()
