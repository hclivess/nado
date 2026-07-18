import asyncio
import functools
import hashlib
import os
import re
import signal
import socket
import sys

from ops import codec
import zstandard as _zstd
from aiohttp import web

# zstd block-sync wire compressor (level 3 matches the on-disk block format; writes the content size into the
# frame so the client can decode). python-zstandard ZstdCompressor is NOT thread-safe, so use a THREAD-LOCAL
# instance — a shared one, hit concurrently by the API + peer-serving paths, corrupts memory and SEGVs.
import threading as _threading
_zstd_wire_tls = _threading.local()
def _zstd_wire():
    c = getattr(_zstd_wire_tls, "c", None)
    if c is None:
        c = _zstd_wire_tls.c = _zstd.ZstdCompressor(level=3)
    return c

import versioner
import time
from config import get_protocol, get_config, get_timestamp_seconds, hostport
from ops import self_update
from genesis import make_genesis, make_folders
from loops.consensus_loop import ConsensusClient
from loops.core_loop import CoreClient
from loops.message_loop import MessageClient
from loops.peer_loop import PeerClient
from memserver import MemServer
from ops.account_ops import get_account, fetch_totals, get_bonded_registry
from ops.address_ops import proof_sender
from signatures import verify as _mldsa_verify, unhex as _mldsa_unhex
from ops.mining_ops import total_shares
from ops.block_ops import get_block, recommended_fee, get_block_number, SYNC_BATCH_MAX, SYNC_BATCH_BYTES
from ops.data_ops import get_home, allow_async, get_byte_size
from ops.key_ops import keyfile_found, generate_keys, save_keys
from ops.log_ops import get_logger
from ops.peer_ops import save_peer, get_remote_status, check_ip, me_to, known_peer_ips
from ops.transaction_ops import get_transaction, get_transactions_of_account, to_readable_amount
from ops import snapshot_ops
from protocol import GENESIS_ADDRESS, TREASURY_ADDRESS, TREASURY_GENESIS, GENESIS_TIMESTAMP, CHAIN_ID, ADDRESS_PREFIX

import gc  # replaces pympler/muppy — the full-heap walk fatally trips CPython GC under asyncio load

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_HERE, "static")


def is_port_in_use(port: int, host: str = "localhost") -> bool:
    """True if a TCP connect to host:port succeeds — used at boot to refuse a second node on the same port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def handler(signum, frame):
    """SIGINT/SIGTERM handler: set memserver.terminate (loops drain gracefully), persist the off-chain
    message pool to disk, then exit 0. Block/state integrity needs no flush here (atomic writes + replay)."""
    logger.info(f"Terminating: {signum}: {frame}")
    memserver.terminate = True
    # Persist the off-chain message pool so a restart/redeploy doesn't drop undelivered DMs + prekeys.
    try:
        n = memserver.message_pool.stats().get("messages", 0)
        memserver.message_pool.save(memserver.message_pool_path)
        logger.info(f"Message pool persisted ({n} messages)")
    except Exception as e:
        logger.error(f"Message pool save on shutdown failed: {e}")
    sys.exit(0)


def serialize(output, name=None, compress=None):
    """Wire-encode an API payload per ?compress: 'zstd' -> zstd(JSON codec) (the node<->node block-sync
    format), anything else -> left for JSON, with non-dict outputs wrapped under `name`."""
    if compress == "zstd":
        # zstd(codec/JSON): the node<->node block-sync wire format (ops/block_ops.get_blocks_after/before).
        # Block bodies are dominated by hex ML-DSA sigs/pubkeys; zstd recovers most of it over the wire.
        output = _zstd_wire().compress(codec.pack(output))
    elif not isinstance(output, dict) and name:
        output = {name: output}
    return output


# Bulk snapshot sync: checkpoints are captured to disk at incorporation (loops/core_loop.maybe_checkpoint_state)
# and advertised/served from there (ops/snapshot_ops persist/load helpers) — no lazy on-request build.


# --------------------------------------------------------------------------------------------------
# aiohttp helpers — the node's HTTP API is served by aiohttp (Tornado retired). The inter-node HTTP
# CLIENT already used aiohttp (ops/peer_ops, ops/block_ops, ops/snapshot_ops), so this removes the
# last Tornado dependency. "No intensive operations or locks from the API"; blocking DB/file work is
# pushed to a worker thread via asyncio.to_thread so the event loop stays responsive.
# --------------------------------------------------------------------------------------------------
from ops.net_ops import client_ip_from, unpack_tx

try:
    _TRUSTED_PROXIES = frozenset(get_config().get("trusted_proxies") or [])
except Exception:
    _TRUSTED_PROXIES = frozenset()


def _ip(request):
    """The client's source IP. Defaults to the raw socket peer; X-Forwarded-For is honored ONLY when the peer
    is a configured trusted reverse proxy (config 'trusted_proxies'), so the per-IP rate limits + anti-Sybil
    registration cap cannot be header-spoofed on a directly-exposed node."""
    return client_ip_from(request.remote or "unknown", request.headers.get("X-Forwarded-For", ""), _TRUSTED_PROXIES)


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
    """True when the caller's IP (proxy-aware via _ip) has exceeded `limit` requests per `window`
    seconds — the per-endpoint DoS throttle backing every _RL early return. The bucket is keyed by
    (ip, path): a single per-IP bucket shared across endpoints let the web wallet's own
    /mining_status + /tags polling (120/min each) consume the budget and 429 that same user's
    /submit_transaction (30/min) — read polling starved tx submission."""
    from ops.ratelimit import allow
    return not allow(f"{_ip(request)}|{request.path}", limit, window)


_RL = web.json_response({"result": False, "message": "Rate limited — slow down"}, status=429,
                        headers={"Access-Control-Allow-Origin": "*"})


def _q(request, key, default=None):
    """Query-string parameter `key`, or `default` when absent."""
    return request.query.get(key, default)


def _qint(request, key, default):
    """Query-string parameter `key` parsed as an int, falling back to `default` on absence OR a
    non-numeric value — so a malformed `?count=abc` / `?height=xyz` yields a clean default instead of
    a ValueError-500 out of a worker thread. Callers still cap/bound the returned int (e.g. count is
    clamped to SYNC_BATCH_MAX). A too-long digit string also falls through to default (CPython caps
    int(str) length), so a giant-number param can't burn CPU here either."""
    try:
        return int(request.query.get(key, default))
    except (TypeError, ValueError):
        return default


# --- pool / field dump handlers (the repetitive read-only ones) ----------------------------------
def _dump_handler(name, getter):
    """Factory for the repetitive read-only dump endpoints (/peers, /transaction_pool, ...): a GET
    handler returning `getter()` serialized under `name`. Runs inline on the event loop — only use
    for cheap in-memory reads. Honors ?compress=msgpack|zstd."""
    async def _h(request):
        """Dump getter()'s live value serialized under `name`."""
        return _resp(serialize(name=name, output=getter(), compress=_q(request, "compress", "none")))
    return _h


async def home(request):
    """GET /: 302 to the static NADO Interface page."""
    # The node's landing page is the static, client-side NADO Interface (wallet + miner + explorer + shield).
    raise web.HTTPFound("/static/interface.html")


async def legacy_static_redirect(request):
    """GET /static/miner.{html|js|css}: 302 to the renamed interface.* asset so old bookmarks keep working."""
    # The page/assets were renamed miner.* -> interface.* (it's a full interface now, not just a miner).
    # Redirect the old paths so saved links / bookmarks to /static/miner.html keep working.
    raise web.HTTPFound("/static/interface." + request.match_info["ext"])


