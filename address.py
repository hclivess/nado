from hashing import blake2b_hash


def proof_sender(public_key, sender):
    if make_address(public_key) == sender:
        return True


def validate_address(address: str, checksum_size: str = 2):
    if address[-4:] == make_checksum(address[: -checksum_size * 2]):
        return True
    else:
        return False


def make_checksum(public_key: str, checksum_size: int = 2) -> str:
    checksum = blake2b_hash(data=public_key, size=checksum_size)
    return checksum


def make_address(
        public_key: str,
        address_length: int = 42,
        checksum_size: int = 2,
        prefix: str = "ndo",
) -> str:
    address_no_checksum = f"{prefix}{public_key[:address_length]}"
    address = f"{address_no_checksum}{make_checksum(address_no_checksum, checksum_size=checksum_size)}"
    return address


if __name__ == "__main__":
    public_key = "96381e3725f85cfe0ab8de17623957b4565ca9b04d37b903075f2723600c21e3"

    print(make_address(public_key))
    print(
        validate_address(make_address(public_key, address_length=42, checksum_size=2))
    )
