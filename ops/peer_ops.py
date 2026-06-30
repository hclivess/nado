import random
import asyncio
import glob
import ipaddress
import json
import os
import os.path
import statistics
from tornado.httpclient import AsyncHTTPClient

from compounder import compound_get_list_of, compound_announce_self
from compounder import compound_get_status_pool
from config import get_port, get_config, get_timestamp_seconds, update_config
from .data_ops import set_and_sort, get_home
from hashing import base64encode
from .key_ops import load_keys

import aiohttp

def _atomic_write_json(path, obj):
    """write JSON via temp file + fsync + os.replace so a crash mid-write can never leave a
    half-written (corrupt) peer file that load_peer would then silently fail to parse."""
    tmp = f"{path}.tmp"
    with open(tmp, "w") as outfile:
        json.dump(obj, outfile)
        outfile.flush()
        os.fsync(outfile.fileno())
    os.replace(tmp, path)


def validate_dict_structure(dictionary: dict, requirements: list) -> bool:
    if not all(key in requirements for key in dictionary):
        return False
    else:
        return True


def update_local_address(logger):
    my_ip = get_config()["ip"]
    old_address = load_peer(logger=logger,
                            ip=my_ip,
                            key="peer_address")

    new_address = load_keys()["address"]

    if new_address != old_address:
        update_peer(ip=my_ip,
                    logger=logger,
                    key="peer_address",
                    value=new_address)
        logger.info(f"Local address updated to {new_address}")


async def get_remote_status(target_peer, logger) -> [dict, bool]:  # todo add msgpack support

    try:
        url_construct = f"http://{target_peer}:{get_port()}/status"

        
        async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                text = response.text()
                code = response.status

                if code == 200:
                    return json.loads(await text)
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

        _atomic_write_json(peer_path, peers_message)


def ip_stored(ip) -> bool:
    peer_path = f"{get_home()}/peers/{base64encode(ip)}.dat"
    if os.path.exists(peer_path):
        return True
    else:
        return False


def dump_trust(pool_data, logger):
    for key, value in pool_data.items():
        update_peer(ip=key,
                    key="peer_trust",
                    value=value,
                    logger=logger)


def sort_dict_value(values: list, key: str) -> list:
    if values:
        return sorted(values, key=lambda d: d[key], reverse=True)
    else:
        return []


async def load_ips(logger, port, fail_storage, unreachable, minimum=3, top_50=True) -> list:
    """load peers from drive, sort by trust, test in batches asynchronously,
    return when limit is reached"""

    bad_peers = set(fail_storage + list(unreachable.keys()))
    peer_files= glob.glob(f"{get_home()}/peers/*.dat")

    if len(peer_files) < minimum:
        minimum = len(peer_files)

    candidates = []
    status_pool = []

    for file in peer_files:
        try:
            with open(file, "r") as peer_file:
                    peer = json.load(peer_file)
                    if peer["peer_ip"] not in bad_peers:
                        candidates.append(peer)
        except Exception as e:
            logger.info(f"Failed to load {peer}: {e}")

    ip_sorted = []

    candidates_sorted = sort_dict_value(candidates, key="peer_trust")
    if top_50:
        candidates_sorted = sort_dict_value(candidates, key="peer_trust")[:50]


    for entry in candidates_sorted:
        ip = entry["peer_ip"]
        # AUDIT FIX: apply the per-/16 eclipse cap on the disk-reload path too (not just the live-sniff
        # paths), so an attacker who seeds many same-subnet peer files can't dominate a node's peer set
        # when it dips below min_peers and reloads from disk.
        if subnet_diversity_ok(ip, ip_sorted):
            ip_sorted.append(ip)

    start = 0
    end = len(candidates_sorted)
    step = 10

    for i in range(start, end, step):
        x = i
        chunk = ip_sorted[x:x + step]
        logger.info(f"Testing {chunk}")

        gathered = (await asyncio.gather(compound_get_status_pool(ips=chunk,
                                                                  port=port,
                                                                  fail_storage=fail_storage,
                                                                  logger=logger,
                                                                  compress="msgpack",
                                                                  semaphore=asyncio.Semaphore(50))))
        for entry in gathered:
            status_pool.extend(list(entry.keys()))

        logger.info(f"Gathered {len(status_pool)}/{minimum} peers in {i + 1} steps, {len(fail_storage)} failed")

        if len(status_pool) >= minimum:
            break

    logger.info(f"Loaded {len(status_pool)} reachable peers from drive, {len(fail_storage)} failed")

    return status_pool


def load_trust(peer, logger):
    return load_peer(ip=peer,
                     key="peer_trust",
                     logger=logger)


def load_peer(logger, ip, key=None) -> [str, dict]:
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


def update_peer(ip, value, logger, key="peer_trust") -> None:
        try:
            peer_file = f"{get_home()}/peers/{base64encode(ip)}.dat"

            with open(peer_file, "r") as infile:
                peer = json.load(infile)
                addition = {key: value}
                peer.update(addition)
                peer["last_seen"] = get_timestamp_seconds()

            _atomic_write_json(peer_file, peer)
        except Exception as e:
            logger.info(f"Failed to update peer file of {ip}: {e}")


def check_save_peers(peers, logger, fails, unreachable):
    """save all peers to drive if new to drive"""
    good_peers = set(peers) - set(fails) - set(unreachable)

    local_fails = []
    candidates = asyncio.run(compound_get_status_pool(
        ips=good_peers,
        port=get_port(),
        fail_storage=local_fails,
        logger=logger,
        semaphore=asyncio.Semaphore(50)))

    for key, value in candidates.items():
        if not ip_stored(key) and check_ip(key):
            save_peer(
                ip=key,
                port=get_port(),
                address=value["address"],
            )

    if local_fails:
        logger.error(f"Unable to reach peers to get their addresses: {local_fails}")

        for entry in local_fails:
            if entry not in fails:
                fails.append(entry)


    return {"success": candidates.keys(),
            "fails": fails}


