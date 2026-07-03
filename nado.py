import asyncio
import functools
import json
import mimetypes
import os
import signal
import socket
import sys

import msgpack
from aiohttp import web

import versioner
from config import get_config
from genesis import make_genesis, make_folders
from loops.consensus_loop import ConsensusClient
from loops.core_loop import CoreClient
from loops.message_loop import MessageClient
from loops.peer_loop import PeerClient
from memserver import MemServer
from ops.account_ops import get_account, fetch_totals, get_bonded_registry
from ops.mining_ops import total_shares
from ops.block_ops import get_block, fee_over_blocks, get_block_number
from ops.data_ops import get_home, allow_async
from ops.key_ops import keyfile_found, generate_keys, save_keys, load_keys
from ops.log_ops import get_logger, logging
from ops.peer_ops import save_peer, get_remote_status, check_ip
from ops.transaction_ops import get_transaction, get_transactions_of_account, to_readable_amount
from ops import snapshot_ops
from protocol import GENESIS_ADDRESS, TREASURY_ADDRESS, TREASURY_GENESIS, GENESIS_TIMESTAMP

import gc  # replaces pympler/muppy — the full-heap walk fatally trips CPython GC under asyncio load

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_HERE, "static")


def is_port_in_use(port: int, host: str = "localhost") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def handler(signum, frame):
    logger.info(f"Terminating: {signum}: {frame}")
    memserver.terminate = True
    sys.exit(0)


def serialize(output, name=None, compress=None):
    if compress == "msgpack":
        output = msgpack.packb(output)
    elif not isinstance(output, dict) and name:
        output = {name: output}
    return output


# --- bulk snapshot sync: lazily build + cache the current checkpoint snapshot ---
_snapshot_cache = {}  # {height: (manifest, [chunk_bytes, ...])}


def get_current_snapshot(build=True):
    """(manifest, chunks) for the node's current checkpoint, built+cached at most once
    per checkpoint height. Returns (None, None) when the chain is too short to snapshot.
    /status passes build=False so advertising never triggers a heavy build."""
    try:
        tip = memserver.latest_block["block_number"]
    except Exception:
        return None, None
    height = snapshot_ops.choose_checkpoint_height(tip)
    if height is None:
        return None, None
    if height in _snapshot_cache:
        return _snapshot_cache[height]
    if not build:
        return None, None
    block_hash = snapshot_ops.block_hash_at_height(height)
    if not block_hash:
        return None, None
    manifest, chunks = snapshot_ops.build_snapshot(
        snapshot_height=height,
        block_hash=block_hash,
        protocol=memserver.protocol,
        version=memserver.version)
    _snapshot_cache.clear()  # keep only the newest checkpoint
    _snapshot_cache[height] = (manifest, chunks)
    return manifest, chunks


# --------------------------------------------------------------------------------------------------
# aiohttp helpers — the node's HTTP API is served by aiohttp (Tornado retired). The inter-node HTTP
# CLIENT already used aiohttp (ops/peer_ops, ops/block_ops, ops/snapshot_ops), so this removes the
# last Tornado dependency. "No intensive operations or locks from the API"; blocking DB/file work is
# pushed to a worker thread via asyncio.to_thread so the event loop stays responsive.
# --------------------------------------------------------------------------------------------------
def _ip(request):
    """The client's source IP (Tornado's request.remote_ip equivalent)."""
    return request.remote or "unknown"


def _resp(output, status=200, headers=None):
    """Mirror Tornado's self.write() typing for our outputs: bytes -> msgpack/octet body; dict/list ->
    JSON; anything else -> text. CORS-open like the old handlers so a cross-origin page can read it."""
    h = {"Access-Control-Allow-Origin": "*"}
    if headers:
        h.update(headers)
    if isinstance(output, (bytes, bytearray)):
        return web.Response(body=bytes(output), status=status, content_type="application/msgpack", headers=h)
    if isinstance(output, (dict, list)):
        return web.json_response(output, status=status, headers=h)
    return web.Response(text=str(output), status=status, headers=h)


def _rate_limited(request, limit, window=60):
    from ops.ratelimit import allow
    return not allow(_ip(request), limit, window)


_RL = web.json_response({"result": False, "message": "Rate limited — slow down"}, status=429,
                        headers={"Access-Control-Allow-Origin": "*"})


def _q(request, key, default=None):
    return request.query.get(key, default)


# --- pool / field dump handlers (the repetitive read-only ones) ----------------------------------
def _dump_handler(name, getter):
    async def _h(request):
        return _resp(serialize(name=name, output=getter(), compress=_q(request, "compress", "none")))
    return _h


