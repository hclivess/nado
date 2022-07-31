import random
import string
from base64 import b64encode, b64decode
from hashlib import blake2b


def create_nonce(length: int = 8):
    letters = string.ascii_lowercase
    return "".join(random.choice(letters) for i in range(length))


def base64encode(data: str) -> str:
    return b64encode(data.encode()).decode()


def base64decode(data: str) -> str:
    return b64decode(data).decode()


def blake2b_hash(data: any, size: int = 32) -> str:
    hashed = blake2b(repr(data).encode(), digest_size=size).hexdigest()
    return hashed


def blake2b_hash_link(
        link_from: [str, list, int, None], link_to: [str, list, int, None], size: int = 32
) -> str:
    hashed = blake2b(repr((link_from, link_to)).encode(), digest_size=size).hexdigest()
    return hashed


if __name__ == "__main__":
    blake2b_hash_link("test_old", "test_new")
    print(base64encode("b64test"))
    print(base64decode(base64encode("b64test")))