async def status(request):
    """GET /status: the node's status dict — address, chain ends (latest/earliest hash, weight),
    finalized_height + ffg_finalized, protocol/version, chain_id (the network partition key peers gate
    admission on), and the latest FINALIZED snapshot's height/hash for bootstrap discovery. Degrades
    single fields to null rather than 403ing (exec nodes and wallets poll this as a lifeline).
    ?compress=msgpack|zstd."""
    def _build():
        """Assemble the status dict (worker thread)."""
        # Defensive: /status is the exec node's lifeline (finalized_height) and the wallet's connection
        # check, so NO single field may 403 the whole endpoint. Guard the block-ends + snapshot lookups
        # (in rolling mode a pruned body could make these falsy) — degrade to null, never crash.
        lb = memserver.latest_block if isinstance(memserver.latest_block, dict) else {}
        eb = memserver.earliest_block if isinstance(memserver.earliest_block, dict) else {}
        status_dict = {
            "reported_uptime": memserver.reported_uptime,
            "address": memserver.address,
            "transaction_pool_hash": memserver.transaction_pool_hash,
            "upcoming_block_hash": memserver.upcoming_block_hash,
            "latest_block_hash": lb.get("block_hash"),
            "latest_block_weight": lb.get("cumulative_weight", 0),
            "earliest_block_hash": eb.get("block_hash"),
            "finalized_height": memserver.finalized_height,
            "ffg_finalized": memserver.ffg_finalized,
            "protocol": memserver.protocol,
            "version": memserver.version,
            # UPDATE VISIBILITY: the commit this process RUNS, the newest origin/main commit this node
            # has SEEN (cached by the last /update or daily check — never fetched inline here), and
            # whether it is running behind it. Lets anyone spot a lagging node from /status alone.
            "running_commit": self_update.running_head(),
            "latest_main": self_update.latest_known(),
            "update_available": bool(self_update.latest_known() and self_update.running_head()
                                     and self_update.latest_known() != self_update.running_head()),
            # NETWORK PARTITION KEY: peers gate admission on this (peer_loop) so nodes on a different
            # chain (e.g. a pre-relaunch alphanet) never enter the status/consensus pools — a foreign
            # chain's advertised weight would otherwise stall production via the caught-up gate.
            "chain_id": CHAIN_ID,
        }
        try:
            _ch = snapshot_ops.latest_final_checkpoint_height(memserver.finalized_height)
            snap_manifest = snapshot_ops.load_checkpoint_manifest(_ch) if _ch is not None else None
            snap_manifest = snap_manifest if isinstance(snap_manifest, dict) else None
        except Exception:
            snap_manifest = None
        status_dict["snapshot_height"] = snap_manifest.get("snapshot_height") if snap_manifest else None
        status_dict["snapshot_hash"] = snap_manifest.get("snapshot_hash") if snap_manifest else None
        return serialize(name="status", output=status_dict, compress=_q(request, "compress", "none"))
    try:
        return _resp(await asyncio.to_thread(_build))
    except Exception as e:
        return _resp(f"Error: {e}", status=403)


async def mining_status(request):
    """GET /mining_status?address=&compress=: the address's mining view (lane, presence, share odds)
    at the current height. `address` defaults to this node's own. Full account-set scan under the
    hood, so rate-limited to 120/min per IP."""
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
    """GET /get_recommended_fee: {"fee": N} — the tip block's mean fee + 1, what a wallet should attach."""
    return _resp({"fee": recommended_fee(memserver.latest_block) + 1})


async def transactions_by_id(request):
    """POST /transactions_by_id?compress=: body = codec list of txids (bounded); returns the named
    transactions from OUR pool — the expensive half of mempool set reconciliation, proportional to
    what the caller is actually missing instead of the whole pool. Rate-limited 120/min per IP."""
    if _rate_limited(request, 120):
        return _RL
    body = await request.read()

    def _work(raw):
        from ops import codec as _codec
        if not raw or len(raw) > (1 << 20):
            return "Error: bad body", 400
        try:
            ids = _codec.unpack(raw)
        except Exception:
            return "Error: undecodable body", 400
        if not isinstance(ids, list) or len(ids) > 1000:
            return "Error: too many ids", 400
        wanted = {i for i in ids if isinstance(i, str) and len(i) <= 64}
        txs = [t for t in memserver.transaction_pool if t.get("txid") in wanted]
        return serialize(name="transactions", output=txs, compress=_q(request, "compress", "none")), 200

    out, code = await asyncio.to_thread(_work, body)
    return _resp(out, status=code)


async def submit_transaction(request):
    """POST /submit_transaction: decode a JSON-codec tx from the body (size-bounded by unpack_tx so an
    oversized/malformed payload can't balloon memory) and merge it into the pool as user-origin. `register`
    txs additionally pass the per-source-IP anti-Sybil registration budget. 200 on accept, 403 on reject,
    429 over the 30/min IP rate limit."""
    if _rate_limited(request, 30):
        return _RL

    def _work(body, ip):
        """Decode, anti-Sybil check, and pool-merge the tx (worker thread)."""
        try:
            transaction = unpack_tx(body)   # size-bounded JSON-codec decode (ops/net_ops.py)
            rej = _ip_registration_rejection(ip, transaction)
            if rej:
                return rej, 429
            output = memserver.merge_transaction(transaction, user_origin=True)
            return output, (200 if output.get("result") else 403)
        except Exception as e:
            return f"Error: {e}", 403
    body = await request.read()
    out, code = await asyncio.to_thread(_work, body, _ip(request))
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
    """GET /health?key=&compress=: CPython GC counters/stats for memory-leak triage. Requires the node's
    server key unless called from 127.0.0.1 (heap introspection is not for the public)."""
    server_key = _q(request, "key", "none")
    if server_key != memserver.server_key and _ip(request) != "127.0.0.1":
        return _resp("Unauthorized", status=403)
    compress = _q(request, "compress", "none")
    data = {"gc_counts": list(gc.get_count()),
            "gc_objects_tracked": len(gc.get_objects()),
            "gc_stats": gc.get_stats()}
    return _resp(serialize(name="health", output=data, compress=compress))


async def log(request):
    """GET /log?key=: the last 500 node log lines as <br>-joined HTML. Server-key or localhost only
    (logs leak peer IPs and operational detail)."""
    server_key = _q(request, "key", "none")
    if server_key != memserver.server_key and _ip(request) != "127.0.0.1":
        return _resp("Unauthorized", status=403)

    def _read():
        """Read the log tail (worker thread)."""
        with open(f"{get_home()}/logs/log.log") as logfile:
            return "<br>".join(line for line in logfile.readlines()[-500:]) + "<br>"
    return web.Response(text=await asyncio.to_thread(_read), content_type="text/html",
                        headers={"Access-Control-Allow-Origin": "*"})


async def force_sync(request):
    """GET /force_sync?ip=&key=: pin block sync to the single peer `ip` until majority consensus is
    reached (recovery tool). Server-key or localhost only, and the TARGET must be a routable public IP
    (check_ip) so an authenticated call can't be aimed at loopback/RFC1918/metadata (SSRF hardening)."""
    def _work():
        """Validate caller + target and pin the sync source (worker thread)."""
        try:
            forced_ip = _q(request, "ip")
            server_key = _q(request, "key", "none")
            client_ip = _ip(request)
            if server_key == memserver.server_key or client_ip == "127.0.0.1":
                # validate the TARGET too (not just the caller): reject a non-routable/internal forced_ip so
                # an authenticated force-sync can't be pointed at loopback/RFC1918/metadata (SSRF hardening).
                if not (forced_ip and check_ip(forced_ip)):
                    return f"Invalid or non-routable target IP for force-sync: {forced_ip}", 400
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
    """GET /whats_my_ip: the caller's IP as this node sees it (trusted-proxy aware). ?compress=msgpack."""
    client_ip = _ip(request)
    return _resp(client_ip)


async def terminate(request):
    """GET /terminate?key=: shut the node down (terminate flag, then hard os._exit 0.2s later so the
    response still flushes). Localhost or server-key only."""
    server_key = _q(request, "key", "none")
    client_ip = _ip(request)
    if client_ip == "127.0.0.1" or server_key == memserver.server_key:
        memserver.terminate = True
        asyncio.get_event_loop().call_later(0.2, functools.partial(os._exit, 0))
        return _resp("Termination signal sent, node is shutting down...")
    return _resp("Wrong or missing key for a remote node")


async def transaction(request):
    """GET /get_transaction?txid=&compress=: one transaction by txid; 404 when unknown or pruned."""
    def _work():
        """Blocking tx lookup (worker thread)."""
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
    """GET /get_transactions_of_account?address=&min_block=&compress=: the address's transactions from
    `min_block` upward (address defaults to this node's own). Costs a DUPSORT index scan plus up to
    ~1000 block reads, so rate-limited to 60/min per IP. 404 when none found."""
    if _rate_limited(request, 60):  # DUPSORT scan + up to ~1000 block reads; throttle
        return _RL

    def _work():
        """Blocking DUPSORT index scan + block reads (worker thread)."""
        try:
            address = _q(request, "address", memserver.address)
            min_block = int(_q(request, "min_block", "0"))
            data = get_transactions_of_account(account=address, min_block=min_block)
            code = 200
            if not data:
                data, code = "Not found", 404   # 404, not 403: a missing/pruned record isn't "forbidden"
            return serialize(name="account_transactions", output=data, compress=_q(request, "compress", "none")), code
        except Exception as e:
            return f"Error: {e}", 403
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def block_by_hash(request):
    """GET /get_block?hash=&compress=: one block by hash; 404 when unknown or pruned."""
    def _work():
        """Blocking block read (worker thread)."""
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
    """GET /get_block_number?number=&compress=: one block by height; 404 when unknown or pruned."""
    def _work():
        """Blocking block read (worker thread)."""
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


