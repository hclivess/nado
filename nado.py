import ipaddress
import json
import os
import signal
import socket
import sys

import tornado.ioloop
import tornado.web

from block_ops import get_block, get_latest_block_info
from config import get_config
from consensus import ConsensusClient
from core_loop import CoreClient
from data_ops import set_and_sort
from genesis import make_genesis, make_folders
from keys import keyfile_found, generate_keys, save_keys, load_keys
from logs import get_logger
from memserver import MemServer
from message_loop import MessageClient
from peer_loop import PeerClient
from peers import save_peer, get_remote_peer_address, get_producer_set
from transaction_ops import get_account, get_transaction, get_transactions_of_account
from config import get_timestamp_seconds


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
        self.render("templates/homepage.html")


class StatusHandler(tornado.web.RequestHandler):
    def get(self):
        try:
            status_dict = {
                "reported_uptime": memserver.reported_uptime,
                "address": memserver.address,
                "transaction_pool_hash": memserver.transaction_pool_hash,
                "block_producers_hash": memserver.block_producers_hash,
                "latest_block_hash": get_latest_block_info(logger=logger)["block_hash"],
            }
            self.write(status_dict)
        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class TransactionPoolHandler(tornado.web.RequestHandler):
    def get(self):
        transaction_pool = {"transaction_pool": memserver.transaction_pool}
        self.write(transaction_pool)


class TransactionBufferHandler(tornado.web.RequestHandler):
    def get(self):
        tx_buffer = {"transaction_buffer": memserver.tx_buffer}
        self.write(tx_buffer)


class TrustPoolHandler(tornado.web.RequestHandler):
    def get(self):
        trust_pool = {"trust_pool": consensus.trust_pool}
        self.write(trust_pool)


class PeerPoolHandler(tornado.web.RequestHandler):
    def get(self):
        self.write({"peers": list(memserver.peers)})


class BlockProducerPoolHandler(tornado.web.RequestHandler):
    def get(self):
        self.write({"block_producers": list(memserver.block_producers)})


class BlockProducersHashPoolHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(
            {
                "block_producers_hash_pool": consensus.block_producers_hash_pool,
                "majority_block_producers_hash_pool": consensus.majority_block_producers_hash,
            }
        )


class TransactionHashPoolHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(
            {
                "transactions_hash_pool": consensus.transaction_hash_pool,
                "majority_transactions_hash_pool": consensus.majority_transaction_pool_hash,
            }
        )


class BlockHashPoolHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(
            {
                "block_opinions": consensus.block_hash_pool,
                "majority_block_opinion": consensus.majority_block_hash,
            }
        )


class StatusPoolHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(consensus.status_pool)


class SubmitTransactionHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            transaction = json.loads(SubmitTransactionHandler.get_argument(self, "data"))
            output = memserver.merge_transaction(transaction, user=True)
            self.write(output)

            if not output["result"]:
                self.set_status(403)

        except Exception as e:
            self.write(f"Invalid transaction structure on submission attempt: {e}")


class LogHandler(tornado.web.RequestHandler):
    def get(self):
        with open("logs/log.log") as logfile:
            lines = logfile.readlines()
            for line in lines:
                self.write(line)
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
            output = get_transaction(transaction, logger=logger)
            if not output:
                output = "Not found"
                self.set_status(403)
            self.write(output)
        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class AccountTransactionsHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            address = AccountTransactionsHandler.get_argument(self, "address")
            output = get_transactions_of_account(address, logger=logger)
            if not output:
                output = "Not found"
                self.set_status(403)
            self.write(output)
        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class GetBlockHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            block = GetBlockHandler.get_argument(self, "hash")
            output = get_block(block)
            if not output:
                output = "Not found"
                self.set_status(403)
            self.write(output)
        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class GetBlocksBeforeHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            block_hash = GetBlocksBeforeHandler.get_argument(self, "hash")
            count = int(GetBlocksBeforeHandler.get_argument(self, "count"))

            parent_hash = get_block(block_hash)["parent_hash"]

            collected_blocks = []
            for blocks in range(0, count):
                try:
                    block = get_block(parent_hash)
                    if block:
                        collected_blocks.append(block)
                        parent_hash = block["parent_hash"]
                except Exception as e:
                    print(e)
                    break

            output = collected_blocks
            output.reverse()

            if not output:
                output = "Not found"
                self.set_status(403)

            self.write({"blocks_before": output})

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class GetBlocksAfterHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            block_hash = GetBlocksAfterHandler.get_argument(self, "hash")
            count = int(GetBlocksAfterHandler.get_argument(self, "count"))

            child_hash = get_block(block_hash)["child_hash"]

            collected_blocks = []

            for blocks in range(0, count):
                try:
                    block = get_block(child_hash)
                    if block:
                        collected_blocks.append(block)
                        child_hash = block["child_hash"]
                except:
                    break

            output = collected_blocks

            if not output:
                output = "Not found"
                self.set_status(403)

            self.write({"blocks_after": output})

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class GetLatestBlockHandler(tornado.web.RequestHandler):
    def get(self):
        self.write(get_latest_block_info(logger=logger))


class AccountHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            account = AccountHandler.get_argument(self, "address")
            output = get_account(account, create_on_error=False)
            if not output:
                output = "Not found"
                self.set_status(403)
            self.write(output)

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class ProducerSetHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            producer_set_hash = ProducerSetHandler.get_argument(self, "hash")
            output = get_producer_set(producer_set_hash)
            if not output:
                output = "Not found"
                self.set_status(403)
            self.write(output)

        except Exception as e:
            self.set_status(403)
            self.write(f"Error: {e}")


class AnnouncePeerHandler(tornado.web.RequestHandler):
    def get(self, parameter):
        try:
            peer_ip = AnnouncePeerHandler.get_argument(self, "ip")
            assert ipaddress.ip_address(peer_ip)

            if peer_ip == "127.0.0.1" or peer_ip == get_config()["ip"]:
                self.write("Cannot add home address")
            else:

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
            (r"/status", StatusHandler),
            (r"/get_transactions_of_account(.*)", AccountTransactionsHandler),
            (r"/get_transaction(.*)", TransactionHandler),
            (r"/get_blocks_after(.*)", GetBlocksAfterHandler),
            (r"/get_blocks_before(.*)", GetBlocksBeforeHandler),
            (r"/get_block(.*)", GetBlockHandler),
            (r"/get_account(.*)", AccountHandler),
            (r"/get_producer_set_from_hash(.*)", ProducerSetHandler),
            (r"/transaction_pool", TransactionPoolHandler),
            (r"/transaction_hash_pool", TransactionHashPoolHandler),
            (r"/transaction_buffer", TransactionBufferHandler),
            (r"/trust_pool", TrustPoolHandler),
            (r"/get_latest_block", GetLatestBlockHandler),
            (r"/announce_peer(.*)", AnnouncePeerHandler),
            (r"/status_pool", StatusPoolHandler),
            (r"/peers", PeerPoolHandler),
            (r"/block_producers", BlockProducerPoolHandler),
            (r"/block_producers_hash_pool", BlockProducersHashPoolHandler),
            (r"/block_hash_pool", BlockHashPoolHandler),
            (r"/terminate(.*)", TerminateHandler),
            (r"/submit_transaction(.*)", SubmitTransactionHandler),
            (r"/log", LogHandler),
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
            balance=1000000000000000,
            ip="89.176.130.244",
            port=9173,
            timestamp=1657829259,
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
