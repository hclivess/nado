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


def validate_address(address: str, checksum_size: int = None, allow_reserved: bool = True):
    """CONSENSUS address check: the trailing 4 hex chars must be the blake2b checksum of everything
    before them (catches typos/truncation deterministically on every node). Reserved protocol names
    pass only when allow_reserved — see below for why the sender slot must set it False."""
    # keyless protocol pseudo-recipients (bond/unbond/register/heartbeat) are valid ONLY as a
    # recipient/target — NEVER as a sender (no one holds their key). Pass allow_reserved=False for
    # the sender slot so a tx can't claim to originate FROM a reserved name.
    if address in RESERVED_RECIPIENTS:
        return allow_reserved
    # THE CHECKSUM LENGTH IS protocol.ADDRESS_CHECKSUM (4 bytes since format 2; format 1 had 2), and the comparison
    # uses it — this compared the last 4 hex chars whatever `checksum_size` said, so a longer checksum was never
    # actually checked. The exact length is required too: a 46-char format-1 address is rejected.
    # A MULTISIG address has its OWN exact length: MSIG_PREFIX + body + the same checksum (54 in format 2). Requiring the
    # key-address length alone refused every multisig sender — "Invalid sender msig…" on every M-of-N spend (bc0f8986,
    # caught by tests/test_multisig.py in the gen-28 rehearsal before it shipped).
    from protocol import ADDRESS_CHECKSUM, ADDRESS_LENGTH, MSIG_PREFIX, ADDRESS_BODY
    n = (ADDRESS_CHECKSUM if checksum_size is None else checksum_size) * 2
    want = ADDRESS_LENGTH
    if MSIG_PREFIX and isinstance(address, str) and address.startswith(MSIG_PREFIX):
        want = len(MSIG_PREFIX) + ADDRESS_BODY + n
    if (isinstance(address, str)
            and len(address) == (want if checksum_size is None else len(address))
            and len(address) > n
            and address[-n:] == make_checksum(address[:-n], checksum_size=n // 2)):
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
    from protocol import ADDRESS_CHECKSUM
    n = ADDRESS_CHECKSUM * 2
    body = value[:-n]
    if not body or any(c not in "0123456789abcdef" for c in body):
        return False
    return value[-n:] == make_checksum(body, checksum_size=ADDRESS_CHECKSUM)


def make_checksum(public_key: str, checksum_size: int = None) -> str:
    """2-byte (4-hex) blake2b checksum appended to addresses so a typo/truncation fails validation
    instead of silently burning coins.

    REIMPLEMENTERS: this is blake2b with an OUTPUT LENGTH of 2 bytes — NOT the first 2 bytes of a 32-byte
    digest. blake2b keys its output length into the IV, so those are different values and slicing a 32-byte
    hash yields a wrong checksum that rejects every valid address. The in-tree JS does this correctly
    (static/interface.js: blake2bHash(body, 2) -> noble blake2b {dkLen: 2}); match that, not a slice."""
    if checksum_size is None:
        from protocol import ADDRESS_CHECKSUM as checksum_size        # 4 bytes (format 1's 2: legacy_address only)
    checksum = blake2b_hash(data=public_key, size=checksum_size)
    return checksum


def make_address(
        public_key: str,
        address_length: int = None,
        checksum_size: int = None,
        prefix: str = None,
) -> str:
    """Derive the canonical address: ADDRESS_PREFIX + address_body_v2(public key) + ADDRESS_CHECKSUM-byte blake2b
    checksum (protocol.py owns all three — the one-constant rebrand point). A MULTISIG address (prefix MSIG_PREFIX)
    passes a descriptor hash as `public_key` and keeps format 1's body rule: its first ADDRESS_BODY hex. Must stay
    DETERMINISTIC and stable — proof_sender re-derives it to bind a pubkey to its sender, so any
    change here orphans every existing address (= ships only with a CHAIN_GENERATION reroll)."""
    from protocol import ADDRESS_PREFIX, ADDRESS_BODY, ADDRESS_CHECKSUM
    if address_length is None:
        address_length = ADDRESS_BODY
    if checksum_size is None:
        checksum_size = ADDRESS_CHECKSUM
    if prefix is None:
        prefix = ADDRESS_PREFIX
    # FORMAT 2 for key-derived addresses (gen 28, protocol.py "ADDRESS FORMAT 2"): the body commits to the WHOLE key —
    # format 1's first 21 bytes are the key's rho, which a forger chooses. A multisig address (prefix MSIG_PREFIX) is
    # derived from a descriptor hash already and keeps format 1's body rule; its bytes must never change.
    if prefix == ADDRESS_PREFIX:
        body = address_body_v2(public_key, address_length)
    else:
        body = public_key[:address_length]
    address_no_checksum = f"{prefix}{body}"
    address = f"{address_no_checksum}{make_checksum(address_no_checksum, checksum_size=checksum_size)}"
    return address


def address_body_v2(public_key: str, address_length: int = None) -> str:
    """Format-2 address body: blake2b over [DOMAIN_ADDRESS_V2, lowercase public-key hex], ADDRESS_BODY/2 bytes.
    LOWERCASED so one key has exactly one address (the hex of a key is not unique: 'AB' and 'ab' are the same bytes).
    Mirrored byte-for-byte by static/nadotx.js and static/interface.js (blake2bHash over the same canonical list)."""
    from protocol import ADDRESS_BODY, DOMAIN_ADDRESS_V2
    n = ADDRESS_BODY if address_length is None else address_length
    return blake2b_hash([DOMAIN_ADDRESS_V2, str(public_key).lower()], size=n // 2)


def legacy_address(public_key: str) -> str:
    """The FORMAT-1 address of a key (its first ADDRESS_BODY hex chars + checksum). Only for recognising what an
    account was called on a format-1 chain — the legacy-claim path — never for authorising anything on its own."""
    from protocol import ADDRESS_PREFIX, ADDRESS_BODY
    body = f"{ADDRESS_PREFIX}{public_key[:ADDRESS_BODY]}"
    return body + make_checksum(body, checksum_size=2)             # format 1's 2-byte checksum, always


def key_bound(address, public_key, height=None, account=None):
    """THE ADDRESS IS BOUND TO ITS PUBLISHED KEY: may `public_key` act for `address` given the key the account already
    has on chain? make_address only binds the first 21 bytes of the key's rho, which a forger CHOOSES (review
    2026-09-25), so a key must also EQUAL the account's recorded key when it has one. True for an address with no
    recorded key (nothing to compare). `height` None = judged under the rule; a height below 1 is not (gen 25's
    ADDRESS_KEY_BIND_HEIGHT was 1 from gen 26 and is deleted — height 0 keeps the verdict it had below that gate).
    `account` may be passed to avoid a second lookup. Pure read; never raises (a lookup failure refuses)."""
    if height is not None and int(height) < 1:
        return True
    try:
        if account is None:
            from ops import kv_ops
            account = kv_ops.get_account(address)
    except Exception:
        return False
    stored = (account or {}).get("public_key")
    return (not stored) or str(stored) == str(public_key)
