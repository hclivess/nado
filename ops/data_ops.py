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


def sort_list_dict(entries) -> list:
    """order-preserving dedup for a list of dicts (transactions/blocks are unhashable, so set() won't do);
    keeps the FIRST occurrence"""
    clean_list = []
    for entry in entries:
        if entry not in clean_list:
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
