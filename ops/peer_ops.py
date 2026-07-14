import asyncio
import glob
import ipaddress
import json
import os
import os.path
import threading

from compounder import compound_get_list_of, compound_announce_self
from compounder import compound_get_status_pool
from config import get_port, get_config, get_timestamp_seconds, update_config, hostport
from .data_ops import set_and_sort, get_home
from .net_ops import read_capped, unpack_zstd_peer, MAX_PEER_BODY

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
# SINGLE peer store. Peers live in ONE file (peers.dat) as {ip: {peer_address, peer_port, last_seen}},
# not one file per peer. The old per-file layout accreted "ghost" files — a dead seed, the
# node's OWN ip (re-saved by update_local_ip on every IP refresh), same-subnet spam — that were awkward to
# reap and kept getting reloaded/redialed. One file is atomic, reaps cleanly, and lets us enforce ONE
# invariant in one place: our own IP is NEVER a peer (self is advertised via me_to() in /peers; dialing
# self just fails). Read-modify-write is serialized by a lock; writes are atomic (tmp+fsync+os.replace).
# --------------------------------------------------------------------------------------------------
_PEERS_LOCK = threading.RLock()


def _peers_path():
    """the single-file peer store (peers.dat) under the node home"""
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
    """persist the whole peer table in one atomic write (tmp+fsync+os.replace) — a crash mid-save can
    never leave a torn peers.dat that _load_peers would then silently read as empty"""
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
                             "peer_port": p.get("peer_port"), "last_seen": p.get("last_seen", 0)}
        except Exception:
            pass
    _save_peers(table)
    for fp in files:
        try:
            os.remove(fp)
        except Exception:
            pass
    return table



# FIELD-TYPE SCHEMA for an admitted /status dict. A peer's status is UNTRUSTED input, and its numeric
# fields flow straight into consensus arithmetic — latest_block_weight into the objective fork-choice
# comparison (consensus_loop.refresh_heaviest_tip `w > tip_weights[...]`) and the caught-up gate
# (core_loop.peer_claims_heavier_tip `weight > our_weight`). In Python 3 `"9" > 5` raises TypeError, so a
# SINGLE peer advertising a STRING weight would crash the consensus refresh EVERY pass and FREEZE
# fork-choice node-wide (same halt-class as the unvalidated min_block). We therefore reject a status whose
# known numeric/hash field is present but wrong-typed, at the admission boundary — so no downstream
# consumer ever compares a mistyped value. Absent/None is allowed (a mid-restart peer legitimately omits
# fields); bool is rejected for numerics (True/False must not masquerade as a weight/height).
_STATUS_INT_FIELDS = ("latest_block_weight", "finalized_height", "ffg_finalized",
                      "snapshot_height", "reported_uptime", "protocol")
_STATUS_STR_FIELDS = ("latest_block_hash", "earliest_block_hash", "upcoming_block_hash",
                      "transaction_pool_hash", "snapshot_hash", "address", "version", "chain_id")


def status_fields_well_typed(status) -> bool:
    """True iff `status` is a dict whose known consensus fields are each absent, None, or the RIGHT type
    (ints for weights/heights — bool rejected; strings for hashes/ids). Fail-closed: a malformed status
    is refused at admission so a mistyped weight can never reach a fork-choice comparison and crash it."""
    if not isinstance(status, dict):
        return False
    for f in _STATUS_INT_FIELDS:
        v = status.get(f)
        if v is not None and (not isinstance(v, int) or isinstance(v, bool)):
            return False
    for f in _STATUS_STR_FIELDS:
        v = status.get(f)
        if v is not None and not isinstance(v, str):
            return False
    return True


async def get_remote_status(target_peer, logger) -> [dict, bool]:
    """fetch a peer's /status dict over the bomb-capped zstd(msgpack) wire (5s total timeout); False on
    any failure. The answer is UNTRUSTED peer input — callers pool it and act on the get_majority vote,
    never on a single peer's word."""

    try:
        url_construct = f"http://{hostport(target_peer, get_port())}/status?compress=zstd"

        async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url_construct) as response:
                if response.status == 200:
                    # anti-OOM: cap the untrusted body like every other peer fetcher (compressed side),
                    # and unpack_zstd_peer caps the decompressed side against a zstd bomb.
                    status = unpack_zstd_peer(await read_capped(response, MAX_PEER_BODY))
                    # reject a malformed-typed status here too (this fetcher feeds the snapshot/reanchor
                    # weight comparisons directly, bypassing the peer_loop admission gate).
                    return status if status_fields_well_typed(status) else False
                else:
                    return False

    except Exception as e:
        logger.error(f"Failed to get status from {target_peer}: {e}")
        return False


