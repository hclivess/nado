from hashlib import blake2b
from random import shuffle

import matplotlib.pyplot as plt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey)

from hashing import create_nonce

BLOCKS = 1000
ADDRESSES = 1000

def get_hash_penalty(a: str, b: str):
    assert a and b, "One of the values to hash is empty"

    shorter_string = min([a, b], key=len)

    score = 0
    for letters in enumerate(shorter_string):
        if b[letters[0]] == (letters[1]):
            score += 1
        score = score + a.count(letters[1])
        score = score + b.count(letters[1])
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


if __name__ == "__main__":
    addresses = []
    pseudoblocks = []

    for x in range(0, ADDRESSES):
        address_base = generate_keydict()
        address = make_address(public_key=address_base["public_key"])
        addresses.append(address)

    for x in range(0, BLOCKS):
        block = blake2b_hash_link(link_from=create_nonce(64), link_to=create_nonce(64))
        pseudoblocks.append(block)

    for x in addresses:
        base_penalties = []
        for y in pseudoblocks:
            base_penalty = get_hash_penalty(a=x, b=y)
            base_penalties.append(base_penalty)

        # print(f"sum/min/max for {x}: {sum(base_penalties)}/{min(base_penalties)}/{max(base_penalties)}")
        # print(f"{x};{sum(base_penalties)};{min(base_penalties)};{max(base_penalties)}")

    winners = []


    for x in pseudoblocks:
        previous_block_penalty = None
        best_producer = None

        shuffle(addresses)

        for y in addresses:
            block_penalty = get_hash_penalty(a=y, b=x)

            if not previous_block_penalty or block_penalty <= previous_block_penalty:
                previous_block_penalty = block_penalty
                best_producer = y
        winners.append(best_producer)

            # print(winners)

    wins = {}
    for address in winners:
        wins[address] = winners.count(address)

    #print(wins)

    x_axis = []
    y_axis = []

    for key, value in wins.items():
        print(f"{key};{value}")

        x_axis.append(key)
        y_axis.append(value)

        plt.bar(x_axis, y_axis)
        plt.draw()

    plt.xticks(rotation=-90)
    plt.show()

