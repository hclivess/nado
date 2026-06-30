import asyncio
import json
import os
import signal
import socket
import sys

import msgpack
import tornado.ioloop
import tornado.web

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
from protocol import TREASURY_ADDRESS, TREASURY_GENESIS, GENESIS_TIMESTAMP

import gc  # replaces pympler/muppy — the full-heap walk fatally trips CPython GC under asyncio load


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


class NoCacheStaticFileHandler(tornado.web.StaticFileHandler):
    """Serve the browser wallet (static/) with NO-CACHE + permissive CORS, so wallet edits are picked
    up immediately (no stale cached miner.js — a recurring confusion) and a cross-origin page can load
    the assets."""
    def set_extra_headers(self, path):
        self.set_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.set_header("Pragma", "no-cache")
        self.set_header("Access-Control-Allow-Origin", "*")


class HomeHandler(tornado.web.RequestHandler):
    def home(self):
        self.render("templates/homepage.html", ip=get_config()["ip"])

    def get(self):
        self.home()


class StatusHandler(tornado.web.RequestHandler):
    def status(self):
        compress = StatusHandler.get_argument(self, "compress", default="none")

        try:
            status_dict = {
                "reported_uptime": memserver.reported_uptime,
                "address": memserver.address,
                "transaction_pool_hash": memserver.transaction_pool_hash,
                "block_producers_hash": memserver.block_producers_hash,
                "latest_block_hash": memserver.latest_block["block_hash"],
                # #16 step 3: advertise the tip's grind-proof cumulative_weight so peers run the
                # objective heaviest-weight fork-choice (it is only a HINT for which peer to sync from
                # — the weight is re-derived and enforced by verify_block on the actual blocks).
                "latest_block_weight": memserver.latest_block.get("cumulative_weight", 0),
                "earliest_block_hash": memserver.earliest_block["block_hash"],
                "finalized_height": memserver.finalized_height,  # #17: enforced-finality floor (time-based)
                "ffg_finalized": memserver.ffg_finalized,        # #6: stake-attested finalized checkpoint
                "protocol": memserver.protocol,
                "version": memserver.version,
            }

            # advertise the snapshot a joining/behind peer could bulk-download from us
            snap_manifest, _ = get_current_snapshot(build=False)
            status_dict["snapshot_height"] = snap_manifest["snapshot_height"] if snap_manifest else None
            status_dict["snapshot_hash"] = snap_manifest["snapshot_hash"] if snap_manifest else None

            self.write(serialize(name="status",
                                 output=status_dict,
                                 compress=compress))

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

    async def get(self, parameter):
        await asyncio.to_thread(self.status)


class MiningStatusHandler(tornado.web.RequestHandler):
    def mining_status(self):
        # two-lane mining snapshot for wallets/light-miners: lane split, each lane's total weight,
        # this address's open/bonded weight, and the derived expected time-to-mine. Read-only.
        from ops.block_ops import mining_status as compute_mining_status
        compress = MiningStatusHandler.get_argument(self, "compress", default="none")
        address = MiningStatusHandler.get_argument(self, "address", default=memserver.address)
        try:
            data = compute_mining_status(address=address,
                                         latest_block_number=memserver.latest_block["block_number"],
                                         block_time=memserver.block_time)
            self.write(serialize(name="mining_status", output=data, compress=compress))
        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

    async def get(self, parameter):
        await asyncio.to_thread(self.mining_status)


class TransactionPoolHandler(tornado.web.RequestHandler):
    def transaction_pool(self):
        compress = TransactionPoolHandler.get_argument(self, "compress", default="none")
        transaction_pool_data = memserver.transaction_pool
        self.write(serialize(name="transaction_pool",
                             output=transaction_pool_data,
                             compress=compress))

    async def get(self, parameter):
        await asyncio.to_thread(self.transaction_pool)


class TransactionBufferHandler(tornado.web.RequestHandler):
    def transaction_buffer(self):
        compress = TransactionBufferHandler.get_argument(self, "compress", default="none")
        buffer_data = memserver.tx_buffer

        self.write(serialize(name="transaction_buffer",
                             output=buffer_data,
                             compress=compress))

    async def get(self, parameter):
        await asyncio.to_thread(self.transaction_buffer)