async def home(request):
    # The node's landing page is the static, client-side NADO Interface (wallet + miner + explorer + shield).
    raise web.HTTPFound("/static/interface.html")


async def legacy_static_redirect(request):
    # The page/assets were renamed miner.* -> interface.* (it's a full interface now, not just a miner).
    # Redirect the old paths so saved links / bookmarks to /static/miner.html keep working.
    raise web.HTTPFound("/static/interface." + request.match_info["ext"])


async def status(request):
    def _build():
        # Defensive: /status is the exec node's lifeline (finalized_height) and the wallet's connection
        # check, so NO single field may 403 the whole endpoint. Guard the block-ends + snapshot lookups
        # (in rolling mode a pruned body could make these falsy) — degrade to null, never crash.
        lb = memserver.latest_block if isinstance(memserver.latest_block, dict) else {}
        eb = memserver.earliest_block if isinstance(memserver.earliest_block, dict) else {}
        status_dict = {
            "reported_uptime": memserver.reported_uptime,
            "address": memserver.address,
            "transaction_pool_hash": memserver.transaction_pool_hash,
            "block_producers_hash": memserver.block_producers_hash,
            "latest_block_hash": lb.get("block_hash"),
            "latest_block_weight": lb.get("cumulative_weight", 0),
            "earliest_block_hash": eb.get("block_hash"),
            "finalized_height": memserver.finalized_height,
            "ffg_finalized": memserver.ffg_finalized,
            "protocol": memserver.protocol,
            "version": memserver.version,
        }
        try:
            snap_manifest, _ = get_current_snapshot(build=False)
            snap_manifest = snap_manifest if isinstance(snap_manifest, dict) else None
        except Exception:
            snap_manifest = None
        status_dict["snapshot_height"] = snap_manifest["snapshot_height"] if snap_manifest else None
        status_dict["snapshot_hash"] = snap_manifest["snapshot_hash"] if snap_manifest else None
        return serialize(name="status", output=status_dict, compress=_q(request, "compress", "none"))
    try:
        return _resp(await asyncio.to_thread(_build))
    except Exception as e:
        return _resp(f"Error: {e}", status=403)


async def mining_status(request):
    if _rate_limited(request, 120):  # /mining_status full-scans the account set; throttle it
        return _RL
    from ops.block_ops import mining_status as compute_mining_status
    address = _q(request, "address", memserver.address)
    compress = _q(request, "compress", "none")
    try:
        data = await asyncio.to_thread(compute_mining_status, address,
                                       memserver.latest_block["block_number"], memserver.block_time)
        return _resp(serialize(name="mining_status", output=data, compress=compress))
    except Exception as e:
        return _resp(f"Error: {e}", status=403)


async def get_recommended_fee(request):
    fee = await asyncio.to_thread(lambda: fee_over_blocks(logger=logger) + 1)
    return _resp({"fee": fee})


async def submit_transaction(request):
    if _rate_limited(request, 30):
        return _RL

    def _work(body, ctype, ip):
        try:
            if "msgpack" in ctype:
                transaction = msgpack.unpackb(body, raw=False)
            else:
                transaction = json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)
            rej = _ip_registration_rejection(ip, transaction)
            if rej:
                return rej, 429
            output = memserver.merge_transaction(transaction, user_origin=True)
            return output, (200 if output.get("result") else 403)
        except Exception as e:
            return f"Error: {e}", 403
    body = await request.read()
    out, code = await asyncio.to_thread(_work, body, request.headers.get("Content-Type", ""), _ip(request))
    return _resp(out, status=code)


def _ip_registration_rejection(ip, transaction):
    """IP-DIVERSITY cap (non-consensus relay admission control): for a `register` tx, enforce the
    per-source-IP progressive registration budget so one device/range can't script thousands of
    identities. Returns a rejection dict if over budget, else None. Never raises into tx submission."""
    try:
        if not isinstance(transaction, dict) or transaction.get("recipient") != "register":
            return None
        from ops.ratelimit import allow_registration
        cap = getattr(memserver, "max_registrations_per_ip", 64)
        window = getattr(memserver, "max_registrations_window", 7200.0)
        if not allow_registration(ip, str(transaction.get("sender", "")), cap, window):
            return {"result": False,
                    "message": "Too many registrations from this IP/range — one device can onboard only a "
                               "limited number of mining addresses (anti-Sybil). Use fewer addresses."}
    except Exception:
        return None
    return None


async def health(request):
    server_key = _q(request, "key", "none")
    if server_key != memserver.server_key and _ip(request) != "127.0.0.1":
        return _resp("Unauthorized", status=403)
    compress = _q(request, "compress", "none")
    data = {"gc_counts": list(gc.get_count()),
            "gc_objects_tracked": len(gc.get_objects()),
            "gc_stats": gc.get_stats()}
    return _resp(msgpack.packb(data) if compress == "msgpack" else serialize(name="health", output=data, compress=compress))


