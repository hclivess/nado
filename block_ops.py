import json
import os
import time

import msgpack
import requests
from tornado.httpclient import AsyncHTTPClient

from account_ops import get_account_value
from config import get_timestamp_seconds, get_config
from data_ops import set_and_sort, average, get_home
from hashing import blake2b_hash_link
from keys import load_keys
from log_ops import get_logger
from peer_ops import load_peer
from sqlite_ops import DbHandler
import difflib
import math


def float_to_int(x):
    return math.floor(x * (2 ** 31))


def get_hash_penalty(address: str, block_hash: str, block_number: int):
    if block_number > 20000:
        address_mingled = blake2b_hash_link(address, block_hash)
        score = 0
        for letters in enumerate(address_mingled):
            score = score + block_hash.count(letters[1])

        return score

    else:

        shorter_string = min([address, block_hash], key=len)

        score = 0
        for letters in enumerate(shorter_string):
            if block_hash[letters[0]] == (letters[1]):
                score += 1
            score = score + address.count(letters[1])
            score = score + block_hash.count(letters[1])

        return score


def get_block_reward(logger, blocks_backward=100, reward_cap=5000000000):
    """based on number of transactions"""
    latest_block_info = get_latest_block_info(logger=logger)
    parent = latest_block_info["block_hash"]
    latest_block_number = latest_block_info["block_number"]
    block_number = latest_block_number
    tx_count = 0
    reward = 0

    while 0 < block_number > (latest_block_number - blocks_backward):
        block = load_block_from_hash(parent, logger=logger)
        parent = block["parent_hash"]
        block_number = block["block_number"]

        tx_count += len(block["block_transactions"])

    reward = tx_count * 1000000
    if reward > reward_cap:
        reward = reward_cap

    return reward

def valid_block_timestamp(new_block):
    new_timestamp = new_block["block_timestamp"]

    if new_block["block_number"] < 20000:  # compatibility
        return True
    if not get_timestamp_seconds() >= new_timestamp:
        return False
    else:
        return True


def check_target_match(transaction_list, block_number, logger):
    try:
        for transaction in transaction_list:
            if transaction["target_block"] != block_number:
                return False
        return True
    except Exception as e:
        logger.error(f"Error when checking transaction target block: {e}")
        return False


def match_transactions_target(transaction_list, block_number, logger):
    try:
        matched_txs = []

        for transaction in transaction_list:
            if transaction["target_block"] == block_number:
                matched_txs.append(transaction)

        return matched_txs
    except Exception as e:
        logger.error(f"Error when matching transactions to target block: {e}")
        return False


def get_block_candidate(
        block_producers, block_producers_hash, transaction_pool, logger, event_bus, peer_file_lock, latest_block, block_time
):
    best_producer = pick_best_producer(block_producers,
                                       logger=logger,
                                       event_bus=event_bus,
                                       peer_file_lock=peer_file_lock,
                                       latest_block=latest_block)

    logger.info(
        f"Producing block candidate for: {len(block_producers)} block producers won by {best_producer}"
    )

    block_number = latest_block["block_number"] + 1

    targeted_transactions = match_transactions_target(transaction_list=transaction_pool.copy(),
                                                      block_number=block_number,
                                                      logger=logger)

    creator = load_peer(logger=logger,
                        ip=best_producer,
                        key="peer_address",
                        peer_file_lock=peer_file_lock)

    block = construct_block(
        block_timestamp=latest_block["block_timestamp"]+block_time,
        block_number=block_number,
        parent_hash=latest_block["block_hash"],
        block_ip=best_producer,
        creator=creator,
        transaction_pool=targeted_transactions,
        block_producers_hash=block_producers_hash,
        block_reward=get_block_reward(logger=logger),
    )
    return block


def fee_over_blocks(logger, number_of_blocks=250):
    """returns average fee over last x blocks"""
    last_block = get_latest_block_info(logger=logger)

    if last_block["block_number"] < number_of_blocks:
        number_of_blocks = last_block["block_number"]

    fees = []
    for number in range(0, number_of_blocks):
        for transaction in last_block["block_transactions"]:
            fees.append(transaction["fee"])
    if fees:
        return average(fees)
    else:
        return 0


def get_transaction_pool_demo():
    """use for demo only"""
    config = get_config()
    ip = config["ip"]
    port = config["port"]
    tx_pool_message = requests.get(f"http://{ip}:{port}/transaction_pool?compress=msgpack", timeout=5).text
    tx_pool_dict = msgpack.unpackb(tx_pool_message)
    return tx_pool_dict


def get_block(block):
    """return transaction based on txid"""
    block_path = f"{get_home()}/blocks/{block}.block"
    if os.path.exists(block_path):
        with open(block_path, "rb") as file:
            block = msgpack.load(file)
        return block
    else:
        return False


