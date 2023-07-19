import requests
import tornado.ioloop
import tornado.web
import asyncio
import json

nado_node = "http://127.0.0.1:9173"

class BaseHandler(tornado.web.RequestHandler):
    def write_error(self, status_code, **kwargs):
        self.render("templates/error.html")

class HomeHandler(BaseHandler):
    def home(self):
        data = self.get_data()
        self.render("templates/explorer.html",
                    data=data)

    def get_data(self):
        data = requests.get(f"{nado_node}/get_latest_block").text
        return json.loads(data)

    def get(self):
        self.home()

class BlockNumberHandler(BaseHandler):
    def block(self, block):
        data = self.get_data(block)
        self.render("templates/explorer.html",
                    data=data)

    def get_data(self, block):
        data = requests.get(f"{nado_node}/get_block_number?number={block}").text
        return json.loads(data)

    def get(self, parameters):
        entry = BlockNumberHandler.get_argument(self, "entry")
        self.block(block=entry)

class BlockHashHandler(BaseHandler):
    def block(self, hash):
        data = self.get_data(hash)
        self.render("templates/explorer.html",
                    data=data)

    def get_data(self, hash):
        data = requests.get(f"{nado_node}/get_block?hash={hash}").text
        return json.loads(data)

    def get(self, parameters):
        entry = BlockHashHandler.get_argument(self, "entry")
        self.block(hash=entry)

class AccountHandler(BaseHandler):
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


class TransactionHandler(BaseHandler):
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


class SupplyHandler(BaseHandler):
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
            (r"/get_block(.*)", BlockHashHandler),
            (r"/get_supply", SupplyHandler),
            (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": "static"}),
            (r'/(favicon.ico)', tornado.web.StaticFileHandler, {"path": "graphics"}),

        ]
    )
    application.listen(port)
    await asyncio.Event().wait()


asyncio.run(make_app(9890))