async def log(request):
    server_key = _q(request, "key", "none")
    if server_key != memserver.server_key and _ip(request) != "127.0.0.1":
        return _resp("Unauthorized", status=403)

    def _read():
        with open(f"{get_home()}/logs/log.log") as logfile:
            return "<br>".join(line for line in logfile.readlines()[-500:]) + "<br>"
    return web.Response(text=await asyncio.to_thread(_read), content_type="text/html",
                        headers={"Access-Control-Allow-Origin": "*"})


async def force_sync(request):
    def _work():
        try:
            forced_ip = _q(request, "ip")
            server_key = _q(request, "key", "none")
            client_ip = _ip(request)
            if server_key == memserver.server_key or client_ip == "127.0.0.1":
                if client_ip == "127.0.0.1" or check_ip(client_ip):
                    memserver.force_sync_ip = forced_ip
                    memserver.peers = [forced_ip]
                    return f"Synchronization is now forced only from {forced_ip} until majority consensus is reached", 200
                return f"Failed to force to sync from {forced_ip}", 200
            return f"Wrong server key {server_key}", 200
        except Exception as e:
            return f"Error: {e}", 403
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def whats_my_ip(request):
    client_ip = _ip(request)
    return _resp(msgpack.packb(client_ip) if _q(request, "compress", "none") == "msgpack" else client_ip)


async def terminate(request):
    server_key = _q(request, "key", "none")
    client_ip = _ip(request)
    if client_ip == "127.0.0.1" or server_key == memserver.server_key:
        memserver.terminate = True
        asyncio.get_event_loop().call_later(0.2, functools.partial(os._exit, 0))
        return _resp("Termination signal sent, node is shutting down...")
    return _resp("Wrong or missing key for a remote node")


async def transaction(request):
    def _work():
        try:
            txid = _q(request, "txid")
            data = get_transaction(txid, logger=logger)
            code = 200
            if not data:
                data, code = "Not found", 404   # 404, not 403: a missing/pruned record isn't "forbidden"
            return serialize(name="txid", output=data, compress=_q(request, "compress", "none")), code
        except Exception as e:
            return f"Error: {e}", 403
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def account_transactions(request):
    if _rate_limited(request, 60):  # DUPSORT scan + up to ~1000 block reads; throttle
        return _RL

    def _work():
        try:
            address = _q(request, "address", memserver.address)
            min_block = int(_q(request, "min_block", "0"))
            data = get_transactions_of_account(account=address, min_block=min_block, logger=logger)
            code = 200
            if not data:
                data, code = "Not found", 404   # 404, not 403: a missing/pruned record isn't "forbidden"
            return serialize(name="account_transactions", output=data, compress=_q(request, "compress", "none")), code
        except Exception as e:
            return f"Error: {e}", 403
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def block_by_hash(request):
    def _work():
        try:
            data = get_block(_q(request, "hash"))
            code = 200
            if not data:
                data, code = "Not found", 404
            return serialize(name="block_hash", output=data, compress=_q(request, "compress", "none")), code
        except Exception as e:
            return f"Error: {e}", 403
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def block_by_number(request):
    def _work():
        try:
            data = get_block_number(_q(request, "number"))
            code = 200
            if not data:
                data, code = "Not found", 404   # 404, not 403: a missing/pruned record isn't "forbidden"
            return serialize(name="block_number", output=data, compress=_q(request, "compress", "none")), code
        except Exception as e:
            return f"Error: {e}", 403
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def blocks_before(request):
    if _rate_limited(request, 60):  # up to 100 block-file reads per call; throttle
        return _RL

    def _work():
        block_hash = _q(request, "hash")
        count = min(int(_q(request, "count", "1")), 100)
        collected, code = [], 200
        try:
            parent = get_block(block_hash)
            if parent:
                parent_hash = parent["parent_hash"]
                for _ in range(count):
                    block = get_block(parent_hash)
                    if not block:
                        break
                    collected.append(block)
                    parent_hash = block["parent_hash"]
                collected.reverse()
            else:
                code = 404
        except Exception as e:
            logger.debug(f"Block collection hit a roadblock: {e}")
            if not collected:
                code = 403
        return serialize(name="blocks_before", output=collected, compress=_q(request, "compress", "none")), code
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def blocks_after(request):
    if _rate_limited(request, 60):  # up to 100 block-file reads per call; throttle
        return _RL

    def _work():
        block_hash = _q(request, "hash")
        count = min(int(_q(request, "count", "1")), 100)
        collected, code = [], 200
        try:
            child = get_block(block_hash)
            if child:
                child_hash = child["child_hash"]
                for _ in range(count):
                    block = get_block(child_hash)
                    if not block:
                        break
                    collected.append(block)
                    child_hash = block["child_hash"]
            else:
                code = 404
        except Exception as e:
            logger.debug(f"Block collection hit a roadblock: {e}")
            if not collected:
                code = 403
        return serialize(name="blocks_after", output=collected, compress=_q(request, "compress", "none")), code
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def get_supply(request):
    def _work():
        readable = _q(request, "readable", "none")
        data = fetch_totals()
        treasury_acc = get_account(address=TREASURY_ADDRESS)
        data.update({"block_number": memserver.latest_block["block_number"]})
        data.update({"treasury": treasury_acc["balance"]})
        data.update({"total_supply": TREASURY_GENESIS + data["produced"] - data["fees"]})
        data.update({"circulating": data["total_supply"] - data["treasury"]})
        if readable == "true":
            for key in ("produced", "fees", "treasury", "circulating", "total_supply"):
                data[key] = to_readable_amount(data[key])
        return data
    return _resp(await asyncio.to_thread(_work))