class UserTxBufferHandler(tornado.web.RequestHandler):
    def transaction_buffer(self):
        compress = UserTxBufferHandler.get_argument(self, "compress", default="none")
        buffer_data = memserver.user_tx_buffer

        self.write(serialize(name="user_transaction_buffer",
                             output=buffer_data,
                             compress=compress))

    async def get(self, parameter):
        await asyncio.to_thread(self.transaction_buffer)


class TrustPoolHandler(tornado.web.RequestHandler):
    def trust_pool(self):
        compress = TrustPoolHandler.get_argument(self, "compress", default="none")
        trust_pool_data = consensus.trust_pool

        self.write(serialize(name="trust_pool_data",
                             output=trust_pool_data,
                             compress=compress,
                             ))

    async def get(self, parameter):
        await asyncio.to_thread(self.trust_pool)


class PeerPoolHandler(tornado.web.RequestHandler):
    def peer_pool(self):
        compress = PeerPoolHandler.get_argument(self, "compress", default="none")
        peers_data = list(memserver.peers)

        self.write(serialize(name="peers",
                             output=peers_data,
                             compress=compress
                             ))

    async def get(self, parameter):
        await asyncio.to_thread(self.peer_pool)

class PeerBufferHandler(tornado.web.RequestHandler):
    def peer_buffer(self):
        compress = PeerBufferHandler.get_argument(self, "compress", default="none")
        peers_data = list(memserver.peer_buffer)

        self.write(serialize(name="peer_buffer",
                             output=peers_data,
                             compress=compress
                             ))

    async def get(self, parameter):
        await asyncio.to_thread(self.peer_buffer)



class UnreachableHandler(tornado.web.RequestHandler):
    def unreachable(self):
        compress = PeerPoolHandler.get_argument(self, "compress", default="none")
        unreachable_data = memserver.unreachable

        self.write(serialize(name="unreachable",
                             output=unreachable_data,
                             compress=compress
                             ))

    async def get(self, parameter):
        await asyncio.to_thread(self.unreachable)


class BlockProducerPoolHandler(tornado.web.RequestHandler):
    def block_producers(self):
        compress = BlockProducerPoolHandler.get_argument(self, "compress", default="none")
        producer_data = list(memserver.block_producers)

        self.write(serialize(name="block_producers",
                             output=producer_data,
                             compress=compress))

    async def get(self, parameter):
        await asyncio.to_thread(self.block_producers)


class BlockProducersHashPoolHandler(tornado.web.RequestHandler):
    def block_producers_hash_pool(self):
        compress = BlockProducersHashPoolHandler.get_argument(self, "compress", default="none")

        output = {
            "block_producers_hash_pool": consensus.block_producers_hash_pool,
            "majority_block_producers_hash_pool": consensus.majority_block_producers_hash,
        }

        self.write(serialize(name="block_producers_hash_pool",
                             output=output,
                             compress=compress))

    async def get(self, parameter):
        await asyncio.to_thread(self.block_producers_hash_pool)


class TransactionHashPoolHandler(tornado.web.RequestHandler):
    def transaction_hash_pool(self):
        compress = TransactionHashPoolHandler.get_argument(self, "compress", default="none")

        output = {
            "transactions_hash_pool": consensus.transaction_hash_pool,
            "majority_transactions_hash_pool": consensus.majority_transaction_pool_hash,
        }

        self.write(serialize(name="transactions_hash_pool",
                             output=output,
                             compress=compress))

    async def get(self, parameter):
        await asyncio.to_thread(self.transaction_hash_pool)


class BlockHashPoolHandler(tornado.web.RequestHandler):
    def block_hash_pool(self):
        compress = BlockHashPoolHandler.get_argument(self, "compress", default="none")

        output = {
            "block_opinions": consensus.block_hash_pool,
            "majority_block_opinion": consensus.majority_block_hash,
        }

        self.write(serialize(name="block_hash_pool",
                             output=output,
                             compress=compress))

    async def get(self, parameter):
        await asyncio.to_thread(self.block_hash_pool)


