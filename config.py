import asyncio
import json
import os
import time

from tornado.httpclient import AsyncHTTPClient

from data_ops import get_home
from hashing import create_nonce


def config_found(file=f"{get_home()}/private/config.dat"):
    if os.path.isfile(file):
        return True
    else:
        return False


def get_timestamp():
    return float(time.time())


def get_timestamp_seconds():
    return int(time.time_ns() / 1000000000)


def get_protcol():
    return 2


def get_port():
    return 9173


async def get_public_ip():
    http_client = AsyncHTTPClient()
    url = "https://api.ipify.org"
    ip = await http_client.fetch(url)
    return ip.body.decode()


def get_config(config_path: str = f"{get_home()}/private/config.dat"):
    with open(config_path) as infile:
        return json.loads(infile.read())


def update_config(new_config: dict, config_path: str = f"{get_home()}/private/config.dat"):
    config = get_config()
    for key, value in new_config.items():
        config[key] = value

    with open(config_path, "w") as outfile:
        json.dump(config, outfile)


def create_config(config_path: str = f"{get_home()}/private/config.dat"):
    config_contents = {
        "port": get_port(),
        "ip": asyncio.run(get_public_ip()),
        "protocol": get_protcol(),
        "server_key": create_nonce(length=64),
    }

    if not os.path.exists(config_path):
        with open(config_path, "w") as outfile:
            json.dump(config_contents, outfile)


if __name__ == "__main__":
    create_config()
