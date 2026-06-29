import json
import math
import os
import time

import msgpack
import requests
from tornado.httpclient import AsyncHTTPClient
import aiohttp
from .account_ops import get_account_value, get_bonded_registry
from config import get_timestamp_seconds, get_config
from .data_ops import set_and_sort, average, get_home, is_hex_hash
from hashing import blake2b_hash_link
from .key_ops import load_keys
from .log_ops import get_logger
from .peer_ops import load_peer
from .sqlite_ops import DbHandler
from .mining_ops import select_producer, epoch_of, compute_beacon
from protocol import CHAIN_ID, REWARD_WINDOW, REWARD_CAP, GENESIS_BEACON, EPOCH_LENGTH


def float_to_int(x):
    return math.floor(x * (2 ** 31))


def get_hash_penalty(address: str, block_hash: str, block_number: int):
    address_mingled = blake2b_hash_link(address, block_hash)
    score = 0
    for letters in enumerate(address_mingled):
        score = score + block_hash.count(letters[1])

    return score


def get_block_reward(parent_block, logger):
    """Fee-weighted elastic block reward, computed as a PURE function of the block's own
    ancestry (NOT the verifier's tip), so a full node and a snapshot/pruned node agree on it
    and neither rejects the other's blocks. Every block header carries `cumulative_fees`, the
    running total of fees burned up to and including that block; the reward for the child of
    `parent_block` is the average fee per block over the last REWARD_WINDOW blocks:

        reward = (cumFee[parent] - cumFee[parent_height - REWARD_WINDOW]) // REWARD_WINDOW

    capped at REWARD_CAP. This is one indexed lookback (get_block_number) instead of the old
    REWARD_WINDOW-deep block-file walk on every call (audit: tip-anchored walk would fork
    snapshot nodes and was a hot-path perf regression; the old fee_over_blocks was also buggy)."""
    end_cumfee = parent_block.get("cumulative_fees", 0)
    lookback_height = parent_block["block_number"] - REWARD_WINDOW
    if lookback_height < 0:
        start_cumfee = 0
    else:
        start_block = get_block_number(lookback_height)
        start_cumfee = start_block.get("cumulative_fees", 0) if start_block else 0

    reward = (end_cumfee - start_cumfee) // REWARD_WINDOW
    if reward < 0:
        reward = 0
    if reward > REWARD_CAP:
        reward = REWARD_CAP
    return reward


def valid_block_timestamp(new_block):
    new_timestamp = new_block["block_timestamp"]
    if new_timestamp > get_timestamp_seconds():
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
        block_producers, block_producers_hash, transaction_pool, logger, event_bus, latest_block, block_time
):
    block_number = latest_block["block_number"] + 1

    # S4.3: select the producer from the BONDED registry + the per-epoch beacon (split-neutral,
    # grind-resistant) instead of the grindable per-IP pick_best_producer. Every node computes the
    # SAME winner deterministically from committed parent state and builds the identical block
    # crediting the winner ADDRESS — the winner need not be online (liveness does not depend on it
    # broadcasting). block_ip is set to the winner address so the hashed body is identical per node.
    registry = get_bonded_registry()
    beacon = epoch_beacon(epoch_of(block_number))
    winner = select_producer(registry, beacon, slot=block_number)
    if winner is None:
        logger.error("No eligible bonded producer (empty registry / total_shares=0); skipping block")
        return None
    logger.info(f"Block {block_number} producer (bonded): {winner} | {len(registry)} eligible")

    targeted_transactions = match_transactions_target(transaction_list=transaction_pool.copy(),
                                                      block_number=block_number,
                                                      logger=logger)

    block = construct_block(
        block_timestamp=latest_block["block_timestamp"] + block_time,
        block_number=block_number,
        parent_hash=latest_block["block_hash"],
        block_ip=winner,
        creator=winner,
        transaction_pool=targeted_transactions,
        block_producers_hash=block_producers_hash,
        block_reward=get_block_reward(parent_block=latest_block, logger=logger),
        parent_cumulative_fees=latest_block.get("cumulative_fees", 0),
    )
    return block


def fee_over_blocks(logger, number_of_blocks=250):
    """returns average fee over last x blocks"""
    last_block = get_block_ends_info(logger=logger)["latest_block"]

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
    """return a block by its hash"""
    # SECURITY: `block` reaches here from the unauthenticated /get_block?hash= arg;
    # validate it is a real block hash so it can't traverse to arbitrary *.block paths
    # (also collapses the missing-vs-malformed responses into one 'not found').
    if not is_hex_hash(block):
        return False
    block_path = f"{get_home()}/blocks/{block}.block"
    if os.path.exists(block_path):
        with open(block_path, "rb") as file:
            block = msgpack.load(file)
        return block
    else:
        return False


