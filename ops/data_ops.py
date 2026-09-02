import asyncio
import json
import os
import random
import re
import sys
from pathlib import Path


def get_home():
    """the node's home directory (~/nado) — every data path (state DBs, peers.dat, snapshots, keys)
    is derived from this one root"""
    return f"{Path.home()}/nado"


# ---- CHAIN GENERATION (genesis-reroll support; see protocol.CHAIN_GENERATION) --------------------------------
# A reroll ships as ONE commit: the new genesis + a bumped protocol.CHAIN_GENERATION. Every node persists the
# GENERATION its on-disk data was built under; a mismatch at boot wipes all CHAIN-DERIVED data (blocks, index,
# peers, snapshots, exec state/DA — NEVER private/ keys+config) and regenesis/resyncs. This is what makes
# the integrated /update wave sufficient for a reroll: pull -> restart -> purge -> fresh chain.

def _purge_marker():
    return f"{get_home()}/chain_generation"


def stored_chain_generation():
    """The CHAIN_GENERATION this node's data was built under, or None (fresh node / pre-flag data)."""
    try:
        with open(_purge_marker()) as f:
            return int(f.read().strip())
    except Exception:
        return None


def stamp_chain_generation():
    from protocol import CHAIN_GENERATION
    with open(_purge_marker(), "w") as f:
        f.write(str(CHAIN_GENERATION))


def chain_purge_due():
    """True when the code's CHAIN_GENERATION moved past the on-disk data's generation. A missing marker is NOT
    due: fresh installs and first-boot-after-this-feature just get stamped with the current generation."""
    from protocol import CHAIN_GENERATION
    stored = stored_chain_generation()
    return stored is not None and stored != CHAIN_GENERATION


PURGE_LOG = "purge_log.json"          # under private/ (survives every purge by design): one timestamp per purge
PURGE_STORM_WINDOW_S = 86400
PURGE_STORM_LIMIT = 2                  # a THIRD dead-fork purge inside the window is refused (purge_storm)


def _purge_log_path():
    return f"{get_home()}/private/{PURGE_LOG}"


def purge_history() -> list:
    """Timestamps (int seconds) of every recorded purge, oldest first; [] when none / unreadable."""
    try:
        with open(_purge_log_path()) as f:
            return [int(x) for x in json.load(f)]
    except Exception:
        return []


def record_purge(now: int):
    """Append one purge to the node-local log (best effort, atomic rename)."""
    try:
        hist = purge_history() + [int(now)]
        hist = hist[-64:]
        os.makedirs(os.path.dirname(_purge_log_path()), exist_ok=True)
        tmp = _purge_log_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(hist, f)
        os.replace(tmp, _purge_log_path())
    except Exception:
        pass


def purge_storm(now: int, history=None, window=PURGE_STORM_WINDOW_S, limit=PURGE_STORM_LIMIT) -> bool:
    """CIRCUIT BREAKER. True when `limit` or more purges already happened inside `window` seconds before
    `now`. Every dead-fork verdict on 2026-09-01/02 was individually correct — and the node purged FOURTEEN
    times in twelve hours because its own peer loop was broken, re-forking from block 7 after each resync.
    Nothing in the process survives the os._exit() a purge ends with, so the only brake that can exist is
    on disk. A third correct verdict in a day is evidence that the SYNC path is broken, not the chain."""
    hist = purge_history() if history is None else list(history)
    return sum(1 for t in hist if int(now) - int(t) < window) >= limit


def purge_chain_data(logger=None, dead_fork=False):
    """Wipe every chain-derived artifact under the node home. EXPLICIT allowlist only — private/
    (keys, config) and the repo checkout are never touched.

    `dead_fork=True` (the in-process dead-fork escape) keeps what an L1 fork does NOT taint: the learned
    peer table (peers/, peers.dat — a node whose peer loop is already sick must not also lose the only
    peers it knows; the CLI purge.py never deleted them) and the exec DA store (exec_da/: content-addressed,
    commitment-keyed, self-verifying shards; a shard for a losing branch is simply never asked for, while
    this box may be the fleet's only holder). The CHAIN_GENERATION reroll path keeps the full wipe — there
    everything really is foreign."""
    import glob
    import shutil
    home = get_home()
    say = (logger.warning if logger else print)
    dirs = ("blocks", "index", "snapshots") if dead_fork else ("blocks", "index", "peers", "snapshots", "exec_da")
    for d in dirs:
        p = f"{home}/{d}"
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            say(f"PURGE: removed {p}/")
    pats = ("exec_state.json*", "version") if dead_fork else ("peers.dat", "exec_state.json*", "version")
    for pat in pats:
        for p in glob.glob(f"{home}/{pat}"):
            try:
                os.remove(p)
                say(f"PURGE: removed {p}")
            except OSError:
                pass

    # EXEC LAYER, authoritative wipe (reroll Gap A): the exec node (nado-exec) resolves its state + DA from
    # NADO_EXEC_STATE / NADO_EXEC_DA, which on a --home / split repo-data install point OUTSIDE get_home() —
    # so the home-relative wipes above MISS them. If a reroll leaves stale exec state, the exec node replays
    # the FRESH chain onto OLD state (cursor != -1, root != EXEC_GENESIS_ROOT) and silently forks L2. Its own
    # self-purge is unreliable (nado restamps the generation marker before nado-exec even imports), so
    # purge_chain_data must be authoritative. Resolve the SAME env vars the exec node uses; for a relative
    # value cover both the home and the repo root (the exec service's WorkingDirectory) so every layout hits.
    _repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _exec_candidates(env, default):
        raw = os.environ.get(env, default)
        if os.path.isabs(raw):
            return [raw]
        return [os.path.join(home, raw), os.path.join(_repo, raw), os.path.abspath(raw)]

    for base in _exec_candidates("NADO_EXEC_STATE", "exec_state.json"):
        for p in glob.glob(base + "*"):
            try:
                os.remove(p)
                say(f"PURGE: removed exec state {p}")
            except OSError:
                pass
    if dead_fork:
        say("PURGE: kept peers/, peers.dat and the exec DA store (not chain-derived; see purge_chain_data)")
        return
    for da in _exec_candidates("NADO_EXEC_DA", "exec_da"):
        if os.path.isdir(da):
            shutil.rmtree(da, ignore_errors=True)
            say(f"PURGE: removed exec DA {da}/")



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
