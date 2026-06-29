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
from ops.block_ops import get_block_number
from compounder import compound_send_transaction
from config import get_config
from config import get_timestamp_seconds
from ops.data_ops import sort_list_dict, get_home, get_byte_size
from hashing import create_nonce, blake2b_hash
from ops.key_ops import load_keys
from ops.log_ops import get_logger
from ops.peer_ops import load_ips
from ops.sqlite_ops import DbHandler
from protocol import CHAIN_ID, MIN_TX_FEE
import aiohttp


def tx_index_path():
    """single, consolidated transaction index (replaces the per-10k-block split files)"""
    return f"{get_home()}/index/transactions.db"


_tx_index_ready = False


def ensure_tx_index(handler=None):
    """create the consolidated tx index + the indexes that actually serve our queries.
    Idempotent. Returns an OPEN handler; the caller is responsible for closing it
    (whether it passed one in or not). The DDL only runs once per process — on the
    hot read/write paths this skips four redundant CREATE ... IF NOT EXISTS calls."""
    global _tx_index_ready
    if handler is None:
        handler = DbHandler(db_file=tx_index_path())
    if not _tx_index_ready:
        handler.db_execute(
            "CREATE TABLE IF NOT EXISTS tx_index(txid TEXT, block_number INTEGER, sender TEXT, recipient TEXT)")
        # lookups by txid (get_transaction); UNIQUE makes (re)indexing idempotent
        handler.db_execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_txid ON tx_index(txid)")
        # account history: filter by sender/recipient, range + order by block_number
        handler.db_execute("CREATE INDEX IF NOT EXISTS idx_sender ON tx_index(sender, block_number)")
        handler.db_execute("CREATE INDEX IF NOT EXISTS idx_recipient ON tx_index(recipient, block_number)")
        _tx_index_ready = True
    return handler


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
        tx_handler = ensure_tx_index()
        fetched = tx_handler.db_fetch("SELECT block_number FROM tx_index WHERE txid = ?", (txid,))
        tx_handler.close()

        if not fetched:
            return None

        block = get_block_number(number=fetched[0][0])
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
    # canonical encoding (sorted keys) commits the whole body — incl. chain_id — so the
    # signature (over the txid) binds every field and cannot be replayed cross-chain.
    return blake2b_hash(transaction)


def validate_transaction(transaction, logger, block_height):
    assert isinstance(transaction, dict), "Data structure incomplete"
    assert transaction.get("chain_id") == CHAIN_ID, "Wrong or missing chain id"
    assert validate_origin(transaction), "Invalid origin"
    assert validate_address(transaction["sender"]), f"Invalid sender {transaction['sender']}"
    assert validate_address(transaction["recipient"]), f"Invalid recipient {transaction['recipient']}"
    assert isinstance(transaction["fee"], int) and not isinstance(transaction["fee"], bool), "Transaction fee is not an integer"
    # deterministic minimum-fee floor (anti-spam), enforced in consensus from block 1
    assert transaction["fee"] >= MIN_TX_FEE, f"Transaction fee below minimum {MIN_TX_FEE}"
    # amount must be a non-negative integer (not a bool, not a float): a float would
    # satisfy the old check_balance comparison and corrupt the integer-satoshi ledger
    assert isinstance(transaction["amount"], int) and not isinstance(transaction["amount"], bool), "Transaction amount is not an integer"
    assert transaction["amount"] >= 0, "Transaction amount lower than zero"
    assert len(transaction["txid"]) >= 64
    # bind the signature to the FULL body: the signature only covers the txid, so
    # without recomputing the txid from the body an attacker could keep a valid
    # (sender, public_key, txid, signature) and swap recipient/amount. The block
    # path previously skipped this (only the mempool checked it).
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
    """history for an account, from the single consolidated index.

    A UNION of two index-served lookups (sender, recipient) replaces the old
    OR-over-an-unusable-index full scan, and txids are grouped by block so each
    block file is read at most once instead of once per transaction."""
    acc_handler = ensure_tx_index()
    fetched = acc_handler.db_fetch(
        """SELECT txid, block_number FROM tx_index WHERE sender = ? AND block_number >= ?
           UNION
           SELECT txid, block_number FROM tx_index WHERE recipient = ? AND block_number >= ?
           ORDER BY block_number LIMIT ?""",
        (account, min_block, account, min_block, limit))
    acc_handler.close()

    txids_by_block = {}
    block_order = []
    for txid, block_number in fetched:
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
    other tx — including `bond` and `burn` — consumes amount+fee from spendable balance."""
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

    assert proof_sender(
        sender=transaction["sender"],
        public_key=transaction["public_key"]
    ), "Invalid sender"

    assert verify(
        signed=signature,
        message=unhex(transaction["txid"]),
        public_key=transaction["public_key"],
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


def unindex_transactions(block, logger, block_height):
    # revert balance changes exactly once (each call retries internally); only the
    # idempotent index delete below is retried on transient db locks
    txids_to_unindex = [[transaction["txid"]] for transaction in block["block_transactions"]]
    for transaction in block["block_transactions"]:
        reflect_transaction(transaction=transaction,
                            revert=True,
                            logger=logger,
                            block_height=block_height)

    while True:
        try:
            tx_handler = ensure_tx_index()
            if txids_to_unindex:
                tx_handler.db_executemany("DELETE FROM tx_index WHERE txid = ?", txids_to_unindex)
            tx_handler.close()
            break
        except Exception as e:
            logger.error(f"Failed to unindex transactions: {e}")
            time.sleep(1)


def index_transactions(block, sorted_transactions, logger):
    block_height = block["block_number"]

    # apply balance changes exactly once (reflect_transaction retries internally);
    # only the idempotent index write below is retried on transient db locks
    for transaction in sorted_transactions:
        reflect_transaction(transaction=transaction,
                            logger=logger,
                            block_height=block_height)

    txs_to_index = [(transaction['txid'],
                     block_height,
                     transaction['sender'],
                     transaction['recipient'])
                    for transaction in sorted_transactions]

    while True:
        try:
            tx_handler = ensure_tx_index()
            if txs_to_index:
                tx_handler.db_executemany("INSERT OR IGNORE INTO tx_index VALUES (?,?,?,?)", txs_to_index)
            tx_handler.close()
            break
        except Exception as e:
            logger.error(f"Failed to index transactions of {block['block_hash']}: {e}")
            time.sleep(1)


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