def get_block_number(number):
    try:
        block_handler = DbHandler(db_file=f"{get_home()}/index/blocks.db")
        fetched = block_handler.db_fetch("SELECT block_hash FROM block_index WHERE block_number = ?", (number,))[0][0]
        block_handler.close()
        return get_block(fetched)
    except Exception as e:
        return False


def get_block_producers_hash_demo():
    """use for demo only"""
    config = get_config()
    ip = config["ip"]
    port = config["port"]
    status_message = requests.get(f"http://{ip}:{port}/status", timeout=5).text
    block_producers_hash = json.loads(status_message)["block_producers_hash"]
    return block_producers_hash


def load_block_from_hash(block_hash: str, logger):
    try:
        with open(f"{get_home()}/blocks/{block_hash}.block", "rb") as infile:
            return msgpack.unpack(infile)
    except Exception as e:
        logger.info(f"Failed to load block {block_hash}: {e}")
        return False


def load_block_producers() -> list:
    block_producers_path = f"{get_home()}/index/block_producers.dat"
    if os.path.exists(block_producers_path):
        with open(block_producers_path, "r") as infile:
            return json.load(infile)
    else:
        return []


def save_block_producers(block_producers: list):
    block_producers_path = f"{get_home()}/index/block_producers.dat"
    with open(block_producers_path, "w") as outfile:
        json.dump(set_and_sort(block_producers), outfile)
    return True


def save_block(block: dict, logger):
    path = f"{get_home()}/blocks/{block['block_hash']}.block"

    while True:
        try:
            with open(path, "wb") as outfile:
                msgpack.pack(block, outfile)

            with open(path, "rb") as infile:
                """validate"""
                read_block = msgpack.load(infile)

            if read_block == block:
                return True
            else:
                logger.warning("Block incoherence encountered")

        except Exception as e:
            logger.warning(f"Failed to save block {block['block_hash']} due to {e}")
            time.sleep(1)


def get_latest_block_info(logger):
    try:
        with open(f"{get_home()}/index/latest_block.dat", "r") as infile:
            info = load_block_from_hash(block_hash=json.load(infile),
                                        logger=logger)
            return info
    except Exception as e:
        logger.info(f"Failed to get latest block info: {e}")


def unindex_block(block, logger):
    while True:
        try:
            block_handler = DbHandler(db_file=f"{get_home()}/index/blocks.db")
            block_handler.db_execute(
                "DELETE FROM block_index WHERE block_number = ?", (block['block_number'],))
            block_handler.close()

            block_data = f"{get_home()}/blocks/{block['block_hash']}.block"
            while os.path.exists(block_data):
                try:
                    os.remove(block_data)
                except Exception as e:
                    logger.error(f"Failed to remove {block_data}: {e}, retrying")
            break
        except Exception as e:
            logger.error(f"Failed to unindex block: {e}")


def set_latest_block_info(block: dict, logger):
    while True:
        try:
            new_hash = block["block_hash"]
            old_hash = None

            while not old_hash == new_hash:
                with open(f"{get_home()}/index/latest_block.dat", "w") as outfile:
                    json.dump(new_hash, outfile)

                with open(f"{get_home()}/index/latest_block.dat", "r") as infile:
                    """read data to verify they have been saved properly"""
                    old_hash = json.load(infile)

            blocks_handler = DbHandler(db_file=f"{get_home()}/index/blocks.db")
            blocks_handler.db_execute("INSERT OR IGNORE INTO block_index VALUES (?, ?)",
                                      (block['block_hash'], block['block_number']))

            blocks_handler.close()

            return block

        except Exception as e:
            logger.info(f"Failed to set latest block info to {block['block_hash']}: {e}")
            time.sleep(1)


def construct_block(
        block_timestamp: int,
        block_number: int,
        parent_hash: str,
        creator: str,
        block_ip: str,
        block_producers_hash: str,
        transaction_pool: list,
        block_reward: int,
):
    """timestamp is approximate so hash matches across the network"""

    block_message = {
        "block_number": block_number,
        "block_hash": None,
        "parent_hash": parent_hash,
        "block_ip": block_ip,
        "block_creator": creator,
        "block_timestamp": None,
        "block_transactions": transaction_pool,
        "block_penalty": None,
        "block_producers_hash": block_producers_hash,
        "child_hash": None,
        "block_reward": block_reward,
    }
    block_hash = blake2b_hash_link(link_from=parent_hash, link_to=block_message)
    block_message.update(block_hash=block_hash)
    block_message.update(block_timestamp=block_timestamp)

    block_penalty = get_penalty(producer_address=creator,
                                block_hash=block_hash,
                                block_number=block_number)

    block_message.update(block_penalty=block_penalty)
    return block_message


async def knows_block(target_peer, port, hash, logger):
    try:
        http_client = AsyncHTTPClient()
        url = f"http://{target_peer}:{port}/get_block?hash={hash}"
        result = await http_client.fetch(url)

        if result.code == 200:
            return True
        else:
            return False

    except Exception as e:
        logger.error(f"Failed to check block {hash} from {target_peer}: {e}")
        return False


