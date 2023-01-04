import json
import msgpack
from tornado.httpclient import AsyncHTTPClient
import asyncio
from peer_ops import load_ips
from compounder import compound_send_transaction
from Curve25519 import sign, verify
from account_ops import get_account, reflect_transaction
from address import proof_sender
from address import validate_address
from block_ops import get_block_number
from config import get_config
from config import get_timestamp_seconds
from data_ops import sort_list_dict, get_home
from hashing import create_nonce, blake2b_hash
from keys import load_keys
from log_ops import get_logger
from sqlite_ops import DbHandler


async def get_recommneded_fee(target, port):
    http_client = AsyncHTTPClient()
    url = f"http://{target}:{port}/get_recommended_fee"
    response = await http_client.fetch(url)
    result = json.loads(response.body.decode())
    return result['fee']


async def get_target_block(target, port):
    http_client = AsyncHTTPClient()
    url = f"http://{target}:{port}/get_latest_block"
    response = await http_client.fetch(url)
    result = json.loads(response.body.decode())
    return result['block_number'] + 5


def remove_outdated_transactions(transaction_list, block_number):
    cleaned = []
    for transaction in transaction_list:
        if block_number + 360 < transaction["target_block"] > block_number:
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
    if get_transaction(transaction, logger=logger):
        return False
    else:
        return True


def validate_transaction(transaction, logger):
    assert isinstance(transaction, dict), "Data structure incomplete"
    assert validate_origin(transaction), "Invalid origin"
    assert validate_address(transaction["sender"]), f"Invalid sender {transaction['sender']}"
    assert validate_address(transaction["recipient"]), f"Invalid recipient {transaction['recipient']}"
    assert validate_uniqueness(transaction["txid"], logger=logger), f"Transaction {transaction['txid']} already exists"
    assert isinstance(transaction["fee"], int), "Transaction fee is not an integer"
    assert transaction["fee"] >= 0, "Transaction fee lower than zero"
    return True


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


def validate_origin(transaction: dict):
    """save signature and then remove it as it is not a part of the signed message"""

    transaction = transaction.copy()
    signature = transaction["signature"]
    del transaction["signature"]

    assert proof_sender(
        sender=transaction["sender"], public_key=transaction["public_key"]
    ), "Invalid sender"

    assert verify(
        signed=signature,
        message=msgpack.packb(transaction),
        public_key=transaction["public_key"],
    ), "Invalid sender"

    return True


def create_transaction(sender, recipient, amount, public_key, private_key, timestamp, data, fee, target_block):
    """construct transaction, then add txid, then add signature as last"""
    transaction_message = {
        "sender": sender,
        "recipient": recipient,
        "amount": amount,
        "timestamp": timestamp,
        "data": data,
        "nonce": create_nonce(),
        "fee": fee,
        "public_key": public_key,
        "target_block": target_block
    }
    txid = create_txid(transaction_message)
    transaction_message.update(txid=txid)

    signature = sign(private_key=private_key, message=msgpack.packb(transaction_message))
    transaction_message.update(signature=signature)

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
            logger.error(f"Failed to index transactions: {e}")


if __name__ == "__main__":
    logger = get_logger(file="transactions.log")
    # print(get_account("noob23"))

    key_dict = load_keys()
    address = key_dict["address"]
    recipient = "ndo6a7a7a6d26040d8d53ce66343a47347c9b79e814c66e29"
    private_key = key_dict["private_key"]
    public_key = key_dict["public_key"]
    amount = to_raw_amount(0)
    data = {"data_id": "seek_id", "data_content": "some_actual_content"}

    config = get_config()
    ip = config["ip"]
    # ips = ["127.0.0.1"]
    port = config["port"]

    ips = asyncio.run(load_ips(logger=logger,
                               fail_storage=[],
                               port=port))

    for x in range(0, 50000):
        try:
            transaction = create_transaction(sender=address,
                                             recipient=recipient,
                                             amount=to_raw_amount(amount),
                                             data=data,
                                             fee=0,
                                             public_key=public_key,
                                             private_key=private_key,
                                             timestamp=get_timestamp_seconds(),
                                             target_block=asyncio.run(get_target_block(target=ips[0], port=port)))

            print(transaction)
            print(validate_transaction(transaction, logger=logger))

            fails = []
            results = asyncio.run(compound_send_transaction(ips=ips,
                                                            port=port,
                                                            fail_storage=fails,
                                                            logger=logger,
                                                            transaction=transaction))

            print(f"Submitted to {len(results)} nodes successfully")

            # time.sleep(5)
        except Exception as e:
            print(e)
            raise

    # tx_pool = json.loads(requests.get(f"http://{ip}:{port}/transaction_pool").text, timeout=5)
