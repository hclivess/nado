import json
import os
import socket
import time

from ops.data_ops import get_home
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


def test_self_port(ip, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        result = sock.connect_ex((ip, port))
        if not result:
            return True
        else:
            return False


def get_config(config_path: str = f"{get_home()}/private/config.dat"):
    with open(config_path) as infile:
        return json.loads(infile.read())


def update_config(new_config: dict, config_path: str = f"{get_home()}/private/config.dat"):
    config = get_config()
    for key, value in new_config.items():
        config[key] = value

    with open(config_path, "w") as outfile:
        json.dump(config, outfile)


def create_config(ip: str, config_path: str = f"{get_home()}/private/config.dat"):
    config_contents = {
        "port": get_port(),
        "ip": ip,
        "protocol": get_protcol(),
        "server_key": create_nonce(length=64),
        "min_peers": 2,
        "max_rollbacks": 10,
        "cascade_limit": 1,
        "promiscuous": False,
        "quick_sync": False
    }

    if not os.path.exists(config_path):
        with open(config_path, "w") as outfile:
            json.dump(config_contents, outfile)


if __name__ == "__main__":
    pass
