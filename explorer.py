import requests
import tornado.ioloop
import tornado.web
import asyncio
import json
from datetime import datetime

nado_node = "http://127.0.0.1:9173"


def to_readable_amount(raw_amount: int) -> str:
    return f"{(raw_amount / 10000000000):.10f}"


class BaseHandler(tornado.web.RequestHandler):
    def write_error(self, status_code, **kwargs):
        self.render("templates/error.html")


class HomeHandler(BaseHandler):
    def home(self):
        data = self.get_data()
        self.render("templates/explorer.html",
                    data=data,
                    node=nado_node)

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
        self.render("templates/explorer.html",
                    data=data,
                    node=nado_node)

    def get_data(self, block):
        data_raw = requests.get(f"{nado_node}/get_block_number?number={block}").text
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

    def get(self, parameters):
        entry = BlockNumberHandler.get_argument(self, "entry")
        self.block(block=entry)


class BlockHashHandler(BaseHandler):
    def block(self, hash):
        data = self.get_data(hash)
        self.render("templates/explorer.html",
                    data=data,
                    node=nado_node)

    def get_data(self, hash):
        data_raw = requests.get(f"{nado_node}/get_block?hash={hash}").text
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

    def get(self, parameters):
        entry = BlockHashHandler.get_argument(self, "entry")
        self.block(hash=entry)


class AccountHandler(BaseHandler):
    def account(self, account):
        data = self.get_data(account)
        self.render("templates/account.html",
                    data=data,
                    node=nado_node)

    def get_data(self, account):
        data = requests.get(f"{nado_node}/get_account?address={account}&readable=true").text
        return json.loads(data)

    def get(self, parameters):
        entry = AccountHandler.get_argument(self, "entry")
        self.account(account=entry)


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


class TransactionHandler(BaseHandler):
    def transaction(self, txid):
        data = self.get_data(txid)
        self.render("templates/transaction.html",
                    data=data,
                    node=nado_node)

    def get_data(self, txid):
        data_raw = requests.get(f"{nado_node}/get_transaction?txid={txid}&readable=true").text
        data = json.loads(data_raw)
        readable_ts = {"timestamp": datetime.fromtimestamp(data["timestamp"])}
        readable_reward = {"fee": to_readable_amount(data["fee"])}
        data.update(readable_ts)
        data.update(readable_reward)
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


async def make_app(port):
    application = tornado.web.Application(
        [
            (r"/", HomeHandler),
            (r"/get_account_txs(.*)", TxsOfAccountHandler),
            (r"/get_account(.*)", AccountHandler),
            (r"/get_transaction(.*)", TransactionHandler),
            (r"/get_block_number(.*)", BlockNumberHandler),
            (r"/get_block(.*)", BlockHashHandler),
            (r"/get_supply", SupplyHandler),
            (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": "static"}),
            (r"/graphics/(.*)", tornado.web.StaticFileHandler, {"path": "graphics"}),
            (r'/(favicon.ico)', tornado.web.StaticFileHandler, {"path": "graphics"}),

        ]
    )
    application.listen(port)
    await asyncio.Event().wait()


asyncio.run(make_app(9890))
