import json
import os

from .Curve25519 import generate_keydict


def save_keys(keydict, file="private/keys.dat"):
    with open(file, "w") as keyfile:
        keyfile.write(json.dumps(keydict))


def load_keys(file="private/keys.dat"):
    """{"private_key": "", "public_key": "", "address": ""}"""
    with open(file, "r") as keyfile:
        keydict = json.load(keyfile)
    return keydict


def keyfile_found(file="private/keys.dat"):
    if os.path.isfile(file):
        return True
    else:
        return False


def generate_keys():
    keydict = generate_keydict()
    return keydict


if __name__ == "__main__":
    if not keyfile_found():
        keydict = generate_keys()
        save_keys(keydict)
    else:
        keydict = load_keys()