async def latest_block(request):
    return _resp(serialize(name="latest_block", output=memserver.latest_block, compress=_q(request, "compress", "none")))


async def account(request):
    def _work():
        try:
            addr = _q(request, "address", memserver.address)
            readable = _q(request, "readable", "none")
            data = get_account(addr, create_on_error=False)
            code = 200
            if data:
                from ops import kv_ops
                data["reg_epoch"] = kv_ops.recert_latest(addr)   # latest PoSW recert epoch (presence lease)
                if readable == "true":
                    data.update({"balance": to_readable_amount(data["balance"])})
                    data.update({"produced": to_readable_amount(data["produced"])})
                    data.update({"bonded": to_readable_amount(data["bonded"])})
            else:
                data, code = "Not found", 404   # 404, not 403: a missing/pruned record isn't "forbidden"
            return serialize(name="address", output=data, compress=_q(request, "compress", "none")), code
        except Exception as e:
            return f"Error: {e}", 403
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def announce_peer(request):
    # ECLIPSE HARDENING: rate-limit peer announcements per source IP (eclipse-groundwork throttle).
    if _rate_limited(request, 10):
        return _resp("Rate limited — slow down", status=429)
    try:
        peer_ip = _q(request, "ip")
        if not check_ip(peer_ip):
            return _resp("Invalid IP address")
        if peer_ip not in memserver.peers and peer_ip not in memserver.unreachable.keys():
            status_data = await get_remote_status(peer_ip, logger=logger)
            assert status_data, f"{peer_ip} unreachable"
            address = status_data["address"]
            protocol = status_data["protocol"]
            assert address, "No address detected"
            assert protocol >= get_config()["protocol"], f"Protocol of {peer_ip} is too low"
            await asyncio.to_thread(functools.partial(
                save_peer, ip=peer_ip, address=address, port=get_config()["port"], overwrite=True))
            if peer_ip not in memserver.peer_buffer:
                memserver.peer_buffer.append(peer_ip)
                message = f"Peer {peer_ip} added to peer buffer"
            else:
                message = f"{peer_ip} already waiting in peer buffer"
        else:
            message = f"Peer {peer_ip} is known or invalid"
        return _resp(message)
    except Exception as e:
        return _resp(f"Error: {e}", status=403)


async def snapshot_manifest(request):
    def _work():
        compress = _q(request, "compress", "msgpack")
        snap_manifest, _ = get_current_snapshot(build=True)
        if not snap_manifest:
            return None, 404
        return (msgpack.packb(snap_manifest) if compress == "msgpack" else snap_manifest), 200
    out, code = await asyncio.to_thread(_work)
    if out is None:
        return _resp("No snapshot available (chain too short)", status=404)
    return _resp(out, status=code)


async def snapshot_chunk(request):
    def _work():
        try:
            cid = int(_q(request, "id"))
        except Exception:
            return None, 400
        _, chunks = get_current_snapshot(build=True)
        if not chunks or cid < 0 or cid >= len(chunks):
            return None, 404
        return chunks[cid], 200
    out, code = await asyncio.to_thread(_work)
    if out is None:
        return _resp("No such snapshot chunk", status=code)
    return web.Response(body=out, content_type="application/msgpack",
                        headers={"Access-Control-Allow-Origin": "*"})


_richest_cache = {"height": -1, "value": 0, "address": None}


