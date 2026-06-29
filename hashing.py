import json
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


def canonical_bytes(data) -> bytes:
    """Deterministic, cross-platform encoding for all consensus hashing/signing.

    Replaces the previous repr()-based encoding (audit item M14), which varied across
    Python versions/implementations and could silently fork the network. Rules:
      - object keys are sorted, so dict insertion order is irrelevant;
      - compact separators, so whitespace is irrelevant;
      - inputs MUST be JSON primitives (str/int/list/dict/None) and contain NO floats.
    These rules are intentionally trivial to reproduce in a browser light-miner with a
    BigInt-aware serializer, so a phone can compute identical txids/hashes/signatures
    (Python's json emits ints exactly; JS must use BigInt to match for amounts > 2**53).
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def blake2b_hash(data, size: int = 32) -> str:
    return blake2b(canonical_bytes(data), digest_size=size).hexdigest()


def blake2b_hash_link(link_from, link_to, size: int = 32) -> str:
    # a 2-element list (not a tuple) so the encoding is JSON/browser-reproducible
    return blake2b(canonical_bytes([link_from, link_to]), digest_size=size).hexdigest()


if __name__ == "__main__":
    blake2b_hash_link("test_old", "test_new")
    print(base64encode("b64test"))
    print(base64decode(base64encode("b64test")))
