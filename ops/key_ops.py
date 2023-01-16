import json
import os

from Curve25519 import generate_keydict
from .data_ops import get_home


def save_keys(keydict, file=f"{get_home()}/private/keys.dat"):
    with open(file, "w") as keyfile:
        json.dump(keydict, keyfile)


def load_keys(file=f"{get_home()}/private/keys.dat"):
    """{"private_key": "", "public_key": "", "address": ""}"""
    with open(file, "r") as keyfile:
        keydict = json.load(keyfile)
    return keydict


def keyfile_found(file=f"{get_home()}/private/keys.dat"):
    if os.path.isfile(file):
        return True
    else:
        return False

def uniqueness(value):
    return len(set(value))

def generate_keys():
    keydict = None
    while not keydict or uniqueness(keydict["address"]) < 18:
        keydict = generate_keydict()
    return keydict


if __name__ == "__main__":
    if not keyfile_found():
        keydict = generate_keys()
        save_keys(keydict)
    else:
        keydict = load_keys()