def get_block_number(number):
    try:
        block_handler = DbHandler(db_file=f"{get_home()}/index/index.db")
        fetched = block_handler.db_fetch("SELECT block_hash FROM block_index WHERE block_number = ?", (number,))[0][0]
        block_handler.close()
        return get_block(fetched)
    except Exception as e:
        return False


def get_block_hash_by_number(number):
    """block hash for a block number from the block_index, or None (no block-file read)."""
    try:
        h = DbHandler(db_file=f"{get_home()}/index/index.db")
        fetched = h.db_fetch("SELECT block_hash FROM block_index WHERE block_number = ?", (number,))
        h.close()
        return fetched[0][0] if fetched else None
    except Exception:
        return None


def epoch_beacon(epoch):
    """Per-epoch, grind-resistant selection beacon (S4.3).

    Epochs 0-1 use the fixed GENESIS_BEACON (no finalized prior epoch exists yet). For epoch>=2
    the beacon chains GENESIS_BEACON with the hash of the FIRST block of the immediately-preceding
    epoch ((epoch-1)*EPOCH_LENGTH) -- a block that is >= EPOCH_LENGTH blocks behind the first slot
    this beacon governs, so it is deeply finalized and is NOT the grindable parent hash (audit M6).
    The per-slot rotation comes from select_producer hashing [beacon, slot].

    INVARIANT: max_rollbacks < EPOCH_LENGTH, so the anchor block can never be reorged out from
    under a live epoch (otherwise the whole epoch's winners would flip). The full on-chain
    commit-reveal RANDAO (mining_ops.compute_beacon over revealed secrets) is the hardening step."""
    if epoch < 2:
        return GENESIS_BEACON
    anchor = get_block_hash_by_number((epoch - 1) * EPOCH_LENGTH)
    if not anchor:
        return GENESIS_BEACON  # anchor not available locally -> deterministic fallback
    return compute_beacon(GENESIS_BEACON, [anchor])


def block_already_indexed(block_hash):
    """True if this exact block was already incorporated (its hash is in block_index).
    Used to make incorporate_block idempotent against a re-fetched / replayed block."""
    try:
        handler = DbHandler(db_file=f"{get_home()}/index/index.db")
        found = handler.db_fetch("SELECT 1 FROM block_index WHERE block_hash = ? LIMIT 1", (block_hash,))
        handler.close()
        return bool(found)
    except Exception:
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
    # SECURITY: reachable from the unauthenticated /get_blocks_after / /get_blocks_before
    # hash arg; validate so it can't read arbitrary *.block paths off disk.
    if not is_hex_hash(block_hash):
        return False
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
    # SECURITY: a synced block's hash is peer-supplied; refuse to write outside blocks/
    if not is_hex_hash(block.get("block_hash")):
        logger.warning(f"Refusing to save block with invalid hash {block.get('block_hash')!r}")
        return False
    path = f"{get_home()}/blocks/{block['block_hash']}.block"
    tmp_path = f"{path}.tmp"

    # pack once, write to a temp file, fsync, then atomically rename into place. os.replace
    # is atomic so a reader never sees a half-written block. Bounded retries: the old
    # `while True` spun forever on a persistent error (full disk / permissions), silently
    # wedging the caller; after the cap we raise so the node fails loudly and can restart.
    last_error = None
    for _ in range(60):
        try:
            packed = msgpack.packb(block)
            with open(tmp_path, "wb") as outfile:
                outfile.write(packed)
                outfile.flush()
                os.fsync(outfile.fileno())
            os.replace(tmp_path, path)
            return True
        except Exception as e:
            last_error = e
            logger.warning(f"Failed to save block {block['block_hash']} due to {e}")
            time.sleep(0.5)
    raise RuntimeError(f"Could not save block {block['block_hash']} after retries: {last_error}")


def get_block_ends_info(logger):
    try:
        with open(f"{get_home()}/index/block_ends.dat", "r") as ends_file:
            block_ends = json.load(ends_file)

            latest_block = load_block_from_hash(block_hash=block_ends["latest_block"],
                                                logger=logger)
            earliest_block = load_block_from_hash(block_hash=block_ends["earliest_block"],
                                                  logger=logger)

            block_ends = {"earliest_block": earliest_block,
                          "latest_block": latest_block}

            return block_ends

    except Exception as e:
        logger.info(f"Failed to get block ends info: {e}")