class FeeHandler(tornado.web.RequestHandler):
    def fee(self):
        self.write({"fee": fee_over_blocks(logger=logger) + 1})

    async def get(self):
        await asyncio.to_thread(self.fee)


class StatusPoolHandler(tornado.web.RequestHandler):
    def status_pool(self):
        compress = StatusPoolHandler.get_argument(self, "compress", default="none")
        status_pool_data = consensus.status_pool

        self.write(serialize(name="status_pool",
                             output=status_pool_data,
                             compress=compress))

    async def get(self, parameter):
        await asyncio.to_thread(self.status_pool)


class SubmitTransactionHandler(tornado.web.RequestHandler):
    def submit_transaction(self):
        try:
            transaction_raw = SubmitTransactionHandler.get_argument(self, "data")
            transaction = json.loads(transaction_raw)

            output = memserver.merge_transaction(transaction, user_origin=True)
            self.write(output)

            if not output["result"]:
                self.set_status(403)

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

    async def get(self, parameter):
        from ops.ratelimit import allow
        if not allow(self.request.remote_ip, limit=30, window=60):
            self.set_status(429); self.write({"result": False, "message": "Rate limited — slow down"}); return
        await asyncio.to_thread(self.submit_transaction)

    def submit_transaction_post(self):
        # POST path (#14): the transaction is the request BODY (msgpack, or JSON fallback), not a
        # GET query string. A GET URL caps at a few KB and logs the payload — fine for a 0.5 KB
        # Ed25519 tx, but a post-quantum (ML-DSA) tx is ~7.8 KB and will NOT fit. POST removes that
        # cliff and is the prerequisite for PQ-sized txs. Backward-compatible: GET still works.
        import msgpack
        try:
            body = self.request.body
            ctype = self.request.headers.get("Content-Type", "")
            if "msgpack" in ctype:
                transaction = msgpack.unpackb(body, raw=False)
            else:
                transaction = json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)
            output = memserver.merge_transaction(transaction, user_origin=True)
            self.write(output)
            if not output["result"]:
                self.set_status(403)
        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

    async def post(self, parameter):
        from ops.ratelimit import allow
        if not allow(self.request.remote_ip, limit=30, window=60):
            self.set_status(429); self.write({"result": False, "message": "Rate limited — slow down"}); return
        await asyncio.to_thread(self.submit_transaction_post)


class HealthHandler(tornado.web.RequestHandler):
    def health(self):
        # gated like the other admin ops. Uses cheap gc stats instead of the old
        # muppy.get_objects() full-heap walk, which both starved this server and fatally
        # tripped CPython's GC ("PyObject_GC_Track ... _asyncio.FutureIter") under load.
        server_key = HealthHandler.get_argument(self, "key", default="none")
        if server_key != memserver.server_key and self.request.remote_ip != "127.0.0.1":
            self.set_status(403)
            self.write("Unauthorized")
            return
        compress = HealthHandler.get_argument(self, "compress", default="none")
        health = {"gc_counts": list(gc.get_count()),
                  "gc_objects_tracked": len(gc.get_objects()),
                  "gc_stats": gc.get_stats()}

        if compress == "msgpack":
            output = msgpack.packb(health)
        else:
            output = serialize(name="health",
                                 output=health,
                                 compress=compress)
        self.write(output)

    async def get(self, parameter):
        await asyncio.to_thread(self.health)

class LogHandler(tornado.web.RequestHandler):
    def log(self):
        # the log exposes peer topology, the node address, key-file paths and
        # tracebacks -- require the admin key and bound how much is returned.
        server_key = LogHandler.get_argument(self, "key", default="none")
        if server_key != memserver.server_key and self.request.remote_ip != "127.0.0.1":
            self.set_status(403)
            self.write("Unauthorized")
            return
        compress = LogHandler.get_argument(self, "compress", default="none")

        with open(f"{get_home()}/logs/log.log") as logfile:
            lines = logfile.readlines()[-500:]
            for line in lines:
                if compress == "msgpack":
                    output = msgpack.packb(line)
                else:
                    output = line
                self.write(output)
                self.write("<br>")

    async def get(self, parameter):
        await asyncio.to_thread(self.log)


