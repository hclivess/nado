UNIQUENESS = 20


from hashlib import blake2b
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey)
from random import random, shuffle
import matplotlib.pyplot as plt
from hashing import create_nonce

BLOCKS = 1000
ADDRESSES = 100


def get_hash_penalty(a: str, b: str):
    assert a and b, "One of the values to hash is empty"

    # a = blake2b_hash(a, size=64)
    # b = blake2b_hash(b, size=64)

    shorter_string = min([a, b], key=len)

    # a = str("".join(set(a)))
    # b = str("".join(set(b)))



    score = 0
    for letters in enumerate(shorter_string):
        score = score + a.count(letters[1])
        score = score + b.count(letters[1])

    # print(a, b, score)
    return score


def blake2b_hash_link(
        link_from: [str, list, int, None], link_to: [str, list, int, None], size: int = 32
) -> str:
    hashed = blake2b(repr((link_from, link_to)).encode(), digest_size=size).hexdigest()
    return hashed


def make_address(
        public_key: str,
        address_length: int = 42,
        checksum_size: int = 2,
        prefix: str = "ndo",
) -> str:
    address_no_checksum = f"{prefix}{public_key[:address_length]}"
    address = f"{address_no_checksum}{make_checksum(address_no_checksum, checksum_size=checksum_size)}"
    return address


def make_checksum(public_key: str, checksum_size: int = 2) -> str:
    checksum = blake2b_hash(data=public_key, size=checksum_size)
    return checksum


def blake2b_hash(data: any, size: int = 32) -> str:
    hashed = blake2b(repr(data).encode(), digest_size=size).hexdigest()
    return hashed


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

def uniqueness(value):
    return len(set(value))

def generate_keys():
    keydict = None
    while not keydict or uniqueness(keydict["address"]) < 18:
        keydict = generate_keydict()
    return keydict

if __name__ == "__main__":
    keydict = generate_keys()
    print(keydict)