import ipaddress
import asyncio
import glob
import json
import os
import os.path

from tornado.httpclient import AsyncHTTPClient

from compounder import compound_get_list_of, compound_announce_self
from compounder import compound_get_status_pool
from config import get_port, get_config, get_timestamp_seconds, update_config
from data_ops import set_and_sort, get_home
from hashing import base64encode, blake2b_hash
from keys import load_keys


def validate_dict_structure(dictionary: dict, requirements: list) -> bool:
    if not all(key in requirements for key in dictionary):
        return False
    else:
        return True


def update_local_address(logger, peer_file_lock):
    my_ip = get_config()["ip"]
    old_address = load_peer(logger=logger,
                            ip=my_ip,
                            peer_file_lock=peer_file_lock,
                            key="peer_address")

    new_address = load_keys()["address"]

    if new_address != old_address:
        update_peer(ip=my_ip,
                    logger=logger,
                    peer_file_lock=peer_file_lock,
                    key="peer_address",
                    value=new_address)
        logger.info(f"Local address updated to {new_address}")


async def get_remote_status(target_peer, logger) -> [dict, bool]:  # todo add msgpack support
    try:
        http_client = AsyncHTTPClient()
        url = f"http://{target_peer}:{get_port()}/status"
        result = await http_client.fetch(url)
        text = result.body.decode()
        code = result.code

        if code == 200:
            return json.loads(text)
        else:
            return False

    except Exception as e:
        logger.error(f"Failed to get status from {target_peer}: {e}")
        return False


def delete_peer(ip, logger):
    peer_path = f"{get_home()}/peers/{base64encode(ip)}.dat"
    if os.path.exists(peer_path):
        os.remove(peer_path)
        logger.warning(f"Deleted peer {ip}")


def save_peer(ip, port, address, peer_trust=50, overwrite=False):
    peer_path = f"{get_home()}/peers/{base64encode(ip)}.dat"
    if overwrite or not ip_stored(ip):
        peers_message = {
            "peer_address": address,
            "peer_ip": ip,
            "peer_port": port,
            "peer_trust": peer_trust,
        }

        with open(peer_path, "w") as outfile:
            json.dump(peers_message, outfile)


def ip_stored(ip) -> bool:
    peer_path = f"{get_home()}/peers/{base64encode(ip)}.dat"
    if os.path.exists(peer_path):
        return True
    else:
        return False


def dump_trust(pool_data, logger, peer_file_lock):
    for key, value in pool_data.items():
        update_peer(ip=key,
                    key="trust",
                    value=value,
                    logger=logger,
                    peer_file_lock=peer_file_lock)


def sort_dict_value(values, key):
    return sorted(values, key=lambda d: d[key], reverse=True)


async def load_ips(logger, port, fail_storage, minimum=3) -> list:
    """load peers from drive, sort by trust, test in batches asynchronously,
    return when limit is reached"""

    peer_files = glob.glob(f"{get_home()}/peers/*.dat")

    if len(peer_files) < minimum:
        minimum = len(peer_files)

    candidates = []
    status_pool = []

    for file in peer_files:
        with open(file, "r") as peer_file:
            peer = json.load(peer_file)
            candidates.append(peer)

    ip_sorted = []
    candidates_sorted = sort_dict_value(candidates, key="peer_trust")

    for entry in candidates_sorted:
        ip = entry["peer_ip"]
        ip_sorted.append(ip)

    start = 0
    end = len(peer_files)
    step = 12

    for i in range(start, end, step):
        x = i
        chunk = ip_sorted[x:x + step]
        logger.info(f"Testing {chunk}")

        gathered = (await asyncio.gather(compound_get_status_pool(ips=chunk,
                                                                  port=port,
                                                                  fail_storage=fail_storage,
                                                                  logger=logger,
                                                                  compress="msgpack")))
        for entry in gathered:
            status_pool.extend(list(entry.keys()))

        logger.info(f"Gathered {len(status_pool)}/{minimum} peers in {i + 1} steps, {len(fail_storage)} failed")

        if len(status_pool) > minimum:
            break

    logger.info(f"Loaded {len(status_pool)} reachable peers from drive, {len(fail_storage)} failed")

    return status_pool


def load_trust(peer, logger, peer_file_lock):
    return load_peer(ip=peer,
                     key="peer_trust",
                     logger=logger,
                     peer_file_lock=peer_file_lock)


def load_peer(logger, ip, peer_file_lock, key=None) -> [str, dict]:
    with peer_file_lock:
        try:
            peer_file = f"{get_home()}/peers/{base64encode(ip)}.dat"
            if not key:
                with open(peer_file, "r") as peer_file:
                    peer_dict = json.load(peer_file)
                return peer_dict
            else:
                with open(peer_file, "r") as peer_file:
                    peer_key = json.load(peer_file)[key]
                return peer_key
        except Exception as e:
            logger.info(f"Failed to load peer {ip} from drive: {e}")