def get_list_of_peers(ips, port, fail_storage, logger) -> list:
    """gets peers of peers"""
    returned_peers = asyncio.run(
        compound_get_list_of(key="peers",
                             entries=ips,
                             port=port,
                             logger=logger,
                             fail_storage=fail_storage,
                             compress="msgpack",
                             semaphore=asyncio.Semaphore(50))
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

def get_median_int(list_of_values):
    if list_of_values:
        return int(statistics.median(list_of_values))
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
                                       fail_storage=fail_storage,
                                       semaphore=asyncio.Semaphore(50)))


def check_ip(ip):
    try:
        addr = ipaddress.IPv4Address(ip)
    except:
        return False
    # reject our own IP and any non-globally-routable address (loopback, RFC1918
    # private, link-local, reserved, multicast, unspecified): accepting these lets a
    # peer seed us with internal targets (eclipse groundwork / limited SSRF probing).
    if ip == get_config()["ip"]:
        return False
    # NADO_TESTNET: allow loopback/private peers so a local multi-node testnet can mesh over
    # 127.0.0.x. NEVER set this on mainnet — it disables the SSRF/eclipse IP guard below.
    if os.environ.get("NADO_TESTNET"):
        return True
    if (addr.is_loopback or addr.is_private or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
        return False
    return True


# ECLIPSE HARDENING (#18 step 8): cap how many peers from the SAME /16 may occupy the live peer
# slots, so a single network/operator can't fill a victim's peer view (eclipse). With peer_limit=24
# and a cap of 4, an attacker needs >= 6 distinct /16s to monopolize the slots — far costlier than
# spinning up many IPs inside one subnet. Pairs with the /announce_peer rate-limit. Testnet
# (127.0.0.x) is exempt so a local multi-node mesh can still form.
MAX_PEERS_PER_SUBNET = 4


def subnet16(ip: str):
    """The /16 network prefix 'a.b' of an IPv4 dotted string (None if malformed)."""
    try:
        a, b = ip.split(".")[:2]
        int(a); int(b)
        return f"{a}.{b}"
    except Exception:
        return None


def subnet_diversity_ok(new_ip: str, current_peers) -> bool:
    """True if admitting new_ip keeps the per-/16 peer count within MAX_PEERS_PER_SUBNET. Always True
    under NADO_TESTNET (the local mesh runs on a single 127.0.0.x /16)."""
    if os.environ.get("NADO_TESTNET"):
        return True
    sub = subnet16(new_ip)
    if sub is None:
        return False
    same = sum(1 for p in current_peers if subnet16(p) == sub)
    return same < MAX_PEERS_PER_SUBNET


async def get_public_ip(logger):
    # testnet/offline: use the configured IP instead of phoning home to ipify/ipinfo
    if os.environ.get("NADO_TESTNET"):
        try:
            return get_config()["ip"]
        except Exception:
            return "127.0.0.1"
    urls = ["https://api.ipify.org", "https://ipinfo.io/ip"]

    for url_construct in urls:
        try:
            async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url_construct) as response:
                    ip = await response.text()
                    return ip

        except Exception as e:
            logger.error(f"Unable to fetch IP from {url_construct}: {e}")

def update_local_ip(ip, logger):
    old_ip = get_config()["ip"]
    new_ip = ip

    if old_ip != new_ip:
        peer_me = load_peer(ip=old_ip,
                            logger=logger)

        save_peer(ip=new_ip,
                  address=peer_me["peer_address"],
                  port=peer_me["peer_port"],
                  overwrite=True
                  )

        new_config = {"ip": new_ip}
        update_config(new_config)

        logger.info(f"Local IP updated to {new_ip}")


def qualifies_to_sync(peer, peer_trust, peer_protocol, known_tree, memserver_protocol, median_trust,
                      unreachable_list, peer_hash, required_hash, promiscuous) -> dict:
    if not known_tree:
        """we don't know peer's root hash"""
        return {"result": False,
                "flag": f"Our root hash is unknown to them"}

    # #16 step 3: TRUST DEMOTED to an advisory transport hint — it no longer GATES sync. The objective
    # heaviest-cumulative_weight fork-choice already chose required_hash (the heaviest tip), and
    # verify_block + the finality floor enforce that chain on the real blocks, so a low-trust / Sybil
    # peer cannot feed us a chain we wouldn't independently accept. (Was: reject if
    # median_trust > peer_trust and not promiscuous — which a Sybil could pass by farming free trust.)
    if peer in unreachable_list:
        """peer assigned to unreachable"""
        return {"result": False,
                "flag": "Peer unreachable"}
    if peer_protocol < memserver_protocol:
        """peer protocol too low"""
        return {"result": False,
                "flag": "Peer protocol too low"}
    if not peer_hash == required_hash:
        """hash of the peer not in the currently cascaded one"""
        return {"result": False,
                "flag": "Peer hash not in majority"}

    return {"result": True}


if __name__ == "__main__":
    print(load_ips())
    # save_peer(ip="1.1.1.1", port=0, address="haha")
    # delete_peers(["1.1.1.1"])
    # save_peer(ip="1.1.2", port=0, address="haha2")
    # save_peer(ip="127.0.0.1", port=9173, address="sop3a7f8a5af60b15460181d9b2ff76ad5f5cfc7c5766ab77")
    # print(asyncio.run(get_remote_peer_address_async('89.176.130.244')))
    # update_peer("89.176.130.244",value=0,key="greeting")
