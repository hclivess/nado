import ipaddress
import json
import os
import signal
import socket
import sys

import msgpack
import tornado.ioloop
import tornado.web

from block_ops import get_block, get_latest_block_info, fee_over_blocks
from config import get_config
from loops.consensus_loop import ConsensusClient
from loops.core_loop import CoreClient
from data_ops import set_and_sort
from genesis import make_genesis, make_folders
from keys import keyfile_found, generate_keys, save_keys, load_keys
from log_ops import get_logger
from memserver import MemServer
from loops.message_loop import MessageClient
from loops.peer_loop import PeerClient
from peer_ops import save_peer, get_remote_peer_address, get_producer_set, update_peer, load_peer
from transaction_ops import get_transaction, get_transactions_of_account
from config import get_timestamp_seconds
from account_ops import get_account


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


def handler(signum, frame):
    logger.info("Terminating..")
    memserver.terminate = True
    tornado.ioloop.IOLoop.current().stop()
    sys.exit(0)


class HomeHandler(tornado.web.RequestHandler):
    def get(self):
        self.render("templates/homepage.html", ip=get_config()["ip"])


def serialize(output, name=None, compress=None):
    if compress == "msgpack":
        output = msgpack.packb(output)
    elif not isinstance(output, dict) and name:
        output = {name: output}
    return output


class StatusHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")

        try:
            status_dict = {
                "reported_uptime": memserver.reported_uptime,
                "address": memserver.address,
                "transaction_pool_hash": memserver.transaction_pool_hash,
                "block_producers_hash": memserver.block_producers_hash,
                "latest_block_hash": get_latest_block_info(logger=logger)["block_hash"],
                "protocol": memserver.protocol,
            }

            self.write(serialize(name="status",
                                 output=status_dict,
                                 compress=compress))

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class TransactionPoolHandler(tornado.web.RequestHandler):

    def get(self, parameter):
        compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")
        transaction_pool_data = memserver.transaction_pool
        self.write(serialize(name="transaction_pool",
                             output=transaction_pool_data,
                             compress=compress))


class TransactionBufferHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")
        buffer_data = memserver.tx_buffer

        self.write(serialize(name="transaction_buffer",
                             output=buffer_data,
                             compress=compress))


class TrustPoolHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")
        trust_pool_data = consensus.trust_pool

        self.write(serialize(name="trust_pool_data",
                             output=trust_pool_data,
                             compress=compress,
                             ))


class PeerPoolHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")
        peers_data = list(memserver.peers)

        self.write(serialize(name="peers",
                             output=peers_data,
                             compress=compress
                             ))


class BlockProducerPoolHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")
        producer_data = list(memserver.block_producers)

        self.write(serialize(name="block_producers",
                             output=producer_data,
                             compress=compress))


class BlockProducersHashPoolHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")

        output = {
            "block_producers_hash_pool": consensus.block_producers_hash_pool,
            "majority_block_producers_hash_pool": consensus.majority_block_producers_hash,
        }

        self.write(serialize(name="block_producers_hash_pool",
                             output=output,
                             compress=compress))


class TransactionHashPoolHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")

        output = {
            "transactions_hash_pool": consensus.transaction_hash_pool,
            "majority_transactions_hash_pool": consensus.majority_transaction_pool_hash,
        }

        self.write(serialize(name="transactions_hash_pool",
                             output=output,
                             compress=compress))


class BlockHashPoolHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        compress = BlockHashPoolHandler.get_argument(self, "compress", default="none")

        output = {
            "block_opinions": consensus.block_hash_pool,
            "majority_block_opinion": consensus.majority_block_hash,
        }

        self.write(serialize(name="block_hash_pool",
                             output=output,
                             compress=compress))


class FeeHandler(tornado.web.RequestHandler):
    def get(self):
        self.write({"fee": fee_over_blocks(logger=logger)})


class StatusPoolHandler(tornado.web.RequestHandler):  # validate
    def get(self, parameter):
        compress = StatusPoolHandler.get_argument(self, "compress", default="none")
        status_pool_data = consensus.status_pool

        self.write(serialize(name="status_pool",
                             output=status_pool_data,
                             compress=compress))


class SubmitTransactionHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            transaction_raw = SubmitTransactionHandler.get_argument(self, "data")
            transaction = json.loads(transaction_raw)

            output = memserver.merge_transaction(transaction, user=True)
            self.write(msgpack.packb(output))

            if not output["result"]:
                self.set_status(403)

        except Exception as e:
            self.write(msgpack.packb(f"Invalid tx structure: {e}"))
            raise


class LogHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")

        with open("logs/log.log") as logfile:
            lines = logfile.readlines()
            for line in lines:
                if compress == "msgpack":
                    output = msgpack.packb(line)
                else:
                    output = line
                self.write(output)
                self.write("<br>")


class TerminateHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            server_key = TerminateHandler.get_argument(self, "key")

            if server_key == memserver.server_key:
                memserver.terminate = True
                tornado.ioloop.IOLoop.current().stop()
        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class TransactionHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            transaction = TransactionHandler.get_argument(self, "txid")
            transaction_data = get_transaction(transaction, logger=logger)
            compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")

            if not transaction_data:
                transaction_data = "Not found"
                self.set_status(403)

            self.write(serialize(name="transaction",
                                 output=transaction_data,
                                 compress=compress))

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class AccountTransactionsHandler(tornado.web.RequestHandler):
    """get transactions from a transaction index batch"""
    """batch takes number or max"""

    def get(self, parameter):
        try:
            address = AccountTransactionsHandler.get_argument(self, "address")
            batch = AccountTransactionsHandler.get_argument(self, "batch")
            compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")

            transaction_data = get_transactions_of_account(account=address,
                                                           logger=logger,
                                                           batch=batch)

            if not transaction_data:
                transaction_data = "Not found"
                self.set_status(403)

            self.write(serialize(name="account_transactions",
                                 output=transaction_data,
                                 compress=compress))
        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class GetBlockHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            block = GetBlockHandler.get_argument(self, "hash")
            compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")
            block_data = get_block(block)

            if not block_data:
                block_data = "Not found"
                self.set_status(403)

            self.write(serialize(name="block",
                                 output=block_data,
                                 compress=compress))

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class GetBlocksBeforeHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            block_hash = GetBlocksBeforeHandler.get_argument(self, "hash")
            count = int(GetBlocksBeforeHandler.get_argument(self, "count"))
            compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")

            parent_hash = get_block(block_hash)["parent_hash"]

            collected_blocks = []
            for blocks in range(0, count):
                try:
                    block = get_block(parent_hash)
                    if block:
                        collected_blocks.append(block)
                        parent_hash = block["parent_hash"]
                except Exception as e:
                    logger.debug("Block collection hit a roadblock")
                    break

            collected_blocks.reverse()

            if not collected_blocks:
                collected_blocks = "Not found"
                self.set_status(403)

            self.write(serialize(name="blocks_before",
                                 output=collected_blocks,
                                 compress=compress
                                 ))


        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class GetBlocksAfterHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            block_hash = GetBlocksAfterHandler.get_argument(self, "hash")
            count = int(GetBlocksAfterHandler.get_argument(self, "count"))
            compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")

            child_hash = get_block(block_hash)["child_hash"]

            collected_blocks = []

            for blocks in range(0, count):
                try:
                    block = get_block(child_hash)
                    if block:
                        collected_blocks.append(block)
                        child_hash = block["child_hash"]
                except Exception as e:
                    logger.debug("Block collection hit a roadblock")
                    break

            if not collected_blocks:
                collected_blocks = "Not found"
                self.set_status(403)

            self.write(serialize(name="blocks_after",
                                 output=collected_blocks,
                                 compress=compress,
                                 ))

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class GetLatestBlockHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        latest_block_data = get_latest_block_info(logger=logger)
        compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")

        self.write(serialize(name="latest_block",
                             output=latest_block_data,
                             compress=compress))

class AccountHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            account = AccountHandler.get_argument(self, "address")
            compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")
            account_data = get_account(account, create_on_error=False)

            if not account_data:
                account_data = "Not found"
                self.set_status(403)

            self.write(serialize(name="account",
                                 output=account_data,
                                 compress=compress))

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class ProducerSetHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            producer_set_hash = ProducerSetHandler.get_argument(self, "hash")
            compress = GetBlocksAfterHandler.get_argument(self, "compress", default="none")

            producer_data = get_producer_set(producer_set_hash)

            if not producer_data:
                producer_data = "Not found"
                self.set_status(403)

            self.write(serialize(name="producer_set",
                                 output=producer_data,
                                 compress=compress))
        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


def update_address(peer_ip):
    address = get_remote_peer_address(peer_ip, logger=logger)
    """get address from peer itself in case they decided to change it"""
    old_address = load_peer(logger=logger,
                            ip=peer_ip,
                            peer_file_lock=memserver.peer_file_lock,
                            key="peer_address")

    if address and address != old_address:
        update_peer(ip=peer_ip,
                    logger=logger,
                    peer_file_lock=memserver.peer_file_lock,
                    key="peer_address",
                    value=address)
        logger.info(f"{peer_ip} address updated")


class AnnouncePeerHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            peer_ip = AnnouncePeerHandler.get_argument(self, "ip")
            assert ipaddress.ip_address(peer_ip)

            if peer_ip == "127.0.0.1" or peer_ip == get_config()["ip"]:
                self.write("Cannot add home address")
            else:
                update_address(peer_ip)

                if peer_ip in memserver.unreachable:
                    logger.info(f"Removed {peer_ip} from unreachable")
                    memserver.unreachable.remove(peer_ip)

                if peer_ip not in memserver.peers:
                    address = get_remote_peer_address(peer_ip, logger=logger)
                    assert address, "No address detected"

                    save_peer(ip=peer_ip,
                              address=address,
                              port=get_config()["port"],
                              last_seen=get_timestamp_seconds()
                              )

                    if peer_ip not in memserver.peers + memserver.peer_buffer:
                        if memserver.period == 3:
                            memserver.peer_buffer.append(peer_ip)
                            memserver.peer_buffer = set_and_sort(memserver.peer_buffer)
                        else:
                            memserver.peers.append(peer_ip)
                            memserver.peers = set_and_sort(memserver.peers)

                    message = f"Peer {peer_ip} added"
                else:
                    message = f"Peer {peer_ip} is known or invalid"
                self.write(message)

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


def make_app():
    return tornado.web.Application(
        [
            (r"/", HomeHandler),
            (r"/status(.*)", StatusHandler),
            (r"/get_transactions_of_account(.*)", AccountTransactionsHandler),
            (r"/get_transaction(.*)", TransactionHandler),
            (r"/get_blocks_after(.*)", GetBlocksAfterHandler),
            (r"/get_blocks_before(.*)", GetBlocksBeforeHandler),
            (r"/get_block(.*)", GetBlockHandler),
            (r"/get_account(.*)", AccountHandler),
            (r"/get_producer_set_from_hash(.*)", ProducerSetHandler),
            (r"/transaction_pool(.*)", TransactionPoolHandler),
            (r"/transaction_hash_pool(.*)", TransactionHashPoolHandler),
            (r"/transaction_buffer(.*)", TransactionBufferHandler),
            (r"/trust_pool(.*)", TrustPoolHandler),
            (r"/get_latest_block(.*)", GetLatestBlockHandler),
            (r"/announce_peer(.*)", AnnouncePeerHandler),
            (r"/status_pool(.*)", StatusPoolHandler),
            (r"/peers(.*)", PeerPoolHandler),
            (r"/block_producers(.*)", BlockProducerPoolHandler),
            (r"/block_producers_hash_pool(.*)", BlockProducersHashPoolHandler),
            (r"/block_hash_pool(.*)", BlockHashPoolHandler),
            (r"/get_recommended_fee", FeeHandler),
            (r"/terminate(.*)", TerminateHandler),
            (r"/submit_transaction(.*)", SubmitTransactionHandler),
            (r"/log(.*)", LogHandler),
            (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": "static"}),
            (r'/(favicon.ico)', tornado.web.StaticFileHandler, {"path": ""}),

        ]
    )


if __name__ == "__main__":
    logger = get_logger()

    if not os.path.exists("blocks"):
        make_folders()
        make_genesis(
            address="ndo18c3afa286439e7ebcb284710dbd4ae42bdaf21b80137b",
            balance=10000000000000000,
            ip="78.102.98.72",
            port=9173,
            timestamp=1666666666,
            logger=logger,
        )

    if not keyfile_found():
        save_keys(generate_keys())
        save_peer(ip=get_config()["ip"],
                  address=load_keys()["address"],
                  port=get_config()["port"],
                  peer_trust=10000,
                  last_seen=get_timestamp_seconds())

    assert not is_port_in_use(get_config()["port"]), "Port already in use, exiting"
    signal.signal(signal.SIGINT, handler)

    memserver = MemServer(logger=logger)

    consensus = ConsensusClient(memserver=memserver, logger=logger)
    consensus.start()

    core = CoreClient(memserver=memserver, consensus=consensus, logger=logger)
    core.start()

    peers = PeerClient(memserver=memserver, consensus=consensus, logger=logger)
    peers.start()

    messages = MessageClient(memserver=memserver, consensus=consensus, core=core, peers=peers, logger=logger)
    messages.start()

    logger.info("Starting Request Handler")

    app = make_app()
    app.listen(get_config()["port"])
    tornado.ioloop.IOLoop.current().start()