class ForceSyncHandler(tornado.web.RequestHandler):
    def force_sync(self):
        try:
            forced_ip = ForceSyncHandler.get_argument(self, "ip")
            server_key = ForceSyncHandler.get_argument(self, "key", default="none")

            client_ip = self.request.remote_ip
            if server_key == memserver.server_key or client_ip == "127.0.0.1":
                if client_ip == "127.0.0.1" or check_ip(client_ip):
                    memserver.force_sync_ip = forced_ip
                    memserver.peers = [forced_ip]
                    self.write(f"Synchronization is now forced only from {forced_ip} until majority consensus is reached")
                else:
                    self.write(f"Failed to force to sync from {forced_ip}")
            else:
                self.write(f"Wrong server key {server_key}")

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

    async def get(self, parameter):
        await asyncio.to_thread(self.force_sync)


class IpHandler(tornado.web.RequestHandler):
    def log(self):
        compress = IpHandler.get_argument(self, "compress", default="none")
        client_ip = self.request.remote_ip

        if compress == "msgpack":
            output = msgpack.packb(client_ip)
        else:
            output = client_ip
        self.write(output)

    async def get(self, parameter):
        await asyncio.to_thread(self.log)


class TerminateHandler(tornado.web.RequestHandler):
    def terminate(self):
        try:
            server_key = TerminateHandler.get_argument(self, "key", default="none")

            client_ip = self.request.remote_ip
            if client_ip == "127.0.0.1" or server_key == memserver.server_key:
                self.write("Termination signal sent, node is shutting down...")
                memserver.terminate = True
                sys.exit(0)
            elif server_key != memserver.server_key:
                self.write("Wrong or missing key for a remote node")
        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

    async def get(self, parameter):
        await asyncio.to_thread(self.terminate)


class TransactionHandler(tornado.web.RequestHandler):
    def transaction(self):
        try:
            transaction = TransactionHandler.get_argument(self, "txid")
            transaction_data = get_transaction(transaction, logger=logger)
            compress = TransactionHandler.get_argument(self, "compress", default="none")

            if not transaction_data:
                transaction_data = "Not found"
                self.set_status(403)

            self.write(serialize(name="txid",
                                 output=transaction_data,
                                 compress=compress))

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

    async def get(self, parameter):
        await asyncio.to_thread(self.transaction)


class AccountTransactionsHandler(tornado.web.RequestHandler):
    """get transactions from a transaction index batch"""

    def account_transactions(self):
        try:
            address = AccountTransactionsHandler.get_argument(self, "address", default=memserver.address)
            min_block = AccountTransactionsHandler.get_argument(self, "min_block", default="0")
            compress = AccountTransactionsHandler.get_argument(self, "compress", default="none")

            transaction_data = get_transactions_of_account(account=address,
                                                           min_block=int(min_block),
                                                           logger=logger)

            if not transaction_data:
                transaction_data = "Not found"
                self.set_status(403)

            self.write(serialize(name="account_transactions",
                                 output=transaction_data,
                                 compress=compress))
        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

    async def get(self, parameter):
        await asyncio.to_thread(self.account_transactions)


class GetBlockHandler(tornado.web.RequestHandler):
    def block(self):
        output = ""

        try:
            block = GetBlockHandler.get_argument(self, "hash")
            compress = GetBlockHandler.get_argument(self, "compress", default="none")
            block_data = get_block(block)

            if not block_data:
                self.set_status(404)
                block_data = "Not found"

            output = serialize(name="block_hash",
                               output=block_data,
                               compress=compress)

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

        finally:
            self.write(output)

    async def get(self, parameter):
        await asyncio.to_thread(self.block)


