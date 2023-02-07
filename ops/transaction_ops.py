import asyncio
import json
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

async def get_recommneded_fee(target, port, base_fee, logger):
    try:
        http_client = AsyncHTTPClient()
        url = f"http://{target}:{port}/get_recommended_fee"
        response = await http_client.fetch(url, request_timeout=5)
        result = json.loads(response.body.decode())
        return result['fee'] + base_fee
    except Exception as e:
        logger.warning(f"Failed to get recommended fee: {e}")
    finally:
        del http_client


async def get_target_block(target, port, logger):
    try:
        http_client = AsyncHTTPClient()
        url = f"http://{target}:{port}/get_latest_block"
        response = await http_client.fetch(url, request_timeout=5)
        result = json.loads(response.body.decode())
        return result['block_number'] + 2
    except Exception as e:
        logger.warning(f"Failed to get target block: {e}")
    finally:
        del http_client

def remove_outdated_transactions(transaction_list, block_number):
    cleaned = []
    for transaction in transaction_list:
        if block_number < transaction["target_block"] < block_number + 360:
            cleaned.append(transaction)

    return cleaned


def get_transaction(txid, logger):
    """return transaction based on txid"""

    try:
        tx_handler = DbHandler(db_file=f"{get_home()}/index/transactions.db")
        block_number = tx_handler.db_fetch("SELECT block_number FROM tx_index WHERE txid = ?", (txid,))[0][0]
        tx_handler.close()

        block = get_block_number(number=block_number)

        for transaction in block["block_transactions"]:
            if transaction["txid"] == txid:
                return transaction

    except Exception as e:
        return None


def create_txid(transaction):
    return blake2b_hash(json.dumps(transaction))


def validate_uniqueness(transaction, logger):
    """no longer needed, better safe than sorry"""
    if get_transaction(transaction, logger=logger):
        return False
    else:
        return True


def validate_transaction(transaction, logger, block_height):
    assert isinstance(transaction, dict), "Data structure incomplete"
    assert validate_origin(transaction, block_height=block_height), "Invalid origin"
    assert validate_address(transaction["sender"]), f"Invalid sender {transaction['sender']}"
    assert validate_address(transaction["recipient"]), f"Invalid recipient {transaction['recipient']}"
    assert validate_uniqueness(transaction["txid"], logger=logger), f"Transaction {transaction['txid']} already exists"
    assert isinstance(transaction["fee"], int), "Transaction fee is not an integer"
    assert transaction["fee"] >= 0, "Transaction fee lower than zero"
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


def get_transactions_of_account(account, min_block: int, logger):
    """rework"""

    max_block = min_block + 100
    acc_handler = DbHandler(db_file=f"{get_home()}/index/transactions.db")

    fetched = acc_handler.db_fetch(
        "SELECT txid FROM tx_index WHERE (sender = ? OR recipient = ?) AND (block_number >= ? AND block_number <= ?) ORDER BY block_number",
        (account, account, min_block, max_block,))

    acc_handler.close()

    tx_list = []
    for txid in fetched:
        tx_list.append(get_transaction(logger=logger,
                                       txid=txid[0]))

    return {f"{min_block}-{max_block}": tx_list}
    # return {batch: tx_list}


def to_readable_amount(raw_amount: int) -> str:
    return f"{(raw_amount / 1000000000):.10f}"


def to_raw_amount(amount: [int, float]) -> int:
    return int(float(amount) * 1000000000)


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


def validate_single_spending(transaction_pool: list, transaction):
    """validate spending of a single spender against his transactions in a transaction pool"""
    transaction_pool.append(transaction)  # future state

    sender = transaction["sender"]

    standing_balance = get_account(sender)["balance"]
    amount_sum = 0
    fee_sum = 0

    for pool_tx in transaction_pool:
        if pool_tx["sender"] == sender:
            check_balance(
                account=sender,
                amount=pool_tx["amount"],
                fee=pool_tx["fee"],
            )

            amount_sum += pool_tx["amount"]
            fee_sum += pool_tx["fee"]

            spending = amount_sum + fee_sum
            assert spending <= standing_balance, "Overspending attempt"
    return True


def validate_all_spending(transaction_pool: list):
    """validate spending of all spenders in a transaction pool against their transactions"""
    sender_pool = get_senders(transaction_pool)

    for sender in sender_pool:
        standing_balance = get_account(sender)["balance"]
        amount_sum = 0
        fee_sum = 0

        for pool_tx in transaction_pool:
            if pool_tx["sender"] == sender:
                check_balance(
                    account=sender,
                    amount=pool_tx["amount"],
                    fee=pool_tx["fee"],
                )

                amount_sum += pool_tx["amount"]
                fee_sum += pool_tx["fee"]

                spending = amount_sum + fee_sum
                assert spending <= standing_balance, "Overspending attempt"
    return True


def validate_origin(transaction: dict, block_height):
    """save signature and then remove it as it is not a part of the signed message"""

    transaction = transaction.copy()
    signature = transaction["signature"]
    del transaction["signature"]

    assert proof_sender(
        sender=transaction["sender"],
        public_key=transaction["public_key"]
    ), "Invalid sender"

    if block_height < 102000:
        assert verify(
            signed=signature,
            message=msgpack.packb(transaction),
            public_key=transaction["public_key"],
        ), "Invalid sender"
    else:
        assert verify(
            signed=signature,
            message=unhex(transaction["txid"]),
            public_key=transaction["public_key"],
        ), "Invalid sender"



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

    #from ops.log_ops import get_logger
    #print(validate_txid(transaction=transaction_message, logger=get_logger()))
    #time.sleep(10000)

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
        "target_block": target_block
    }

    return transaction_message

def unindex_transactions(block, logger):
    while True:
        try:
            txs_to_unindex = []
            for transaction in block["block_transactions"]:
                txs_to_unindex.append(transaction["txid"])
                reflect_transaction(transaction, revert=True, logger=logger)

            tx_handler = DbHandler(db_file=f"{get_home()}/index/transactions.db")
            tx_handler.db_executemany("DELETE FROM tx_index WHERE txid = ?", (txs_to_unindex,))
            tx_handler.close()
            break

        except Exception as e:
            logger.error(f"Failed to unindex transactions: {e}")


def index_transactions(block, sorted_transactions, logger):
    while True:
        try:
            txs_to_index = []
            for transaction in sorted_transactions:
                reflect_transaction(transaction, logger=logger)
                txs_to_index.append((transaction['txid'],
                                     block['block_number'],
                                     transaction['sender'],
                                     transaction['recipient']))

            tx_handler = DbHandler(db_file=f"{get_home()}/index/transactions.db")
            tx_handler.db_executemany("INSERT INTO tx_index VALUES (?,?,?,?)", txs_to_index)
            tx_handler.close()
            break

        except Exception as e:
            logger.error(f"Failed to index transactions of {block['block_hash']}: {e}")
            time.sleep(1)


if __name__ == "__main__":
    logger = get_logger(file="transactions.log")
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

            transaction = create_transaction(draft=draft, private_key=private_key,fee=0)

            print(transaction)
            print(validate_transaction(transaction, logger=logger, block_height=0))

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
