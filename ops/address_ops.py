from hashing import blake2b_hash
from protocol import RESERVED_RECIPIENTS


def proof_sender(public_key, sender):
    """True iff public_key derives EXACTLY the claimed sender address — the pubkey-to-address binding
    every signature verification rests on; without it a valid signature under some OTHER key could
    spend from an address it doesn't own."""
    if make_address(public_key) == sender:
        return True
    else:
        return False


def validate_address(address: str, checksum_size: int = 2, allow_reserved: bool = True):
    """CONSENSUS address check: the trailing 4 hex chars must be the blake2b checksum of everything
    before them (catches typos/truncation deterministically on every node). Reserved protocol names
    pass only when allow_reserved — see below for why the sender slot must set it False."""
    # keyless protocol pseudo-recipients (bond/unbond/register/heartbeat) are valid ONLY as a
    # recipient/target — NEVER as a sender (no one holds their key). Pass allow_reserved=False for
    # the sender slot so a tx can't claim to originate FROM a reserved name.
    if address in RESERVED_RECIPIENTS:
        return allow_reserved
    if (isinstance(address, str)
            and len(address) > checksum_size * 2
            and address[-4:] == make_checksum(address[: -checksum_size * 2])):
        return True
    return False


def is_address(value) -> bool:
    """True iff `value` is a well-formed KEYED address: exact length, lowercase hex, valid checksum.

    THIS REPLACES `x.startswith(ADDRESS_PREFIX)`. That idiom appeared in a dozen places meaning "is this
    recipient an address rather than a reserved protocol name or an alias", and it was always a sniff rather
    than a test — "mldsa44" followed by garbage passed it. With the prefix removed it becomes actively
    dangerous, because `"".startswith("")` is True for EVERY string: _lands_flexibly would classify bond,
    register, attest and settle as flexibly-landing and silently discard the exact-landing timing invariant
    those transactions depend on, and alias_ops would reject every alias name. Neither would raise.

    So the discriminator is now the real thing: an address is what validates as one. Multisig accounts keep
    their own MSIG_PREFIX and are deliberately NOT accepted here — a caller that means "any account" has to
    say so, which is exactly the distinction the prefix sniff blurred."""
    from protocol import ADDRESS_LENGTH, MSIG_PREFIX
    if not isinstance(value, str) or len(value) != ADDRESS_LENGTH:
        return False
    if MSIG_PREFIX and value.startswith(MSIG_PREFIX):
        return False
    body = value[:-4]
    if not body or any(c not in "0123456789abcdef" for c in body):
        return False
    return value[-4:] == make_checksum(body)


def make_checksum(public_key: str, checksum_size: int = 2) -> str:
    """2-byte (4-hex) blake2b checksum appended to addresses so a typo/truncation fails validation
    instead of silently burning coins.

    REIMPLEMENTERS: this is blake2b with an OUTPUT LENGTH of 2 bytes — NOT the first 2 bytes of a 32-byte
    digest. blake2b keys its output length into the IV, so those are different values and slicing a 32-byte
    hash yields a wrong checksum that rejects every valid address. The in-tree JS does this correctly
    (static/interface.js: blake2bHash(body, 2) -> noble blake2b {dkLen: 2}); match that, not a slice."""
    checksum = blake2b_hash(data=public_key, size=checksum_size)
    return checksum


def make_address(
        public_key: str,
        address_length: int = None,
        checksum_size: int = None,
        prefix: str = None,
) -> str:
    """Derive the canonical address: ADDRESS_PREFIX + first ADDRESS_BODY hex chars of the public key
    + 4-hex blake2b checksum (protocol.py owns all three — the one-constant rebrand point). Must stay
    DETERMINISTIC and stable — proof_sender re-derives it to bind a pubkey to its sender, so any
    change here orphans every existing address (= ships only with a CHAIN_GENERATION reroll)."""
    from protocol import ADDRESS_PREFIX, ADDRESS_BODY, ADDRESS_CHECKSUM
    if address_length is None:
        address_length = ADDRESS_BODY
    if checksum_size is None:
        checksum_size = ADDRESS_CHECKSUM
    if prefix is None:
        prefix = ADDRESS_PREFIX
    address_no_checksum = f"{prefix}{public_key[:address_length]}"
    address = f"{address_no_checksum}{make_checksum(address_no_checksum, checksum_size=checksum_size)}"
    return address


if __name__ == "__main__":
    public_key = "96381e3725f85cfe0ab8de17623957b4565ca9b04d37b903075f2723600c21e3"

    print(make_address(public_key))
    print(
        validate_address(make_address(public_key, address_length=42, checksum_size=2))
    )
