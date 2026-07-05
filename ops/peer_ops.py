import asyncio
import glob
import ipaddress
import json
import os
import os.path
import threading

from compounder import compound_get_list_of, compound_announce_self
from compounder import compound_get_status_pool
from config import get_port, get_config, get_timestamp_seconds, update_config
from .data_ops import set_and_sort, get_home

import aiohttp

def _atomic_write_json(path, obj):
    """write JSON via temp file + fsync + os.replace so a crash mid-write can never leave a
    half-written (corrupt) file that a reader would then silently fail to parse."""
    tmp = f"{path}.tmp"
    with open(tmp, "w") as outfile:
        json.dump(obj, outfile)
        outfile.flush()
        os.fsync(outfile.fileno())
    os.replace(tmp, path)


# --------------------------------------------------------------------------------------------------
# SINGLE peer store. Peers live in ONE file (peers.dat) as {ip: {peer_address, peer_port, peer_trust,
# last_seen}}, not one file per peer. The old per-file layout accreted "ghost" files — a dead seed, the
# node's OWN ip (re-saved by update_local_ip on every IP refresh), same-subnet spam — that were awkward to
# reap and kept getting reloaded/redialed. One file is atomic, reaps cleanly, and lets us enforce ONE
# invariant in one place: our own IP is NEVER a peer (self is advertised via me_to() in /peers; dialing
# self just fails). Read-modify-write is serialized by a lock; writes are atomic (tmp+fsync+os.replace).
# --------------------------------------------------------------------------------------------------
_PEERS_LOCK = threading.RLock()


def _peers_path():
    return f"{get_home()}/peers.dat"


def _load_peers() -> dict:
    """The whole peer table {ip: {...}}. Migrates the legacy peers/*.dat directory on first use (then
    retires it), and returns {} on a missing/corrupt file (an empty peer table is always valid)."""
    path = _peers_path()
    if not os.path.isfile(path):
        migrated = _migrate_legacy_peers()
        return migrated if migrated is not None else {}
    try:
        with open(path, "r") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_peers(table: dict):
    _atomic_write_json(_peers_path(), table)


def _migrate_legacy_peers():
    """One-time import of the old peers/<b64(ip)>.dat files into peers.dat, then delete them so the ghost
    files can never be reloaded again. Returns the migrated table, or None if there was nothing to migrate."""
    old_dir = f"{get_home()}/peers"
    files = glob.glob(f"{old_dir}/*.dat")
    if not files:
        return None
    my_ip = get_config().get("ip")
    table = {}
    for fp in files:
        try:
            with open(fp, "r") as f:
                p = json.load(f)
            ip = p.get("peer_ip")
            # skip our OWN ip (the old update_local_ip saved it as a ghost self-peer) and non-routable
            # junk — carrying them poisons the table and stalls the bootstrap seed on the next boot.
            if ip and ip != my_ip and check_ip(ip):
                table[ip] = {"peer_address": p.get("peer_address", ""), "peer_ip": ip,
                             "peer_port": p.get("peer_port"), "peer_trust": p.get("peer_trust", 50),
                             "last_seen": p.get("last_seen", 0)}
        except Exception:
            pass
    _save_peers(table)
    for fp in files:
        try:
            os.remove(fp)
        except Exception:
            pass
    return table



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
    with _PEERS_LOCK:
        table = _load_peers()
        if table.pop(ip, None) is not None:
            _save_peers(table)
            logger.warning(f"Deleted peer {ip}")


def save_peer(ip, port, address, peer_trust=50, overwrite=False):
    # INVARIANT: never store our own IP — self is advertised to peers via me_to() in /peers, and dialing
    # ourselves just fails (this is what created the old ghost self-peer + the repeated self-dial errors).
    if not ip or ip == get_config()["ip"]:
        return
    with _PEERS_LOCK:
        table = _load_peers()
        if ip in table and not overwrite:
            return
        table[ip] = {"peer_address": address, "peer_ip": ip, "peer_port": port,
                     "peer_trust": peer_trust, "last_seen": get_timestamp_seconds()}
        _save_peers(table)


# Baked-in bootstrap seed(s). A freshly-cloned node (`python node.py`) has an EMPTY peers/ dir and no way
# to discover the network, so it starts from these. Extend/override with NADO_SEED_PEERS (comma-separated).
DEFAULT_SEED_PEERS = ["38.242.201.206"]   # get.nadochain.com — the public bootstrap node

# Trust floor pinned on every operator seed. load_ips() sorts the dial set by peer_trust (highest first)
# and keeps only the top 50, and ordinary peers accrete trust indefinitely (+1 per agreement round — the
# live table already has one peer at 1600+). A seed left at the ordinary default (50) would sink below the
# aged peers and eventually fall out of the top-50 dial set, stranding a reconnecting node from its
# weak-subjectivity anchor. Pinning the seed far above any organically reachable value keeps it at the head
# of the dial order forever. NOTE: trust does NOT gate sync (see qualifies_to_sync / minority_block_consensus
# — fork choice is objective heaviest-weight, and the lone-donor snapshot anchor is seed-SET membership, not
# a trust number), so this is purely a reachability/preference lever and carries no Sybil surface: the seed
# set is operator-defined.
SEED_TRUST = 1_000_000


def trusted_seeds():
    """Operator-trusted bootstrap seed set: baked-in DEFAULT_SEED_PEERS + any NADO_SEED_PEERS the operator
    configured (comma-separated). Used to seed a fresh node AND as the weak-subjectivity trust anchor for
    accepting a snapshot from a LONE donor (loops/core_loop.snapshot_bootstrap)."""
    extra = [x.strip() for x in (os.environ.get("NADO_SEED_PEERS") or "").split(",") if x.strip()]
    return list(dict.fromkeys(DEFAULT_SEED_PEERS + extra))