def update_peer(ip, value, logger, peer_file_lock, key="peer_trust") -> None:
    with peer_file_lock:
        try:
            peer_file = f"{get_home()}/peers/{base64encode(ip)}.dat"

            with open(peer_file, "r") as infile:
                peer = json.load(infile)
                addition = {key: value}
                peer.update(addition)
                peer["last_seen"] = get_timestamp_seconds()

            with open(peer_file, "w") as outfile:
                json.dump(peer, outfile)
        except Exception as e:
            logger.info(f"Failed to update peer file of {ip}: {e}")


def store_producer_set(producer_set):
    producer_set_hash = blake2b_hash(producer_set)
    path = f"{get_home()}/index/producer_sets/{producer_set_hash}.dat"
    producer_set_dict = {
        "producer_set_hash": producer_set_hash,
        "producer_set": producer_set,
    }
    if not os.path.exists(path):
        with open(path, "w") as outfile:
            json.dump(producer_set_dict, outfile)


def get_producer_set(producer_set_hash):
    path = f"{get_home()}/index/producer_sets/{producer_set_hash}.dat"
    if os.path.exists(path):
        with open(path) as infile:
            fetched = json.load(infile)
        return fetched
    else:
        return None


def dump_peers(peers, logger):
    """save all peers to drive if new to drive"""
    for peer in peers:
        if not ip_stored(peer) and check_ip(peer):
            try:
                status = asyncio.run(get_remote_status(peer, logger=logger))
                address = status["address"]

                save_peer(
                    ip=peer,
                    port=get_port(),
                    address=address,
                )

            except Exception as e:
                logger.error(f"Unable to reach {peer} to get their address: {e}")


def get_list_of_peers(fetch_from, port, failed, logger) -> list:
    """gets peers of peers"""
    returned_peers = asyncio.run(
        compound_get_list_of(key="peers",
                             entries=fetch_from,
                             port=port,
                             logger=logger,
                             fail_storage=failed,
                             compress="msgpack")
    )

    pool = []
    for peer in returned_peers:
        pool.append(peer)
    return pool


def most_trusted_peer(trust_pool: dict):
    return max(trust_pool, key=trust_pool.get)


def percentage(value, list) -> float:
    if value and list:
        part = list.count(value)
        whole = len(list)
        return 100 * float(part) / float(whole)
    else:
        return 0


def get_majority(in_what) -> [str, None]:
    if None not in in_what.values():
        return max(
            list(sorted(in_what.values())),
            key=list(in_what.values()).count,
        )
    else:
        return None


def get_average_int(list_of_values):
    if list_of_values:
        return int(sum(list_of_values) / len(list_of_values))
    else:
        return None


def me_to(target) -> list:
    """useful in 1 peer network where self can't be reached after kicked from peer list"""
    public_ip = get_config()["ip"]
    if public_ip not in target:
        target.append(public_ip)
        target = set_and_sort(target)
    return target


def announce_me(targets, port, my_ip, logger, fail_storage) -> None:
    """announce self node to other peers"""
    asyncio.run(compound_announce_self(ips=targets,
                                       port=port,
                                       my_ip=my_ip,
                                       logger=logger,
                                       fail_storage=fail_storage))


def check_ip(ip):
    try:
        ipaddress.IPv4Address(ip)
    except:
        return False
    if ip == get_config()["ip"] or ipaddress.ip_address(ip).is_loopback or ip == "0.0.0.0":
        return False
    else:
        return True


async def get_public_ip(logger):
    http_client = AsyncHTTPClient()
    urls = ["https://api.ipify.org", "https://ipinfo.io/ip"]
    for url in urls:
        try:
            ip = await http_client.fetch(url)
            return ip.body.decode()
        except Exception as e:
            logger.error(f"Unable to fetch IP from {url}: {e}")


def update_local_ip(ip, logger, peer_file_lock):
    old_ip = get_config()["ip"]
    new_ip = ip

    if old_ip != new_ip:
        peer_me = load_peer(ip=old_ip,
                            logger=logger,
                            peer_file_lock=peer_file_lock)

        save_peer(ip=new_ip,
                  address=peer_me["peer_address"],
                  port=peer_me["peer_port"],
                  overwrite=True
                  )

        new_config = {"ip": new_ip}
        update_config(new_config)

        logger.info(f"Local IP updated to {new_ip}")


if __name__ == "__main__":
    print(load_ips())
    # save_peer(ip="1.1.1.1", port=0, address="haha")
    # delete_peers(["1.1.1.1"])
    # save_peer(ip="1.1.2", port=0, address="haha2")
    # save_peer(ip="127.0.0.1", port=9173, address="sop3a7f8a5af60b15460181d9b2ff76ad5f5cfc7c5766ab77")
    # print(asyncio.run(get_remote_peer_address_async('89.176.130.244')))
    # update_peer("89.176.130.244",value=0,key="greeting")
