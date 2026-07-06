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


def make_checksum(public_key: str, checksum_size: int = 2) -> str:
    """2-byte (4-hex) blake2b checksum appended to addresses so a typo/truncation fails validation
    instead of silently burning coins"""
    checksum = blake2b_hash(data=public_key, size=checksum_size)
    return checksum


def make_address(
        public_key: str,
        address_length: int = 42,
        checksum_size: int = 2,
        prefix: str = "ndo",
) -> str:
    """Derive the canonical address: "ndo" + first 42 hex chars of the public key + 4-hex blake2b
    checksum (49 chars). Must stay DETERMINISTIC and stable — proof_sender re-derives it to bind a
    pubkey to its sender, so any change here orphans every existing address."""
    address_no_checksum = f"{prefix}{public_key[:address_length]}"
    address = f"{address_no_checksum}{make_checksum(address_no_checksum, checksum_size=checksum_size)}"
    return address


if __name__ == "__main__":
    public_key = "96381e3725f85cfe0ab8de17623957b4565ca9b04d37b903075f2723600c21e3"

    print(make_address(public_key))
    print(
        validate_address(make_address(public_key, address_length=42, checksum_size=2))
    )
