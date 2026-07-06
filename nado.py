import asyncio
import functools
import mimetypes
import os
import signal
import socket
import sys

import msgpack
import zstandard as _zstd
from aiohttp import web

# Reused, thread-safe compressor for the zstd block-sync wire format (see serialize()). level 3 matches the
# on-disk block format (ops/block_ops); it writes the content size into the frame so the client can decode.
_ZSTD_WIRE = _zstd.ZstdCompressor(level=3)

import versioner
from config import get_config, get_timestamp_seconds
from genesis import make_genesis, make_folders
from loops.consensus_loop import ConsensusClient
from loops.core_loop import CoreClient
from loops.message_loop import MessageClient
from loops.peer_loop import PeerClient
from memserver import MemServer
from ops.account_ops import get_account, fetch_totals, get_bonded_registry
from ops.address_ops import proof_sender
from Curve25519 import verify as _mldsa_verify, unhex as _mldsa_unhex
from ops.mining_ops import total_shares
from ops.block_ops import get_block, fee_over_blocks, get_block_number
from ops.data_ops import get_home, allow_async
from ops.key_ops import keyfile_found, generate_keys, save_keys
from ops.log_ops import get_logger
from ops.peer_ops import save_peer, get_remote_status, check_ip, me_to
from ops.transaction_ops import get_transaction, get_transactions_of_account, to_readable_amount
from ops import snapshot_ops
from protocol import GENESIS_ADDRESS, TREASURY_ADDRESS, TREASURY_GENESIS, GENESIS_TIMESTAMP, CHAIN_ID

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
    """Wire-encode an API payload per ?compress: 'zstd' -> zstd(msgpack) (the node<->node block-sync
    format), 'msgpack' -> raw msgpack, anything else -> left for JSON, with non-dict outputs wrapped
    under `name` so the JSON shape matches the legacy Tornado handlers."""
    if compress == "zstd":
        # zstd(msgpack): the node<->node block-sync wire format (ops/block_ops.get_blocks_after/before).
        # Block bodies are dominated by hex ML-DSA sigs/pubkeys, so raw msgpack over the wire is ~3x larger
        # than it needs to be; zstd recovers it (a 50-block batch: ~336KB -> ~115KB). The json/msgpack paths
        # are left untouched so browser light-miners (which fetch single small objects, not block batches)
        # keep working with no zstd dependency.
        output = _ZSTD_WIRE.compress(msgpack.packb(output))
    elif compress == "msgpack":
        output = msgpack.packb(output)
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
    seconds — the per-endpoint DoS throttle backing every _RL early return."""
    from ops.ratelimit import allow
    return not allow(_ip(request), limit, window)


_RL = web.json_response({"result": False, "message": "Rate limited — slow down"}, status=429,
                        headers={"Access-Control-Allow-Origin": "*"})


def _q(request, key, default=None):
    """Query-string parameter `key`, or `default` when absent."""
    return request.query.get(key, default)


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
            "latest_block_hash": lb.get("block_hash"),
            "latest_block_weight": lb.get("cumulative_weight", 0),
            "earliest_block_hash": eb.get("block_hash"),
            "finalized_height": memserver.finalized_height,
            "ffg_finalized": memserver.ffg_finalized,
            "protocol": memserver.protocol,
            "version": memserver.version,
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
    """GET /get_recommended_fee: {"fee": N} — the recent-blocks fee estimate + 1, what a wallet should attach."""
    fee = await asyncio.to_thread(lambda: fee_over_blocks(logger=logger) + 1)
    return _resp({"fee": fee})


async def submit_transaction(request):
    """POST /submit_transaction: decode a msgpack/JSON tx from the body (size-bounded by unpack_tx so an
    oversized/malformed payload can't balloon memory) and merge it into the pool as user-origin. `register`
    txs additionally pass the per-source-IP anti-Sybil registration budget. 200 on accept, 403 on reject,
    429 over the 30/min IP rate limit."""
    if _rate_limited(request, 30):
        return _RL

    def _work(body, ctype, ip):
        """Decode, anti-Sybil check, and pool-merge the tx (worker thread)."""
        try:
            transaction = unpack_tx(body, ctype)   # size-bounded msgpack/JSON decode (ops/net_ops.py)
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
    """GET /health?key=&compress=: CPython GC counters/stats for memory-leak triage. Requires the node's
    server key unless called from 127.0.0.1 (heap introspection is not for the public)."""
    server_key = _q(request, "key", "none")
    if server_key != memserver.server_key and _ip(request) != "127.0.0.1":
        return _resp("Unauthorized", status=403)
    compress = _q(request, "compress", "none")
    data = {"gc_counts": list(gc.get_count()),
            "gc_objects_tracked": len(gc.get_objects()),
            "gc_stats": gc.get_stats()}
    return _resp(msgpack.packb(data) if compress == "msgpack" else serialize(name="health", output=data, compress=compress))


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
    return _resp(msgpack.packb(client_ip) if _q(request, "compress", "none") == "msgpack" else client_ip)


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


async def blocks_before(request):
    """GET /get_blocks_before?hash=&count=&compress=: up to `count` ancestors of `hash` (count capped at
    100 — the read-amplification bound), returned oldest-first. Rate-limited 60/min per IP since each
    block is a disk read. ?compress=zstd is the block-sync wire format peers use."""
    if _rate_limited(request, 60):  # up to 100 block-file reads per call; throttle
        return _RL

    def _work():
        """Walk parent_hash links collecting up to `count` blocks (worker thread)."""
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
    """GET /get_blocks_after?hash=&count=&compress=: up to `count` descendants of `hash` (count capped at
    100), ascending — the primary block-sync pull peers use with ?compress=zstd. Rate-limited 60/min per
    IP since each block is a disk read."""
    if _rate_limited(request, 60):  # up to 100 block-file reads per call; throttle
        return _RL

    def _work():
        """Walk child_hash links collecting up to `count` blocks (worker thread)."""
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
    """Serve the highest FINALIZED persisted checkpoint's manifest (reorg-safe). Cheap disk read."""
    def _work():
        """Load the latest finalized checkpoint manifest (worker thread)."""
        compress = _q(request, "compress", "msgpack")
        h = snapshot_ops.latest_final_checkpoint_height(memserver.finalized_height)
        manifest = snapshot_ops.load_checkpoint_manifest(h) if h is not None else None
        if not manifest:
            return None, 404
        return (msgpack.packb(manifest) if compress == "msgpack" else manifest), 200
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
        height = int(h) if h is not None else snapshot_ops.latest_final_checkpoint_height(memserver.finalized_height)
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
        """Single-pass log-normal fit over non-zero accounts, cached per height (worker thread)."""
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
        """Compute the anchored difficulty multiplier + window stats (worker thread)."""
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
    """GET /get_open_weights: the CURRENT epoch's open registry as {address: fidelity-weighted open-lane
    shares} — the execution node reads this to accrue the presence dividend. Rate-limited 60/min per IP."""
    # Present open registry + open-lane weights for the CURRENT epoch — the execution node reads this to
    # accrue the presence dividend to currently-present miners, fidelity-weighted (doc/presence-dividend.md).
    if _rate_limited(request, 60):
        return _RL
    def _work():
        """Read the open registry and weight by fidelity (worker thread)."""
        from ops.account_ops import get_open_registry
        from ops.mining_ops import open_shares, epoch_of
        epoch = epoch_of(memserver.latest_block["block_number"])
        reg = get_open_registry(epoch)
        weights = {addr: open_shares(info.get("fidelity", 0)) for addr, info in reg.items()}
        return {"epoch": epoch, "weights": weights}
    return _resp(await asyncio.to_thread(_work))


async def get_settled(request):
    """GET /get_settled: the canonical SETTLED execution-layer checkpoint {exec_cursor, state_root} —
    the state the bonded quorum has attested; what exec nodes and bridges treat as L1-enforced."""
    # The canonical SETTLED execution-layer checkpoint (Phase 2): the (exec_cursor, state_root) the bonded
    # quorum has attested. Execution nodes / bridges read this as the L1-enforced exec-layer state.
    def _work():
        """Read the latest settled checkpoint (worker thread)."""
        from ops.settlement_ops import latest_settled
        cursor, root = latest_settled()
        return {"exec_cursor": cursor, "state_root": root}
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


async def static_handler(request):
    """GET /static/{path}: serve a file from static/ with no-cache headers + open CORS. Path-traversal
    contained: the normpath'd target must stay under _STATIC_DIR or it 404s."""
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
    """GET /favicon.ico: the icon from graphics/, or 404 if absent."""
    p = os.path.join(_HERE, "graphics", "favicon.ico")
    return web.FileResponse(p) if os.path.isfile(p) else web.Response(status=404)


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
    def _work(body, ctype):
        """Decode + pool-admit the envelope (worker thread)."""
        try:
            env = unpack_tx(body, ctype)
            ok, why, mid = memserver.message_pool.add_message(
                env, get_timestamp_seconds(), _msg_is_registered, _msg_verify_sig)
            return {"result": ok, "reason": why, "id": mid}, (200 if ok else 403)
        except Exception as e:
            return f"Error: {e}", 403
    body = await request.read()
    out, code = await asyncio.to_thread(_work, body, request.headers.get("Content-Type", ""))
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
    def _work(body, ctype):
        """Decode + pool-admit the prekey bundle (worker thread)."""
        try:
            bundle = unpack_tx(body, ctype)
            ok, why = memserver.message_pool.add_prekey(bundle, _msg_is_registered, _prekey_verify_sig)
            return {"result": ok, "reason": why}, (200 if ok else 403)
        except Exception as e:
            return f"Error: {e}", 403
    body = await request.read()
    out, code = await asyncio.to_thread(_work, body, request.headers.get("Content-Type", ""))
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
_TAB_PATHS = ("wallet", "send", "receive", "aliases", "stake", "quorum", "messages",
              "history", "rich", "stats", "swap", "shield", "explore", "settings")


async def interface_page(request):
    """Serve the single-page interface for the deep-linkable tab paths (/wallet, /send, /aliases, ...)."""
    return web.FileResponse(os.path.join(_HERE, "static", "interface.html"))


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
        web.get("/transaction_pool", _dump_handler("transaction_pool", lambda: memserver.transaction_pool)),
        web.get("/transaction_hash_pool", _dump_handler("transactions_hash_pool", lambda: {
            "transactions_hash_pool": consensus.transaction_hash_pool,
            "majority_transactions_hash_pool": consensus.majority_transaction_pool_hash})),
        web.get("/transaction_buffer", _dump_handler("transaction_buffer", lambda: memserver.tx_buffer)),
        web.get("/user_transaction_buffer", _dump_handler("user_transaction_buffer", lambda: memserver.user_tx_buffer)),
        web.get("/get_latest_block", latest_block),
        web.get("/get_supply", get_supply),
        web.get("/announce_peer", announce_peer),
        web.get("/status_pool", _dump_handler("status_pool", lambda: consensus.status_pool)),
        web.get("/mining_status", mining_status),
        web.get("/status", status),
        web.get("/peers", _dump_handler("peers", lambda: me_to(list(memserver.peers)))),
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