def unindex_block(block, logger):
    attempts = 0
    while True:
        try:
            block_handler = DbHandler(db_file=f"{get_home()}/index/index.db")
            block_handler.db_execute(
                "DELETE FROM block_index WHERE block_number = ?", (block['block_number'],))
            block_handler.close()

            block_data = f"{get_home()}/blocks/{block['block_hash']}.block"
            # bounded + backed off: the old inner loop had no sleep and never gave up,
            # so a permission error / open handle spun a CPU at 100% forever.
            for _ in range(10):
                if not os.path.exists(block_data):
                    break
                try:
                    os.remove(block_data)
                    break
                except FileNotFoundError:
                    break
                except Exception as e:
                    logger.error(f"Failed to remove {block_data}: {e}")
                    time.sleep(1)
            break
        except Exception as e:
            attempts += 1
            logger.error(f"Failed to unindex block: {e}")
            if attempts >= 30:
                logger.error("Giving up on unindex_block after repeated failures")
                break
            time.sleep(1)


def _update_block_ends(updates: dict, logger):
    """Atomically merge `updates` into index/block_ends.dat (temp file + fsync + os.replace).

    Replaces the old write-then-read-back-and-compare `while not old_hash == new_hash` spin:
    that inner loop never exited if the read-back didn't match (concurrent writer, fs cache,
    full disk), wedging the single block-processing thread forever. block_ends is written only
    by the core thread (genesis/snapshot/incorporate/rollback), so an atomic replace is safe
    and needs no readback. Bounded retries, then raise rather than hang."""
    path = f"{get_home()}/index/block_ends.dat"
    tmp = f"{path}.tmp"
    last_error = None
    for _ in range(30):
        try:
            current = {}
            if os.path.exists(path):
                with open(path, "r") as infile:
                    current = json.load(infile)
            current.update(updates)
            with open(tmp, "w") as outfile:
                json.dump(current, outfile)
                outfile.flush()
                os.fsync(outfile.fileno())
            os.replace(tmp, path)
            return current
        except Exception as e:
            last_error = e
            logger.info(f"Failed to update block_ends {updates}: {e}")
            time.sleep(0.5)
    raise RuntimeError(f"Could not persist block_ends {updates} after retries: {last_error}")


def set_earliest_block_info(earliest_block: dict, logger):
    _update_block_ends({"earliest_block": earliest_block["block_hash"]}, logger=logger)
    return earliest_block


def set_latest_block_info(latest_block: dict, logger):
    _update_block_ends({"latest_block": latest_block["block_hash"]}, logger=logger)

    blocks_handler = DbHandler(db_file=f"{get_home()}/index/index.db")
    blocks_handler.db_execute("INSERT OR IGNORE INTO block_index VALUES (?, ?)",
                              (latest_block['block_hash'], latest_block['block_number']))
    blocks_handler.close()

    return latest_block


def index_block_number(block):
    """Insert the block's number<->hash row — the 'applied' marker that block_already_indexed
    checks. Called INSIDE the incorporate transaction so the marker commits ATOMICALLY with the
    balance/totals mutations: a crash either applies the whole block or none of it, so a replay
    on restart can never double-credit (audit LO-1/CO-4)."""
    handler = DbHandler(db_file=f"{get_home()}/index/index.db")
    handler.db_execute("INSERT OR IGNORE INTO block_index VALUES (?, ?)",
                       (block["block_hash"], block["block_number"]))
    handler.close()


def construct_block(
        block_timestamp: int,
        block_number: int,
        parent_hash: str,
        creator: str,
        block_ip: str,
        block_producers_hash: str,
        transaction_pool: list,
        block_reward: int,
        parent_cumulative_fees: int = 0,
):
    """timestamp is approximate so hash matches across the network"""

    block_fees = sum(transaction["fee"] for transaction in transaction_pool)

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
        # running fee total committed in the header so the elastic reward is verifiable from
        # headers alone (see get_block_reward); chain_id binds the block to this chain.
        "cumulative_fees": parent_cumulative_fees + block_fees,
        "chain_id": CHAIN_ID,
    }
    block_hash = blake2b_hash_link(link_from=parent_hash, link_to=block_message)
    block_message.update(block_hash=block_hash)
    block_message.update(block_timestamp=block_timestamp)

    # block_penalty is legacy (the burn-to-bribe / produced penalty that drove the old per-IP
    # selection); selection is now bonded, so it is no longer consensus-relevant. Stamp 0. This
    # runs AFTER block_hash is computed, so it does not affect the hash.
    block_message.update(block_penalty=0)
    return block_message