def _collect_block_chain(start_hash, count, link_field):
    """Walk `link_field` ("child_hash" forward / "parent_hash" backward) from the block at
    `start_hash`, collecting up to min(count, SYNC_BATCH_MAX) linked blocks under the
    SYNC_BATCH_BYTES budget (fat-block batches must stay far under the sync client's 64 MiB wire
    bomb cap). Standalone + thread-safe (LMDB reads only) — the shared engine of the two block-sync
    endpoints below. Returns (blocks-in-walk-order, http_code)."""
    collected, size, code = [], 0, 200
    try:
        anchor = get_block(start_hash)
        if not anchor:
            return collected, 404
        link = anchor[link_field]
        for _ in range(min(count, SYNC_BATCH_MAX)):
            block = get_block(link)
            if not block:
                break
            collected.append(block)
            size += get_byte_size(block)
            if size > SYNC_BATCH_BYTES:
                break
            link = block[link_field]
    except Exception as e:
        logger.debug(f"Block collection hit a roadblock: {e}")
        if not collected:
            code = 403
    return collected, code


async def blocks_before(request):
    """GET /get_blocks_before?hash=&count=&compress=: up to `count` ancestors of `hash` (count capped at
    SYNC_BATCH_MAX + byte-budgeted, see _collect_block_chain), returned oldest-first. Rate-limited
    60/min per IP since each block is a disk read. ?compress=zstd is the block-sync wire format peers use."""
    if _rate_limited(request, 60):  # up to SYNC_BATCH_MAX block-file reads per call; throttle
        return _RL

    def _work():
        collected, code = _collect_block_chain(_q(request, "hash"), _qint(request, "count", 1),
                                               link_field="parent_hash")
        collected.reverse()          # walked toward genesis; serve oldest-first
        return serialize(name="blocks_before", output=collected, compress=_q(request, "compress", "none")), code
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def blocks_after(request):
    """GET /get_blocks_after?hash=&count=&compress=: up to `count` descendants of `hash` (count capped
    at SYNC_BATCH_MAX + byte-budgeted, see _collect_block_chain), ascending — the primary block-sync
    pull peers use with ?compress=zstd. Rate-limited 60/min per IP since each block is a disk read."""
    if _rate_limited(request, 60):  # up to SYNC_BATCH_MAX block-file reads per call; throttle
        return _RL

    def _work():
        collected, code = _collect_block_chain(_q(request, "hash"), _qint(request, "count", 1),
                                               link_field="child_hash")
        return serialize(name="blocks_after", output=collected, compress=_q(request, "compress", "none")), code
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def get_supply(request):
    """GET /get_supply?readable=: emission totals at the current height — produced, fees, treasury,
    total_supply (= treasury genesis + produced - fees) and circulating (= total - treasury).
    ?readable=true formats amounts as human-readable decimals."""
    def _work():
        """Compute the supply totals (worker thread)."""
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
    """GET /get_latest_block?compress=: the in-memory latest block (no disk read)."""
    return _resp(serialize(name="latest_block", output=memserver.latest_block, compress=_q(request, "compress", "none")))


async def account(request):
    """GET /get_account?address=&readable=&compress=: the account record (balance/produced/bonded, plus
    schemaless fields) enriched with reg_epoch, the latest PoSW recert epoch (presence lease). No
    create-on-read; 404 when the account doesn't exist. ?readable=true formats the amounts."""
    def _work():
        """Blocking account + recert lookup (worker thread)."""
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


async def account_mempool(request):
    """GET /get_account_mempool?address=: the address's PENDING (mempool — not yet sealed into a block)
    activity, summarized for wallet display: raw totals arriving into / leaving the spendable balance
    (free_in/free_out) and moving into / out of the execution-layer playable balance (exec_in/exec_out),
    plus light per-tx summaries (no pubkeys/signatures/proofs — a pool dump is megabytes of PQ material,
    this is a few hundred bytes). Pure in-memory pool scan + at most a few alias lookups per call."""
    if _rate_limited(request, 60):   # full O(mempool) scan + per-tx alias LMDB reads; throttle like the other scans
        return _RL
    def _work():
        """Blocking pool scan (worker thread — alias resolution reads LMDB)."""
        try:
            addr = _q(request, "address", memserver.address)
            lb = memserver.latest_block if isinstance(memserver.latest_block, dict) else {}
            height = int(lb.get("block_number") or 0)
            from ops import alias_ops
            free_in = free_out = exec_in = exec_out = 0
            txs = []
            for tx in list(memserver.transaction_pool):
                if not isinstance(tx, dict):
                    continue
                if int(tx.get("max_block") or 0) <= height:
                    continue    # expired leftover — can never enter a block, so it isn't "confirming"
                sender, recipient = tx.get("sender"), tx.get("recipient")
                amount, fee = int(tx.get("amount") or 0), int(tx.get("fee") or 0)
                data = tx.get("data") if isinstance(tx.get("data"), dict) else {}
                fi = fo = ei = eo = 0
                # exits proven straight to data["addr"] (bridge/shield claims), whoever submitted them
                if recipient in ("bridge_withdraw", "unshield") and data.get("addr") == addr:
                    fi += int(data.get("amount") or 0)
                if sender == addr:
                    if recipient == "withdraw":            # matured unbond claim: bonded -> spendable
                        fi += int(data.get("amount") or 0)
                    elif recipient == "bridge":            # L1 -> exec (playable) deposit
                        fo += amount + fee
                        ei += amount
                    elif recipient == "blob":              # exec call: the fee leaves L1; a value escrows from playable
                        fo += fee
                        op = data.get("op")
                        if op == "call":
                            eo += int(data.get("value") or 0)
                        elif op == "bridge_withdraw":      # playable -> L1 (lands via a later bridge_withdraw claim)
                            eo += int(data.get("amount") or 0)
                    elif recipient in ("bridge_withdraw", "unshield", "unbond", "register", "heartbeat",
                                       "msgkey", "attest", "commit", "reveal", "settle", "slash",
                                       "xmsg", "htlc_claim"):
                        pass                               # fee-exempt / no spendable movement (exit credits handled above)
                    else:                                  # plain send, bond, shield, alias, htlc_lock, ...
                        fo += amount + fee
                        if recipient == addr:
                            fi += amount                   # self-send: only the fee actually leaves
                else:
                    # incoming: direct address match, or a send addressed to one of the address's aliases
                    to = recipient
                    if to and not to.startswith(ADDRESS_PREFIX):
                        to = alias_ops.resolve_alias(recipient) or recipient
                    if to == addr:
                        fi += amount
                if fi or fo or ei or eo:
                    free_in += fi; free_out += fo; exec_in += ei; exec_out += eo
                    if len(txs) < 50:
                        txs.append({"txid": tx.get("txid"), "sender": sender, "recipient": recipient,
                                    "amount": amount, "fee": fee, "op": data.get("op") if data else None,
                                    "free_in": fi, "free_out": fo, "exec_in": ei, "exec_out": eo})
            out = {"address": addr, "height": height,
                   "free_in": free_in, "free_out": free_out, "exec_in": exec_in, "exec_out": exec_out,
                   "txs": txs}
            return serialize(name="account_mempool", output=out, compress=_q(request, "compress", "none")), 200
        except Exception as e:
            return f"Error: {e}", 403
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


async def announce_peer(request):
    """GET /announce_peer?ip=: offer this node a peer candidate. The IP must pass check_ip (routable,
    non-internal), answer a live remote /status probe, and run a compatible protocol before it is saved
    and queued in the peer buffer (never straight into the active set). Rate-limited 10/min per IP —
    the eclipse-attack groundwork throttle."""
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
            assert protocol >= get_protocol(), f"Protocol of {peer_ip} is too low"
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
    """Serve the highest FINALIZED persisted checkpoint's manifest (reorg-safe). Cheap disk read."""
    def _work():
        """Load the latest finalized checkpoint manifest (worker thread)."""
        compress = _q(request, "compress", "none")
        h = snapshot_ops.latest_final_checkpoint_height(memserver.finalized_height)
        manifest = snapshot_ops.load_checkpoint_manifest(h) if h is not None else None
        if not manifest:
            return None, 404
        # HONOR ?compress: peers pull this with ?compress=zstd (ops.snapshot_ops.fetch_snapshot). Returning the
        # raw dict here made /get_snapshot_manifest ignore the param and answer JSON while /status et al. sent
        # zstd — so every zstd-expecting fetcher hit "Unknown frame descriptor" and no node could ever
        # re-anchor off this one. serialize() with compress="none" still returns the dict unchanged.
        return serialize(output=manifest, compress=compress), 200
    out, code = await asyncio.to_thread(_work)
    if out is None:
        return _resp("No snapshot available (chain too short / no finalized checkpoint)", status=404)
    return _resp(out, status=code)


