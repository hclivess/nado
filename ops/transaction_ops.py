import asyncio
import json
import os.path
import time

import msgpack
from tornado.httpclient import AsyncHTTPClient

from Curve25519 import sign, verify, unhex
from ops.account_ops import get_account, reflect_transaction
from ops.address_ops import proof_sender
from ops.address_ops import validate_address
from ops.mining_ops import verify_registration_pow
from ops.block_ops import get_block_number
from compounder import compound_send_transaction
from config import get_config
from config import get_timestamp_seconds
from ops.data_ops import sort_list_dict, get_home, get_byte_size
from hashing import create_nonce, blake2b_hash
from ops.key_ops import load_keys
from ops.log_ops import get_logger
from ops.peer_ops import load_ips
from ops import kv_ops
from protocol import CHAIN_ID, MIN_TX_FEE, EPOCH_LENGTH
import aiohttp


async def get_recommneded_fee(target, port, base_fee, logger):
    try:
        url_construct = f"http://{target}:{port}/get_recommended_fee"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                result = json.loads(await response.text())
                return result['fee'] + base_fee
    except Exception as e:
        logger.warning(f"Failed to get recommended fee: {e}")


async def get_target_block(target, port, logger):
    try:
        url_construct = f"http://{target}:{port}/get_latest_block"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                result = json.loads(await response.text())
                return result['block_number'] + 2
    except Exception as e:
        logger.warning(f"Failed to get target block: {e}")


def remove_outdated_transactions(transaction_list, block_number):
    cleaned = []
    for transaction in transaction_list:
        if block_number < transaction["target_block"] < block_number + 360:
            cleaned.append(transaction)

    return cleaned


def get_transaction(txid, logger):
    """return transaction based on txid via a single indexed lookup"""
    try:
        entry = kv_ops.tx_get(txid)
        if not entry:
            return None

        block = get_block_number(number=entry["block_number"])
        if not block:
            return None

        for transaction in block["block_transactions"]:
            if transaction["txid"] == txid:
                return transaction

        return None

    except Exception as e:
        logger.error(f"Failed to get transaction {txid}: {e}")
        return None


def create_txid(transaction):
    # canonical encoding (sorted keys) commits the whole body — incl. chain_id — so the signature
    # (over the txid) binds every field and cannot be replayed cross-chain. PUBKEY-ONCE (#19): the
    # `public_key` is EXCLUDED from the preimage — it is a recoverable authentication witness (bound
    # to the sender address by proof_sender, stored on-chain on first use), not part of the tx
    # identity — so a later tx may OMIT the 1312-byte ML-DSA key and still produce the same txid.
    # The browser light-miner computes the identical txid (canonical_bytes, public_key excluded).
    body = {k: v for k, v in transaction.items() if k != "public_key"}
    return blake2b_hash(body)


def validate_transaction(transaction, logger, block_height):
    assert isinstance(transaction, dict), "Data structure incomplete"
    assert transaction.get("chain_id") == CHAIN_ID, "Wrong or missing chain id"
    assert validate_origin(transaction), "Invalid origin"
    # SENDER must be a real keyed address — never a reserved protocol pseudo-recipient.
    assert validate_address(transaction["sender"], allow_reserved=False), f"Invalid sender {transaction['sender']}"
    # RECIPIENT (the target) must be a checksum-valid address OR a reserved protocol recipient
    # (bond/unbond/register/heartbeat). A malformed/typo target with a bad checksum is rejected.
    assert validate_address(transaction["recipient"]), f"Invalid recipient {transaction['recipient']}"
    assert isinstance(transaction["fee"], int) and not isinstance(transaction["fee"], bool), "Transaction fee is not an integer"
    # amount must be a non-negative integer (not a bool, not a float): a float would
    # satisfy the old check_balance comparison and corrupt the integer-satoshi ledger
    assert isinstance(transaction["amount"], int) and not isinstance(transaction["amount"], bool), "Transaction amount is not an integer"
    assert transaction["amount"] >= 0, "Transaction amount lower than zero"
    assert len(transaction["txid"]) >= 64

    recipient = transaction["recipient"]
    if recipient in ("register", "heartbeat"):
        # OPEN-lane mining txs: FEE-EXEMPT (a zero-balance newcomer can't pay) and move no coins.
        assert transaction["amount"] == 0, "Open-lane (register/heartbeat) tx must have zero amount"
        assert transaction["fee"] == 0, "Open-lane (register/heartbeat) tx is fee-exempt (fee must be 0)"
        if recipient == "register":
            # the one-time light registration PoW substitutes for the unaffordable fee; it binds
            # the nonce to the sender's address so it can't be reused for a different identity.
            assert verify_registration_pow(transaction["sender"], transaction.get("pow_nonce")), "Invalid or missing registration PoW"
            assert get_account(transaction["sender"])["registered"] == 0, "Address already registered"
        else:  # heartbeat
            # Bound to the epoch of the block it DETERMINISTICALLY lands in — its target_block (the
            # block builder matches a tx into exactly target_block == block_number). Validating against
            # target_block (NOT the passed block_height) makes the mempool gate (block_height = current
            # tip) AGREE with block-build validation (block_height = block_number == target_block) and
            # with apply_heartbeat's recorded epoch — so a heartbeat near an epoch boundary is no longer
            # spuriously rejected just because the tip's epoch differs from its landing block's epoch.
            # Still unforgeable/non-replayable: epoch + target_block are in the signed body (the txid),
            # and one-per-(address,epoch) is enforced by the DUPSORT heartbeats sub-DB on apply.
            assert transaction.get("epoch") == transaction["target_block"] // EPOCH_LENGTH, "Heartbeat epoch mismatch"
            assert get_account(transaction["sender"])["registered"] == 1, "Heartbeat from an unregistered address"
    else:
        # ordinary transfer / bond / unbond: deterministic minimum-fee floor (anti-spam), from block 1
        assert transaction["fee"] >= MIN_TX_FEE, f"Transaction fee below minimum {MIN_TX_FEE}"

    # bind the signature to the FULL body: the signature only covers the txid, so without
    # recomputing the txid from the body an attacker could keep a valid (sender, public_key,
    # txid, signature) and swap recipient/amount. The block path previously skipped this.
    assert validate_txid(transaction, logger=logger), "Transaction id does not match its contents"
    return True


