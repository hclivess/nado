import os.path

import requests
import tornado.ioloop
import tornado.web
import asyncio
import json
from datetime import datetime
import ssl

with open("config_explorer.json") as certlocfile:
    contents = json.load(certlocfile)
    certfile = contents["certfile"]
    keyfile = contents["keyfile"]
    nado_node = contents["nado_node"]


def to_readable_amount(raw_amount: int) -> str:
    return f"{(raw_amount / 10000000000):.10f}"


class BaseHandler(tornado.web.RequestHandler):
    def write_error(self, status_code, **kwargs):
        self.render("templates/error.html",
                    node=nado_node)


class HomeHandler(BaseHandler):
    def home(self):
        data = self.get_data()
        self.render("templates/explorer.html",
                    data=data,
                    node=nado_node,
                    tx_no=len(data["block_transactions"]))

    def get_data(self):
        data_raw = requests.get(f"{nado_node}/get_latest_block").text
        data = json.loads(data_raw)
        readable_ts = {"block_timestamp": datetime.fromtimestamp(data["block_timestamp"])}
        readable_reward = {"block_reward": to_readable_amount(data["block_timestamp"])}
        data.update(readable_ts)
        data.update(readable_reward)

        for transaction in data["block_transactions"]:
            readable_amount = {"amount": to_readable_amount(transaction["amount"])}
            readable_fee = {"fee": to_readable_amount(transaction["fee"])}
            transaction.update(readable_amount)
            transaction.update(readable_fee)
        return data

    def get(self):
        self.home()


class BlockNumberHandler(BaseHandler):
    def block(self, block):
        data = self.get_data(block)

        if data["block_number"] == "Not found":
            self.render("templates/error.html",
                        node=nado_node)

        else:
            readable_ts = {"block_timestamp": datetime.fromtimestamp(data["block_timestamp"])}
            readable_reward = {"block_reward": to_readable_amount(data["block_timestamp"])}
            data.update(readable_ts)
            data.update(readable_reward)

            for transaction in data["block_transactions"]:
                readable_amount = {"amount": to_readable_amount(transaction["amount"])}
                readable_fee = {"fee": to_readable_amount(transaction["fee"])}
                transaction.update(readable_amount)
                transaction.update(readable_fee)

            self.render("templates/explorer.html",
                        data=data,
                        node=nado_node,
                        tx_no=len(data["block_transactions"]))

    def get_data(self, block):
        data_raw = requests.get(f"{nado_node}/get_block_number?number={block}").text
        data = json.loads(data_raw)

        return data

    def get(self, parameters):
        entry = BlockNumberHandler.get_argument(self, "entry")
        self.block(block=entry)


class BlockHashHandler(BaseHandler):
    def block(self, hash):
        data = self.get_data(hash)

        if data["block_hash"] == "Not found":
            self.render("templates/error.html",
                        node=nado_node)

        else:

            readable_ts = {"block_timestamp": datetime.fromtimestamp(data["block_timestamp"])}
            readable_reward = {"block_reward": to_readable_amount(data["block_timestamp"])}
            data.update(readable_ts)
            data.update(readable_reward)

            for transaction in data["block_transactions"]:
                readable_amount = {"amount": to_readable_amount(transaction["amount"])}
                readable_fee = {"fee": to_readable_amount(transaction["fee"])}
                transaction.update(readable_amount)
                transaction.update(readable_fee)

            self.render("templates/explorer.html",
                        data=data,
                        node=nado_node,
                        tx_no=len(data["block_transactions"]))

    def get_data(self, hash):
        data_raw = requests.get(f"{nado_node}/get_block?hash={hash}").text
        data = json.loads(data_raw)

        return data

    def get(self, parameters):
        entry = BlockHashHandler.get_argument(self, "entry")
        self.block(hash=entry)


class AccountHandler(BaseHandler):
    def account(self, account):
        data = self.get_data(account)

        if data["address"] == "Not found":
            self.render("templates/error.html",
                        node=nado_node)

        else:
            self.render("templates/account.html",
                        data=data,
                        node=nado_node)

    def get_data(self, account):
        data = requests.get(f"{nado_node}/get_account?address={account}&readable=true").text
        return json.loads(data)

    def get(self, parameters):
        entry = AccountHandler.get_argument(self, "entry")
        self.account(account=entry)