async def get_richest(request):
    # The largest account by total holdings (balance + bonded) — powers the wallet's relative "coin
    # pile" visual. O(accounts) scan, cached per block height so it runs at most once per block.
    def _work():
        from ops import kv_ops
        try:
            h = memserver.latest_block["block_number"]
        except Exception:
            h = 0
        if _richest_cache["height"] == h and _richest_cache["address"] is not None:
            return {"richest": _richest_cache["value"], "address": _richest_cache["address"], "block_number": h}
        best_v, best_a = 0, None
        for addr, acc in kv_ops.iter_accounts():
            tot = int(acc.get("balance", 0)) + int(acc.get("bonded", 0))
            if tot > best_v:
                best_v, best_a = tot, addr
        _richest_cache.update(height=h, value=best_v, address=best_a)
        return {"richest": best_v, "address": best_a, "block_number": h}
    return _resp(await asyncio.to_thread(_work))


_wealth_cache = {"height": -1, "data": None}


async def get_wealth_stats(request):
    # Distribution of account wealth (balance + bonded) for the wallet's rank / "coin pile". Wealth is
    # heavily right-skewed, so a single O(accounts) pass fits a LOG-NORMAL: it returns count + the richest
    # + the mean/std of ln(total) over non-zero accounts. The client turns its own ln(total) into a z-score
    # -> percentile ("richer than X% of wallets"), a distribution-based rank instead of "% of the single
    # richest wallet" (which one whale dominates). Cached per block height.
    def _work():
        import math
        from ops import kv_ops
        try:
            h = memserver.latest_block["block_number"]
        except Exception:
            h = 0
        if _wealth_cache["height"] == h and _wealth_cache["data"] is not None:
            return _wealth_cache["data"]
        n, s, s2, richest = 0, 0.0, 0.0, 0
        for _addr, acc in kv_ops.iter_accounts():
            tot = int(acc.get("balance", 0)) + int(acc.get("bonded", 0))
            if tot > richest:
                richest = tot
            if tot > 0:
                lt = math.log(tot)
                n += 1; s += lt; s2 += lt * lt
        mean = (s / n) if n else 0.0
        std = math.sqrt(max(0.0, s2 / n - mean * mean)) if n else 0.0
        data = {"count": n, "richest": richest, "log_mean": mean, "log_std": std, "block_number": h}
        _wealth_cache.update(height=h, data=data)
        return data
    return _resp(await asyncio.to_thread(_work))