def delete_peer(ip, logger):
    """drop one peer from the table (lock-serialized; persisted atomically). No-op if absent, so callers
    can evict unconditionally."""
    with _PEERS_LOCK:
        table = _load_peers()
        if table.pop(ip, None) is not None:
            _save_peers(table)
            logger.warning(f"Deleted peer {ip}")


def save_peer(ip, port, address, overwrite=False):
    """add one peer to the table (lock-serialized read-modify-write, atomic persist). Silently refuses our
    OWN ip — self is NEVER a peer (self is advertised via me_to() in /peers; storing it created the old
    ghost self-peer + self-dial errors) — and leaves an existing entry alone unless overwrite=True."""
    # INVARIANT: never store our own IP — self is advertised to peers via me_to() in /peers, and dialing
    # ourselves just fails (this is what created the old ghost self-peer + the repeated self-dial errors).
    if not ip or ip == get_config()["ip"]:
        return
    with _PEERS_LOCK:
        table = _load_peers()
        if ip in table and not overwrite:
            return
        table[ip] = {"peer_address": address, "peer_ip": ip, "peer_port": port,
                     "last_seen": get_timestamp_seconds()}
        _save_peers(table)


# Baked-in bootstrap seed(s). A freshly-cloned node (`python node.py`) has an EMPTY peers/ dir and no way
# to discover the network, so it starts from these. Extend/override with NADO_SEED_PEERS (comma-separated).
DEFAULT_SEED_PEERS = ["38.242.201.206"]   # get.nadochain.com — the public bootstrap node

def seed_peers():
    """Operator seed set: baked-in DEFAULT_SEED_PEERS + any NADO_SEED_PEERS the operator configured
    (comma-separated). Used to seed a fresh node AND as the weak-subjectivity anchor for accepting a
    snapshot from a LONE donor (loops/core_loop.snapshot_bootstrap) — membership in this operator-defined
    set is the anchor; there is no peer-reputation score."""
    extra = [x.strip() for x in (os.environ.get("NADO_SEED_PEERS") or "").split(",") if x.strip()]
    return list(dict.fromkeys(DEFAULT_SEED_PEERS + extra))


def seed_default_peers(logger, my_ip=None):
    """Ensure the baked-in bootstrap seed(s) are present so a node is NEVER stranded with no one to dial.
    save_peer is a no-op for a seed that already exists or for our own IP, so this is idempotent — but it
    re-asserts the seed UNCONDITIONALLY rather than only on an empty table. That is what recovers a node
    whose table got poisoned (e.g. only our own migrated-in IP, which load_ips then excludes) — the old
    'skip if the table is non-empty' left such a node looping 'Loaded 0 reachable peers'."""
    for ip in seed_peers():
        if not ip or ip == (my_ip or get_config().get("ip")):
            continue
        try:
            save_peer(ip=ip, port=get_port(), address="")
        except Exception as e:
            logger.info(f"Failed to seed bootstrap peer {ip}: {e}")


def ip_stored(ip) -> bool:
    """whether ip is already present in the peer table"""
    return ip in _load_peers()


async def load_ips(logger, port, fail_storage, unreachable, minimum=3, top_50=True) -> list:
    """load peers from drive, most-recently-seen first, test in batches asynchronously,
    return when limit is reached"""

    bad_peers = set(fail_storage + list(unreachable.keys()))
    bad_peers -= set(seed_peers())      # operator seeds are the anchor: ALWAYS a dial candidate, even if a
                                        # transient blip landed them in unreachable/fail — never exile the seed
    bad_peers.add(get_config()["ip"])   # ...but never dial our OWN ip (added AFTER the seed carve-out, so a
                                        # node that is itself a seed still never dials itself)
    table = _load_peers()

    if len(table) < minimum:
        minimum = len(table)

    status_pool = []
    candidates = [entry for ip, entry in table.items() if ip not in bad_peers and entry.get("peer_ip")]

    ip_sorted = []

    # DIAL ORDER: operator seeds first (the weak-subjectivity anchor — always try a known-good peer
    # ahead of ordinary ones so a reconnecting node can never be stranded), then ordinary peers
    # most-recently-seen first. Seed membership is the ONLY preference; there is no peer-reputation score.
    _seeds = set(seed_peers())
    candidates_sorted = sorted(
        candidates,
        key=lambda d: (d.get("peer_ip") in _seeds, d.get("last_seen", 0) or 0),
        reverse=True,
    )
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
                                                                  compress="zstd",
                                                                  semaphore=asyncio.Semaphore(50))))
        for entry in gathered:
            status_pool.extend(list(entry.keys()))

        logger.info(f"Gathered {len(status_pool)}/{minimum} peers in {i + 1} steps, {len(fail_storage)} failed")

        if len(status_pool) >= minimum:
            break

    logger.info(f"Loaded {len(status_pool)} reachable peers from drive, {len(fail_storage)} failed")

    return status_pool