def min_from_transaction_pool(transactions: list, key="fee") -> dict:
    """returns dictionary from a list of dictionaries with minimum value"""
    return min(sort_list_dict(transactions), key=lambda transaction: transaction[key])


def max_from_transaction_pool(transactions: list, key="fee") -> dict:
    """returns dictionary from a list of dictionaries with maximum value"""
    return max(sort_list_dict(transactions), key=lambda transaction: transaction[key])


def sort_transaction_pool(transactions: list, key="txid") -> list:
    """sorts list of dictionaries based on a dictionary value"""
    return sorted(
        sort_list_dict(transactions), key=lambda transaction: transaction[key]
    )


def get_transactions_of_account(account, min_block: int, logger, limit: int = 1000):
    """history for an account, from the consolidated KV index.

    A UNION of the two DUPSORT secondary indexes (tx_by_sender, tx_by_recipient) — each ordered by
    block — replaces the old OR-over-an-unusable-index full scan, deduped and ordered by block, then
    txids are grouped by block so each block file is read at most once instead of once per tx."""
    fetched = kv_ops.tx_of_account(account, min_block, limit)  # [(block_number, txid)], block-ordered

    txids_by_block = {}
    block_order = []
    for block_number, txid in fetched:
        if block_number not in txids_by_block:
            txids_by_block[block_number] = set()
            block_order.append(block_number)
        txids_by_block[block_number].add(txid)

    all_txs = []
    for block_number in block_order:
        block = get_block_number(number=block_number)
        if not block:
            continue
        wanted = txids_by_block[block_number]
        for transaction in block["block_transactions"]:
            if transaction["txid"] in wanted:
                all_txs.append(transaction)

    return {"transactions": all_txs}


def to_readable_amount(raw_amount: int) -> str:
    return f"{(raw_amount / 10000000000):.10f}"


def to_raw_amount(amount: [int, float]) -> int:
    return int(float(amount) * 10000000000)


def check_balance(account, amount, fee):
    """for single transaction, check if the fee and the amount spend are allowable"""
    balance = get_account(account)["balance"]
    assert (
            balance - amount - fee > 0 <= amount
    ), f"{account} spending more than owned in a single transaction"
    return True


def get_senders(transaction_pool: list) -> list:
    sender_pool = []
    for transaction in transaction_pool:
        if transaction["sender"] not in sender_pool:
            sender_pool.append(transaction["sender"])
    return sender_pool


def _spend_costs(tx):
    """(spendable-balance cost, bonded-stake cost) of a tx for overspend checks.
    An `unbond` draws its `amount` from bonded stake (only the fee leaves balance); every
    other tx — including `bond` — consumes amount+fee from spendable balance."""
    if tx["recipient"] == "unbond":
        return tx["fee"], tx["amount"]
    return tx["amount"] + tx["fee"], 0


def validate_single_spending(transaction_pool: list, transaction):
    """validate spending of a single spender against his transactions in a transaction pool"""
    pool = transaction_pool + [transaction]  # future state (no mutation of the caller's list)
    sender = transaction["sender"]
    acc = get_account(sender)
    balance, bonded = acc["balance"], acc["bonded"]

    balance_spent = 0
    bonded_spent = 0
    for pool_tx in pool:
        if pool_tx["sender"] == sender:
            b_cost, bond_cost = _spend_costs(pool_tx)
            balance_spent += b_cost
            bonded_spent += bond_cost
            assert balance_spent <= balance, "Overspending balance"
            assert bonded_spent <= bonded, "Overspending bonded stake"
    return True