async def snapshot_chunk(request):
    """Serve one chunk of a checkpoint by id. `height` pins the checkpoint the fetcher's manifest came
    from (defaults to the latest finalized one) so chunks stay consistent with that manifest."""
    def _work():
        """Load one checkpoint chunk from disk (worker thread)."""
        try:
            cid = int(_q(request, "id"))
        except Exception:
            return None, 400
        h = _q(request, "height")
        if h is not None:
            try:
                height = int(h)
            except (TypeError, ValueError):
                return None, 400          # malformed ?height= -> clean 400, not a worker-thread 500
        else:
            height = snapshot_ops.latest_final_checkpoint_height(memserver.finalized_height)
        if height is None:
            return None, 404
        chunk = snapshot_ops.load_checkpoint_chunk(height, cid)
        if chunk is None:
            return None, 404
        return chunk, 200
    out, code = await asyncio.to_thread(_work)
    if out is None:
        return _resp("No such snapshot chunk", status=code or 404)
    return web.Response(body=out, content_type="application/msgpack",
                        headers={"Access-Control-Allow-Origin": "*"})


_richest_cache = {"height": -1, "value": 0, "address": None}


async def get_richest(request):
    """GET /get_richest: the single largest account by balance+bonded (wallet "coin pile" visual).
    O(accounts) scan, but cached per block height so it costs at most one scan per block."""
    # The largest account by total holdings (balance + bonded) — powers the wallet's relative "coin
    # pile" visual. O(accounts) scan, cached per block height so it runs at most once per block.
    def _work():
        """Cached-per-height O(accounts) max scan (worker thread)."""
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
    """GET /wealth_stats: log-normal fit of the wealth distribution — {count, richest, log_mean,
    log_std, block_number} over non-zero accounts (balance+bonded). The client converts its own
    ln(total) to a z-score/percentile for a whale-proof "richer than X%" rank. Cached per height."""
    # Distribution of account wealth (balance + bonded) for the wallet's rank / "coin pile". Wealth is
    # heavily right-skewed, so a single O(accounts) pass fits a LOG-NORMAL: it returns count + the richest
    # + the mean/std of ln(total) over non-zero accounts. The client turns its own ln(total) into a z-score
    # -> percentile ("richer than X% of wallets"), a distribution-based rank instead of "% of the single
    # richest wallet" (which one whale dominates). Cached per block height.
    def _work():
        """Single-pass log-normal fit over non-zero accounts, cached per height (worker thread).
        The same pass also builds the WALLET-DISTRIBUTION data the explorer stats chart shows:
        `buckets` — non-zero wallet counts per NADO decade (<0.01, 0.01–0.1, …, 100k–1M, ≥1M) —
        and the held-supply concentration (`sum_total`, `top10`, `top100`, raw as strings)."""
        import heapq
        import math
        from ops import kv_ops
        from protocol import DENOMINATION
        try:
            h = memserver.latest_block["block_number"]
        except Exception:
            h = 0
        if _wealth_cache["height"] == h and _wealth_cache["data"] is not None:
            return _wealth_cache["data"]
        n, s, s2, richest = 0, 0.0, 0.0, 0
        buckets = [0] * 10
        top, gsum = [], 0
        for _addr, acc in kv_ops.iter_accounts():
            tot = int(acc.get("balance", 0)) + int(acc.get("bonded", 0))
            if tot > richest:
                richest = tot
            if tot > 0:
                lt = math.log(tot)
                n += 1; s += lt; s2 += lt * lt
                gsum += tot
                nado = tot / DENOMINATION
                buckets[0 if nado < 0.01 else min(9, int(math.floor(math.log10(nado))) + 3)] += 1
                heapq.heappush(top, tot)
                if len(top) > 100:
                    heapq.heappop(top)
        mean = (s / n) if n else 0.0
        std = math.sqrt(max(0.0, s2 / n - mean * mean)) if n else 0.0
        tops = sorted(top, reverse=True)
        data = {"count": n, "richest": richest, "log_mean": mean, "log_std": std, "block_number": h,
                "buckets": buckets, "sum_total": str(gsum),
                "top10": str(sum(tops[:10])), "top100": str(sum(tops))}
        _wealth_cache.update(height=h, data=data)
        return data
    return _resp(await asyncio.to_thread(_work))


# ------------------------------------------------ peer geolocation (interface stats world map) ----
GEO_API = "http://ip-api.com/batch"   # free tier: http-only, 100 IPs/batch — fine: server-side + TTL-cached
GEO_TTL = 6 * 3600                    # re-geolocate peers at most every 6 hours (IPs rarely move)
_geo_state = {"cache": None, "computing": False}


def _geo_cache_path():
    return f"{get_home()}/index/geo_peers.json"


def _geo_peer_status() -> dict:
    """Every peer IP this node knows -> 'connected' | 'unreachable' | 'known'. Connected = the live peer
    set; unreachable = the temp-exiled set; known = the persistent peer table (peers.dat) + the admission
    buffer. Non-routable/own IPs are dropped via check_ip (not geolocatable), and the set is capped so a
    hostile peer-table flood can't turn the geolocation batch into unbounded outbound traffic."""
    connected = set(memserver.peers)
    unreachable = set(memserver.unreachable.keys())
    known = set(known_peer_ips()) | set(memserver.peer_buffer)
    status = {}
    for ip in known | connected | unreachable:
        ip = str(ip)
        if not check_ip(ip):
            continue
        # precedence: a currently-connected peer wins; unreachable beats merely-known
        status[ip] = "connected" if ip in connected else ("unreachable" if ip in unreachable else "known")
    return dict(sorted(status.items())[:500])