async def knows_block(target_peer, port, hash, logger):
    try:
        url_construct = f"http://{target_peer}:{port}/get_block?hash={hash}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                if response.status == 200:
                    return True
                else:
                    return False

    except Exception as e:
        logger.error(f"Failed to check block {hash} from {target_peer}: {e}")
        return False


def update_child_in_latest_block(child_hash, logger, parent):
    """the only method to save block except for creation to avoid read/write collision"""
    # save_block is now bounded + atomic and raises on persistent failure; the old
    # `while True` here had NO sleep, so any persistent error pinned a CPU at 100% forever.
    parent["child_hash"] = child_hash
    return save_block(parent, logger=logger)


async def get_blocks_after(target_peer, from_hash, logger, count=50, compress="msgpack"):
    try:
        url_construct = f"http://{target_peer}:{get_config()['port']}/get_blocks_after?hash={from_hash}&count={count}&compress={compress}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                code = response.status

                if code == 200 and compress == "msgpack":
                    read = response.read()
                    return msgpack.unpackb(await read)
                elif code == 200:
                    text = response.text()
                    return json.loads(await text)["blocks_after"]
                else:
                    return False

    except Exception as e:
        logger.error(f"Failed to get blocks after {from_hash} from {target_peer}: {e}")


async def get_blocks_before(target_peer, from_hash, count=50, compress="true"):
    try:
        url_construct = f"http://{target_peer}:{get_config()['port']}/get_blocks_before?hash={from_hash}&count={count}&compress={compress}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                code = response.status

                if code == 200 and compress == "msgpack":
                    read = response.read()
                    return msgpack.unpackb(await read)
                elif code == 200:
                    text = response.text()
                    return json.loads(await text)["blocks_before"]
                else:
                    return False

    except Exception as e:
        logger.error(f"Failed to get blocks before {from_hash} from {target_peer}: {e}")
        return False


async def get_from_single_target(key, target_peer, logger) -> list:  # todo add msgpack support
    """obtain from a single target, returns list"""

    try:
        url_construct = f"http://{target_peer}:{get_config()['port']}/{key}"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                text = response.text()
                code = response.status

                if code == 200:
                    return json.loads(await text)[key]
                else:
                    return []

    except Exception as e:
        logger.error(f"Failed to get {key} from {target_peer}: {e}")
        return []


def get_ip_penalty(producer, logger, blocks_backward=50):
    """calculates how many blocks an ip received over a given period"""
    latest_block_info = get_block_ends_info(logger=logger)["latest_block"]

    parent = latest_block_info["block_hash"]
    latest_block_number = latest_block_info["block_number"]
    block_number = latest_block_number
    produced_count = 0

    while 0 < block_number > (latest_block_number - blocks_backward):
        block = load_block_from_hash(parent, logger=logger)
        if not block:
            break  # ran out of local history -> stop here
        parent = block["parent_hash"]
        block_number = block["block_number"]

        if block["block_ip"] == producer:
            produced_count += 1

    return produced_count


def get_penalty(producer_address, block_hash, block_number):
    # Burn-to-bribe removed: penalty = deterministic hash score + the producer's cumulative
    # 'produced' (recent winners back off). NOTE: this legacy IP-based penalty is superseded by
    # the bonded split-neutral select_producer in mining_ops; it remains until the S4.3 wiring.
    hash_penalty = get_hash_penalty(address=producer_address, block_hash=block_hash, block_number=block_number)
    miner_penalty = get_account_value(address=producer_address, key="produced")
    return hash_penalty + miner_penalty


def pick_best_producer(block_producers, logger, event_bus, latest_block):
    block_hash = latest_block["block_hash"]

    previous_block_penalty = None
    best_producer = None

    penalty_list = {}
    for producer_ip in block_producers:
        producer_address = load_peer(logger=logger,
                                     ip=producer_ip,
                                     key="peer_address")
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
    logger = get_logger(file="block_ops.log", logger_name="block_ops_logger")
    load_block_producers()
    block_ip = get_config()["ip"]
    address = load_keys()["address"]
    # rollback_one_block()
    no_of_blocks = 1
    for _ in range(0, no_of_blocks):
        latest_block_info = get_block_ends_info(logger=logger)["latest_block"]

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
