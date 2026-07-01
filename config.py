import json
import os
import socket
import time

from hashing import create_nonce
from ops.data_ops import get_home


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
        sock.settimeout(3)
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
        "finality_depth": 30,
        "cascade_limit": 1,
        "promiscuous": False,
        # AUTO-BOND (non-consensus): % of newly-mined earnings to auto-compound into bonded stake,
        # unattended. Defaults to protocol.AUTO_BOND_DEFAULT_PERCENT (80) so a fresh node joins the
        # bonded lane hands-free; set 0 to disable. Overridable via the NADO_AUTO_BOND_PERCENT env var.
        "auto_bond_percent": 80,
        # ROLLING MODE (non-consensus, doc/rolling-mode-and-da.md): archive=True keeps ALL block bodies
        # forever (default — no data loss, current behaviour). Set False for a "rolling"/pruned node that
        # drops block BODIES older than history_retention_blocks (state + number<->hash indexes are always
        # kept, so it still validates + serves the beacon/FFG). Overridable via NADO_ARCHIVE / env.
        "archive": True,
        "history_retention_blocks": 0,  # 0 = use protocol.HISTORY_RETENTION_BLOCKS default
        # IP-DIVERSITY registration cap (non-consensus relay admission control): the max DISTINCT
        # OPEN-lane addresses one source IP may register through THIS node per hour. Stops the naive
        # "bot onboards 10k addresses from one device" Sybil at the entry point. Generous by default so
        # legit CGNAT/NAT sharing isn't bricked; 0 disables. Overridable via NADO_MAX_REG_PER_IP.
        "max_registrations_per_ip": 64
    }

    if not os.path.exists(config_path):
        with open(config_path, "w") as outfile:
            json.dump(config_contents, outfile)


if __name__ == "__main__":
    pass
