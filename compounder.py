import asyncio
import json
from urllib.parse import quote

import aiohttp
from ops.data_ops import sort_list_dict
from ops.log_ops import get_logger
from ops.net_ops import read_capped, unpack_zstd_peer, MAX_PEER_BODY
from config import hostport
"""this module is optimized for low memory and bandwidth usage"""


async def get_list_of(key, peer, port, fail_storage, logger, semaphore, compress=None):
    """method compounded by compound_get_list_of, fail storage external by reference (obj)"""
    """bandwith usage of this grows exponentially with number of peers"""
    """peers include themselves in their peer lists"""

    if compress:
        url_construct = f"http://{hostport(peer, port)}/{key}?compress={compress}"
    else:
        url_construct = f"http://{hostport(peer, port)}/{key}"

    try:
        async with semaphore:
            
            async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url_construct) as response:
                    body = await read_capped(response, MAX_PEER_BODY)   # anti-OOM: cap untrusted peer body
                    if compress == "zstd":
                        fetched = unpack_zstd_peer(body)                # bomb-capped zstd(msgpack) wire
                    else:
                        fetched = json.loads(body.decode())[key]
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

    # flatten all peers' lists; dedup belongs to sort_list_dict (the old `if entry not in
    # success_storage` compared a per-peer LIST against a flat list of ITEMS — always true, a no-op).
    success_storage = []
    for entry in result:
        success_storage.extend(entry)

    return sort_list_dict(success_storage)


async def get_tx_ids_of(peer, port, logger, semaphore):
    """GET /transaction_ids from one peer -> (peer, [txid,...]) or None. SILENT on failure (no
    fail_storage): an id-less response just skips reconciliation this pass — a peer on the old wire
    (no /transaction_ids yet) must not get purged for it; dead peers are caught by the status poll."""
    url_construct = f"http://{hostport(peer, port)}/transaction_ids?compress=zstd"
    try:
        async with semaphore:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url_construct) as response:
                    if response.status != 200:
                        return None
                    body = await read_capped(response, MAX_PEER_BODY)
                    fetched = unpack_zstd_peer(body)
                    return (peer, fetched) if isinstance(fetched, list) else None
    except Exception:
        return None


async def compound_get_tx_ids(ips, port, logger, semaphore):
    """{peer: [txid,...]} for every peer that answered /transaction_ids — the cheap half of mempool
    set reconciliation (ids are ~64B vs ~7KB per full ML-DSA tx)."""
    results = await asyncio.gather(*[get_tx_ids_of(ip, port, logger, semaphore) for ip in ips])
    return {peer: ids for peer, ids in filter(None, results)}


async def post_txs_by_id(peer, port, txids, logger, fail_storage, semaphore):
    """POST /transactions_by_id: fetch ONLY the named txs from a peer's pool (the expensive half of
    set reconciliation, now proportional to what we're actually missing). Returns a list ([] on
    any failure)."""
    from ops import codec
    url_construct = f"http://{hostport(peer, port)}/transactions_by_id?compress=zstd"
    try:
        async with semaphore:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.post(url_construct, data=codec.pack(list(txids))) as response:
                    if response.status != 200:
                        return []
                    body = await read_capped(response, MAX_PEER_BODY)
                    fetched = unpack_zstd_peer(body)
                    return fetched if isinstance(fetched, list) else []
    except Exception as e:
        if peer not in fail_storage:
            logger.error(f"Compounder: Failed to fetch txs by id from {peer}: {e}")
            fail_storage.append(peer)
        return []


async def send_transaction(peer, port, logger, fail_storage, transaction, semaphore):
    """method compounded by compound_send_transaction"""

    url_construct = f"http://{hostport(peer, port)}/submit_transaction?data={quote(json.dumps(transaction))}"

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

async def compound_send_transaction(ips, port, logger, fail_storage, transaction, semaphore):
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
        url_construct = f"http://{hostport(peer, port)}/status?compress={compress}"
    else:
        url_construct = f"http://{hostport(peer, port)}/status"

    try:
        async with semaphore:
            
            async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url_construct) as response:
                    body = await read_capped(response, MAX_PEER_BODY)   # anti-OOM: cap untrusted peer body
                    if compress == "zstd":
                        fetched = unpack_zstd_peer(body)                # bomb-capped zstd(msgpack) wire
                    else:
                        fetched = json.loads(body.decode())

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
            await asyncio.gather(*[get_status(ip, port, logger, fail_storage, semaphore, compress) for ip in ips]),
        )
    )

    result_dict = {}
    for entry in result:
        result_dict[entry[0]] = entry[1]

    return result_dict


async def announce_self(peer, port, my_ip, fail_storage, semaphore):
    """method compounded by compound_announce_self"""

    url_construct = (
        f"http://{hostport(peer, port)}/announce_peer?ip={my_ip}"
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
    """announces own ip to multiple peers at once, returns raw responses of peers that answered"""
    result = list(
        filter(
            None,
            await asyncio.gather(
                *[announce_self(ip, port, my_ip, fail_storage, semaphore) for ip in ips]
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
