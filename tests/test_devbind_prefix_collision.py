"""ENROLMENT ROWS AND WEBAUTHN DEVICE BINDINGS SHARE A KEY PREFIX, AND MUST NOT BE CONFUSED.

ops/device_attest.device_binding_key returns "tpm:" + sha256(AIK certificate) for the Windows Hello
class, and those rows have been in the devbind DB since long before enrolments existed. Enrolment rows
were then added at "tpm:" + enrol id. A prefix scan therefore returns both, and unpacking a 2-element
binding into 13 fields raises IndexError.

That is not hypothetical: it ran on every node, every block, for as long as any enrolment existed, and
it was invisible because the challenger duty catches exceptions so a failing duty cannot stop block
production. The first real enrolment on this chain sat unanswered for hundreds of blocks because of it,
while the logs said only "TPM challenge duty failed: list index out of range".

Renaming the prefix would be the obvious fix and is the wrong one: these rows are in the state root, so
a node replaying the chain would write them under a different key than nodes that applied those blocks
live, and the two would disagree on the root. They are told apart by SHAPE, which changes no stored byte.

Run: python3 tests/test_devbind_prefix_collision.py
"""
import hashlib
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-collide-")
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def main():
    from genesis import create_indexers
    create_indexers()
    from ops import kv_ops, tpm_enrol as E
    from ops.device_attest import device_binding_key

    # A REAL device binding key, produced by the function that produces them, not a hand-made string.
    import base64
    import struct

    def cbor_bytes(b):
        return (bytes([0x58, len(b)]) if len(b) < 256
                else bytes([0x59, len(b) >> 8, len(b) & 0xFF])) + b

    cert = b"\x30\x82" + b"\x01" * 400
    att = (b"\xa3" + b"\x63fmt" + b"\x63tpm"
           + b"\x67attStmt" + b"\xa1" + b"\x63x5c" + b"\x81" + cbor_bytes(cert)
           + b"\x68authData" + cbor_bytes(b"\x00" * 37))
    dkey = device_binding_key({"att": base64.b64encode(att).decode()}, 0)
    check("a WebAuthn tpm binding really does use the 'tpm:' prefix", dkey.startswith("tpm:"), dkey[:20])
    check("and it is the sha256 of the certificate",
          dkey == "tpm:" + hashlib.sha256(cert).hexdigest())

    kv_ops.devbind_set(dkey, "bound-identity", 700)
    check("the binding reads back as a binding", (kv_ops.devbind_get(dkey) or ("",))[0] == "bound-identity")

    # THE COLLISION: reading that binding through the enrolment accessor must return nothing, not raise.
    try:
        got = kv_ops.tpm_enrol_get(dkey[4:])
        check("a device binding is not read as an enrolment", got is None, got)
    except Exception as e:
        check("a device binding is not read as an enrolment", False, f"{type(e).__name__}: {e}")

    # And a scan must skip it rather than die on it — this is the exact call the challenger duty makes.
    rec = E.new_record("aa" * 32, b"\x30\x82spki", "bb" * 17, b"\x00\x01pub", "owner", 100,
                       ["c1", "c2", "c3"])
    kv_ops.tpm_enrol_set("cc" * 16, rec)
    try:
        live = kv_ops.tpm_enrols_live()
        check("the live scan returns only the enrolment", [e[0] for e in live] == ["cc" * 16], live)
    except Exception as e:
        check("the live scan returns only the enrolment", False, f"{type(e).__name__}: {e}")
    try:
        check("the expiry sweep survives the mixed prefix",
              kv_ops.tpm_enrols_expired(10 ** 9) == ["cc" * 16])
    except Exception as e:
        check("the expiry sweep survives the mixed prefix", False, f"{type(e).__name__}: {e}")

    # A THREE-ELEMENT (permanent-mode) BINDING TOO, since that is a different length again.
    perm = "tpm:" + hashlib.sha256(b"another").hexdigest()
    kv_ops.devbind_set(perm, "other-identity", 701, mode="perm")
    try:
        check("a permanent-mode binding is also skipped",
              kv_ops.tpm_enrol_get(perm[4:]) is None
              and [e[0] for e in kv_ops.tpm_enrols_live()] == ["cc" * 16])
    except Exception as e:
        check("a permanent-mode binding is also skipped", False, f"{type(e).__name__}: {e}")

    # AND THE ENROLMENT ITSELF STILL WORKS — the guard must not have excluded real records.
    back = kv_ops.tpm_enrol_get("cc" * 16)
    check("the enrolment reads back intact", back and back["owner"] == "owner" and back["h"] == 100)

    print("\n" + ("ALL OK" if not _fails else f"{len(_fails)} FAILURES"))
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
