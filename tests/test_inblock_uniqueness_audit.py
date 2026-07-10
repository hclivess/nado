"""
Audit fix: in-block uniqueness for reserved txs (and cross-block heartbeat/reveal guards).

Closes: K-withdraw bond drain / slash-escape / chain-halt, duplicate-slash over-burn/halt, and
heartbeat/reveal DUPSORT desync forks — by deduping at block assembly, rejecting duplicates in
verify_block, and rejecting a cross-block second heartbeat (per address,epoch) / reveal (per secret).
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_uniq_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("uniq"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.account_ops import create_account, reflect_transaction
from ops.transaction_ops import (reserved_uniqueness_key, dedupe_reserved, assert_unique_reserved,
                                 create_txid, validate_transaction)
from signatures import generate_keydict, sign, unhex
from protocol import CHAIN_ID, EPOCH_LENGTH, B_MIN

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def tx(r, sender="s", **kw):
    """Build a minimal tx dict with recipient r, sender, and extra fields kw."""
    return {"recipient": r, "sender": sender, **kw}


def t1_keys():
    """Prove reserved_uniqueness_key maps each reserved recipient to its one-per-block key (None for retired heartbeat and plain transfers)."""
    assert reserved_uniqueness_key(tx("withdraw")) == ("withdraw", "s")
    assert reserved_uniqueness_key(tx("unbond")) == ("unbond", "s")
    # heartbeat is RETIRED (recert-via-register is the presence mechanism, doc/presence-dividend.md
    # §2.4) — it is no longer a reserved recipient and must not claim a uniqueness slot
    assert reserved_uniqueness_key(tx("heartbeat", max_block=125)) is None
    assert reserved_uniqueness_key(tx("register")) == ("register", "s")
    assert reserved_uniqueness_key(tx("reveal", data={"secret": "abc", "target_epoch": 4})) == ("reveal", "abc")
    assert reserved_uniqueness_key(tx("attest", data={"target_epoch": 3, "target_hash": "h"})) == ("attest", "s", 3)
    assert reserved_uniqueness_key(tx("ndo" + "0" * 46)) is None  # ordinary transfer
check("reserved_uniqueness_key maps each reserved tx to its one-per-block key", t1_keys)


def t2_dedup_and_reject():
    """Prove two same-sender withdraws are deduped at block assembly and rejected by verify, while distinct senders pass."""
    two = [tx("withdraw"), tx("withdraw", nonce="2")]
    assert len(dedupe_reserved(two)) == 1, "block assembly must drop the 2nd withdraw"
    raised = False
    try:
        assert_unique_reserved(two)
    except ValueError:
        raised = True
    assert raised, "verify_block must reject two withdraws (the drain/halt block)"
    assert_unique_reserved([tx("withdraw", sender="a"), tx("withdraw", sender="b")])  # distinct ok
check("two withdraws/one block: deduped on build, rejected on verify; distinct senders ok", t2_dedup_and_reject)


def t3_slash_offence_dedup():
    """Prove two slashes of one (offender, height) offence are rejected even when filed by different reporters."""
    kd = generate_keydict()
    s1 = tx("slash", sender="r1", data={"public_key": kd["public_key"], "block_number": 7})
    s2 = tx("slash", sender="r2", data={"public_key": kd["public_key"], "block_number": 7})
    raised = False
    try:
        assert_unique_reserved([s1, s2])
    except ValueError:
        raised = True
    assert raised, "two slashes of one (offender,height) must be rejected (over-burn/halt)"
check("duplicate slash of one offence is rejected (even from two reporters)", t3_slash_offence_dedup)


def t4_attest_cross_block():
    """Prove a second attest tx for an already-attested epoch is rejected at validation (cross-block guard)."""
    # heartbeat is RETIRED; the surviving cross-block one-per-epoch guard is the FFG attestation
    # index — a second attest tx for an already-attested epoch must be rejected at validation.
    kd = generate_keydict(); s = kd["address"]
    create_account(s); kv_ops.account_set(s, "bonded", B_MIN); kv_ops.account_set_field(s, "public_key", kd["public_key"])
    epoch = 1
    with kv_ops.write_txn():
        kv_ops.attestation_put(epoch, s, "aa" * 32)
    assert kv_ops.attestation_exists(epoch, s)
    tb = epoch * EPOCH_LENGTH + 3
    at = {"sender": s, "recipient": "attest", "amount": 0, "timestamp": 1,
          "data": {"target_epoch": epoch, "target_hash": "bb" * 32}, "nonce": "a2",
          "public_key": kd["public_key"], "max_block": tb, "chain_id": CHAIN_ID, "fee": 0}
    at["txid"] = create_txid(at); at["signature"] = sign(kd["private_key"], unhex(at["txid"]))
    try:
        validate_transaction(at, logger, block_height=tb); raise RuntimeError("2nd attestation accepted")
    except AssertionError as e:
        assert "already attested" in str(e).lower()
check("cross-block: a 2nd attestation for an already-attested epoch is rejected", t4_attest_cross_block)


print(f"\n{'ALL IN-BLOCK UNIQUENESS CHECKS PASSED' if not fails else str(fails) + ' FAILURE(S)'}")
sys.exit(1 if fails else 0)
