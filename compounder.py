import asyncio
import json
from urllib.parse import quote

import msgpack
import aiohttp
from ops.data_ops import sort_list_dict
from ops.log_ops import get_logger
"""this module is optimized for low memory and bandwidth usage"""


async def get_list_of(key, peer, port, fail_storage, logger, semaphore, compress=None):
    """method compounded by compound_get_list_of, fail storage external by reference (obj)"""
    """bandwith usage of this grows exponentially with number of peers"""
    """peers include themselves in their peer lists"""

    if compress:
        url_construct = f"http://{peer}:{port}/{key}?compress={compress}"
    else:
        url_construct = f"http://{peer}:{port}/{key}"

    try:
        async with semaphore:
            
            async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url_construct) as response:
                    if compress == "msgpack":
                        fetched = msgpack.unpackb(await (response.read()))
                    else:
                        fetched = json.loads(await response.text())[key]
        return fetched

    except Exception as e:
        if peer not in fail_storage:
            logger.error(f"Compounder: Failed to get {key} of {peer} from {url_construct} {e}")
            fail_storage.append(peer)

async def compound_get_list_of(key, entries, port, logger, fail_storage, semaphore, compress=None):
    """returns a list of lists of raw peers from multiple peers at once"""

    result = list(
        filter(
            None,
            await asyncio.gather(
                *[get_list_of(key, entry, port, fail_storage, logger, semaphore, compress) for entry in entries]
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


async def get_url(peer, port, url, logger, fail_storage, semaphore, compress=None):
    """method compounded by compound_get_url"""

    url_construct = f"http://{peer}:{port}/{url}"
    try:
        async with semaphore:
            
            async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url_construct) as response:
                    fetched = await response.text()
                    return peer, fetched

    except Exception as e:
        if peer not in fail_storage:
            logger.error(f"Compounder: Failed to get URL {url_construct} {e}")
            fail_storage.append(peer)

async def compound_get_url(ips, port, url, logger, fail_storage, semaphore, compress=None):
    """returns result of urls with arbitrary data past slash"""
    result = list(
        filter(
            None,
            await asyncio.gather(*[get_url(ip, port, url, logger, fail_storage, semaphore) for ip in ips]),
        )
    )

    result_dict = {}
    for entry in result:
        result_dict[entry[0]] = entry[1]

    return result_dict


async def send_transaction(peer, port, logger, fail_storage, transaction, semaphore, compress=None):
    """method compounded by compound_send_transaction"""

    url_construct = f"http://{peer}:{port}/submit_transaction?data={quote(json.dumps(transaction))}"

    try:
        async with semaphore:
            
            async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url_construct) as response:
                    fetched = json.loads(await response.text())["message"]
                    return peer, fetched

    except Exception as e:
        if peer not in fail_storage:
            logger.error(f"Compounder: Failed to send transaction to {url_construct} {e}")
            fail_storage.append(peer)

async def compound_send_transaction(ips, port, logger, fail_storage, transaction, semaphore, compress=None):
    """returns a list of dicts where ip addresses are keys"""
    result = list(
        filter(
            None,
            await asyncio.gather(
                *[send_transaction(ip, port, logger, fail_storage, transaction, semaphore) for ip in ips]),
        )
    )

    result_dict = {}
    for entry in result:
        result_dict[entry[0]] = entry[1]

    return result_dict


async def get_status(peer, port, logger, fail_storage, semaphore, compress=None):
    """method compounded by compound_get_status_pool"""

    if compress:
        url_construct = f"http://{peer}:{port}/status?compress={compress}"
    else:
        url_construct = f"http://{peer}:{port}/status"

    try:
        async with semaphore:
            
            async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url_construct) as response:
                    if compress == "msgpack":
                        fetched = msgpack.unpackb(await response.read())
                    else:
                        fetched = json.loads(await response.text())

                    return peer, fetched

    except Exception as e:
        if peer not in fail_storage:
            logger.error(f"Compounder: Failed to get status from {url_construct} {e}")
            fail_storage.append(peer)

async def compound_get_status_pool(ips, port, logger, fail_storage, semaphore, compress=None):
    """returns a list of dicts where ip addresses are keys"""
    result = list(
        filter(
            None,
            await asyncio.gather(*[get_status(ip, port, logger, fail_storage, semaphore) for ip in ips]),
        )
    )

    result_dict = {}
    for entry in result:
        result_dict[entry[0]] = entry[1]

    return result_dict


async def announce_self(peer, port, my_ip, logger, fail_storage, semaphore):
    """method compounded by compound_announce_self"""

    url_construct = (
        f"http://{peer}:{port}/announce_peer?ip={my_ip}"
    )

    try:
        async with semaphore:
            
            async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url_construct) as response:
                    fetched = await response.text()
                    return fetched

    except Exception:
        if peer not in fail_storage:
            # logger.info(f"Failed to announce self to {url_construct} {e}")
            fail_storage.append(peer)


async def compound_announce_self(ips, port, my_ip, logger, fail_storage, semaphore):
    result = list(
        filter(
            None,
            await asyncio.gather(
                *[announce_self(ip, port, my_ip, logger, fail_storage, semaphore) for ip in ips]
            ),
        )
    )
    return result


if __name__ == "__main__":
    peers = ["127.0.0.1", "5.189.152.114"]
    logger = get_logger(file="compounder.log", logger_name="compounder_logger")
    fail_storage = []  # needs to be object because it is changed on the go

    logger.info(
        asyncio.run(
            compound_get_list_of(
                "peers", peers, logger=logger, fail_storage=fail_storage, port=9173, semaphore=asyncio.Semaphore(50)
            )
        )
    )
    logger.info(
        asyncio.run(
            compound_get_status_pool(peers, logger=logger, fail_storage=fail_storage, port=9173, semaphore=asyncio.Semaphore(50)
                                     )
        )
    )
    logger.info(
        asyncio.run(
            compound_get_list_of(
                "transaction_pool", peers, logger=logger, fail_storage=fail_storage, port=9173, semaphore=asyncio.Semaphore(50)
            )
        )
    )
