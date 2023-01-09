import time
from hashlib import blake2b
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey)
from random import random, shuffle
import matplotlib.pyplot as plt
from hashing import create_nonce
import difflib
import math

BLOCKS = 10000
ADDRESSES = 100
DIFFTYPE = 2


def floatToInt(x):
    return math.floor(x * (2 ** 31))


def get_hash_penalty(address: str, block_hash: str, block_number):
    if block_number == 1:
        score = floatToInt(difflib.SequenceMatcher(None, address, block_hash).quick_ratio())

    elif block_number == 2:

        address_mingled = blake2b_hash_link(address, block_hash)
        score = 0
        for letters in enumerate(address_mingled):
            score = score + block_hash.count(letters[1])

        return score

    else:

        assert address and block_hash, "One of the values to hash is empty"

        shorter_string = min([address, block_hash], key=len)

        score = 0
        for letters in enumerate(shorter_string):
            score = score + address.count(letters[1])
            score = score + block_hash.count(letters[1])

        return score

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
    time_start = time.time()

    addresses = ["ndobf0622d0135a0a3837eac5067504378aed6dec74404390"]
    pseudoblocks = []

    for x in range(0, ADDRESSES):
        address_base = generate_keys()
        address = make_address(public_key=address_base["public_key"])
        addresses.append(address)

    for x in range(0, BLOCKS):
        block = blake2b_hash_link(link_from=create_nonce(64), link_to=create_nonce(64))
        pseudoblocks.append(block)

    for x in addresses:
        base_penalties = []
        for y in pseudoblocks:
            base_penalty = get_hash_penalty(address=x, block_hash=y, block_number=DIFFTYPE)
            base_penalties.append(base_penalty)

        # print(f"sum/min/max for {x}: {sum(base_penalties)}/{min(base_penalties)}/{max(base_penalties)}")
        # print(f"{x};{sum(base_penalties)};{min(base_penalties)};{max(base_penalties)}")

    winners = []

    for x in pseudoblocks:
        previous_block_penalty = None
        best_producer = None

        # shuffle(addresses)

        for y in addresses:
            block_penalty = get_hash_penalty(address=y, block_hash=x, block_number=DIFFTYPE)

            if not previous_block_penalty or block_penalty <= previous_block_penalty:
                previous_block_penalty = block_penalty
                best_producer = y
        winners.append(best_producer)

        # print(winners)

    wins = {}
    for address in winners:
        wins[address] = winners.count(address)

    # print(wins)

    x_axis = []
    y_axis = []

    time_total = time.time() - time_start

    for key, value in wins.items():
        print(f"{key};{value};{uniqueness(key)}")

        x_axis.append(key)
        y_axis.append(value)

        plt.bar(x_axis, y_axis)
        plt.draw()

    plt.xticks(rotation=-90)
    plt.show()

    print(time_total)
