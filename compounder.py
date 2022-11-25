import asyncio
import json
import time

import aiohttp
import msgpack

from config import get_config
from data_ops import sort_list_dict
from log_ops import get_logger

"""this module is optimized for low memory and bandwidth usage"""


async def get_list_of(key, peer, fail_storage, logger, compress=None):
    """method compounded by compound_get_list_of, fail storage external by reference (obj)"""
    """bandwith usage of this grows exponentially with number of peers"""
    """peers include themselves in their peer lists"""

    if compress:
        url_construct = f"http://{peer}:{get_config()['port']}/{key}?compress={compress}"
    else:
        url_construct = f"http://{peer}:{get_config()['port']}/{key}"

    try:
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url_construct) as response:
                if compress == "msgpack":
                    fetched = msgpack.unpackb(await response.read())
                else:
                    fetched = json.loads(await response.text())[key]
                return fetched

    except Exception:
        if peer not in fail_storage:
            logger.info(f"Compounder: Failed to get {key} of {peer} from {url_construct}")
            fail_storage.append(peer)


async def compound_get_list_of(key, entries, logger, fail_storage, compress=None):
    """returns a list of lists of raw peers from multiple peers at once"""

    result = list(
        filter(
            None,
            await asyncio.gather(
                *[get_list_of(key, entry, fail_storage, logger, compress) for entry in entries]
            ),
        )
    )

    success_storage = []
    for entry in result:
        if entry not in success_storage:
            success_storage.extend(entry)

    if isinstance(success_storage, list):
        success_storage = sort_list_dict(success_storage)

    return success_storage


async def get_status(peer, logger, fail_storage, compress=None):
    """method compounded by compound_get_status_pool"""

    if compress:
        url_construct = f"http://{peer}:{get_config()['port']}/status?compress={compress}"
    else:
        url_construct = f"http://{peer}:{get_config()['port']}/status"
    try:
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url_construct) as response:

                if compress == "msgpack":
                    fetched = msgpack.unpackb(await response.read())
                else:
                    fetched = json.loads(await response.text())

                return peer, fetched

    except Exception:
        if peer not in fail_storage:
            logger.info(f"Compounder: Failed to get status from {url_construct}")
            fail_storage.append(peer)

async def compound_get_status_pool(ips, logger, fail_storage, compress=None):
    """returns a list of dicts where ip addresses are keys"""
    result = list(
        filter(
            None,
            await asyncio.gather(*[get_status(ip, logger, fail_storage) for ip in ips]),
        )
    )

    result_dict = {}
    for entry in result:
        result_dict[entry[0]] = entry[1]

    return result_dict


async def announce_self(peer, logger, fail_storage):
    """method compounded by compound_announce_self"""
    url_construct = (
        f"http://{peer}:{get_config()['port']}/announce_peer?ip={get_config()['ip']}"
    )

    try:
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url_construct) as response:
                fetched = await response.text()
                return fetched

    except Exception:
        if peer not in fail_storage:
            logger.info(f"Failed to announce self to {url_construct}")
            fail_storage.append(peer)


async def compound_announce_self(ips, logger, fail_storage):
    result = list(
        filter(
            None,
            await asyncio.gather(
                *[announce_self(ip, logger, fail_storage) for ip in ips]
            ),
        )
    )
    return result


if __name__ == "__main__":
    peers = ["127.0.0.1", "5.189.152.114"]
    logger = get_logger(file="compounder.log")
    fail_storage = []  # needs to be object because it is changed on the go

    logger.info(
        asyncio.run(
            compound_get_list_of(
                "peers", peers, logger=logger, fail_storage=fail_storage
            )
        )
    )
    logger.info(
        asyncio.run(
            compound_get_status_pool(peers, logger=logger, fail_storage=fail_storage)
        )
    )
    logger.info(
        asyncio.run(
            compound_get_list_of(
                "transaction_pool", peers, logger=logger, fail_storage=fail_storage
            )
        )
    )