def _geo_fetch(ips):
    """Batch-geolocate up to 100 IPs per ip-api.com call (SERVER-side, so the browser never talks to the
    http-only free tier — no mixed content). Returns {ip: {country, cc, lat, lon, city}}; best-effort —
    a failed/rate-limited batch just stops and yields what we have so far."""
    import json as _json
    import time as _time
    import urllib.request
    out = {}
    for i in range(0, len(ips), 100):
        batch = ips[i:i + 100]
        body = _json.dumps([{"query": ip, "fields": "query,status,country,countryCode,lat,lon,city"}
                            for ip in batch]).encode("utf-8")
        try:
            req = urllib.request.Request(GEO_API, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                arr = _json.loads(r.read().decode("utf-8"))
            for rec in arr:
                if rec.get("status") == "success" and rec.get("query"):
                    out[rec["query"]] = {"country": rec.get("country"), "cc": rec.get("countryCode"),
                                         "lat": rec.get("lat"), "lon": rec.get("lon"), "city": rec.get("city")}
        except Exception:
            break               # rate-limited / offline: stop, use what we have
        _time.sleep(1.0)        # stay well under the free-tier rate limit
    return out


def _geo_compute():
    """Kick ONE background re-geolocation; callers keep serving the stale cache meanwhile."""
    if _geo_state["computing"]:
        return
    _geo_state["computing"] = True

    def work():
        try:
            import json as _json
            import time as _time
            ips = list(_geo_peer_status().keys())
            geo = _geo_fetch(ips) if ips else {}
            old = _geo_state["cache"]
            if not geo and old and old.get("geo"):
                geo = old["geo"]    # ip-api down: keep the last good locations rather than blanking the map
            cache = {"ts": int(_time.time()), "geo": geo}
            _geo_state["cache"] = cache
            try:
                tmp = _geo_cache_path() + ".tmp"
                with open(tmp, "w") as f:
                    _json.dump(cache, f)
                os.replace(tmp, _geo_cache_path())
            except Exception:
                pass            # persistence is best-effort; the in-memory cache still serves
        except Exception as e:
            logger.warning(f"geo compute failed: {e}")
        finally:
            _geo_state["computing"] = False

    _threading.Thread(target=work, daemon=True).start()


async def geo_peers(request):
    """GET /geo_peers: geolocated peers for the interface's stats world map — {status, ts, count,
    status_counts, points:[{ip,lat,lon,country,cc,city,status}], countries}. Geolocation is TTL-cached
    server-side + persisted across restarts; each peer's live status (connected|known|unreachable) is
    recomputed fresh per call. The first (cold) call kicks a background lookup and returns 'computing'.
    Exposes nothing new: /peers and /unreachable already publish these IPs."""
    def _work():
        import json as _json
        import time as _time
        cache = _geo_state["cache"]
        if cache is None:
            try:
                with open(_geo_cache_path()) as f:
                    cache = _json.load(f)
                _geo_state["cache"] = cache
            except Exception:
                cache = None
        if cache is None or int(_time.time()) - int(cache.get("ts", 0)) >= GEO_TTL:
            _geo_compute()      # refresh in the background; serve stale meanwhile if we have it
        if cache is None:
            return {"status": "computing", "points": [], "countries": []}
        geo = cache.get("geo", {}) or {}
        status_map = _geo_peer_status()
        points, by_country = [], {}
        counts = {"connected": 0, "known": 0, "unreachable": 0}
        for ip, g in geo.items():
            if g.get("lat") is None or g.get("lon") is None:
                continue
            st = status_map.get(ip, "known")    # located earlier but no longer in any set -> merely known
            points.append({"ip": ip, "lat": g["lat"], "lon": g["lon"], "country": g.get("country"),
                           "cc": g.get("cc"), "city": g.get("city"), "status": st})
            counts[st] = counts.get(st, 0) + 1
            key = (g.get("cc") or "??", g.get("country") or "Unknown")
            by_country[key] = by_country.get(key, 0) + 1
        countries = [{"cc": cc, "country": c, "count": n}
                     for (cc, c), n in sorted(by_country.items(), key=lambda kv: -kv[1])]
        return {"status": "ok", "ts": cache.get("ts"), "count": len(points),
                "status_counts": counts, "points": points, "countries": countries}
    return _resp(await asyncio.to_thread(_work))


async def get_treasury_status(request):
    """GET /treasury_status: treasury governance snapshot for the Quorum tab — balance, spend cap
    (bps of balance), burn schedule, activated-stake quorum bar, and every live proposal with its
    tally + status (open/passed/executed). Expired never-executed proposals are dropped and the list
    is capped at 50, open-first, so the response stays bounded. Rate-limited 60/min per IP."""
    # Treasury governance snapshot for the Quorum tab (doc/treasury.md §3.3): the treasury balance, the burn
    # schedule, and every proposal with its LIVE tally (approving activated-stake vs the 2/3 quorum bar) + status.
    if _rate_limited(request, 60):
        return _RL
    def _work():
        """Tally every live proposal against the activated bonded registry (worker thread)."""
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
    """GET /posw_difficulty: the CONSENSUS registration-PoSW difficulty at the current finalized anchor
    epoch — multiplier, base/required sequential steps, and recent registration count in the window.
    Wallets read it to prove at the right difficulty and show the expected wait."""
    # Current registration PoSW difficulty (doc/ip-spoofing-and-sybil.md): the CONSENSUS multiplier + required
    # sequential-step count for a registration anchored at the current finalized anchor epoch. The wallet reads
    # this to (a) prove at the right difficulty and (b) show the user the expected wait ("×N due to a spike").
    def _work():
        """Compute the difficulty a prover should use RIGHT NOW (worker thread) — the strict v2
        chain-derived requirement; there is no other mode."""
        from ops.reg_difficulty import difficulty_multiplier, _window_count
        from ops.mining_ops import epoch_of
        from protocol import POSW_T, POSW_ANCHOR_OFFSET, POSW_DIFF_WINDOW
        try:
            h = memserver.latest_block["block_number"]
        except Exception:
            h = 0
        max_block = h + 6                      # the CLI/wallet target a registration a few blocks out
        anchor_epoch = epoch_of(max(0, max_block - POSW_ANCHOR_OFFSET))
        mult = difficulty_multiplier(anchor_epoch)
        recent = _window_count(anchor_epoch - POSW_DIFF_WINDOW, anchor_epoch - 1)
        return {"block_number": h, "anchor_epoch": anchor_epoch, "multiplier": mult,
                "base_t": POSW_T, "required_t": POSW_T * mult,
                "recent_registrations": recent, "window_epochs": POSW_DIFF_WINDOW}
    return _resp(await asyncio.to_thread(_work))


_rich_list_cache = {"height": -1, "list": None}


async def get_rich_list(request):
    """GET /get_rich_list?n=: top-n accounts by balance+bonded (n clamped to 1..100, default 25) — the
    wallet leaderboard. O(accounts) scan cached per block height (top 100 kept, sliced to n)."""
    # Top-N accounts by total holdings (balance + bonded) — powers the wallet's rich list / leaderboard.
    # O(accounts) scan, cached per block height (top 100 kept, sliced to n) so it runs at most once/block.
    def _work():
        """Cached-per-height O(accounts) top-100 scan (worker thread)."""
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
    """GET /get_open_weights[?epoch=E]: open-lane weights {address: fidelity-weighted shares}. With ?epoch=
    it returns the DETERMINISTIC, reconstructible weights_at_epoch(E) (present set + fidelity AS OF epoch E)
    — what the execution node accrues the presence dividend against, per completed epoch. Without it, the
    CURRENT epoch's live weights (legacy). Rate-limited 60/min per IP."""
    if _rate_limited(request, 60):
        return _RL
    q_epoch = request.query.get("epoch")
    def _work():
        """Read the open-lane weights (worker thread)."""
        from ops.mining_ops import open_shares, epoch_of
        if q_epoch is not None:
            from ops.dividend_ops import weights_at_epoch
            try:
                e = int(q_epoch)
            except (TypeError, ValueError):
                return {"error": "bad epoch"}
            # WEIGHT SAFETY (idle-GC, ops/gc_ops.py): weights_at_epoch(E) replays recert rows down
            # to E - SATURATION_LOOKBACK_EPOCHS; rows below the gc_rows_below watermark are GONE.
            # Refuse (410-style error) rather than serve a silently-truncated reconstruction — a
            # cold exec node must bootstrap from a SETTLED checkpoint instead of ancient replay.
            from protocol import SATURATION_LOOKBACK_EPOCHS
            from ops import kv_ops as _kv
            # the reconstruction needs rows from max(0, E - lookback); refuse iff pruning has
            # crossed that floor (with nothing pruned yet — watermark 0 — every epoch serves).
            if max(0, e - SATURATION_LOOKBACK_EPOCHS) < _kv.meta_get_int("gc_rows_below", 0):
                return {"error": "epoch too old: recert history pruned (bootstrap the exec node "
                                 "from a settled checkpoint)", "epoch": e}
            return {"epoch": e, "weights": weights_at_epoch(e)}
        from ops.account_ops import get_open_registry
        epoch = epoch_of(memserver.latest_block["block_number"])
        reg = get_open_registry(epoch)
        weights = {addr: open_shares(info.get("fidelity", 0)) for addr, info in reg.items()}
        return {"epoch": epoch, "weights": weights}
    return _resp(await asyncio.to_thread(_work))


async def duty_committee(request):
    """GET /duty_committee[?epoch=E&address=A]: the epoch's DUTY COMMITTEE (consensus-aggregation.md) —
    {epoch, seats:{address:n}}. If ?address= is given, also {in_committee: bool, seats_of: n}. A bonded
    validator (the browser light-miner included) posts its merged `duty` tx ONLY when it holds a seat,
    so this is the pre-check that stops non-committee validators from broadcasting rejected duties.
    Defaults to the current tip's epoch. Rate-limited 60/min per IP."""
    if _rate_limited(request, 60):
        return _RL
    q_epoch = request.query.get("epoch")
    addr = request.query.get("address")

    def _work():
        from ops.block_ops import duty_committee_for_epoch
        from ops.mining_ops import epoch_of
        try:
            e = int(q_epoch) if q_epoch is not None else epoch_of(memserver.latest_block["block_number"])
        except (TypeError, ValueError):
            return {"error": "bad epoch"}
        try:
            seats = duty_committee_for_epoch(e)
        except Exception:
            seats = {}                       # beacon anchor unavailable -> empty (no committee derivable)
        out = {"epoch": e, "seats": seats}
        if addr:
            out["in_committee"] = addr in seats
            out["seats_of"] = seats.get(addr, 0)
        return out
    return _resp(await asyncio.to_thread(_work))


async def get_dividend_inflow(request):
    """GET /get_dividend_inflow?epoch=E: the TOTAL DIVIDEND_POOL inflow credited during epoch E — the
    deterministic, epoch-bound amount the execution node distributes over weights_at_epoch(E). 400 on a bad
    epoch. Rate-limited 60/min per IP."""
    if _rate_limited(request, 60):
        return _RL
    try:
        e = int(request.query.get("epoch", ""))
    except (TypeError, ValueError):
        return _resp({"error": "bad epoch"}, status=400)
    def _work():
        from ops.kv_ops import dividend_inflow_get
        return {"epoch": e, "inflow": dividend_inflow_get(e)}
    return _resp(await asyncio.to_thread(_work))


async def get_settled(request):
    """GET /get_settled[?ns=]: the canonical SETTLED execution-layer checkpoint {ns, exec_cursor, state_root}
    for namespace `ns` (default DEFAULT_NS) — the state the bonded quorum has attested; what exec nodes and
    bridges treat as L1-enforced."""
    from protocol import DEFAULT_NS, valid_namespace
    ns = _q(request, "ns", DEFAULT_NS)
    if not valid_namespace(ns):
        return _resp({"error": "invalid ns"}, status=400)
    def _work():
        """Read the latest settled checkpoint for the namespace (worker thread)."""
        from ops.settlement_ops import latest_settled
        cursor, root = latest_settled(ns)
        return {"ns": ns, "exec_cursor": cursor, "state_root": root}
    return _resp(await asyncio.to_thread(_work))


async def resolve_alias(request):
    """GET /resolve_alias?name=: alias -> owner address; input is lowercased (registry names are
    all-lowercase) and owner is null when unregistered."""
    from ops import alias_ops
    name = _q(request, "name", "").strip().lower()   # registry names are all-lowercase
    owner = await asyncio.to_thread(alias_ops.resolve_alias, name)
    return _resp({"name": name, "owner": owner})   # owner is None when the alias is unregistered


async def msig_address(request):
    """GET /msig_address?threshold=&members=: derive the M-of-N multisig address for a descriptor
    (members comma-separated, any order — canonicalized by sorting). Pure function over the inputs
    (nothing is registered on-chain); clients can compute the same locally, this is a convenience/
    cross-check endpoint. Returns the canonical descriptor + address, 400 on a bad descriptor."""
    from ops import multisig_ops
    try:
        threshold = int(_q(request, "threshold", "0"))
        members = sorted(m.strip().lower() for m in _q(request, "members", "").split(",") if m.strip())
        multisig_ops.validate_descriptor({"threshold": threshold, "members": members})
        return _resp({"threshold": threshold, "members": members,
                      "address": multisig_ops.multisig_address(threshold, members)})
    except Exception as e:
        return _resp({"error": str(e)}, status=400)


async def aliases_of(request):
    """GET /get_aliases_of?address=: every alias name owned by the address (defaults to this node's own)."""
    from ops import kv_ops
    addr = _q(request, "address", memserver.address)
    names = await asyncio.to_thread(kv_ops.aliases_of, addr)
    return _resp({"address": addr, "aliases": names})


async def get_htlc(request):
    """GET /get_htlc?id=: one HTLC (cross-chain atomic swap) by id (the lock tx's txid); htlc is null when unknown."""
    # A single HTLC (cross-chain atomic swap) by id (== the lock tx's txid), or null if unknown.
    from ops import kv_ops
    hid = _q(request, "id", "")
    doc = await asyncio.to_thread(kv_ops.htlc_get, hid)
    return _resp({"id": hid, "htlc": doc})


async def htlcs(request):
    """GET /htlcs?address=: all HTLCs, optionally filtered to those where `address` is sender or
    claimant (a wallet's own swaps). Full-set read — rate-limited 60/min per IP."""
    # All HTLCs, optionally filtered to those where `address` is the sender OR claimant (the wallet's swaps).
    if _rate_limited(request, 60):
        return _RL
    from ops import kv_ops
    addr = _q(request, "address")
    allh = await asyncio.to_thread(kv_ops.htlc_all)
    if addr:
        allh = {i: d for i, d in allh.items() if d.get("sender") == addr or d.get("claimant") == addr}
    return _resp({"htlcs": allh})


# HTML pages are served with their /static/<asset> references stamped ?v=<file mtime>. The stamped URL
# changes whenever the file on disk changes, so the assets themselves can be cached as immutable (by the
# browser AND the CDN edge) while an edit still propagates on the next page load — the interface pulls
# ~1.5 MB of JS (i18n.js alone is ~1 MiB), which under the old blanket no-store re-downloaded every visit.
_STATIC_REF_RE = re.compile(rb'((?:src|href)=")(/static/[A-Za-z0-9_./-]+)(")')
# ES-module import specifiers inside a served .js:  from "./x.js"  ·  import("./x.js")  ·  import "./x.js"
_JS_IMPORT_RE = re.compile(rb'(\bfrom\s*["\']|import\s*\(\s*["\']|import\s*["\'])(\.{1,2}/[A-Za-z0-9_./-]+\.js)(["\'])')


def _js_epoch():
    """A single version number = the NEWEST mtime across ALL static .js files. Every .js reference (HTML
    <script> AND in-file ES imports) is stamped with THIS, so editing ANY module bumps the version of the
    WHOLE graph at once. That guarantees coherency: a browser/CDN can never load a fresh game.js against a
    stale cached nadodapp.js (the bug that made 'sign in do nothing' after an SDK export was added) — the
    stamped URLs all change together, so a cache miss on one is a cache miss on all its dependencies."""
    newest = 0
    try:
        for root, _dirs, names in os.walk(_STATIC_DIR):
            for name in names:
                if name.endswith(".js"):
                    newest = max(newest, int(os.stat(os.path.join(root, name)).st_mtime))
    except OSError:
        pass
    return newest


def _stamp_static_refs(html):
    """Rewrite src/href="/static/<asset>" references in `html` (bytes) to .../<asset>?v=<version>. A .js
    asset is stamped with the global JS epoch (so all modules bust together); other assets use their own
    mtime. References whose file doesn't exist are left untouched."""
    jsep = _js_epoch()
    def sub(m):
        rel = m.group(2)[len(b"/static/"):].decode()
        try:
            v = jsep if rel.endswith(".js") else int(os.stat(os.path.join(_STATIC_DIR, rel)).st_mtime)
        except (OSError, UnicodeDecodeError):
            return m.group(0)
        return m.group(1) + m.group(2) + b"?v=%d" % v + m.group(3)
    return _STATIC_REF_RE.sub(sub, html)


def _stamp_js_imports(js_bytes):
    """Rewrite a served .js file's relative ES-module imports (from './x.js') to '.../x.js?v=<js epoch>',
    so the shared modules (nadodapp.js, nadotx.js, …) are fetched at the SAME coherent version as the
    importing file — never a stale CDN-cached copy that's missing a newly-added export."""
    v = b"?v=%d" % _js_epoch()
    return _JS_IMPORT_RE.sub(lambda m: m.group(1) + m.group(2) + v + m.group(3), js_bytes)


def _html_response(request, full):
    """Serve an HTML file with stamped asset references, a strong ETag over the stamped body, and
    revalidation caching (no-cache = store + ask; a 304 answers the ask in one small round trip)."""
    with open(full, "rb") as f:
        body = _stamp_static_refs(f.read())
    etag = '"' + hashlib.blake2b(body, digest_size=16).hexdigest() + '"'
    # X-Frame-Options/frame-ancestors: the wallet must NEVER be framed — the exec_sign / forum-login confirm is
    # the only human gate, and a header-delivered frame denial defeats clickjacking of it (a <meta> CSP cannot).
    headers = {"Cache-Control": "no-cache", "ETag": etag, "Access-Control-Allow-Origin": "*",
               "X-Frame-Options": "DENY", "Content-Security-Policy": "frame-ancestors 'none'"}
    inm = request.headers.get("If-None-Match", "")
    if etag in (t.strip() for t in inm.split(",")):
        return web.Response(status=304, headers=headers)
    return web.Response(body=body, content_type="text/html", charset="utf-8", headers=headers)


async def static_handler(request):
    """GET /static/{path}: serve a file from static/ with open CORS. HTML goes through _html_response
    (asset-stamped + ETag revalidation). An asset requested with a numeric ?v= is content-addressed by
    construction (the stamp is its mtime), so it's served immutable for a year — cacheable by browsers
    and the CDN edge. Everything else is no-cache: stored but revalidated (ETag/Last-Modified -> 304),
    so wallet/explorer edits are picked up immediately without re-downloading unchanged bytes.
    Path-traversal contained: the normpath'd target must stay under _STATIC_DIR or it 404s."""
    rel = request.match_info.get("path", "")
    full = os.path.normpath(os.path.join(_STATIC_DIR, rel))
    if not (full == _STATIC_DIR or full.startswith(_STATIC_DIR + os.sep)) or not os.path.isfile(full):
        return web.Response(status=404, text="Not found")
    if full.endswith(".html"):
        return _html_response(request, full)
    immutable = request.query.get("v", "").isdigit()
    headers = {"Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache",
               "Access-Control-Allow-Origin": "*"}
    # A .js module's relative imports are rewritten to the coherent global JS version so the CDN can never
    # pair a fresh importer with a stale imported module (missing-export -> dead page). Read + rewrite in
    # process (JS files are small); everything else streams via FileResponse.
    if full.endswith(".js"):
        with open(full, "rb") as f:
            body = _stamp_js_imports(f.read())
        return web.Response(body=body, content_type="application/javascript", charset="utf-8", headers=headers)
    return web.FileResponse(full, headers=headers)


async def favicon(request):
    """GET /favicon.ico: the icon from graphics/, or 404 if absent."""
    p = os.path.join(_HERE, "graphics", "favicon.ico")
    return web.FileResponse(p) if os.path.isfile(p) else web.Response(status=404)


async def robots_txt(request):
    """GET /robots.txt: allow-all + the shared sitemap. The node answers this for EVERY domain that
    fronts it (get.nadochain.com and all the game subdomains), and the sitemap reference is what makes
    nadochain.com/sitemap.xml's cross-host entries valid for crawlers (sitemaps.org cross-submits)."""
    return web.Response(text="User-agent: *\nAllow: /\n\nSitemap: https://nadochain.com/sitemap.xml\n",
                        content_type="text/plain")


# --- off-chain messaging (doc/messaging.md): a gossiped, ephemeral, E2E-encrypted message pool. The node
#     is a BLIND relay — it stores/serves opaque ciphertext and only gates on shape/size/PoW + a REGISTERED
#     sender with a valid ML-DSA signature. It never decrypts, and none of this touches consensus. --------
def _msg_is_registered(address):
    """True when `address` is a registered on-chain account — the message pool's spam-admission gate
    (only identities that paid registration PoSW may post). Never raises."""
    try:
        acc = get_account(address, create_on_error=False)
        return bool(acc) and acc.get("registered", 0) == 1
    except Exception:
        return False


def _msg_verify_sig(public_key, sender, env):
    """proof_sender binds the pubkey to the sender address; then the ML-DSA sig must verify over the
    signing digest (every envelope field except `sig`). Same verify() the tx path uses."""
    from ops.message_pool import signing_digest
    try:
        if not public_key or not proof_sender(sender=sender, public_key=public_key):
            return False
        return _mldsa_verify(signed=env.get("sig", ""), public_key=public_key,
                             message=_mldsa_unhex(signing_digest(env)))
    except Exception:
        return False


def _prekey_verify_sig(public_key, address, bundle):
    """Prekey-bundle authenticity: the pubkey must bind to `address` (proof_sender) and the ML-DSA sig
    must verify over the bundle's signing digest. False (never raises) on any failure."""
    from ops.message_pool import prekey_signing_digest
    try:
        if not public_key or not proof_sender(sender=address, public_key=public_key):
            return False
        return _mldsa_verify(signed=bundle.get("sig", ""), public_key=public_key,
                             message=_mldsa_unhex(prekey_signing_digest(bundle)))
    except Exception:
        return False


async def post_message(request):
    """POST /message: submit an opaque E2E-encrypted envelope to the gossiped off-chain message pool.
    The node is a blind relay: admission checks shape/size/PoW plus a REGISTERED sender with a valid
    ML-DSA signature (size-bounded decode via unpack_tx) — it never decrypts. Returns {result, reason,
    id}; 403 on rejection, 429 over the 30/min IP rate limit."""
    if _rate_limited(request, 30):
        return _RL
    def _work(body):
        """Decode + pool-admit the envelope (worker thread)."""
        try:
            env = unpack_tx(body)
            ok, why, mid = memserver.message_pool.add_message(
                env, get_timestamp_seconds(), _msg_is_registered, _msg_verify_sig)
            return {"result": ok, "reason": why, "id": mid}, (200 if ok else 403)
        except Exception as e:
            return f"Error: {e}", 403
    body = await request.read()
    out, code = await asyncio.to_thread(_work, body)
    return _resp(out, status=code)


async def get_tags(request):
    """GET /tags?since=: message-pool recipient tags newer than pool cursor `since`, plus the current
    cursor — the poll clients use to notice mail without revealing who they are. Rate-limited 120/min."""
    if _rate_limited(request, 120):
        return _RL
    try:
        since = int(_q(request, "since", "0") or 0)
    except Exception:
        since = 0
    def _work():
        """Snapshot tags + cursor (worker thread)."""
        mp = memserver.message_pool
        return {"tags": mp.list_tags(since_seq=since), "cursor": mp.cursor()}
    return _resp(await asyncio.to_thread(_work))


async def get_message(request):
    """GET /message?id=: one opaque ciphertext envelope by id; 404 when unknown or expired."""
    mid = _q(request, "id", "")
    env = await asyncio.to_thread(memserver.message_pool.get_message, mid)
    if env is None:
        return _resp("Not found", status=404)
    return _resp({"message": env})


async def post_msg_key(request):
    """POST /msg_key: publish a signed ML-KEM prekey bundle to the pool (legacy path — the on-chain
    fee-exempt `msgkey` tx is preferred). Same registered-sender + signature gating as messages;
    rate-limited 20/min per IP."""
    if _rate_limited(request, 20):
        return _RL
    def _work(body):
        """Decode + pool-admit the prekey bundle (worker thread)."""
        try:
            bundle = unpack_tx(body)
            ok, why = memserver.message_pool.add_prekey(bundle, _msg_is_registered, _prekey_verify_sig)
            return {"result": ok, "reason": why}, (200 if ok else 403)
        except Exception as e:
            return f"Error: {e}", 403
    body = await request.read()
    out, code = await asyncio.to_thread(_work, body)
    return _resp(out, status=code)


async def get_msg_key(request):
    """GET /msg_key?address=: the recipient's ML-KEM-768 messaging pubkey — the on-chain `kem_pub`
    account field first (consensus state, never wiped), the legacy off-chain prekey pool as fallback;
    404 when neither exists. The response's `source` field says which path served it."""
    addr = _q(request, "address", "")
    def _work():
        """Chain-first kem_pub lookup with pool fallback (worker thread)."""
        # ON-CHAIN FIRST: the recipient's ML-KEM-768 messaging pubkey is bound to their identity by the
        # fee-exempt `msgkey` tx (schemaless account field `kem_pub`) — consensus state, on every node, never
        # wiped, no pre-publish/wallet-open needed. Fall back to the legacy off-chain prekey pool if absent.
        acc = get_account(addr, create_on_error=False)
        if acc and acc.get("kem_pub"):
            return {"kem_pub": acc["kem_pub"], "address": addr, "source": "chain"}, 200
        bundle = memserver.message_pool.get_prekey(addr)
        if bundle is not None:
            return {"bundle": bundle, "source": "pool"}, 200
        return "Not found", 404
    out, code = await asyncio.to_thread(_work)
    return _resp(out, status=code)


# Deep-linkable interface URLs — /aliases, /messages, /send, … serve the SAME single-page interface, so a
# shared link like https://get.nadochain.com/aliases opens straight on that tab (the client reads the path).
_TAB_PATHS = ("wallet", "send", "receive", "aliases", "stake", "quorum", "multisig", "messages",
              "history", "rich", "stats", "swap", "shield", "settlement", "rollup", "explore", "settings")


async def interface_page(request):
    """Serve the single-page interface for the deep-linkable tab paths (/wallet, /send, /aliases, ...)."""
    return _html_response(request, os.path.join(_HERE, "static", "interface.html"))


async def update_node(request):
    """GET /update: ask this node to SELF-UPDATE — fast-forward onto origin/main of the official repo and
    restart its services when new code actually landed (ops/self_update.py has the full safety story).
    Callable by ANYONE: the caller controls only the WHEN, never the WHAT, and an already-current node
    answers up_to_date and does nothing. After a real update the node forwards the ping to its linked
    peers (the update WAVE) before its own restart, so one call updates the whole reachable fleet;
    current nodes do not re-forward, so the wave dies out on its own. ?wave=0 disables forwarding."""
    result = await asyncio.to_thread(self_update.check_and_update, "remote")
    if result.get("status") == "updated" and request.query.get("wave", "1") != "0":
        peer_list = list(memserver.peers)

        async def _fan_out():
            try:
                import aiohttp
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
                    async def _one(p):
                        try:
                            async with s.get(f"http://{hostport(p, get_config()['port'])}/update?wave=1"):
                                pass
                        except Exception:
                            pass
                    await asyncio.gather(*(_one(p) for p in peer_list))
            except Exception:
                pass
        asyncio.create_task(_fan_out())
    return _resp(result)


async def make_app(port):
    """Build the aiohttp application with every route and serve it forever. Mainnet binds IPv4 on
    0.0.0.0 plus a best-effort SEPARATE IPV6_V6ONLY socket (so v4 clients keep plain v4 addresses for
    rate-limit keys); NADO_TESTNET binds only the node's own configured IP so several nodes can share
    the port on distinct 127.0.0.x addresses. Never returns."""
    app = web.Application()
    app.add_routes([
        web.get("/", home),
        *[web.get("/" + _t, interface_page) for _t in _TAB_PATHS],
        web.post("/message", post_message),
        web.get("/tags", get_tags),
        web.get("/message", get_message),
        web.post("/msg_key", post_msg_key),
        web.get("/msg_key", get_msg_key),
        web.get("/get_snapshot_manifest", snapshot_manifest),
        web.get("/get_snapshot_chunk", snapshot_chunk),
        web.get("/get_transactions_of_account", account_transactions),
        web.get("/get_transaction", transaction),
        web.get("/get_blocks_after", blocks_after),
        web.get("/get_blocks_before", blocks_before),
        web.get("/get_block_number", block_by_number),
        web.get("/get_block", block_by_hash),
        web.get("/get_account", account),
        web.get("/get_account_mempool", account_mempool),
        web.get("/transaction_pool", _dump_handler("transaction_pool", lambda: memserver.transaction_pool)),
        web.get("/update", update_node),
        # mempool SET RECONCILIATION wire (memserver.merge_remote_transactions): the cheap id list +
        # the bounded fetch-by-id — divergent peers no longer re-download each other's whole pools.
        web.get("/transaction_ids", _dump_handler("transaction_ids",
                                                  lambda: [t.get("txid") for t in memserver.transaction_pool])),
        web.post("/transactions_by_id", transactions_by_id),
        web.get("/transaction_hash_pool", _dump_handler("transactions_hash_pool", lambda: {
            "transactions_hash_pool": consensus.transaction_hash_pool,
            "majority_transactions_hash_pool": consensus.majority_transaction_pool_hash})),
        web.get("/get_latest_block", latest_block),
        web.get("/get_supply", get_supply),
        web.get("/announce_peer", announce_peer),
        web.get("/status_pool", _dump_handler("status_pool", lambda: consensus.status_pool)),
        web.get("/mining_status", mining_status),
        web.get("/status", status),
        web.get("/peers", _dump_handler("peers", lambda: me_to(list(memserver.peers)))),
        web.get("/geo_peers", geo_peers),
        web.get("/peer_buffer", _dump_handler("peer_buffer", lambda: list(memserver.peer_buffer))),
        web.get("/unreachable", _dump_handler("unreachable", lambda: memserver.unreachable)),
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
        web.get("/duty_committee", duty_committee),
        web.get("/get_dividend_inflow", get_dividend_inflow),
        web.get("/get_settled", get_settled),
        web.get("/resolve_alias", resolve_alias),
        web.get("/msig_address", msig_address),
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
        web.get("/robots.txt", robots_txt),
        web.get("/static/miner.{ext:html|js|css}", legacy_static_redirect),   # old name -> interface.*
        web.get("/static/{path:.*}", static_handler),
    ])
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    # In NADO_TESTNET mode bind to the node's own (loopback) IP so several nodes can share the port on
    # distinct 127.0.0.x addresses.
    if os.environ.get("NADO_TESTNET"):
        await web.TCPSite(runner, host=get_config()["ip"], port=port).start()
    else:
        # DUAL-STACK: bind IPv4 on all interfaces, AND a SEPARATE IPv6 socket with IPV6_V6ONLY=1. Keeping
        # them separate (rather than one dual-stack "::" socket) means v4 clients arrive as plain 1.2.3.4
        # on the v4 socket instead of ::ffff:1.2.3.4 — so client_ip_from / rate-limiting see real v4 keys.
        # The v6 listener is best-effort: a host with no IPv6 just skips it (v4 keeps working).
        await web.TCPSite(runner, host="0.0.0.0", port=port).start()
        try:
            s6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s6.bind(("::", port))
            s6.setblocking(False)
            await web.SockSite(runner, s6).start()
            logger.info(f"Also listening on [::]:{port} (IPv6)")
        except Exception as e:
            logger.warning(f"IPv6 listener not started (no IPv6 on this host?): {e}")
    await asyncio.Event().wait()


"""warning, no intensive operations or locks should be invoked from API interface"""
logger = get_logger(logger_name="main_logger")

allow_async()

updated_version = versioner.update_version()
if updated_version:
    versioner.set_version(updated_version)

# CHAIN GENERATION (genesis-reroll flag): if the code's protocol.CHAIN_GENERATION moved past the epoch this node's
# data was built under, the operator's /update pull carried a REROLL — wipe every chain-derived artifact
# (never private/) and fall through to a fresh genesis below. Fresh nodes just get stamped.
from ops.data_ops import chain_purge_due, purge_chain_data, stamp_chain_generation
if chain_purge_due():
    logger.warning("CHAIN_GENERATION bumped — a genesis reroll shipped with this update; wiping chain data for regenesis")
    purge_chain_data(logger)
stamp_chain_generation()

# GENESIS SENTINEL: key off block_ends.dat (written LAST by make_genesis), NOT the blocks/ dir (created FIRST
# by make_folders). Using blocks/ meant a genesis that died after make_folders but before block_ends.dat was
# written left blocks/ present -> genesis skipped forever -> "block_ends.dat missing" crash on every boot.
# make_folders + make_genesis are now idempotent, so this simply re-runs genesis until it fully completes.
if not os.path.exists(f"{get_home()}/index/block_ends.dat"):
    make_folders()
    make_genesis(
        address=GENESIS_ADDRESS,        # genesis address == treasury (no personal premine)
        balance=TREASURY_GENESIS,        # bootstrap allocation minted to the treasury
        ip="38.242.201.206",          # get.nadochain.com — the live public bootstrap node
        port=9173,
        timestamp=GENESIS_TIMESTAMP,
        logger=logger,
    )

# BLOCK-STORE migration (idempotent, one-time): fold any legacy per-file bodies (flat or sharded
# *.block) into the append-only segment store, and repair a torn segment tail from a crash mid-append.
try:
    from ops.block_ops import migrate_block_store
    migrate_block_store(logger)
except Exception as _e:
    logger.error(f"block-store segment migration failed: {_e}")
    raise SystemExit(1)   # a half-migrated store must not silently run — fix disk/permissions and restart

# CHECKPOINT SWEEP (idempotent, boot-time): drop any persisted checkpoint that does not anchor to THIS
# node's canonical chain. New non-canonical checkpoints can no longer come into existence (a re-anchor
# wipes them via adopt_new_identity; a rollback drops reverted ones) — this cleans disks written before
# that invariant existed. A stale advertised checkpoint poisons every fresh joiner that bootstraps from
# this node (observed live: a dead fork's checkpoint 13000 wedged a new node at birth).
try:
    from ops.snapshot_ops import sweep_noncanonical_checkpoints
    _sw = sweep_noncanonical_checkpoints()
    if _sw:
        logger.warning(f"Dropped {_sw} fork-stale checkpoint(s) that no longer anchor to the canonical chain")
except Exception as _e:
    logger.error(f"checkpoint sweep failed (non-fatal): {_e}")

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
    # NOTE: we intentionally do NOT save our own IP as a peer here. Doing so put self into the
    # dial set (load_ips -> memserver.peers), so the node kept trying to fetch /peers and /status
    # from itself (unreachable over its own public IP behind NAT). Self is advertised to OTHER
    # nodes via me_to() in the /peers handler instead, and load_ips drops our own IP defensively.

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

# SNAPSHOT HYGIENE: discard any on-disk checkpoint ABOVE our current tip. A checkpoint higher than our
# own height cannot belong to our chain — it is a ghost from a prior chain/relaunch that reused this data
# dir (or a not-yet-rebuilt post-rollback remnant). Left in place, the keep-highest-N prune in
# persist_checkpoint would evict our REAL checkpoints, and /status would advertise a snapshot we don't
# actually hold on this chain — which strands fresh joiners on the snapshot-bootstrap path.
try:
    snapshot_ops.drop_checkpoints_above(memserver.latest_block["block_number"])
except Exception as e:
    logger.error(f"Snapshot reconciliation at startup failed (non-fatal): {e}")

# S4.3: surface the bonded producer registry loudly at startup. total_shares == 0 means NO eligible
# producer (every bond < B_MIN, or none seeded) -> fail-closed selection silently produces no blocks.
_registry = get_bonded_registry()
logger.warning(f"Bonded producer registry: {len(_registry)} eligible, total_shares={total_shares(_registry)}")

consensus = ConsensusClient(memserver=memserver, logger=logger)
consensus.start()

core = CoreClient(memserver=memserver, consensus=consensus, logger=logger)
core.start()

peers = PeerClient(memserver=memserver, consensus=consensus, logger=logger)
peers.start()

messages = MessageClient(memserver=memserver, consensus=consensus, core=core, peers=peers, logger=logger)
messages.start()

logger.info("Starting Request Handler")


def _daily_update_loop():
    """Integrated auto-updater cadence: check origin/main once a day (plus whenever someone hits
    /update). First check 10 minutes after boot so a freshly restarted node settles/syncs first; a
    check that pulls new code schedules its own restart, after which the node is up to date and the
    next boot's timer re-arms. Opt out with \"auto_update\": false in private/config.json."""
    time.sleep(600)
    while True:
        try:
            res = self_update.check_and_update("daily")
            logger.info(f"Daily update check: {res.get('status')}"
                        + (f" ({res.get('reason')})" if res.get("reason") else "")
                        + (f" {res.get('from')} -> {res.get('to')}" if res.get("status") == "updated" else ""))
        except Exception as e:
            logger.info(f"Daily update check failed: {e}")
        time.sleep(86400)


_threading.Thread(target=_daily_update_loop, daemon=True, name="self_update").start()
logger.info("Integrated auto-updater armed: daily origin/main check + remote /update trigger (wave-forwarding)")

asyncio.run(make_app(get_config()["port"]))
