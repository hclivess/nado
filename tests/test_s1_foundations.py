import os, sys, tempfile, traceback
home = tempfile.mkdtemp(prefix="nado_s1_")
os.environ["HOME"] = home
os.makedirs(os.path.join(home, "nado", "logs"), exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logger = logging.getLogger("s1"); logger.addHandler(logging.NullHandler())

from hashing import blake2b_hash, blake2b_hash_link, canonical_bytes
from protocol import CHAIN_ID, MIN_TX_FEE
from signatures import generate_keydict
from ops.address_ops import make_address, validate_address
from ops.transaction_ops import (create_txid, draft_transaction, create_transaction,
                                  validate_transaction, validate_txid)
from config import get_timestamp_seconds

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def t1():
    """Prove blake2b_hash of a nested dict is independent of key insertion order (canonical encoding)."""
    h1 = blake2b_hash({"b":2,"a":1,"n":{"y":[3,2,1],"x":"s"}})
    h2 = blake2b_hash({"n":{"x":"s","y":[3,2,1]},"a":1,"b":2})
    assert h1 == h2, "key order changed the hash"
check("canonical hash is key-order-independent", t1)

def t2():
    """Prove canonical_bytes encodes big integers exactly (no float mangling) and such values still hash."""
    assert canonical_bytes({"amount":10**18}) == b'{"amount":1000000000000000000}'
    h = blake2b_hash({"amount":10**18, "fee":2**60}); assert len(h) == 64
check("canonical encodes big ints exactly (no float)", t2)

def t3():
    """Prove blake2b_hash_link is deterministic and sensitive to argument order."""
    assert blake2b_hash_link("a","b") == blake2b_hash_link("a","b")
    assert blake2b_hash_link("a","b") != blake2b_hash_link("b","a")
check("hash_link deterministic and order-sensitive", t3)

kd = generate_keydict()
def t4():
    """Prove address checksum round-trips, bad checksums and 'burn' are rejected, and bond/unbond/treasury reserved labels validate (treasury only as recipient)."""
    assert validate_address(kd["address"]), "fresh address fails checksum under canonical hashing"
    assert not validate_address("ndo"+"f"*42+"0000"), "bad checksum accepted"
    assert validate_address("bond") and validate_address("unbond"), "reserved bond/unbond rejected"
    # burn mechanic removed: "burn" is no longer a reserved/valid recipient
    assert not validate_address("burn"), "'burn' must no longer be a valid recipient"
    # treasury IS a keyless reserved label now (protocol.TREASURY_ADDRESS = "treasury"): valid as a
    # recipient/target only — coins leave it solely via quorum treasury_execute — never as a sender.
    from protocol import TREASURY_ADDRESS
    assert validate_address(TREASURY_ADDRESS), "'treasury' must validate as a recipient"
    assert not validate_address(TREASURY_ADDRESS, allow_reserved=False), \
        "'treasury' must never validate as a sender (no key exists)"
check("address checksum round-trips + reserved accepted", t4)

def build_tx(chain=None, fee=MIN_TX_FEE):
    """Draft and sign a self-send tx from kd, optionally overriding chain_id and fee."""
    d = draft_transaction(sender=kd["address"], recipient=kd["address"], amount=1000,
                          public_key=kd["public_key"], timestamp=get_timestamp_seconds(),
                          data={"x":"y"}, max_block=5)
    if chain is not None: d["chain_id"] = chain
    return create_transaction(draft=d, private_key=kd["private_key"], fee=fee)

def t5():
    """Prove an honest signed tx carries CHAIN_ID and passes txid and full validation at height 0."""
    tx = build_tx()
    assert tx["chain_id"] == CHAIN_ID
    assert validate_txid(tx, logger=logger), "txid mismatch on honest tx"
    assert validate_transaction(tx, logger=logger, block_height=0), "valid tx rejected at height 0"
check("valid tx passes at height 0 (always txid-signing)", t5)

def expect_reject(name, tx):
    """Assert validate_transaction rejects tx with AssertionError; PASS on rejection, FAIL if accepted or wrong error type."""
    global fails
    try:
        validate_transaction(tx, logger=logger, block_height=0)
        fails += 1; print(f"FAIL  {name}: accepted but should be rejected")
    except AssertionError as e:
        print(f"PASS  {name}: rejected -> {e}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: wrong error type {e!r}")

expect_reject("wrong chain_id", build_tx(chain="evil-chain"))
expect_reject("fee below MIN_TX_FEE", build_tx(fee=MIN_TX_FEE-1))
_t = build_tx(); _t["recipient"] = make_address(generate_keydict()["public_key"])
expect_reject("tampered recipient", _t)

print(f"\n{'ALL S1 CHECKS PASSED' if fails==0 else str(fails)+' S1 CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
