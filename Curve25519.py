import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from address import make_address


def unhex(hexed):
    return b"".fromhex(hexed)


def sign(private_key, message):
    private_bytes = unhex(private_key)
    private_key_raw = Ed25519PrivateKey.generate().from_private_bytes(private_bytes)
    signed = private_key_raw.sign(message.encode()).hex()
    return signed


def verify(signed, public_key, message):
    public_bytes = unhex(public_key)
    public_key_raw = Ed25519PublicKey.from_public_bytes(public_bytes)
    public_key_raw.verify(unhex(signed), message.encode())
    return True


def generate_keydict():
    private_key_raw = Ed25519PrivateKey.generate()
    public_key_raw = private_key_raw.public_key()

    private_bytes = private_key_raw.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )

    public_bytes = public_key_raw.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )

    keydict = {
        "private_key": private_bytes.hex(),
        "public_key": public_bytes.hex(),
        "address": make_address(public_bytes.hex()),
    }

    return keydict


if __name__ == "__main__":
    keydict = generate_keydict()
    test_message = json.dumps({"amount": 50})
    print(keydict["private_key"])
    print(keydict["public_key"])
    print(keydict["address"])

    signature = sign(private_key=keydict["private_key"], message=test_message)
    print(signature)
    print(
        verify(message=test_message, public_key=keydict["public_key"], signed=signature)
    )