class StatsHandler(BaseHandler):
    def stats(self):
        data = self.get_data()

        self.render("templates/stats.html",
                    data=json.dumps(data, indent=4, sort_keys=True, default=str),
                    node=nado_node)

    def get_data(self):
        status = json.loads(requests.get(f"{nado_node}/status").text)
        status_pool = json.loads(requests.get(f"{nado_node}/status_pool").text)
        transaction_pool = json.loads(requests.get(f"{nado_node}/transaction_pool").text)
        transaction_buffer = json.loads(requests.get(f"{nado_node}/transaction_buffer").text)
        user_transaction_buffer = json.loads(requests.get(f"{nado_node}/user_transaction_buffer").text)
        peers = json.loads(requests.get(f"{nado_node}/peers").text)
        peers_buffer = json.loads(requests.get(f"{nado_node}/peers_buffer").text)
        unreachable = json.loads(requests.get(f"{nado_node}/unreachable").text)
        block_producers = json.loads(requests.get(f"{nado_node}/block_producers").text)
        penalties = json.loads(requests.get(f"{nado_node}/penalties").text)
        transaction_hash_pool = json.loads(requests.get(f"{nado_node}/transaction_hash_pool").text)
        block_hash_pool = json.loads(requests.get(f"{nado_node}/block_hash_pool").text)
        block_producers_hash_pool = json.loads(requests.get(f"{nado_node}/block_producers_hash_pool").text)
        trust_pool = json.loads(requests.get(f"{nado_node}/trust_pool").text)

        data = {"status": status,
                "status_pool": status_pool,
                "transaction_pool": transaction_pool,
                "transaction_buffer": transaction_buffer,
                "user_transaction_buffer": user_transaction_buffer,
                "peers": peers,
                "peers_buffer": peers_buffer,
                "unreachable": unreachable,
                "block_producers": block_producers,
                "penalties": penalties,
                "transaction_hash_pool": transaction_hash_pool,
                "block_hash_pool": block_hash_pool,
                "block_producers_hash_pool": block_producers_hash_pool,
                "trust_pool": trust_pool,
                }

        return data

    def get(self):
        self.stats()

class TxsOfAccountHandler(BaseHandler):
    def accounttxs(self, accounttxs, min_block):
        data = self.get_data(accounttxs, min_block)
        self.render("templates/txsofaccount.html",
                    data=data,
                    node=nado_node)

    def get_data(self, account, min_block):
        data = requests.get(f"{nado_node}/get_transactions_of_account?address={account}&min_block={min_block}").text
        return json.loads(data)

    def get(self, parameters):
        entry = TxsOfAccountHandler.get_argument(self, "entry")
        min_block = TxsOfAccountHandler.get_argument(self, "min_block", default="0")
        self.accounttxs(accounttxs=entry,
                        min_block=min_block)

class AutomaticHandler(BaseHandler):
    def get(self, parameters):
        entry = TransactionHandler.get_argument(self, "entry")

        if len(entry) == 49:
            self.redirect(f"/get_account?entry={entry}")
        elif len(entry) == 49:
            self.redirect(f"/get_account?entry={entry}")

class TransactionHandler(BaseHandler):
    def transaction(self, txid):
        data = self.get_data(txid)

        if data["txid"] == "Not found":
            self.render("templates/error.html",
                        node=nado_node)

        else:
            readable_ts = {"timestamp": datetime.fromtimestamp(data["timestamp"])}
            readable_reward = {"fee": to_readable_amount(data["fee"])}
            data.update(readable_ts)
            data.update(readable_reward)

            self.render("templates/transaction.html",
                        data=data,
                        raw=json.dumps(data, indent=4, sort_keys=True, default=str),
                        node=nado_node)

    def get_data(self, txid):
        data_raw = requests.get(f"{nado_node}/get_transaction?txid={txid}&readable=true").text
        data = json.loads(data_raw)

        return data

    def get(self, parameters):
        entry = TransactionHandler.get_argument(self, "entry")
        self.transaction(txid=entry)


class SupplyHandler(BaseHandler):
    def supply(self):
        data = self.get_data()
        self.render("templates/supply.html",
                    data=data,
                    node=nado_node)

    def get_data(self):
        data = requests.get(f"{nado_node}/get_supply?&readable=true").text
        return json.loads(data)

    def get(self):
        self.supply()


class RedirectToHTTPSHandler(tornado.web.RequestHandler):
    def get(self, parameters):
        self.redirect(self.request.full_url().replace('http://', 'https://'), permanent=True)


async def make_app(port):
    if os.path.exists(certfile):
        ssl_options = {
            "certfile": certfile,
            "keyfile": keyfile,
        }
    else:
        ssl_options = None

    application = tornado.web.Application(
        [
            (r"/", HomeHandler),
            (r"/get_account_txs(.*)", TxsOfAccountHandler),
            (r"/get_account(.*)", AccountHandler),
            (r"/get_transaction(.*)", TransactionHandler),
            (r"/get_block_number(.*)", BlockNumberHandler),
            (r"/get_block(.*)", BlockHashHandler),
            (r"/stats", StatsHandler),
            (r"/automatic(.*)", AutomaticHandler),
            (r"/get_supply", SupplyHandler),
            (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": "static"}),
            (r"/graphics/(.*)", tornado.web.StaticFileHandler, {"path": "graphics"}),
            (r'/(favicon.ico)', tornado.web.StaticFileHandler, {"path": "graphics"}),

        ]
    )

    application_redirect = tornado.web.Application(
        [
            (r"/(.*)", RedirectToHTTPSHandler),
        ]
    )

    application.listen(port, ssl_options=ssl_options)
    application_redirect.listen(80)
    await asyncio.Event().wait()


asyncio.run(make_app(443))
