import asyncio
import os
import random
import re
import sys
from pathlib import Path


def get_home():
    """the node's home directory (~/nado) — every data path (state DBs, peers.dat, snapshots, keys)
    is derived from this one root"""
    return f"{Path.home()}/nado"


# ---- PURGE EPOCH (genesis-reroll support; see protocol.PURGE_EPOCH) --------------------------------
# A reroll ships as ONE commit: the new genesis + a bumped protocol.PURGE_EPOCH. Every node persists the
# epoch its on-disk data was built under; a mismatch at boot wipes all CHAIN-DERIVED data (blocks, index,
# peers, snapshots, exec state/DA — NEVER private/ keys+config) and regenesis/resyncs. This is what makes
# the integrated /update wave sufficient for a reroll: pull -> restart -> purge -> fresh chain.

def _purge_marker():
    return f"{get_home()}/purge_epoch"


def stored_purge_epoch():
    """The PURGE_EPOCH this node's data was built under, or None (fresh node / pre-flag data)."""
    try:
        with open(_purge_marker()) as f:
            return int(f.read().strip())
    except Exception:
        return None


def stamp_purge_epoch():
    from protocol import PURGE_EPOCH
    with open(_purge_marker(), "w") as f:
        f.write(str(PURGE_EPOCH))


def chain_purge_due():
    """True when the code's PURGE_EPOCH moved past the on-disk data's epoch. A missing marker is NOT
    due: fresh installs and first-boot-after-this-feature just get stamped with the current epoch."""
    from protocol import PURGE_EPOCH
    stored = stored_purge_epoch()
    return stored is not None and stored != PURGE_EPOCH


def purge_chain_data(logger=None):
    """Wipe every chain-derived artifact under the node home. EXPLICIT allowlist only — private/
    (keys, config) and the repo checkout are never touched."""
    import glob
    import shutil
    home = get_home()
    say = (logger.warning if logger else print)
    for d in ("blocks", "index", "peers", "snapshots", "exec_da"):
        p = f"{home}/{d}"
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            say(f"PURGE: removed {p}/")
    for pat in ("peers.dat", "exec_state.json*", "version"):
        for p in glob.glob(f"{home}/{pat}"):
            try:
                os.remove(p)
                say(f"PURGE: removed {p}")
            except OSError:
                pass



def is_hex_hash(value, length=64):
    """True only for a lowercase hex string of exactly `length` chars (a block or
    producer-set hash). Rejects path-traversal payloads such as '../../private/keys'
    that would otherwise resolve through f-string path construction."""
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None


def set_and_sort(entries: list) -> list:
    """dedup + sort into the ONE canonical ordering, so lists shared with peers (e.g. the /peers reply)
    come out identical regardless of insertion history"""
    sorted_entries = sorted(list(set(entries)))
    return sorted_entries


def average(list_of_values) -> int:
    """integer mean of the values (e.g. average fee over recent blocks)"""
    total = 0
    for value in list_of_values:
        total = total + value
    return int(total / len(list_of_values))


def _freeze(o):
    """recursively hashable stand-in for a json/msgpack-shaped value, EQUALITY-FAITHFUL to the
    original (two values freeze equal iff they compare ==, incl. Python's True == 1): dicts become
    frozensets of (key, frozen value), lists become tuples, hashable leaves pass through."""
    if isinstance(o, dict):
        return frozenset((k, _freeze(v)) for k, v in o.items())
    if isinstance(o, (list, tuple)):
        return tuple(_freeze(x) for x in o)
    return o


def sort_list_dict(entries) -> list:
    """order-preserving dedup for a list of dicts (transactions/blocks are unhashable, so set() won't do);
    keeps the FIRST occurrence. Dedup via a seen-set of _freeze()d entries — O(n) where the old
    `entry not in clean_list` membership scan was O(n²) deep-compares (pathological at mempool
    scale, and this runs on per-second paths). _freeze is equality-faithful, so the output is
    IDENTICAL to the old implementation (consensus callers — block tx dedup — see no change);
    an unfreezable (non-json-shaped) entry falls back to the old linear scan rather than raising."""
    seen = set()
    fallback = []       # unhashable oddballs (never occurs for real txs/blocks) — old O(n) scan
    clean_list = []
    for entry in entries:
        try:
            key = _freeze(entry)
            if key in seen:
                continue
            seen.add(key)
        except TypeError:
            if entry in fallback:
                continue
            fallback.append(entry)
        clean_list.append(entry)
    return clean_list


def get_byte_size(size_of) -> int:
    """rough byte size of an object via sizeof(repr) — fine for LOCAL buffer/pool caps, but
    NON-DETERMINISTIC across Python builds, so it must never gate consensus (see protocol.MIN_TX_FEE:
    the old byte-size base fee was removed for exactly this reason)"""
    return sys.getsizeof(repr(size_of))


def shuffle_dict(dictionary) -> dict:
    """same dict, random iteration order — randomizes which peer the sync loop tries first so no fixed
    entry is systematically preferred"""
    items = list(dictionary.items())
    random.shuffle(items)
    shuffled_dict = {}
    for key, value in items:
        shuffled_dict[key] = value
    return shuffled_dict


def allow_async():
    """Windows py3.8-3.10 shim: those versions default to the Proactor event loop, which misbehaves with
    the aiohttp client/server usage here, so force the selector policy. No-op everywhere else."""
    if sys.platform == "win32" and (3, 11, 0) >= sys.version_info >= (3, 8, 0):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def make_folder(folder_name: str, strict: bool = True):
    """create the folder if missing (True); if it already exists, raise under strict (first-boot paths
    that must not silently reuse old data) or return False when reuse is fine"""
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
        return True
    else:
        if strict:
            raise ValueError(f"{folder_name} folder already exists")
        else:
            return False