def validate_all_spending(transaction_pool: list):
    """validate spending of all spenders in a transaction pool against their balance AND
    their bonded stake (unbond draws from bonded, not from spendable balance)."""
    for sender in get_senders(transaction_pool):
        acc = get_account(sender)
        balance, bonded = acc["balance"], acc["bonded"]

        balance_spent = 0
        bonded_spent = 0
        for pool_tx in transaction_pool:
            if pool_tx["sender"] == sender:
                b_cost, bond_cost = _spend_costs(pool_tx)
                balance_spent += b_cost
                bonded_spent += bond_cost
                assert balance_spent <= balance, "Overspending balance"
                assert bonded_spent <= bonded, "Overspending bonded stake"
    return True


def validate_origin(transaction: dict):
    """signature is verified over the txid (which canonically commits the whole body,
    including chain_id); it is not itself part of the signed message."""

    transaction = transaction.copy()
    signature = transaction["signature"]
    del transaction["signature"]

    # PUBKEY-ONCE (#19): the tx MAY omit public_key. If omitted, recover the sender's pubkey
    # established on-chain by an earlier tx (every address's pubkey is fixed, bound by proof_sender).
    # The very FIRST tx from an address MUST carry it (nothing to recover yet).
    public_key = transaction.get("public_key")
    if not public_key:
        account = get_account(transaction["sender"], create_on_error=False)
        public_key = account.get("public_key") if account else None
        assert public_key, "Missing public_key and no on-chain pubkey for sender (first tx must carry it)"

    assert proof_sender(
        sender=transaction["sender"],
        public_key=public_key
    ), "Invalid sender"

    assert verify(
        signed=signature,
        message=unhex(transaction["txid"]),
        public_key=public_key,
    ), "Invalid signature"

    return True


def get_base_fee(transaction):
    try:
        tx_copy = transaction.copy()
        base_fee = get_byte_size(tx_copy)
        return base_fee

    except Exception as e:
        logger.info(f'Failed to calculate base fee: {e}')
        return False


def validate_base_fee(transaction, logger):
    try:
        tx_copy = transaction.copy()
        fee = tx_copy["fee"]
        tx_copy.pop("fee")
        tx_copy.pop("signature")
        tx_copy.pop("txid")

        if fee >= get_base_fee(tx_copy):
            return True
        else:
            return False

    except Exception as e:
        logger.info(f'Failed to validate base fee: {e}')
        return False


def validate_txid(transaction, logger):
    try:
        tx_copy = transaction.copy()
        txid_to_check = tx_copy["txid"]
        tx_copy.pop("txid")
        tx_copy.pop("signature")
        txid_genuine = create_txid(tx_copy)
        if txid_genuine == txid_to_check:
            return True
        else:
            return False
    except Exception as e:
        logger.info(f'Failed to match transaction to its id: {e}')
        return False


def create_transaction(draft, private_key, fee):
    """construct transaction, then add txid, then add signature as last"""
    transaction_message = draft.copy()
    transaction_message.update(fee=fee)

    txid = create_txid(transaction_message)
    transaction_message.update(txid=txid)

    signature = sign(private_key=private_key, message=unhex(txid))
    transaction_message.update(signature=signature)

    # from ops.log_ops import get_logger
    # print(validate_txid(transaction=transaction_message, logger=get_logger()))
    # time.sleep(10000)

    return transaction_message


def draft_transaction(sender, recipient, amount, public_key, timestamp, data, target_block):
    """construct to be able to calculate base fee, signature and txid are not present here"""
    transaction_message = {
        "sender": sender,
        "recipient": recipient,
        "amount": amount,
        "timestamp": timestamp,
        "data": data,
        "nonce": create_nonce(),
        "public_key": public_key,
        "target_block": target_block,
        "chain_id": CHAIN_ID,
    }

    return transaction_message


def draft_open_lane_transaction(sender, recipient, public_key, timestamp, target_block,
                                pow_nonce=None, epoch=None):
    """Draft a FEE-EXEMPT open-lane mining tx (recipient 'register' or 'heartbeat'): amount 0, and
    create_transaction will set fee 0. Carries pow_nonce (register) or epoch (heartbeat) in the
    SIGNED body so both are committed by the txid. The browser light-miner builds the identical
    structure (canonical_bytes reproducibility)."""
    transaction_message = {
        "sender": sender,
        "recipient": recipient,
        "amount": 0,
        "timestamp": timestamp,
        "data": "",
        "nonce": create_nonce(),
        "public_key": public_key,
        "target_block": target_block,
        "chain_id": CHAIN_ID,
    }
    if pow_nonce is not None:
        transaction_message["pow_nonce"] = pow_nonce
    if epoch is not None:
        transaction_message["epoch"] = epoch
    return transaction_message