def update_child_in_latest_block(child_hash, logger, parent):
    """the only method to save block except for creation to avoid read/write collision"""
    while True:
        try:
            parent["child_hash"] = child_hash
            save_block(parent, logger=logger)
            return True
        except Exception as e:
            logger.error(f"Failed to update child hash in {parent}: {e}")


async def get_blocks_after(target_peer, from_hash, count=50, compress="msgpack"):
    http_client = AsyncHTTPClient()

    url = f"http://{target_peer}:{get_config()['port']}/get_blocks_after?hash={from_hash}&count={count}&compress={compress}"
    result = await http_client.fetch(url)
    code = result.code

    if code == 200 and compress == "msgpack":
        read = result.body
        return msgpack.unpackb(read)
    elif code == 200:
        text = result.body.decode()
        return json.loads(text)["blocks_after"]
    else:
        return False


async def get_blocks_before(target_peer, from_hash, count=50, compress="true"):
    try:
        http_client = AsyncHTTPClient()

        url = f"http://{target_peer}:{get_config()['port']}/get_blocks_before?hash={from_hash}&count={count}&compress={compress}"
        result = await http_client.fetch(url)
        code = result.code

        if code == 200 and compress == "msgpack":
            read = result.body
            return msgpack.unpackb(read)
        elif code == 200:
            text = result.body.decode()
            return json.loads(text)["blocks_before"]
        else:
            return False

    except Exception as e:
        logger.error(f"Failed to get blocks before {from_hash} from {target_peer}: {e}")
        return False


async def get_from_single_target(key, target_peer, logger):  # todo add msgpack support
    """obtain from a single target"""

    try:
        http_client = AsyncHTTPClient()
        url = f"http://{target_peer}:{get_config()['port']}/{key}"
        result = await http_client.fetch(url)
        text = result.body.decode()
        code = result.code

        if code == 200:
            return json.loads(text)[key]
        else:
            return False

    except Exception as e:
        logger.error(f"Failed to get {key} from {target_peer}: {e}")
        return False


def get_ip_penalty(producer, logger, blocks_backward=50):
    """calculates how many blocks an ip received over a given period"""
    latest_block_info = get_latest_block_info(logger=logger)

    parent = latest_block_info["block_hash"]
    latest_block_number = latest_block_info["block_number"]
    block_number = latest_block_number
    produced_count = 0

    while 0 < block_number > (latest_block_number - blocks_backward):
        block = load_block_from_hash(parent, logger=logger)
        parent = block["parent_hash"]
        block_number = block["block_number"]

        if block["block_ip"] == producer:
            produced_count += 1

    return produced_count


def get_penalty(producer_address, block_hash, block_number):
    hash_penalty = get_hash_penalty(address=producer_address, block_hash=block_hash, block_number=block_number)
    miner_penalty = get_account_value(address=producer_address, key="produced")
    combined_penalty = hash_penalty + miner_penalty
    burn_bonus = get_account_value(producer_address, key="burned")
    block_penalty = combined_penalty - burn_bonus * 100

    if block_penalty < hash_penalty:
        block_penalty = hash_penalty

    return block_penalty


def pick_best_producer(block_producers, logger, event_bus, peer_file_lock, latest_block):
    block_hash = latest_block["block_hash"]

    previous_block_penalty = None
    best_producer = None

    penalty_list = {}
    for producer_ip in block_producers:
        producer_address = load_peer(logger=logger,
                                     ip=producer_ip,
                                     key="peer_address",
                                     peer_file_lock=peer_file_lock)
        if producer_address:
            block_penalty = get_penalty(producer_address=producer_address,
                                        block_hash=block_hash,
                                        block_number=latest_block["block_number"])

            penalty_list.update({producer_address: block_penalty})

            if block_penalty:
                if not previous_block_penalty or block_penalty <= previous_block_penalty:
                    previous_block_penalty = block_penalty
                    best_producer = producer_ip

    event_bus.emit('penalty-list-update', penalty_list)

    return best_producer


if __name__ == "__main__":
    logger = get_logger(file="block_ops.log")
    load_block_producers()
    block_ip = get_config()["ip"]
    address = load_keys()["address"]
    # rollback_one_block()
    no_of_blocks = 1
    for _ in range(0, no_of_blocks):
        latest_block_info = get_latest_block_info(logger=logger)

        block_message = construct_block(
            block_timestamp=get_timestamp_seconds(),
            block_number=latest_block_info["block_number"] + 1,
            parent_hash=latest_block_info["block_hash"],
            block_ip=block_ip,
            creator=address,
            transaction_pool=get_transaction_pool_demo(),
            block_producers_hash=get_block_producers_hash_demo(),
            block_reward=get_block_reward(logger=logger),
        )

        """submit as block candidate"""
        config = get_config()
        ip = config["ip"]
        port = config["port"]
        server_key = config["server_key"]
        requests.get(f"http://{ip}:{port}/submit_block?data={json.dumps(block_message)}&key={server_key}", timeout=5)
