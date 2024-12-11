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
from ops.account_ops import get_account, fetch_totals
from ops.block_ops import get_block, fee_over_blocks, get_block_number, get_penalty
from ops.data_ops import get_home, allow_async
from ops.key_ops import keyfile_found, generate_keys, save_keys, load_keys
from ops.log_ops import get_logger, logging
from ops.peer_ops import save_peer, get_remote_status, get_producer_set, check_ip
from ops.transaction_ops import get_transaction, get_transactions_of_account, to_readable_amount

from pympler import summary, muppy


async def is_port_in_use(port: int) -> bool:
    try:
        async with await asyncio.open_connection("localhost", port) as (reader, writer):
            writer.close()
            await writer.wait_closed()
            return True
    except:
        return False


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


class BaseHandler(tornado.web.RequestHandler):
    async def handle_request(self, func, *args, **kwargs):
        try:
            result = await func(*args, **kwargs)
            return result
        except Exception as e:
            self.set_status(403)
            return f"Error: {e}"


class HomeHandler(BaseHandler):
    async def get(self):
        self.render("templates/homepage.html", ip=get_config()["ip"])


class StatusHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")

        try:
            status_dict = {
                "reported_uptime": memserver.reported_uptime,
                "address": memserver.address,
                "transaction_pool_hash": memserver.transaction_pool_hash,
                "block_producers_hash": memserver.block_producers_hash,
                "latest_block_hash": memserver.latest_block["block_hash"],
                "earliest_block_hash": memserver.earliest_block["block_hash"],
                "protocol": memserver.protocol,
                "version": memserver.version,
            }

            self.write(serialize(name="status", output=status_dict, compress=compress))
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class TransactionPoolHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        transaction_pool_data = memserver.transaction_pool
        self.write(serialize(name="transaction_pool", output=transaction_pool_data, compress=compress))


class TransactionBufferHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        buffer_data = memserver.tx_buffer
        self.write(serialize(name="transaction_buffer", output=buffer_data, compress=compress))


class UserTxBufferHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        buffer_data = memserver.user_tx_buffer
        self.write(serialize(name="user_transaction_buffer", output=buffer_data, compress=compress))


class TrustPoolHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        trust_pool_data = consensus.trust_pool
        self.write(serialize(name="trust_pool_data", output=trust_pool_data, compress=compress))


class PeerPoolHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        peers_data = list(memserver.peers)
        self.write(serialize(name="peers", output=peers_data, compress=compress))


class PeerBufferHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        peers_data = list(memserver.peer_buffer)
        self.write(serialize(name="peer_buffer", output=peers_data, compress=compress))


class PenaltiesHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        output = {"penalties": memserver.penalties}
        self.write(serialize(name="penalties", output=output, compress=compress))


class UnreachableHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        unreachable_data = memserver.unreachable
        self.write(serialize(name="unreachable", output=unreachable_data, compress=compress))


class BlockProducerPoolHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        producer_data = list(memserver.block_producers)
        self.write(serialize(name="block_producers", output=producer_data, compress=compress))


class BlockProducersHashPoolHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        output = {
            "block_producers_hash_pool": consensus.block_producers_hash_pool,
            "majority_block_producers_hash_pool": consensus.majority_block_producers_hash,
        }
        self.write(serialize(name="block_producers_hash_pool", output=output, compress=compress))


class TransactionHashPoolHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        output = {
            "transactions_hash_pool": consensus.transaction_hash_pool,
            "majority_transactions_hash_pool": consensus.majority_transaction_pool_hash,
        }
        self.write(serialize(name="transactions_hash_pool", output=output, compress=compress))


class BlockHashPoolHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        output = {
            "block_opinions": consensus.block_hash_pool,
            "majority_block_opinion": consensus.majority_block_hash,
        }
        self.write(serialize(name="block_hash_pool", output=output, compress=compress))


class FeeHandler(BaseHandler):
    async def get(self):
        fee = await asyncio.to_thread(fee_over_blocks, logger=logger)
        self.write({"fee": fee + 1})


class StatusPoolHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        status_pool_data = consensus.status_pool
        self.write(serialize(name="status_pool", output=status_pool_data, compress=compress))