def unindex_transactions(block, logger, block_height):
    """Revert a block's txs: undo the balance/state changes AND delete the exact primary + DUPSORT
    secondary index entries written on apply (the block||txid dup encoding makes each delete
    unambiguous). Runs inside the rollback write txn (kv_ops uses the active txn), so it is atomic
    with the rest of the rollback — no per-statement retry loop is needed or possible under LMDB."""
    for transaction in block["block_transactions"]:
        reflect_transaction(transaction=transaction,
                            revert=True,
                            logger=logger,
                            block_height=block_height)
        kv_ops.tx_index_del(txid=transaction["txid"],
                            block_number=block_height,
                            sender=transaction["sender"],
                            recipient=transaction["recipient"])
        # PUBKEY-ONCE revert: after this tx's index entry is removed, if the sender has NO remaining
        # indexed tx, this block held its first-ever tx -> clear the established pubkey so the account
        # doc returns byte-identical to before (revert-symmetric). A sender with earlier-block txs
        # keeps its pubkey (established earlier).
        if not kv_ops.tx_of_account(transaction["sender"], min_block=0, limit=1):
            kv_ops.account_del_field(transaction["sender"], "public_key")


def index_transactions(block, sorted_transactions, logger):
    block_height = block["block_number"]

    # Apply balance/state changes AND write the tx index (primary + DUPSORT secondaries) for every
    # tx. Runs inside the incorporate write txn (kv_ops uses the active txn), so the balances and the
    # index commit atomically with the rest of the block.
    for transaction in sorted_transactions:
        reflect_transaction(transaction=transaction,
                            logger=logger,
                            block_height=block_height)
        kv_ops.tx_index_put(txid=transaction["txid"],
                            block_number=block_height,
                            sender=transaction["sender"],
                            recipient=transaction["recipient"])
        # PUBKEY-ONCE (#19): record the sender's pubkey on its FIRST indexed tx (the one carrying it),
        # so later txs from this sender (e.g. every-epoch heartbeats) may omit the 1312-byte key.
        # Idempotent (skip if already stored); revert is handled symmetrically in unindex_transactions.
        pk = transaction.get("public_key")
        if pk:
            sender_acc = get_account(transaction["sender"], create_on_error=False)
            if sender_acc is not None and not sender_acc.get("public_key"):
                kv_ops.account_set_field(transaction["sender"], "public_key", pk)


if __name__ == "__main__":
    logger = get_logger(file="transactions.log", logger_name="transactions_logger")
    # print(get_account("noob23"))
    LOCAL = False

    key_dict = load_keys()
    address = key_dict["address"]
    recipient = "ndo6a7a7a6d26040d8d53ce66343a47347c9b79e814c66e29"
    private_key = key_dict["private_key"]
    public_key = key_dict["public_key"]
    amount = to_raw_amount(0)
    data = {"data_id": "seek_id", "data_content": "some_actual_content"}

    config = get_config()
    ip = config["ip"]

    port = config["port"]

    if LOCAL:
        ips = ["127.0.0.1"]
    else:
        ips = asyncio.run(load_ips(logger=logger,
                                   fail_storage=[],
                                   unreachable={},
                                   port=port))

    for x in range(0, 50000):
        try:
            draft = draft_transaction(sender=address,
                                      recipient=recipient,
                                      amount=to_raw_amount(amount),
                                      data=data,
                                      public_key=public_key,
                                      timestamp=get_timestamp_seconds(),
                                      target_block=asyncio.run(get_target_block(target=ips[0],
                                                                                port=port,
                                                                                logger=logger)))
            fee = asyncio.run(get_recommneded_fee(
                target=ips[0],
                port=port,
                base_fee=get_base_fee(transaction=draft),
                logger=logger))

            if fee > 500:
                fee = 500

            transaction = create_transaction(draft=draft,
                                             private_key=private_key,
                                             fee=fee
                                             )

            print(transaction)
            print(validate_transaction(transaction, logger=logger, block_height=111112))

            fails = []
            results = asyncio.run(compound_send_transaction(ips=ips,
                                                            port=port,
                                                            fail_storage=fails,
                                                            logger=logger,
                                                            transaction=transaction,
                                                            semaphore=asyncio.Semaphore(50)))

            print(f"Submitted to {len(results)} nodes successfully")

            # time.sleep(5)
        except Exception as e:
            print(e)
            raise

    # tx_pool = json.loads(requests.get(f"http://{ip}:{port}/transaction_pool").text, timeout=5)
