import asyncio
import glob
import json
import os.path

import aiohttp
import requests

from address import validate_address
from compounder import compound_get_list_of, compound_announce_self
from config import get_port, get_config, get_timestamp_seconds
from data_ops import set_and_sort
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
                            peer_file_lock=peer_file_lock)
    new_address = load_keys()["address"]
    if new_address != old_address:
        update_peer(ip=my_ip,
                    logger=logger,
                    peer_file_lock=peer_file_lock,
                    key="peer_address",
                    value=new_address)
        logger.info(f"Local address updated to {new_address}")

def get_remote_peer_address(target_peer, logger) -> bool:
    try:
        url = f"http://{target_peer}:{get_port()}/status"
        result = requests.get(url=url, timeout=5)
        text = result.text
        code = result.status_code

        if code == 200:
            return json.loads(text)["address"]
        else:
            return False

    except Exception as e:
        logger.error(f"Failed to get wallet address from {target_peer}: {e}")
        return False


def get_reported_uptime(target_peer, logger) -> int:
    try:
        url = f"http://{target_peer}:{get_port()}/status"
        result = requests.get(url=url, timeout=5)

        text = result.text
        code = result.status_code

        if code == 200:
            return json.loads(text)["reported_uptime"]
        else:
            return False
    except Exception as e:
        logger.error(f"Failed to get reported uptime from {target_peer}: {e}")
        return False


async def get_remote_peer_address_async(ip) -> str:
    """fetch address of a raw peer to save it"""
    url = f"http://{ip}:{get_port()}/status"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            html = await response.text()
            address = json.loads(html)["peer_address"]
            assert validate_address(address)
            return address


"""
def delete_old_peers(older_than, logger):
    peer_files = glob.glob("peers/*.dat")
    deleted = []
    
    for file in peer_files:
        with open(file, "r") as peer_file:
            peer = json.load(peer_file)
            last_seen = peer["last_seen"]
            peer_ip = peer["peer_ip"]

        if last_seen < older_than:
            delete_peer(peer_ip, logger=logger)
            deleted.append(file)
    return deleted
"""


def delete_peer(ip, logger):
    peer_path = f"peers/{base64encode(ip)}.dat"
    if os.path.exists(peer_path):
        os.remove(peer_path)
        logger.warning(f"Deleted peer {ip}")


def save_peer(ip, port, address, peer_trust=50, overwrite=False):
    peer_path = f"peers/{base64encode(ip)}.dat"
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
    peer_path = f"peers/{base64encode(ip)}.dat"
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

def is_online(peer_ip):
    url = f"http://{peer_ip}:{get_config()['port']}/status"
    try:
        requests.get(url, timeout=5)
        return True
    except Exception as e:
        return False


def load_ips(limit=8) -> list:
    """load ips from drive"""

    peer_files = glob.glob("peers/*.dat")
    if len(peer_files) < limit:
        limit = len(peer_files)

    ip_pool = []

    for file in peer_files:
        if len(ip_pool) < limit:
            with open(file, "r") as peer_file:
                peer = json.load(peer_file)
                if is_online(peer["peer_ip"]):
                    ip_pool.append(peer["peer_ip"])
        else:
            break

    return ip_pool


def load_trust(peer, logger, peer_file_lock):
    return load_peer(ip=peer,
                     key="peer_trust",
                     logger=logger,
                     peer_file_lock=peer_file_lock)


def load_peer(logger, ip, peer_file_lock, key=None) -> str:
    with peer_file_lock:
        try:
            peer_file = f"peers/{base64encode(ip)}.dat"
            if not key:
                with open(peer_file, "r") as peer_file:
                    peer_key = json.load(peer_file)
                return peer_key
            else:
                with open(peer_file, "r") as peer_file:
                    peer_key = json.load(peer_file)[key]
                return peer_key
        except Exception as e:
            logger.info(f"Failed to load peer {ip} from drive: {e}")


def update_peer(ip, value, logger, peer_file_lock, key="peer_trust") -> None:
    with peer_file_lock:
        try:
            peer_file = f"peers/{base64encode(ip)}.dat"

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
    path = f"index/producer_sets/{producer_set_hash}.dat"
    producer_set_dict = {
        "producer_set_hash": producer_set_hash,
        "producer_set": producer_set,
    }
    if not os.path.exists(path):
        with open(path, "w") as outfile:
            json.dump(list(producer_set_dict), outfile)


def get_producer_set(producer_set_hash):
    path = f"index/producer_sets/{producer_set_hash}.dat"
    if os.path.exists(path):
        with open(path) as infile:
            fetched = json.load(infile)
        return fetched
    else:
        return None


def dump_peers(peers, logger):
    """save all peers to drive if new to drive"""
    for peer in peers:
        if not ip_stored(peer):
            address = get_remote_peer_address(peer, logger=logger)
            if address:
                save_peer(
                    ip=peer,
                    port=get_port(),
                    address=address,
                )


def get_list_of_peers(fetch_from, failed, logger) -> list:
    """gets peers of peers"""
    returned_peers = asyncio.run(
        compound_get_list_of("peers", fetch_from, logger=logger, fail_storage=failed, compress="msgpack")
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


def announce_me(targets, logger, fail_storage) -> None:
    """announce self node to other peers"""
    asyncio.run(compound_announce_self(targets, logger, fail_storage=fail_storage))


if __name__ == "__main__":
    print(load_ips())
    # save_peer(ip="1.1.1.1", port=0, address="haha")
    # delete_peers(["1.1.1.1"])
    # save_peer(ip="1.1.2", port=0, address="haha2")
    # save_peer(ip="127.0.0.1", port=9173, address="sop3a7f8a5af60b15460181d9b2ff76ad5f5cfc7c5766ab77")
    # print(asyncio.run(get_remote_peer_address_async('89.176.130.244')))
    # update_peer("89.176.130.244",value=0,key="greeting")