class SubmitTransactionHandler(BaseHandler):
    async def get(self, parameter):
        try:
            transaction_raw = self.get_argument("data")
            transaction = json.loads(transaction_raw)
            output = await asyncio.to_thread(memserver.merge_transaction, transaction, user_origin=True)

            if not output["result"]:
                self.set_status(403)

            self.write(output)
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class HealthHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        health = await asyncio.to_thread(summary.summarize, muppy.get_objects())
        self.write(serialize(name="health", output=health, compress=compress))


class LogHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        try:
            async with await asyncio.to_thread(open, f"{get_home()}/logs/log.log") as logfile:
                lines = await asyncio.to_thread(logfile.readlines)
                for line in lines:
                    if compress == "msgpack":
                        output = msgpack.packb(line)
                    else:
                        output = line
                    self.write(output)
                    self.write("<br>")
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class ForceSyncHandler(BaseHandler):
    async def get(self, parameter):
        try:
            forced_ip = self.get_argument("ip")
            server_key = self.get_argument("key", default="none")
            client_ip = self.request.remote_ip

            if server_key == memserver.server_key or client_ip == "127.0.0.1":
                if client_ip == "127.0.0.1" or await asyncio.to_thread(check_ip, client_ip):
                    memserver.force_sync_ip = forced_ip
                    memserver.peers = [forced_ip]
                    self.write(
                        f"Synchronization is now forced only from {forced_ip} until majority consensus is reached")
                else:
                    self.write(f"Failed to force to sync from {forced_ip}")
            else:
                self.write(f"Wrong server key {server_key}")
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class IpHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        client_ip = self.request.remote_ip
        self.write(serialize(name="ip", output=client_ip, compress=compress))


class TerminateHandler(BaseHandler):
    async def get(self, parameter):
        try:
            server_key = self.get_argument("key", default="none")
            client_ip = self.request.remote_ip

            if client_ip == "127.0.0.1" or server_key == memserver.server_key:
                self.write("Termination signal sent, node is shutting down...")
                memserver.terminate = True
                sys.exit(0)
            elif server_key != memserver.server_key:
                self.write("Wrong or missing key for a remote node")
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class TransactionHandler(BaseHandler):
    async def get(self, parameter):
        try:
            transaction = self.get_argument("txid")
            compress = self.get_argument("compress", default="none")

            transaction_data = await asyncio.to_thread(get_transaction, transaction, logger=logger)

            if not transaction_data:
                self.set_status(403)
                transaction_data = "Not found"

            self.write(serialize(name="txid", output=transaction_data, compress=compress))
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class AccountTransactionsHandler(BaseHandler):
    async def get(self, parameter):
        try:
            address = self.get_argument("address", default=memserver.address)
            min_block = self.get_argument("min_block", default="0")
            compress = self.get_argument("compress", default="none")

            transaction_data = await asyncio.to_thread(
                get_transactions_of_account,
                account=address,
                min_block=int(min_block),
                logger=logger
            )

            if not transaction_data:
                self.set_status(403)
                transaction_data = "Not found"

            self.write(serialize(name="account_transactions", output=transaction_data, compress=compress))
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class GetBlockHandler(BaseHandler):
    async def get(self, parameter):
        try:
            block = self.get_argument("hash")
            compress = self.get_argument("compress", default="none")

            block_data = await asyncio.to_thread(get_block, block)

            if not block_data:
                self.set_status(404)
                block_data = "Not found"

            self.write(serialize(name="block_hash", output=block_data, compress=compress))
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class GetBlockNumberHandler(BaseHandler):
    async def get(self, parameter):
        try:
            number = self.get_argument("number")
            compress = self.get_argument("compress", default="none")

            block_data = await asyncio.to_thread(get_block_number, number)

            if not block_data:
                self.set_status(403)
                block_data = "Not found"

            self.write(serialize(name="block_number", output=block_data, compress=compress))
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class GetBlocksBeforeHandler(BaseHandler):
    async def get(self, parameter):
        block_hash = self.get_argument("hash")
        count = int(self.get_argument("count", default="1"))
        compress = self.get_argument("compress", default="none")
        collected_blocks = []

        if count > 100:
            count = 100

        try:
            parent = await asyncio.to_thread(get_block, block_hash)
            if parent:
                parent_hash = parent["parent_hash"]

                for _ in range(count):
                    block = await asyncio.to_thread(get_block, parent_hash)
                    if not block:
                        break

                    collected_blocks.append(block)
                    parent_hash = block["parent_hash"]

                collected_blocks.reverse()
            else:
                logger.debug(f"Parent hash of {block_hash} not found")
                self.set_status(404)
        except Exception as e:
            logger.debug(f"Block collection hit a roadblock: {e}")
            if not collected_blocks:
                self.set_status(403)
        finally:
            self.write(serialize(name="blocks_before", output=collected_blocks, compress=compress))


