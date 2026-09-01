import asyncio
import json

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
    # SHAPE GUARD (untrusted): a malicious/broken peer can answer /peers with a non-list (int, str,
    # dict) — `extend(<int>)` then raised TypeError and, escaping only at the peer-loop level, aborted
    # the WHOLE peer pass (status refresh + purge + tx-gossip) every second while that peer stayed
    # reachable. Skip any entry that isn't a list; the per-item consumers (check_ip, set()) still see
    # only what a well-formed peer sent.
    success_storage = []
    for entry in result:
        if isinstance(entry, list):
            success_storage.extend(entry)

    return sort_list_dict(success_storage)


async def get_tx_ids_of(peer, port, logger, fail_storage, semaphore):
    """GET /transaction_ids from one peer -> (peer, [txid,...]) or None. A peer that cannot serve
    the reconciliation wire is treated like any other failing peer (fail_storage -> purge queue) —
    NO legacy-wire tolerance on betanet; the whole mesh speaks one protocol version."""
    url_construct = f"http://{hostport(peer, port)}/transaction_ids?compress=zstd"
    try:
        async with semaphore:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url_construct) as response:
                    if response.status != 200:
                        raise ValueError(f"HTTP {response.status}")
                    body = await read_capped(response, MAX_PEER_BODY)
                    fetched = unpack_zstd_peer(body)
                    if not isinstance(fetched, list):
                        raise ValueError("malformed id list")
                    return peer, fetched
    except Exception as e:
        if peer not in fail_storage:
            logger.error(f"Compounder: Failed to get transaction ids of {peer}: {e}")
            fail_storage.append(peer)
        return None


async def get_next_block_txids_of(peer, port, logger, semaphore, timeout=1.5):
    """GET /next_block_txids from one peer -> (peer, {tip, height, txids}) or None. The pre-assembly
    reconcile's probe (memserver.reconcile_next_block_set): what THAT peer would put in the next block on
    ITS tip. Short timeout — this runs inside the production slot — and a failure is silently None (the
    peer simply does not take part in this pass; the pull reconcile remains the backstop)."""
    url_construct = f"http://{hostport(peer, port)}/next_block_txids"
    try:
        async with semaphore:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.get(url_construct) as response:
                    if response.status != 200:
                        return None
                    body = await read_capped(response, MAX_PEER_BODY)
                    d = json.loads(body)
                    if not isinstance(d, dict) or not isinstance(d.get("txids"), list):
                        return None
                    return peer, d
    except Exception:
        return None


async def compound_get_next_block_txids(ips, port, logger, semaphore, timeout=1.5):
    """{peer: {tip, height, txids}} for every peer that answered /next_block_txids in time."""
    results = await asyncio.gather(*[get_next_block_txids_of(ip, port, logger, semaphore, timeout) for ip in ips])
    return {peer: d for peer, d in filter(None, results)}


async def compound_get_tx_ids(ips, port, logger, fail_storage, semaphore):
    """{peer: [txid,...]} for every peer that answered /transaction_ids — the cheap half of mempool
    set reconciliation (ids are ~64B vs ~7KB per full ML-DSA tx)."""
    results = await asyncio.gather(*[get_tx_ids_of(ip, port, logger, fail_storage, semaphore) for ip in ips])
    return {peer: ids for peer, ids in filter(None, results)}


async def post_txs_by_id(peer, port, txids, logger, fail_storage, semaphore):
    """POST /transactions_by_id: fetch ONLY the named txs from a peer's pool (the expensive half of
    set reconciliation, now proportional to what we're actually missing). Returns a list ([] on
    any failure)."""
    from ops import codec
    url_construct = f"http://{hostport(peer, port)}/transactions_by_id?compress=zstd"
    try:
        async with semaphore:
            # 15 s was sized for ~KB txs. Set reconciliation is the FALLBACK that is supposed to deliver a
            # tx when push-gossip fails, so it must be able to carry the biggest legitimate tx there is: an
            # inline settle proof at ~120 MiB. With both paths timing out, a proof-carrying settle could
            # reach a peer by neither route. read_capped already bounds the body at MAX_PEER_BODY.
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
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
    """PUSH one transaction to a peer's POST /submit_transaction, body = codec.pack(tx) — the exact
    wire net_ops.unpack_tx decodes. (The old GET `?data=<json>` form never matched the POST-body
    endpoint and silently failed.) Returns (peer, message) on success, None on failure. Shared by
    push-gossip (nado._gossip_worker) and the wallet CLI (compound_send_transaction)."""
    from ops import codec
    url_construct = f"http://{hostport(peer, port)}/submit_transaction"
    _body = codec.pack(transaction)
    # TIMEOUT MUST SCALE WITH THE BODY. This was a flat total=5 s, which is fine for the ~KB txs that make
    # up all normal traffic but makes a proof-carrying settle IMPOSSIBLE to gossip: an inline settle proof
    # is ~120 MiB, so 5 s would demand ~24 MB/s sustained AND a verdict inside the same window — and the
    # peer VERIFIES the proof before it answers (measured ~22-94 s). Every push therefore timed out, the tx
    # stayed in our pool alone, and since every node deterministically builds the winner's candidate, a
    # peer's candidate (without our tx) won every time. That is the same "peers never hold it" symptom that
    # DA was blamed for; the transport was only ever half the story.
    # Allow ~2 MB/s plus a fixed verification allowance, floored at the old 5 s so ordinary traffic is
    # unchanged. Best-effort either way: a failed push just means the peer pulls it later.
    _timeout = max(5.0, len(_body) / (2 << 20) + 180.0)
    try:
        async with semaphore:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=_timeout)) as session:
                async with session.post(url_construct, data=_body) as response:
                    body = await response.json(content_type=None)
                    return peer, (body.get("message") if isinstance(body, dict) else body)
    except Exception as e:
        if peer not in fail_storage:
            logger.error(f"Compounder: Failed to send transaction to {url_construct}: {e}")
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