def seed_default_peers(logger, my_ip=None):
    """Ensure the baked-in bootstrap seed(s) are present so a node is NEVER stranded with no one to dial.
    save_peer is a no-op for a seed that already exists (its trust is preserved) or for our own IP, so this
    is idempotent — but it re-asserts the seed UNCONDITIONALLY rather than only on an empty table. That is
    what recovers a node whose table got poisoned (e.g. only our own migrated-in IP, which load_ips then
    excludes) — the old 'skip if the table is non-empty' left such a node looping 'Loaded 0 reachable peers'."""
    for ip in trusted_seeds():
        if not ip or ip == (my_ip or get_config().get("ip")):
            continue
        try:
            if ip_stored(ip):
                # seed already known: raise its trust to the seed floor (idempotent, no-op once pinned)
                # via update_peer, which touches ONLY peer_trust so the learned peer_address is preserved.
                if (load_peer(ip=ip, key="peer_trust", logger=logger) or 0) < SEED_TRUST:
                    update_peer(ip=ip, value=SEED_TRUST, logger=logger)
            else:
                save_peer(ip=ip, port=get_port(), address="", peer_trust=SEED_TRUST)
        except Exception as e:
            logger.info(f"Failed to seed bootstrap peer {ip}: {e}")


def ip_stored(ip) -> bool:
    return ip in _load_peers()


def dump_trust(pool_data, logger):
    with _PEERS_LOCK:
        table = _load_peers()
        changed = False
        for ip, trust in pool_data.items():
            if ip in table:
                table[ip]["peer_trust"] = trust
                table[ip]["last_seen"] = get_timestamp_seconds()
                changed = True
        if changed:
            _save_peers(table)


def sort_dict_value(values: list, key: str) -> list:
    if values:
        return sorted(values, key=lambda d: d.get(key, 0) or 0, reverse=True)
    else:
        return []


async def load_ips(logger, port, fail_storage, unreachable, minimum=3, top_50=True) -> list:
    """load peers from drive, sort by trust, test in batches asynchronously,
    return when limit is reached"""

    bad_peers = set(fail_storage + list(unreachable.keys()))
    bad_peers.add(get_config()["ip"])   # never load our OWN ip into the dial set — we don't sync from
                                        # ourselves; self is advertised to others via me_to() in /peers
    table = _load_peers()

    if len(table) < minimum:
        minimum = len(table)

    status_pool = []
    candidates = [entry for ip, entry in table.items() if ip not in bad_peers and entry.get("peer_ip")]

    ip_sorted = []

    candidates_sorted = sort_dict_value(candidates, key="peer_trust")
    if top_50:
        candidates_sorted = candidates_sorted[:50]


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


def load_peer(logger, ip, key=None) -> [str, dict]:
    peer = _load_peers().get(ip)
    if peer is None:
        return None
    return peer if key is None else peer.get(key)


def update_peer(ip, value, logger, key="peer_trust") -> None:
    with _PEERS_LOCK:
        table = _load_peers()
        if ip not in table:
            return
        table[ip][key] = value
        table[ip]["last_seen"] = get_timestamp_seconds()
        _save_peers(table)


def check_save_peers(peers, logger, fails, unreachable):
    """persist newly-reachable peers to the peer table (skipping self, non-routable, and already-known)"""
    good_peers = set(peers) - set(fails) - set(unreachable)

    local_fails = []
    candidates = asyncio.run(compound_get_status_pool(
        ips=good_peers,
        port=get_port(),
        fail_storage=local_fails,
        logger=logger,
        semaphore=asyncio.Semaphore(50)))

    my_ip = get_config()["ip"]
    with _PEERS_LOCK:
        table = _load_peers()
        changed = False
        for ip, value in candidates.items():
            if ip != my_ip and ip not in table and check_ip(ip):
                table[ip] = {"peer_address": value.get("address", ""), "peer_ip": ip, "peer_port": get_port(),
                             "peer_trust": 50, "last_seen": get_timestamp_seconds()}
                changed = True
        if changed:
            _save_peers(table)

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
    """Keep the node's configured public IP current (detected via get_public_ip). We do NOT store our own
    IP as a peer anymore — self is advertised to others via me_to() in /peers, and dialing ourselves just
    fails. (The old code re-saved the new IP as a peer here, which is what created the ghost self-peer and
    the repeated 'Failed to get peers of <own-ip>' self-dial errors.)"""
    if ip and ip != get_config()["ip"]:
        update_config({"ip": ip})
        logger.info(f"Local IP updated to {ip}")


def qualifies_to_sync(peer, peer_protocol, known_tree, memserver_protocol,
                      unreachable_list, peer_hash, required_hash) -> dict:
    if not known_tree:
        """we don't know peer's root hash"""
        return {"result": False,
                "flag": f"Our root hash is unknown to them"}

    # #16 step 3: TRUST DEMOTED to an advisory transport hint — it no longer GATES sync. The objective
    # heaviest-cumulative_weight fork-choice already chose required_hash (the heaviest tip), and
    # verify_block + the finality floor enforce that chain on the real blocks, so a low-trust / Sybil
    # peer cannot feed us a chain we wouldn't independently accept. (Was: reject if a peer's trust
    # sat below the median — which a Sybil could pass anyway by farming free trust.)
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