class GetBlockNumberHandler(tornado.web.RequestHandler):
    def block(self):
        output = ""

        try:
            number = GetBlockHandler.get_argument(self, "number")
            compress = GetBlockHandler.get_argument(self, "compress", default="none")
            block_data = get_block_number(number)

            if not block_data:
                self.set_status(403)
                block_data = "Not found"

            output = serialize(name="block_number",
                               output=block_data,
                               compress=compress)

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

        finally:
            self.write(output)

    async def get(self, parameter):
        await asyncio.to_thread(self.block)


class GetBlocksBeforeHandler(tornado.web.RequestHandler):

    def blocks_before(self):
        block_hash = GetBlocksBeforeHandler.get_argument(self, "hash")
        count = int(GetBlocksBeforeHandler.get_argument(self, "count", default="1"))
        compress = GetBlocksBeforeHandler.get_argument(self, "compress", default="none")
        collected_blocks = []

        if count > 100:
            count = 100

        try:
            parent = get_block(block_hash)
            if parent:
                parent_hash=["parent_hash"]

                for blocks in range(0, count):
                    block = get_block(parent_hash)
                    if not block:
                        break

                    elif block:
                        collected_blocks.append(block)
                        parent_hash = block["parent_hash"]

                collected_blocks.reverse()
            else:
                logger.debug(f"Parent hash of {block_hash} not found")
                self.set_status(404)

        except Exception as e:
            self.set_status(403)
            logger.debug(f"Block collection hit a roadblock: {e}")

            if not collected_blocks:
                self.set_status(403)

        finally:
            self.write(serialize(name="blocks_before",
                                 output=collected_blocks,
                                 compress=compress
                                 ))

    async def get(self, parameter):
        await asyncio.to_thread(self.blocks_before)


class GetBlocksAfterHandler(tornado.web.RequestHandler):
    def blocks_after(self):

        block_hash = GetBlocksAfterHandler.get_argument(self, "hash")
        count = int(GetBlocksAfterHandler.get_argument(self, "count", default="1"))
        compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")
        collected_blocks = []

        if count > 100:
            count = 100

        try:
            child = get_block(block_hash)
            if child:
                child_hash = child["child_hash"]

                for blocks in range(0, count):
                    block = get_block(child_hash)
                    if not block:
                        break

                    elif block:
                        collected_blocks.append(block)
                        child_hash = block["child_hash"]
            else:
                logger.debug(f"Child hash of {block_hash} not found")
                self.set_status(404)

        except Exception as e:
            logger.debug(f"Block collection hit a roadblock: {e}")

            if not collected_blocks:
                self.set_status(403)

        finally:
            self.write(serialize(name="blocks_after",
                                 output=collected_blocks,
                                 compress=compress,
                                 ))

    async def get(self, parameter):
        await asyncio.to_thread(self.blocks_after)

class GetSupplyHandler(tornado.web.RequestHandler):
    def get_supply(self):
        readable = GetSupplyHandler.get_argument(self, "readable", default="none")
        data = fetch_totals()  # produced (block rewards minted), fees (destroyed)
        treasury_acc = get_account(address=TREASURY_ADDRESS)
        data.update({"block_number": memserver.latest_block["block_number"]})
        # No premine: the only genesis mint is the treasury seed (TREASURY_GENESIS).
        # total = genesis seed + all block rewards minted - fees destroyed. (Burn removed.)
        data.update({"treasury": treasury_acc["balance"]})
        data.update({"total_supply": TREASURY_GENESIS + data["produced"] - data["fees"]})
        # treasury holdings are the genesis-address treasury, counted as non-circulating
        data.update({"circulating": data["total_supply"] - data["treasury"]})

        if readable == "true":
            for key in ("produced", "fees", "treasury", "circulating", "total_supply"):
                data[key] = to_readable_amount(data[key])

        self.write(data)
    async def get(self, parameter):
        await asyncio.to_thread(self.get_supply)