def load_peer(logger, ip, key=None) -> [str, dict]:
    """one peer's record from the table (or a single field of it via `key`); None if unknown"""
    peer = _load_peers().get(ip)
    if peer is None:
        return None
    return peer if key is None else peer.get(key)


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
                             "last_seen": get_timestamp_seconds()}
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
                             compress="zstd",
                             semaphore=asyncio.Semaphore(50))
    )

    pool = []
    for peer in returned_peers:
        pool.append(peer)
    return pool



def percentage(value, list) -> float:
    """what percent of `list` equals `value` — grades how strong a majority is behind a consensus value
    (0 on empty/falsy input)"""
    if value and list:
        part = list.count(value)
        whole = len(list)
        return 100 * float(part) / float(whole)
    else:
        return 0


def get_majority(in_what) -> [str, None]:
    """the most frequent value in a {peer: value} answer pool — the status-consensus vote (e.g. which
    block/tx-pool hash the network majority advertises). Returns None while ANY peer is still unanswered
    (None), so a majority is never declared on partial data. The pre-sort makes tie-breaking deterministic:
    every honest node picks the SAME winner from the same pool. Sybil resistance does NOT live here — the
    vote only steers who we sync from; the objective heaviest-weight fork choice decides what we accept."""
    if None not in in_what.values():
        return max(
            list(sorted(in_what.values())),
            key=list(in_what.values()).count,
        )
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


# own-IP cache for check_ip (audit): check_ip runs per peer per ~1s pass on two hot loops (donor
# selection, peer gossip), and get_config() deliberately re-reads config.dat from disk every call —
# dozens of file reads + JSON parses per second for a value that effectively never changes.
# update_local_ip() invalidates on the one code path that rewrites the IP.
_own_ip_cache = {"v": None}

def _own_ip_cached():
    """the node's configured public IP, read from config.dat once and cached (see above)."""
    if _own_ip_cache["v"] is None:
        _own_ip_cache["v"] = get_config()["ip"]
    return _own_ip_cache["v"]


