"""Funded invite links (protocol.py "FUNDED INVITE LINKS", gate REFERRAL_HEIGHT) — consensus tests.

A referrer escrows NADO under a throwaway ML-DSA key whose seed travels in the link; an ATTESTED identity claims it
with that key's signature naming ITSELF; after expiry the referrer refunds. Pins:
  * before the gate every invite tx is refused, and a send to the "invite" escrow is always refused (the names are
    reserved now, and a reserved name with no branch would fall through to an ordinary transfer and be ACCEPTED where
    an older node refuses it as an unknown alias — a fork before the gate);
  * the lock escrows exactly the amount and burns the fee; claim / refund move exactly that amount; every one of the
    three reverts exactly;
  * a copied claim cannot be re-pointed: the signature names the claimant, so a rival (even an attested one) is refused;
  * only an attested identity may claim; the referrer cannot claim its own; expiry closes the claim and opens the refund;
  * one settle per invite per block, one lock per key per block; an htlc_claim naming "invite:<id>" finds no swap.

Run: python3 tests/test_invite_link_pays_only_the_named_claimant.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_invite_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("invite"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

import protocol as P
from protocol import INVITE_ESCROW, INVITE_MIN_TIMELOCK, INVITE_MAX_TIMELOCK, MIN_TX_FEE, CHAIN_ID, TX_MAX_BYTES
from ops import kv_ops
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import (validate_transaction, reserved_uniqueness_key, create_txid, invite_id_of,
                                 invite_claim_message)
from hashing import canonical_bytes
from signatures import generate_keydict, sign, unhex

GATE = 1000
P.REFERRAL_HEIGHT = GATE

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


RK = generate_keydict(); REF = RK["address"]          # the referrer
NK = generate_keydict(); NEW = NK["address"]          # the newcomer (attested)
XK = generate_keydict(); RIVAL = XK["address"]        # an attested stranger who sees the claim in the mempool
UK = generate_keydict(); BARE = UK["address"]         # an account with no device statement
LINK = generate_keydict()                             # the throwaway link key (the wallet derives it from the seed)
IID = invite_id_of(LINK["public_key"])
AMT = 5_000_000
for kd, bal0 in ((RK, 10_000_000), (NK, 0), (XK, 0), (UK, 0)):
    create_account(kd["address"], balance=bal0)
    kv_ops.account_set_field(kd["address"], "public_key", kd["public_key"])
for who in (NEW, RIVAL):                               # attested: a device stamp and a recert, as apply_register leaves them
    kv_ops.account_set_field(who, "devkey", "webauthn:" + who[:16])
    kv_ops.recert_put(who, 1)


def bal(a):
    return (get_account(a) or {}).get("balance", 0)


def signed(kd, recipient, data, amount=0, fee=0, target=GATE + 10):
    tx = {"sender": kd["address"], "recipient": recipient, "amount": amount, "fee": fee, "data": data,
          "timestamp": 1, "nonce": "n" + recipient + str(target) + str(len(str(data))), "public_key": kd["public_key"],
          "max_block": target, "chain_id": CHAIN_ID}
    tx["txid"] = create_txid(tx); tx["signature"] = sign(kd["private_key"], unhex(tx["txid"]))
    return tx


def link_sig(claimant, iid=IID, key=LINK):
    return sign(key["private_key"], invite_claim_message(iid, claimant))


def expect_reject(tx, substr, height=None):
    try:
        validate_transaction(tx, logger, block_height=tx["max_block"] if height is None else height)
    except AssertionError as e:
        assert substr in str(e), f"wrong reason: {e}"
        return
    raise RuntimeError(f"accepted: {tx['recipient']}")


def lock_tx(target=GATE + 10, key=LINK, expiry=None, amount=AMT):
    return signed(RK, "invite_lock", {"key": key["public_key"], "expiry": expiry or target + 2000},
                  amount=amount, fee=MIN_TX_FEE, target=target)


def claim_tx(kd, sig=None, target=GATE + 20, iid=IID, key=LINK):
    return signed(kd, "invite_claim", {"id": iid, "key": key["public_key"], "sig": sig or link_sig(kd["address"], iid, key)},
                  target=target)


def t_gate():
    expect_reject(lock_tx(target=GATE - 5), "not enabled yet")
    expect_reject(signed(RK, "invite", "", amount=AMT, fee=MIN_TX_FEE, target=GATE + 5), "escrow cannot be paid directly")
    expect_reject(signed(RK, "invite", "", amount=AMT, fee=MIN_TX_FEE, target=GATE - 5), "escrow cannot be paid directly")
    expect_reject(claim_tx(NK, target=GATE - 3), "not enabled yet")


def t_lock_fits_and_validates():
    tx = lock_tx()
    assert len(canonical_bytes(tx)) < TX_MAX_BYTES, "a lock with a real ML-DSA key fits the transaction size cap"
    validate_transaction(tx, logger, block_height=tx["max_block"])
    expect_reject(lock_tx(expiry=GATE + 10 + INVITE_MIN_TIMELOCK - 1), "outside the allowed window")
    expect_reject(lock_tx(expiry=GATE + 10 + INVITE_MAX_TIMELOCK + 1), "outside the allowed window")
    expect_reject(lock_tx(amount=0), "positive amount")
    bad = signed(RK, "invite_lock", {"key": "ab" * 10, "expiry": GATE + 3000}, amount=AMT, fee=MIN_TX_FEE)
    expect_reject(bad, "ML-DSA-44 public key")


def t_lock_escrows_and_reverts():
    r0, e0 = bal(REF), bal(INVITE_ESCROW)
    tx = lock_tx()
    reflect_transaction(tx, logger, block_height=GATE + 10)
    assert bal(REF) == r0 - AMT - MIN_TX_FEE and bal(INVITE_ESCROW) == e0 + AMT, "amount escrowed, fee burned"
    assert kv_ops.invite_get(IID) == [REF, AMT, GATE + 10 + 2000, "open", ""], kv_ops.invite_get(IID)
    expect_reject(lock_tx(), "already exists")
    reflect_transaction(tx, logger, block_height=GATE + 10, revert=True)
    assert bal(REF) == r0 and bal(INVITE_ESCROW) == e0 and kv_ops.invite_get(IID) is None, "lock reverts exactly"
    reflect_transaction(tx, logger, block_height=GATE + 10)          # leave it open for the claim tests


def t_claim_names_its_claimant():
    good = claim_tx(NK)
    assert len(canonical_bytes(good)) < TX_MAX_BYTES, "a claim with a real ML-DSA signature fits the size cap"
    validate_transaction(good, logger, block_height=good["max_block"])
    # FRONT-RUN: the rival copies the newcomer's signature into its own claim -> refused
    expect_reject(claim_tx(XK, sig=good["data"]["sig"]), "does not name this claimant")
    # a claim signed by the wrong key for this id
    other = generate_keydict()
    expect_reject(claim_tx(NK, sig=link_sig(NEW, IID, other), key=other), "does not match the invite")
    expect_reject(claim_tx(UK), "only a registered device identity")
    expect_reject(claim_tx(RK), "cannot claim their own")
    expect_reject(claim_tx(NK, target=GATE + 10 + 2000), "expired")
    expect_reject(signed(NK, "invite_claim", {"id": IID, "key": LINK["public_key"], "sig": link_sig(NEW), "x": 1}),
                  "must be {id, key, sig}")


def t_claim_pays_and_reverts():
    n0, e0 = bal(NEW), bal(INVITE_ESCROW)
    tx = claim_tx(NK)
    reflect_transaction(tx, logger, block_height=GATE + 20)
    assert bal(NEW) == n0 + AMT and bal(INVITE_ESCROW) == e0 - AMT, "the claimant receives exactly the amount"
    assert kv_ops.invite_get(IID)[3:] == ["claimed", NEW]
    expect_reject(claim_tx(NK, target=GATE + 21), "no OPEN invite")
    expect_reject(signed(RK, "invite_refund", {"id": IID}, target=GATE + 2100), "no OPEN invite")
    reflect_transaction(tx, logger, block_height=GATE + 20, revert=True)
    assert bal(NEW) == n0 and bal(INVITE_ESCROW) == e0 and kv_ops.invite_get(IID)[3:] == ["open", ""], "claim reverts exactly"


def t_refund_after_expiry_and_reverts():
    exp = GATE + 10 + 2000
    expect_reject(signed(RK, "invite_refund", {"id": IID}, target=exp - 1), "not expired yet")
    expect_reject(signed(NK, "invite_refund", {"id": IID}, target=exp), "only the referrer")
    tx = signed(RK, "invite_refund", {"id": IID}, target=exp)
    validate_transaction(tx, logger, block_height=exp)
    r0, e0 = bal(REF), bal(INVITE_ESCROW)
    reflect_transaction(tx, logger, block_height=exp)
    assert bal(REF) == r0 + AMT and bal(INVITE_ESCROW) == e0 - AMT and kv_ops.invite_get(IID)[3] == "refunded"
    reflect_transaction(tx, logger, block_height=exp, revert=True)
    assert bal(REF) == r0 and bal(INVITE_ESCROW) == e0 and kv_ops.invite_get(IID)[3:] == ["open", ""], "refund reverts exactly"


def t_block_uniqueness_and_htlc_isolation():
    c, r = claim_tx(NK), signed(RK, "invite_refund", {"id": IID})
    assert reserved_uniqueness_key(c) == reserved_uniqueness_key(r) == ("invite_settle", IID), "one settle per invite per block"
    assert reserved_uniqueness_key(lock_tx()) == reserved_uniqueness_key(lock_tx(target=GATE + 11)) == \
        ("invite_lock", LINK["public_key"]), "one lock per key per block"
    assert kv_ops.htlc_get("invite:" + IID) is None, "an HTLC id naming an invite row finds no swap"
    assert all(not k.startswith("invite:") for k in kv_ops.htlc_all()), "the swap listing never shows an invite"
    assert IID in kv_ops.invite_all()


for name, fn in [("before the gate every invite tx is refused; the escrow is never paid directly", t_gate),
                 ("a lock with a real key validates, fits, and keeps its window", t_lock_fits_and_validates),
                 ("a lock escrows the amount, burns the fee, and reverts exactly", t_lock_escrows_and_reverts),
                 ("a claim must be signed for its own claimant (a copied claim is refused)", t_claim_names_its_claimant),
                 ("a claim pays exactly the amount to the claimant and reverts exactly", t_claim_pays_and_reverts),
                 ("the referrer refunds only after expiry, and the refund reverts exactly", t_refund_after_expiry_and_reverts),
                 ("one settle per invite per block; invite rows never read as HTLCs", t_block_uniqueness_and_htlc_isolation)]:
    check(name, fn)
print("ALL PASS — an invite pays only the claimant its link key names" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