class GetLatestBlockHandler(tornado.web.RequestHandler):
    def latest_block(self):
        latest_block_data = memserver.latest_block
        compress = GetLatestBlockHandler.get_argument(self, "compress", default="none")

        self.write(serialize(name="latest_block",
                             output=latest_block_data,
                             compress=compress))

    async def get(self, parameter):
        await asyncio.to_thread(self.latest_block)


class AccountHandler(tornado.web.RequestHandler):
    def account(self):
        try:
            account = AccountHandler.get_argument(self, "address", default=memserver.address)
            compress = AccountHandler.get_argument(self, "compress", default="none")
            readable = AccountHandler.get_argument(self, "readable", default="none")
            account_data = get_account(account, create_on_error=False)

            if account_data:
                if readable == "true":
                    account_data.update({"balance": to_readable_amount(account_data["balance"])})
                    account_data.update({"produced": to_readable_amount(account_data["produced"])})
                    account_data.update({"bonded": to_readable_amount(account_data["bonded"])})

            else:
                account_data = "Not found"
                self.set_status(403)

            self.write(serialize(name="address",
                                 output=account_data,
                                 compress=compress))

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

    async def get(self, parameter):
        await asyncio.to_thread(self.account)


class AnnouncePeerHandler(tornado.web.RequestHandler):
    def announce(self):
        try:
            peer_ip = AnnouncePeerHandler.get_argument(self, "ip")
            if not check_ip(peer_ip):
                self.write("Invalid IP address")

            else:
                if peer_ip not in memserver.peers and peer_ip not in memserver.unreachable.keys():
                    status = asyncio.run(get_remote_status(peer_ip, logger=logger))

                    assert status, f"{peer_ip} unreachable"

                    address = status["address"]
                    protocol = status["protocol"]

                    assert address, "No address detected"
                    assert protocol >= get_config()["protocol"], f"Protocol of {peer_ip} is too low"

                    save_peer(ip=peer_ip,
                              address=address,
                              port=get_config()["port"],
                              overwrite=True
                              )

                    if peer_ip not in memserver.peer_buffer:
                        memserver.peer_buffer.append(peer_ip)
                        message = f"Peer {peer_ip} added to peer buffer"
                    else:
                        message = f"{peer_ip} already waiting in peer buffer"

                else:
                    message = f"Peer {peer_ip} is known or invalid"
                self.write(message)

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")

    async def get(self, parameter):
        # ECLIPSE HARDENING (#18 step 8): rate-limit peer announcements per source IP. A single origin
        # flooding /announce_peer to stuff a victim's peer view (eclipse groundwork) is throttled here,
        # complementing the per-IP submit_transaction limiter. The fork-choice already ignores peer
        # IPs for weight, but bounding announce volume protects the peer-discovery surface.
        from ops.ratelimit import allow
        if not allow(self.request.remote_ip, limit=10, window=60):
            self.set_status(429)
            self.write("Rate limited — slow down")
            return
        await asyncio.to_thread(self.announce)


class SnapshotManifestHandler(tornado.web.RequestHandler):
    """serve the manifest (state_root, totals, chunk list) for our current checkpoint"""
    def manifest(self):
        compress = SnapshotManifestHandler.get_argument(self, "compress", default="msgpack")
        snap_manifest, _ = get_current_snapshot(build=True)
        if not snap_manifest:
            self.set_status(404)
            self.write("No snapshot available (chain too short)")
            return
        if compress == "msgpack":
            self.set_header("Content-Type", "application/msgpack")
            self.write(msgpack.packb(snap_manifest))
        else:
            self.write(snap_manifest)

    async def get(self, parameter):
        await asyncio.to_thread(self.manifest)


class SnapshotChunkHandler(tornado.web.RequestHandler):
    """serve one deterministic account-state chunk by id; chunks are parallel-fetchable"""
    def chunk(self):
        try:
            cid = int(SnapshotChunkHandler.get_argument(self, "id"))
        except Exception:
            self.set_status(400)
            self.write("Invalid chunk id")
            return
        _, chunks = get_current_snapshot(build=True)
        if not chunks or cid < 0 or cid >= len(chunks):
            self.set_status(404)
            self.write("No such snapshot chunk")
            return
        self.set_header("Content-Type", "application/msgpack")
        self.write(chunks[cid])

    async def get(self, parameter):
        await asyncio.to_thread(self.chunk)


