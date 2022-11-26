import json
import os
import time

import requests

from hashing import create_nonce


def config_found(file="private/config.dat"):
    if os.path.isfile(file):
        return True
    else:
        return False


def get_timestamp():
    return float(time.time())


def get_timestamp_seconds():
    return int(time.time_ns() / 1000000000)


def get_protcol():
    return 1


def get_port():
    return 9173


def get_public_ip():
    ip = requests.get("https://api.ipify.org", timeout=5).text
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
