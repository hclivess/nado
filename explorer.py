import os.path
import asyncio
from datetime import datetime
import json
import ssl

import tornado.ioloop
import tornado.web
from tornado.httpclient import AsyncHTTPClient

# Load config
with open("config_explorer.json") as certlocfile:
    contents = json.load(certlocfile)
    certfile = contents["certfile"]
    keyfile = contents["keyfile"]
    nado_node = contents["nado_node"]


def to_readable_amount(raw_amount: int) -> str:
    return f"{(raw_amount / 10000000000):.10f}"


class BaseHandler(tornado.web.RequestHandler):
    def write_error(self, status_code, **kwargs):
        self.render("templates/error.html", node=nado_node)

    async def fetch_json(self, url):
        client = AsyncHTTPClient()
        response = await client.fetch(url)
        return json.loads(response.body)


class HomeHandler(BaseHandler):
    async def get(self):
        await self.home()

    async def home(self):
        data = await self.get_data()
        self.render("templates/explorer.html",
                    data=data,
                    node=nado_node,
                    tx_no=len(data["block_transactions"]))

    async def get_data(self):
        data = await self.fetch_json(f"{nado_node}/get_latest_block")
        readable_ts = {"block_timestamp": datetime.fromtimestamp(data["block_timestamp"])}
        readable_reward = {"block_reward": to_readable_amount(data["block_timestamp"])}
        data.update(readable_ts)
        data.update(readable_reward)

        for transaction in data["block_transactions"]:
            transaction.update({
                "amount": to_readable_amount(transaction["amount"]),
                "fee": to_readable_amount(transaction["fee"])
            })
        return data


class BlockNumberHandler(BaseHandler):
    async def get(self, parameters):
        entry = self.get_argument("entry")
        await self.block(block=entry)

    async def block(self, block):
        data = await self.get_data(block)

        if data["block_number"] == "Not found":
            self.render("templates/error.html", node=nado_node)
            return

        readable_ts = {"block_timestamp": datetime.fromtimestamp(data["block_timestamp"])}
        readable_reward = {"block_reward": to_readable_amount(data["block_timestamp"])}
        data.update(readable_ts)
        data.update(readable_reward)

        for transaction in data["block_transactions"]:
            transaction.update({
                "amount": to_readable_amount(transaction["amount"]),
                "fee": to_readable_amount(transaction["fee"])
            })

        self.render("templates/explorer.html",
                    data=data,
                    node=nado_node,
                    tx_no=len(data["block_transactions"]))

    async def get_data(self, block):
        return await self.fetch_json(f"{nado_node}/get_block_number?number={block}")


class BlockHashHandler(BaseHandler):
    async def get(self, parameters):
        entry = self.get_argument("entry")
        await self.block(hash=entry)

    async def block(self, hash):
        data = await self.get_data(hash)

        if data["block_hash"] == "Not found":
            self.render("templates/error.html", node=nado_node)
            return

        readable_ts = {"block_timestamp": datetime.fromtimestamp(data["block_timestamp"])}
        readable_reward = {"block_reward": to_readable_amount(data["block_timestamp"])}
        data.update(readable_ts)
        data.update(readable_reward)

        for transaction in data["block_transactions"]:
            transaction.update({
                "amount": to_readable_amount(transaction["amount"]),
                "fee": to_readable_amount(transaction["fee"])
            })

        self.render("templates/explorer.html",
                    data=data,
                    node=nado_node,
                    tx_no=len(data["block_transactions"]))

    async def get_data(self, hash):
        return await self.fetch_json(f"{nado_node}/get_block?hash={hash}")


class AccountHandler(BaseHandler):
    async def get(self, parameters):
        entry = self.get_argument("entry")
        await self.account(account=entry)

    async def account(self, account):
        data = await self.get_data(account)

        if data["address"] == "Not found":
            self.render("templates/error.html", node=nado_node)
            return

        self.render("templates/account.html",
                    data=data,
                    node=nado_node)

    async def get_data(self, account):
        return await self.fetch_json(f"{nado_node}/get_account?address={account}&readable=true")


class StatsHandler(BaseHandler):
    async def get(self):
        await self.stats()

    async def stats(self):
        data = await self.get_data()
        self.render("templates/stats.html",
                    data=json.dumps(data, indent=4, sort_keys=True, default=str),
                    node=nado_node)

    async def get_data(self):
        endpoints = [
            "status", "status_pool", "transaction_pool", "transaction_buffer",
            "user_transaction_buffer", "peers", "peers_buffer", "unreachable",
            "block_producers", "penalties", "transaction_hash_pool",
            "block_hash_pool", "block_producers_hash_pool", "trust_pool"
        ]

        tasks = [self.fetch_json(f"{nado_node}/{endpoint}") for endpoint in endpoints]
        results = await asyncio.gather(*tasks)

        return dict(zip(endpoints, results))


class TxsOfAccountHandler(BaseHandler):
    async def get(self, parameters):
        entry = self.get_argument("entry")
        min_block = self.get_argument("min_block", default="0")
        await self.accounttxs(accounttxs=entry, min_block=min_block)

    async def accounttxs(self, accounttxs, min_block):
        data = await self.get_data(accounttxs, min_block)
        self.render("templates/txsofaccount.html",
                    data=data,
                    node=nado_node)

    async def get_data(self, account, min_block):
        return await self.fetch_json(
            f"{nado_node}/get_transactions_of_account?address={account}&min_block={min_block}"
        )


class AutomaticHandler(BaseHandler):
    def get(self, parameters):
        entry = self.get_argument("entry")
        if len(entry) == 49:
            self.redirect(f"/get_account?entry={entry}")
        elif entry.isnumeric():
            self.redirect(f"/get_block_number?entry={entry}")
        else:
            self.redirect(f"/get_transaction?entry={entry}")


class TransactionHandler(BaseHandler):
    async def get(self, parameters):
        entry = self.get_argument("entry")
        await self.transaction(txid=entry)

    async def transaction(self, txid):
        data = await self.get_data(txid)

        if data["txid"] == "Not found":
            self.set_status(404)
            self.render("templates/error.html", node=nado_node)
            return

        readable_ts = {"timestamp": datetime.fromtimestamp(data["timestamp"])}
        readable_reward = {"fee": to_readable_amount(data["fee"])}
        data.update(readable_ts)
        data.update(readable_reward)

        self.render("templates/transaction.html",
                    data=data,
                    raw=json.dumps(data, indent=4, sort_keys=True, default=str),
                    node=nado_node)

    async def get_data(self, txid):
        return await self.fetch_json(f"{nado_node}/get_transaction?txid={txid}&readable=true")


class SupplyHandler(BaseHandler):
    async def get(self):
        await self.supply()

    async def supply(self):
        data = await self.get_data()
        self.render("templates/supply.html",
                    data=data,
                    node=nado_node)

    async def get_data(self):
        return await self.fetch_json(f"{nado_node}/get_supply?&readable=true")


async def make_app(port):
    ssl_options = {
        "certfile": certfile,
        "keyfile": keyfile,
    } if os.path.exists(certfile) else None

    application = tornado.web.Application([
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
    ])

    application.listen(port, ssl_options=ssl_options)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(make_app(443))