async def make_app(port):
    application = tornado.web.Application(
        [
            (r"/", HomeHandler),
            (r"/get_snapshot_manifest(.*)", SnapshotManifestHandler),
            (r"/get_snapshot_chunk(.*)", SnapshotChunkHandler),
            (r"/get_transactions_of_account(.*)", AccountTransactionsHandler),
            (r"/get_transaction(.*)", TransactionHandler),
            (r"/get_blocks_after(.*)", GetBlocksAfterHandler),
            (r"/get_blocks_before(.*)", GetBlocksBeforeHandler),
            (r"/get_block_number(.*)", GetBlockNumberHandler),
            (r"/get_block(.*)", GetBlockHandler),
            (r"/get_account(.*)", AccountHandler),
            (r"/transaction_pool(.*)", TransactionPoolHandler),
            (r"/transaction_hash_pool(.*)", TransactionHashPoolHandler),
            (r"/transaction_buffer(.*)", TransactionBufferHandler),
            (r"/user_transaction_buffer(.*)", UserTxBufferHandler),
            (r"/trust_pool(.*)", TrustPoolHandler),
            (r"/get_latest_block(.*)", GetLatestBlockHandler),
            (r"/get_supply(.*)", GetSupplyHandler),
            (r"/announce_peer(.*)", AnnouncePeerHandler),
            (r"/status_pool(.*)", StatusPoolHandler),
            (r"/mining_status(.*)", MiningStatusHandler),
            (r"/status(.*)", StatusHandler),
            (r"/peers(.*)", PeerPoolHandler),
            (r"/peer_buffer(.*)", PeerBufferHandler),
            (r"/unreachable(.*)", UnreachableHandler),
            (r"/block_producers_hash_pool(.*)", BlockProducersHashPoolHandler),
            (r"/block_producers(.*)", BlockProducerPoolHandler),
            (r"/block_hash_pool(.*)", BlockHashPoolHandler),
            (r"/get_recommended_fee", FeeHandler),
            (r"/terminate(.*)", TerminateHandler),
            (r"/health(.*)", HealthHandler),
            (r"/submit_transaction(.*)", SubmitTransactionHandler),
            (r"/log(.*)", LogHandler),
            (r"/whats_my_ip(.*)", IpHandler),
            (r"/force_sync(.*)", ForceSyncHandler),
            (r"/static/(.*)", NoCacheStaticFileHandler, {"path": "static"}),
            (r'/(favicon.ico)', tornado.web.StaticFileHandler, {"path": "graphics"}),

        ]
    )
    # In NADO_TESTNET mode bind to the node's own (loopback) IP so several nodes can share the
    # port on distinct 127.0.0.x addresses; on mainnet bind all interfaces (reachable).
    listen_address = get_config()["ip"] if os.environ.get("NADO_TESTNET") else None
    application.listen(port, address=listen_address)
    await asyncio.Event().wait()

"""warning, no intensive operations or locks should be invoked from API interface"""
logging.getLogger('tornado.access').disabled = True
logger = get_logger(logger_name="main_logger")

allow_async()

updated_version = versioner.update_version()
if updated_version:
    versioner.set_version(updated_version)

if not os.path.exists(f"{get_home()}/blocks"):
    make_folders()
    make_genesis(
        address=TREASURY_ADDRESS,        # genesis address == treasury (no personal premine)
        balance=TREASURY_GENESIS,        # bootstrap allocation minted to the treasury
        ip="78.102.98.72",
        port=9173,
        timestamp=GENESIS_TIMESTAMP,
        logger=logger,
    )

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

# S4.3: surface the bonded producer registry loudly at startup. total_shares == 0 means NO
# eligible producer (every bond < B_MIN, or none seeded) -> fail-closed selection silently
# produces no blocks, so this must be obvious rather than a quiet stall at genesis.
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
