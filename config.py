import json
import os
import time

import requests

from hashing import create_nonce


def get_timestamp():
    return float(time.time())


def get_timestamp_seconds():
    return int(time.time_ns() / 1000000000)


def get_protcol():
    return 1


def get_port():
    return 9173


def get_public_ip():
    ip = requests.get("https://api.ipify.org", timeout=3).text
    return ip


def get_config(config_path: str = "private/config.dat"):
    with open(config_path) as infile:
        return json.loads(infile.read())


def create_config(config_path: str = "private/config.dat"):
    config_contents = {
        "port": get_port(),
        "ip": get_public_ip(),
        "protocol": get_protcol(),
        "server_key": create_nonce(length=64),
    }

    if not os.path.exists(config_path):
        with open(config_path, "w") as outfile:
            json.dump(config_contents, outfile)


if __name__ == "__main__":
    create_config()
