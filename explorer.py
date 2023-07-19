import requests
import tornado.ioloop
import tornado.web
import asyncio
import json

nado_node = "http://127.0.0.1:9173"


class HomeHandler(tornado.web.RequestHandler):
    def home(self):
        data = self.get_data()
        self.render("templates/explorer.html",
                    data=data)

    def get_data(self):
        data = requests.get(f"{nado_node}/get_latest_block").text
        return json.loads(data)

    def get(self):
        self.home()

class BlockNumberHandler(tornado.web.RequestHandler):
    def block(self, block):
        data = self.get_data(block)
        self.render("templates/explorer.html",
                    data=data)

    def get_data(self, block):
        data = requests.get(f"{nado_node}/get_block_number?number={block}").text
        return json.loads(data)

    def get(self, parameters):
        entry = AccountHandler.get_argument(self, "entry")
        self.block(block=entry)

class AccountHandler(tornado.web.RequestHandler):
    def account(self, account):
        data = self.get_data(account)
        self.render("templates/account.html",
                    data=data)

    def get_data(self, account):
        data = requests.get(f"{nado_node}/get_account?address={account}&readable=true").text
        return json.loads(data)

    def get(self, parameters):
        entry = AccountHandler.get_argument(self, "entry")
        self.account(account=entry)


class TransactionHandler(tornado.web.RequestHandler):
    def transaction(self, txid):
        data = self.get_data(txid)
        self.render("templates/transaction.html",
                    data=data)

    def get_data(self, txid):
        data = requests.get(f"{nado_node}/get_transaction?txid={txid}&readable=true").text
        return json.loads(data)

    def get(self, parameters):
        entry = TransactionHandler.get_argument(self, "entry")
        self.transaction(txid=entry)


class SupplyHandler(tornado.web.RequestHandler):
    def supply(self):
        data = self.get_data()
        self.render("templates/supply.html",
                    data=data)

    def get_data(self):
        data = requests.get(f"{nado_node}/get_supply?&readable=true").text
        return json.loads(data)

    def get(self):
        self.supply()


async def make_app(port):
    application = tornado.web.Application(
        [
            (r"/", HomeHandler),
            (r"/get_account(.*)", AccountHandler),
            (r"/get_transaction(.*)", TransactionHandler),
            (r"/get_block_number(.*)", BlockNumberHandler),
            (r"/get_supply", SupplyHandler),
            (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": "static"}),
            (r'/(favicon.ico)', tornado.web.StaticFileHandler, {"path": "graphics"}),

        ]
    )
    application.listen(port)
    await asyncio.Event().wait()


asyncio.run(make_app(9890))
