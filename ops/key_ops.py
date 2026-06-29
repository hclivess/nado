import json
import os

from Curve25519 import generate_keydict
from .data_ops import get_home


def save_keys(keydict, file=f"{get_home()}/private/keys.dat"):
    # 0600: the file holds the plaintext private key; don't inherit a broad umask
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as keyfile:
        json.dump(keydict, keyfile)
    try:
        os.chmod(file, 0o600)  # tighten even if the file pre-existed with looser perms
    except OSError:
        pass


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
