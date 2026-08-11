import json
import os

from signatures import generate_keydict
from .data_ops import get_home


def save_keys(keydict, file=f"{get_home()}/private/keys.dat"):
    """Persist the keydict as JSON with 0600 perms — the file holds the PLAINTEXT private key, so it
    must never inherit a broad umask or keep looser pre-existing permissions."""
    # 0600: the file holds the plaintext private key; don't inherit a broad umask
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as keyfile:
        json.dump(keydict, keyfile)
    try:
        os.chmod(file, 0o600)  # tighten even if the file pre-existed with looser perms
    except OSError:
        pass


def load_keys(file=f"{get_home()}/private/keys.dat"):
    """{"private_key": "", "public_key": "", "address": ""}

    The address is ALWAYS re-derived from the public key under the CURRENT ADDRESS_PREFIX rather than
    trusted from the file. A keyfile written before an address-format change (the betanet-7 debrand:
    ndo… → mldsa44…) caches the OLD string, and every consumer — the node's own mining identity in
    /mining_status and the producer registries, contract deploys, operator scripts — would then act as
    an address that owns nothing. make_address is deterministic, so this is a no-op for a current keyfile.
    """
    # SELF-HEAL PERMISSIONS: save_keys writes 0600, but it only runs when no keyfile exists. A keyfile
    # created before that (or copied/restored by a backup, or left by an editor) stays world-readable
    # FOREVER — and this file holds the plaintext ML-DSA seed, i.e. the node's full signing identity
    # (spends, block authorship, attestations). Found at 0644 on the live public node. Tighten on every
    # load so the loose state cannot persist; never fail the load over it.
    try:
        if os.path.exists(file) and (os.stat(file).st_mode & 0o077):
            os.chmod(file, 0o600)
    except Exception:
        pass
    with open(file, "r") as keyfile:
        keydict = json.load(keyfile)
    try:
        from ops.address_ops import make_address
        if keydict.get("public_key"):
            keydict["address"] = make_address(keydict["public_key"])
    except Exception:
        pass          # never make key loading fail on a derivation problem — fall back to the stored value
    return keydict


def keyfile_found(file=f"{get_home()}/private/keys.dat"):
    """whether a keyfile already exists — the guard that keeps startup from generating over (and
    losing) an existing identity"""
    if os.path.isfile(file):
        return True
    else:
        return False

def uniqueness(value):
    """number of distinct characters — the address-entropy heuristic used by generate_keys"""
    return len(set(value))

# Minimum distinct characters in a fresh address — a cheap sanity filter against visually degenerate,
# repetitive-looking addresses. It MUST be satisfiable by the current address alphabet, and that is the
# whole story of this constant:
#
# it was 18, which was fine while addresses carried the mldsa44 name prefix. betanet-14 removed the
# prefix (4ed77695), leaving a bare 46-char LOWERCASE HEX address — an alphabet of exactly 16 symbols. A
# demand for 18 distinct characters then became UNSATISFIABLE, and `while ... < 18: redraw` turned into an
# infinite loop burning a core.
#
# What made that expensive is where it fires: nado.py runs `if not keyfile_found(): save_keys(generate_keys())`,
# so it is unreachable on any node that already has a keyfile and hit EVERY BRAND-NEW node on first boot.
# The network could not take on a new node at all, and no existing node would ever show the symptom.
#
# 13 measured over 3000 draws: accepts 99.67%, rejects only the genuinely degenerate 11-12 tail, so the
# original "redraws are rare" property holds. Max attainable is 16 (see MAX_UNIQUENESS in
# tests/test_address_filter_satisfiable.py, which pins this against the live address format).
MIN_ADDRESS_UNIQUENESS = 13
_MAX_KEYGEN_DRAWS = 1000


def generate_keys():
    """Generate a fresh keydict, redrawing until the address has >= MIN_ADDRESS_UNIQUENESS distinct
    characters.

    BOUNDED on purpose. The filter is a cosmetic nicety; being unable to satisfy it is a CONFIGURATION
    BUG (the threshold outran the address alphabet), and the correct response to that is to say so, not to
    spin forever. An unbounded loop here cost the network every new node it could have gained between
    betanet-14 and now, silently, because a hang reports nothing.
    """
    for _ in range(_MAX_KEYGEN_DRAWS):
        keydict = generate_keydict()
        if uniqueness(keydict["address"]) >= MIN_ADDRESS_UNIQUENESS:
            return keydict
    raise RuntimeError(
        f"could not generate an address with >= {MIN_ADDRESS_UNIQUENESS} distinct characters in "
        f"{_MAX_KEYGEN_DRAWS} draws — MIN_ADDRESS_UNIQUENESS exceeds what the current address alphabet "
        f"can produce. Lower it to match the format (see ops/key_ops.py).")


if __name__ == "__main__":
    if not keyfile_found():
        keydict = generate_keys()
        save_keys(keydict)
    else:
        keydict = load_keys()