async def get_treasury_status(request):
    # Treasury governance snapshot for the Quorum tab (doc/treasury.md §3.3): the treasury balance, the burn
    # schedule, and every proposal with its LIVE tally (approving activated-stake vs the 2/3 quorum bar) + status.
    if _rate_limited(request, 60):
        return _RL
    def _work():
        from ops import kv_ops
        from ops.account_ops import get_account, get_bonded_registry
        from ops.settlement_ops import treasury_justified, _vote_activated
        from ops.mining_ops import epoch_of, selection_shares
        from protocol import (TREASURY_ADDRESS, TREASURY_MAX_SPEND_BPS, BPS_DENOM, TREASURY_SPEND_PERIOD,
                              TREASURY_BURN_BPS, SETTLE_NUM, SETTLE_DEN)
        try:
            h = memserver.latest_block["block_number"]
        except Exception:
            h = 0
        epoch = epoch_of(h + 1)
        acc = get_account(TREASURY_ADDRESS, create_on_error=False)
        bal = int(acc.get("balance", 0)) if acc else 0
        reg = get_bonded_registry()
        total_activated = sum(selection_shares(i["bonded"]) for i in reg.values() if _vote_activated(i, epoch))
        max_spend = bal * TREASURY_MAX_SPEND_BPS // BPS_DENOM
        props = []
        for pid, spend in kv_ops.treasury_proposals_all():
            expiry = int(spend.get("expiry", 0))
            executed = kv_ops.treasury_executed_exists(pid)
            if not executed and h > expiry:
                continue                                    # expired + never executed -> dead; skip (scales the list)
            voters = kv_ops.treasury_voters(pid)
            approving = sum(selection_shares(reg[v]["bonded"]) for v in voters if v in reg and _vote_activated(reg[v], epoch))
            status = "executed" if executed else ("passed" if treasury_justified(pid, reg, epoch) else "open")
            amt = int(spend.get("amount", 0))
            props.append({"pid": pid, "recipient": spend.get("recipient"), "amount": amt,
                          "memo": spend.get("memo", ""), "nonce": spend.get("nonce"), "expiry": expiry,
                          "expires_in": max(0, expiry - h), "approving_shares": approving, "voters": len(voters),
                          "status": status, "within_cap": amt <= max_spend})
        props.sort(key=lambda p: (p["status"] != "open", -p["approving_shares"]))
        props = props[:50]                                  # cap the returned list (open/active first)
        return {"block_number": h, "epoch": epoch, "treasury": bal,
                "total_activated_shares": total_activated,
                "quorum_shares": (total_activated * SETTLE_NUM) // SETTLE_DEN,
                "settle_num": SETTLE_NUM, "settle_den": SETTLE_DEN,
                "max_spend": max_spend, "max_spend_bps": TREASURY_MAX_SPEND_BPS,
                "burn_bps": TREASURY_BURN_BPS, "spend_period": TREASURY_SPEND_PERIOD,
                "next_burn_block": ((h // TREASURY_SPEND_PERIOD) + 1) * TREASURY_SPEND_PERIOD,
                "proposals": props}
    return _resp(await asyncio.to_thread(_work))


async def get_posw_difficulty(request):
    # Current registration PoSW difficulty (doc/ip-spoofing-and-sybil.md): the CONSENSUS multiplier + required
    # sequential-step count for a registration anchored at the current finalized anchor epoch. The wallet reads
    # this to (a) prove at the right difficulty and (b) show the user the expected wait ("×N due to a spike").
    def _work():
        from ops.reg_difficulty import difficulty_multiplier
        from ops.mining_ops import epoch_of
        from ops import kv_ops
        from protocol import POSW_T, POSW_ANCHOR_OFFSET, POSW_DIFF_WINDOW
        try:
            h = memserver.latest_block["block_number"]
        except Exception:
            h = 0
        anchor_epoch = epoch_of(max(0, h - POSW_ANCHOR_OFFSET))
        mult = difficulty_multiplier(anchor_epoch)
        recent = kv_ops.recert_count_in_window(anchor_epoch - POSW_DIFF_WINDOW + 1, anchor_epoch)
        return {"block_number": h, "anchor_epoch": anchor_epoch, "multiplier": mult,
                "base_t": POSW_T, "required_t": POSW_T * mult,
                "recent_registrations": recent, "window_epochs": POSW_DIFF_WINDOW}
    return _resp(await asyncio.to_thread(_work))


_rich_list_cache = {"height": -1, "list": None}


async def get_rich_list(request):
    # Top-N accounts by total holdings (balance + bonded) — powers the wallet's rich list / leaderboard.
    # O(accounts) scan, cached per block height (top 100 kept, sliced to n) so it runs at most once/block.
    def _work():
        from ops import kv_ops
        try:
            h = memserver.latest_block["block_number"]
        except Exception:
            h = 0
        try:
            n = max(1, min(100, int(_q(request, "n", "25"))))
        except Exception:
            n = 25
        if _rich_list_cache["height"] == h and _rich_list_cache["list"] is not None:
            return {"block_number": h, "rich_list": _rich_list_cache["list"][:n]}
        top = []
        for addr, acc in kv_ops.iter_accounts():
            bal, bond = int(acc.get("balance", 0)), int(acc.get("bonded", 0))
            tot = bal + bond
            if tot > 0:
                top.append((tot, addr, bal, bond))
        top.sort(key=lambda t: t[0], reverse=True)
        rich = [{"address": a, "total": tot, "balance": bal, "bonded": bond} for (tot, a, bal, bond) in top[:100]]
        _rich_list_cache.update(height=h, list=rich)
        return {"block_number": h, "rich_list": rich[:n]}
    return _resp(await asyncio.to_thread(_work))


async def get_open_weights(request):
    # Present open registry + open-lane weights for the CURRENT epoch — the execution node reads this to
    # accrue the presence dividend to currently-present miners, fidelity-weighted (doc/presence-dividend.md).
    if _rate_limited(request, 60):
        return _RL
    def _work():
        from ops.account_ops import get_open_registry
        from ops.mining_ops import open_shares, epoch_of
        epoch = epoch_of(memserver.latest_block["block_number"])
        reg = get_open_registry(epoch)
        weights = {addr: open_shares(info.get("fidelity", 0)) for addr, info in reg.items()}
        return {"epoch": epoch, "weights": weights}
    return _resp(await asyncio.to_thread(_work))


async def get_settled(request):
    # The canonical SETTLED execution-layer checkpoint (Phase 2): the (exec_cursor, state_root) the bonded
    # quorum has attested. Execution nodes / bridges read this as the L1-enforced exec-layer state.
    def _work():
        from ops.settlement_ops import latest_settled
        cursor, root = latest_settled()
        return {"exec_cursor": cursor, "state_root": root}
    return _resp(await asyncio.to_thread(_work))


async def resolve_alias(request):
    from ops import alias_ops
    name = _q(request, "name", "")
    owner = await asyncio.to_thread(alias_ops.resolve_alias, name)
    return _resp({"name": name, "owner": owner})   # owner is None when the alias is unregistered


async def aliases_of(request):
    from ops import kv_ops
    addr = _q(request, "address", memserver.address)
    names = await asyncio.to_thread(kv_ops.aliases_of, addr)
    return _resp({"address": addr, "aliases": names})


async def get_htlc(request):
    # A single HTLC (cross-chain atomic swap) by id (== the lock tx's txid), or null if unknown.
    from ops import kv_ops
    hid = _q(request, "id", "")
    doc = await asyncio.to_thread(kv_ops.htlc_get, hid)
    return _resp({"id": hid, "htlc": doc})


async def htlcs(request):
    # All HTLCs, optionally filtered to those where `address` is the sender OR claimant (the wallet's swaps).
    if _rate_limited(request, 60):
        return _RL
    from ops import kv_ops
    addr = _q(request, "address")
    allh = await asyncio.to_thread(kv_ops.htlc_all)
    if addr:
        allh = {i: d for i, d in allh.items() if d.get("sender") == addr or d.get("claimant") == addr}
    return _resp({"htlcs": allh})


async def static_handler(request):
    rel = request.match_info.get("path", "")
    full = os.path.normpath(os.path.join(_STATIC_DIR, rel))
    if not (full == _STATIC_DIR or full.startswith(_STATIC_DIR + os.sep)) or not os.path.isfile(full):
        return web.Response(status=404, text="Not found")
    ctype, _ = mimetypes.guess_type(full)
    # NO-CACHE + permissive CORS so wallet/explorer edits are picked up immediately and a cross-origin
    # page can load the assets (the old NoCacheStaticFileHandler behaviour).
    headers = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
               "Pragma": "no-cache", "Access-Control-Allow-Origin": "*"}
    return web.FileResponse(full, headers=headers)


async def favicon(request):
    p = os.path.join(_HERE, "graphics", "favicon.ico")
    return web.FileResponse(p) if os.path.isfile(p) else web.Response(status=404)


async def make_app(port):
    app = web.Application()
    app.add_routes([
        web.get("/", home),
        web.get("/get_snapshot_manifest", snapshot_manifest),
        web.get("/get_snapshot_chunk", snapshot_chunk),
        web.get("/get_transactions_of_account", account_transactions),
        web.get("/get_transaction", transaction),
        web.get("/get_blocks_after", blocks_after),
        web.get("/get_blocks_before", blocks_before),
        web.get("/get_block_number", block_by_number),
        web.get("/get_block", block_by_hash),
        web.get("/get_account", account),
        web.get("/transaction_pool", _dump_handler("transaction_pool", lambda: memserver.transaction_pool)),
        web.get("/transaction_hash_pool", _dump_handler("transactions_hash_pool", lambda: {
            "transactions_hash_pool": consensus.transaction_hash_pool,
            "majority_transactions_hash_pool": consensus.majority_transaction_pool_hash})),
        web.get("/transaction_buffer", _dump_handler("transaction_buffer", lambda: memserver.tx_buffer)),
        web.get("/user_transaction_buffer", _dump_handler("user_transaction_buffer", lambda: memserver.user_tx_buffer)),
        web.get("/trust_pool", _dump_handler("trust_pool_data", lambda: consensus.trust_pool)),
        web.get("/get_latest_block", latest_block),
        web.get("/get_supply", get_supply),
        web.get("/announce_peer", announce_peer),
        web.get("/status_pool", _dump_handler("status_pool", lambda: consensus.status_pool)),
        web.get("/mining_status", mining_status),
        web.get("/status", status),
        web.get("/peers", _dump_handler("peers", lambda: list(memserver.peers))),
        web.get("/peer_buffer", _dump_handler("peer_buffer", lambda: list(memserver.peer_buffer))),
        web.get("/unreachable", _dump_handler("unreachable", lambda: memserver.unreachable)),
        web.get("/block_producers_hash_pool", _dump_handler("block_producers_hash_pool", lambda: {
            "block_producers_hash_pool": consensus.block_producers_hash_pool,
            "majority_block_producers_hash_pool": consensus.majority_block_producers_hash})),
        web.get("/block_producers", _dump_handler("block_producers", lambda: list(memserver.block_producers))),
        web.get("/block_hash_pool", _dump_handler("block_hash_pool", lambda: {
            "block_opinions": consensus.block_hash_pool,
            "majority_block_opinion": consensus.majority_block_hash})),
        web.get("/get_recommended_fee", get_recommended_fee),
        web.get("/get_richest", get_richest),
        web.get("/wealth_stats", get_wealth_stats),
        web.get("/treasury_status", get_treasury_status),
        web.get("/posw_difficulty", get_posw_difficulty),
        web.get("/get_rich_list", get_rich_list),
        web.get("/get_open_weights", get_open_weights),
        web.get("/get_settled", get_settled),
        web.get("/resolve_alias", resolve_alias),
        web.get("/get_htlc", get_htlc),
        web.get("/htlcs", htlcs),
        web.get("/get_aliases_of", aliases_of),
        web.get("/terminate", terminate),
        web.get("/health", health),
        web.post("/submit_transaction", submit_transaction),
        web.get("/log", log),
        web.get("/whats_my_ip", whats_my_ip),
        web.get("/force_sync", force_sync),
        web.get("/favicon.ico", favicon),
        web.get("/static/miner.{ext:html|js|css}", legacy_static_redirect),   # old name -> interface.*
        web.get("/static/{path:.*}", static_handler),
    ])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    # In NADO_TESTNET mode bind to the node's own (loopback) IP so several nodes can share the port on
    # distinct 127.0.0.x addresses; on mainnet bind all interfaces (reachable).
    listen_address = get_config()["ip"] if os.environ.get("NADO_TESTNET") else "0.0.0.0"
    site = web.TCPSite(runner, host=listen_address, port=port)
    await site.start()
    await asyncio.Event().wait()


"""warning, no intensive operations or locks should be invoked from API interface"""
logger = get_logger(logger_name="main_logger")

allow_async()

updated_version = versioner.update_version()
if updated_version:
    versioner.set_version(updated_version)

if not os.path.exists(f"{get_home()}/blocks"):
    make_folders()
    make_genesis(
        address=GENESIS_ADDRESS,        # genesis address == treasury (no personal premine)
        balance=TREASURY_GENESIS,        # bootstrap allocation minted to the treasury
        ip="78.102.98.72",
        port=9173,
        timestamp=GENESIS_TIMESTAMP,
        logger=logger,
    )

# Self-heal the recert_by_epoch presence index on EVERY boot (idempotent). get_open_registry reads this
# epoch-keyed index; on a node upgraded across the heartbeat->lease refactor it starts empty, so any miner
# whose recert predates the index would be reported ABSENT despite a valid lease. Mirroring the existing
# recerts once fixes them without a re-registration. No-op once the index is populated (DUPSORT dedups).
try:
    from ops import kv_ops as _kv
    _bf = _kv.backfill_recert_by_epoch()
    if _bf:
        logger.warning(f"recert_by_epoch backfill: mirrored {_bf} recert row(s) into the presence index")
except Exception as _e:
    logger.error(f"recert_by_epoch backfill failed (non-fatal): {_e}")

if not keyfile_found():
    save_keys(generate_keys())
    save_peer(ip=get_config()["ip"],
              address=load_keys()["address"],
              port=get_config()["port"],
              peer_trust=10000)

info_path = os.path.normpath(f'{get_home()}/private/keys.dat')
logger.info(f"Key location: {info_path}")

# in testnet mode several nodes share the port on distinct 127.0.0.x IPs, so check THIS node's
# own ip:port, not localhost (which a sibling node would falsely occupy)
_port_check_host = get_config()["ip"] if os.environ.get("NADO_TESTNET") else "localhost"
assert not is_port_in_use(get_config()["port"], _port_check_host), "Port already in use, exiting"
signal.signal(signal.SIGINT, handler)
signal.signal(signal.SIGTERM, handler)

memserver = MemServer(logger=logger)

logger.info(f"NADO version {memserver.version} started")
logger.info(f"Your address: {memserver.address}")
logger.info(f"Your IP: {memserver.ip}")

# S4.3: surface the bonded producer registry loudly at startup. total_shares == 0 means NO eligible
# producer (every bond < B_MIN, or none seeded) -> fail-closed selection silently produces no blocks.
_registry = get_bonded_registry()
logger.warning(f"Bonded producer registry: {len(_registry)} eligible, total_shares={total_shares(_registry)}")
logger.info(f"Promiscuity mode: {memserver.promiscuous}")
logger.info(f"Cascade depth limit: {memserver.cascade_limit}")

consensus = ConsensusClient(memserver=memserver, logger=logger)
consensus.start()

core = CoreClient(memserver=memserver, consensus=consensus, logger=logger)
core.start()

peers = PeerClient(memserver=memserver, consensus=consensus, logger=logger)
peers.start()

messages = MessageClient(memserver=memserver, consensus=consensus, core=core, peers=peers, logger=logger)
messages.start()

logger.info("Starting Request Handler")

asyncio.run(make_app(get_config()["port"]))