def check_ip(ip):
    """routability guard for a peer-supplied (UNTRUSTED) address before it may enter the peer table:
    rejects malformed strings, IPv4-mapped IPv6 disguises, our OWN ip, and anything not globally routable
    (loopback, private/ULA, link-local, reserved, multicast, unspecified). Accepting those would let a
    peer seed us with internal targets — eclipse groundwork / limited SSRF probing. NADO_TESTNET waives
    the routability checks so a local 127.0.0.x multi-node mesh can form; NEVER set it on mainnet."""
    # accept BOTH IPv4 and IPv6 (ip_address parses either); the routability guard below applies to both
    # families. Reject IPv4-mapped IPv6 (::ffff:a.b.c.d) outright so a mapped private/own address can't
    # slip past the v4 checks under a v6 disguise — a real peer should present a plain v4 string instead.
    try:
        addr = ipaddress.ip_address(ip)
    except Exception:
        return False
    if getattr(addr, "ipv4_mapped", None) is not None:
        return False
    # reject our own IP and any non-globally-routable address (loopback, RFC1918/ULA private, link-local,
    # reserved, multicast, unspecified): accepting these lets a peer seed us with internal targets
    # (eclipse groundwork / limited SSRF probing). is_private covers IPv6 ULA (fc00::/7) too.
    if ip == _own_ip_cached():
        return False
    # NADO_TESTNET: allow loopback/private peers so a local multi-node testnet can mesh over
    # 127.0.0.x. NEVER set this on mainnet — it disables the SSRF/eclipse IP guard below.
    if os.environ.get("NADO_TESTNET"):
        return True
    if (addr.is_loopback or addr.is_private or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
        return False
    return True


# ECLIPSE HARDENING (#18 step 8): cap how many peers from the SAME grouping prefix may occupy the live
# peer slots, so a single network/operator can't fill a victim's peer view (eclipse). Grouping is /16 for
# IPv4 and /64 for IPv6 (a /64 is the smallest routable IPv6 allocation, so it maps to one "network" the
# way a /16 roughly does for v4 — and it stops an attacker with a single cheap /64 from spinning 2^64 hosts
# to monopolize the slots). With a cap of 4 an attacker needs >= 6 distinct prefixes. Pairs with the
# /announce_peer rate-limit. Testnet (127.0.0.x) is exempt so a local multi-node mesh can still form.
MAX_PEERS_PER_SUBNET = 4


def subnet_of(ip: str):
    """Eclipse-grouping prefix: IPv4 /16, IPv6 /64 (canonical network string). None if malformed."""
    try:
        addr = ipaddress.ip_address(ip)
    except Exception:
        return None
    prefix = 16 if addr.version == 4 else 64
    net = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
    return f"{net.network_address}/{prefix}"


def subnet_diversity_ok(new_ip: str, current_peers) -> bool:
    """True if admitting new_ip keeps the per-prefix peer count within MAX_PEERS_PER_SUBNET (/16 v4, /64
    v6). Always True under NADO_TESTNET (the local mesh runs on a single 127.0.0.x /16)."""
    if os.environ.get("NADO_TESTNET"):
        return True
    sub = subnet_of(new_ip)
    if sub is None:
        return False
    same = sum(1 for p in current_peers if subnet_of(p) == sub)
    return same < MAX_PEERS_PER_SUBNET


async def get_public_ip(logger):
    """detect our own public IP for self-advertisement, PREFERRING IPv4: on a dual-stack host a v6-only
    self would be unreachable to v4-only peers (most of the current mesh) and could partition us. Tries
    the family-forced probes first (v4, then v6 for v6-ONLY hosts), then generic fallbacks; None if every
    probe fails. Under NADO_TESTNET returns the configured IP so an offline mesh never phones home."""
    # testnet/offline: use the configured IP instead of phoning home to ipify/ipinfo
    if os.environ.get("NADO_TESTNET"):
        try:
            return get_config()["ip"]
        except Exception:
            return "127.0.0.1"
    # PREFER IPv4 for self-advertisement: on a dual-stack host, advertising a v6-only self would make us
    # unreachable to v4-only peers (most of the current mesh) and can partition us. api4/api6 force a family;
    # try v4 first, fall back to v6 (so a v6-ONLY host still gets a usable address), then the generic probe.
    urls = ["https://api4.ipify.org", "https://api6.ipify.org",
            "https://api.ipify.org", "https://ipinfo.io/ip"]

    for url_construct in urls:
        try:
            async with aiohttp.ClientSession(timeout = aiohttp.ClientTimeout(total=5)) as session:
                async with session.get(url_construct) as response:
                    ip = (await response.text()).strip()
                    if ip:
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
        _own_ip_cache["v"] = ip      # keep check_ip's own-IP cache in step
        logger.info(f"Local IP updated to {ip}")


def qualifies_to_sync(peer, peer_protocol, memserver_protocol,
                      unreachable_list, peer_hash, required_hash) -> dict:
    """LOCAL-ONLY gate for picking a sync donor: the peer must advertise EXACTLY the objectively-chosen
    required_hash, be reachable, and speak at least our protocol. All checks are in-memory — the one
    network check (does the peer know our root block?) is dialed by the caller ONLY for peers that pass
    this gate, so a pool full of non-candidates costs zero round-trips. Peer identity carries no weight —
    fork choice is objective (heaviest cumulative_weight already chose required_hash, and verify_block +
    the finality floor re-check every block of the tail), so a Sybil donor can at worst waste our time,
    never feed us a chain we wouldn't independently accept. Returns {"result": bool, "flag": reason}."""
    if not peer_hash == required_hash:
        """hash of the peer not the currently required one"""
        return {"result": False,
                "flag": "Peer hash not the required one"}
    if peer in unreachable_list:
        """peer assigned to unreachable"""
        return {"result": False,
                "flag": "Peer unreachable"}
    if peer_protocol < memserver_protocol:
        """peer protocol too low"""
        return {"result": False,
                "flag": "Peer protocol too low"}

    return {"result": True}


if __name__ == "__main__":
    print(load_ips())
    # save_peer(ip="1.1.1.1", port=0, address="haha")
    # delete_peers(["1.1.1.1"])
    # save_peer(ip="1.1.2", port=0, address="haha2")
    # save_peer(ip="127.0.0.1", port=9173, address="sop3a7f8a5af60b15460181d9b2ff76ad5f5cfc7c5766ab77")
    # print(asyncio.run(get_remote_peer_address_async('89.176.130.244')))
