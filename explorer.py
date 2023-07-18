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


async def make_app(port):
    application = tornado.web.Application(
        [
            (r"/", HomeHandler),
            (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": "static"}),
            (r'/(favicon.ico)', tornado.web.StaticFileHandler, {"path": "graphics"}),

        ]
    )
    application.listen(port)
    await asyncio.Event().wait()


asyncio.run(make_app(9890))