class GetBlocksAfterHandler(BaseHandler):
    async def get(self, parameter):
        block_hash = self.get_argument("hash")
        count = int(self.get_argument("count", default="1"))
        compress = self.get_argument("compress", default="none")
        collected_blocks = []

        if count > 100:
            count = 100

        try:
            child = await asyncio.to_thread(get_block, block_hash)
            if child:
                child_hash = child["child_hash"]

                for _ in range(count):
                    block = await asyncio.to_thread(get_block, child_hash)
                    if not block:
                        break

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
            self.write(serialize(name="blocks_after", output=collected_blocks, compress=compress))


class GetSupplyHandler(BaseHandler):
    async def get(self, parameter):
        try:
            readable = self.get_argument("readable", default="none")
            data = await asyncio.to_thread(fetch_totals)
            genesis_acc = await asyncio.to_thread(get_account,
                                                  address="ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b80137b")

            data.update({
                "block_number": memserver.latest_block["block_number"],
                "reserve": genesis_acc["balance"],
                "reserve_spent": 1000000000000000000 - genesis_acc["balance"]
            })
            data.update({
                "circulating": data["reserve_spent"] + data["produced"] - data["burned"] - data["fees"],
                "total_supply": 1000000000000000000 + data["produced"] - data["burned"] - data["fees"]
            })

            if readable == "true":
                data.update({
                    "produced": to_readable_amount(data["produced"]),
                    "fees": to_readable_amount(data["fees"]),
                    "burned": to_readable_amount(data["burned"]),
                    "reserve": to_readable_amount(data["reserve"]),
                    "reserve_spent": to_readable_amount(data["reserve_spent"]),
                    "circulating": to_readable_amount(data["circulating"]),
                    "total_supply": to_readable_amount(data["total_supply"])
                })

            self.write(data)
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class GetLatestBlockHandler(BaseHandler):
    async def get(self, parameter):
        compress = self.get_argument("compress", default="none")
        latest_block_data = memserver.latest_block
        self.write(serialize(name="latest_block", output=latest_block_data, compress=compress))


class AccountHandler(BaseHandler):
    async def get(self, parameter):
        try:
            account = self.get_argument("address", default=memserver.address)
            compress = self.get_argument("compress", default="none")
            readable = self.get_argument("readable", default="none")

            account_data = await asyncio.to_thread(get_account, account, create_on_error=False)

            if account_data:
                penalty = await asyncio.to_thread(
                    get_penalty,
                    producer_address=account,
                    block_hash=memserver.latest_block["block_hash"],
                    block_number=memserver.latest_block["block_number"]
                )
                account_data.update({"penalty": penalty})

                if readable == "true":
                    account_data.update({
                        "balance": to_readable_amount(account_data["balance"]),
                        "produced": to_readable_amount(account_data["produced"]),
                        "burned": to_readable_amount(account_data["burned"])
                    })
            else:
                self.set_status(403)
                account_data = "Not found"

            self.write(serialize(name="address", output=account_data, compress=compress))
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class ProducerSetHandler(BaseHandler):
    async def get(self, parameter):
        try:
            producer_set_hash = self.get_argument("hash")
            compress = self.get_argument("compress", default="none")

            producer_data = await asyncio.to_thread(get_producer_set, producer_set_hash)

            if not producer_data:
                self.set_status(403)
                producer_data = "Not found"

            self.write(serialize(name="producer_set", output=producer_data, compress=compress))
        except Exception as e:
            await self.handle_request(lambda: f"Error: {e}")


class AnnouncePeerHandler(BaseHandler):
    async def get(self, parameter):
        try:
            peer_ip = self.get_argument("ip")
            if not await asyncio.to_thread(check_ip, peer_ip):
                self.write("Invalid IP address")
                return

            if peer_ip not in memserver.peers and peer_ip not in memserver.unreachable.keys():
                status = await get_remote_status(peer_ip, logger=logger)

                if not status:
                    raise Exception(f"{peer_ip} unreachable")

                address = status["address"]
                protocol = status["protocol"]

                if not address:
                    raise Exception("No address detected")
                if protocol < get_config()["protocol"]:
                    raise Exception(f"Protocol of {peer_ip} is too low")

                await asyncio.to_thread(
                    save_peer,
                    ip=peer_ip,
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
            await self.handle_request(lambda: f"Error: {e}")


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [
            (r"/", HomeHandler),
            (r"/get_transactions_of_account(.*)", AccountTransactionsHandler),
            (r"/get_transaction(.*)", TransactionHandler),
            (r"/get_blocks_after(.*)", GetBlocksAfterHandler),
            (r"/get_blocks_before(.*)", GetBlocksBeforeHandler),
            (r"/get_block_number(.*)", GetBlockNumberHandler),
            (r"/get_block(.*)", GetBlockHandler),
            (r"/get_account(.*)", AccountHandler),
            (r"/get_producer_set_from_hash(.*)", ProducerSetHandler),
            (r"/transaction_pool(.*)", TransactionPoolHandler),
            (r"/transaction_hash_pool(.*)", TransactionHashPoolHandler),
            (r"/transaction_buffer(.*)", TransactionBufferHandler),
            (r"/user_transaction_buffer(.*)", UserTxBufferHandler),
            (r"/trust_pool(.*)", TrustPoolHandler),
            (r"/get_latest_block(.*)", GetLatestBlockHandler),
            (r"/get_supply(.*)", GetSupplyHandler),
            (r"/announce_peer(.*)", AnnouncePeerHandler),
            (r"/status_pool(.*)", StatusPoolHandler),
            (r"/status(.*)", StatusHandler),
            (r"/peers(.*)", PeerPoolHandler),
            (r"/peer_buffer(.*)", PeerBufferHandler),
            (r"/penalties(.*)", PenaltiesHandler),
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
            (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": "static"}),
            (r'/(favicon.ico)', tornado.web.StaticFileHandler, {"path": "graphics"}),
        ]
        super().__init__(handlers)


async def main():
    # Initialize logging
    logging.getLogger('tornado.access').disabled = True
    logger = get_logger(logger_name="main_logger")
    allow_async()

    # Version check
    updated_version = versioner.update_version()
    if updated_version:
        versioner.set_version(updated_version)

    # Initialize folders and genesis if needed
    if not os.path.exists(f"{get_home()}/blocks"):
        make_folders()
        make_genesis(
            address="ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b80137b",
            balance=1000000000000000000,
            ip="78.102.98.72",
            port=9173,
            timestamp=1669852800,
            logger=logger,
        )

    # Initialize keys
    if not keyfile_found():
        save_keys(generate_keys())
        save_peer(
            ip=get_config()["ip"],
            address=load_keys()["address"],
            port=get_config()["port"],
            peer_trust=10000
        )

    info_path = os.path.normpath(f'{get_home()}/private/keys.dat')
    logger.info(f"Key location: {info_path}")

    # Check port availability
    port = get_config()["port"]
    assert not await is_port_in_use(port), "Port already in use, exiting"

    # Set up signal handlers
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    # Initialize server and clients
    global memserver, consensus
    memserver = MemServer(logger=logger)

    logger.info(f"NADO version {memserver.version} started")
    logger.info(f"Your address: {memserver.address}")
    logger.info(f"Your IP: {memserver.ip}")
    logger.info(f"Promiscuity mode: {memserver.promiscuous}")
    logger.info(f"Cascade depth limit: {memserver.cascade_limit}")

    # Initialize clients without awaiting since they're not async yet
    consensus = ConsensusClient(memserver=memserver, logger=logger)
    consensus.start()  # Regular non-async start

    core = CoreClient(memserver=memserver, consensus=consensus, logger=logger)
    core.start()  # Regular non-async start

    peers = PeerClient(memserver=memserver, consensus=consensus, logger=logger)
    peers.start()  # Regular non-async start

    messages = MessageClient(memserver=memserver, consensus=consensus, core=core, peers=peers, logger=logger)
    messages.start()  # Regular non-async start

    logger.info("Starting Request Handler")

    # Start Tornado application
    app = Application()
    app.listen(port)

    # Keep the server running
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())