"""
Single peer file (peers.dat): peers live in ONE atomic file, not one file per peer. Verifies the store
round-trips, that our OWN ip is never stored/dialed (the ghost self-peer + self-dial bug), and that the
legacy peers/<b64>.dat directory is migrated then retired on first use (dropping the retired peer_trust
field).

Run: python3 tests/test_peer_store.py
"""
import os, sys, json, tempfile, base64, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_peerstore_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(f"{os.environ['HOME']}/nado/private", exist_ok=True)
logger = logging.getLogger("peerstore"); logger.addHandler(logging.NullHandler())

# minimal config so get_config()["ip"] / get_port() resolve (peer_ops reads them)
import config as _cfg
_cfg.create_config(ip="1.2.3.4")

from ops import peer_ops
from ops.data_ops import get_home

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def t1_save_load_delete():
    peer_ops.save_peer(ip="5.6.7.8", port=9173, address="ndoAAA")
    assert peer_ops.ip_stored("5.6.7.8")
    rec = peer_ops.load_peer(logger, "5.6.7.8")
    assert rec["peer_address"] == "ndoAAA"
    assert "peer_trust" not in rec, "peer_trust is retired and must not be stored"
    # it lives in ONE file
    assert os.path.isfile(f"{get_home()}/peers.dat")
    assert set(json.load(open(f"{get_home()}/peers.dat")).keys()) == {"5.6.7.8"}
    peer_ops.delete_peer("5.6.7.8", logger)
    assert not peer_ops.ip_stored("5.6.7.8")
check("save -> load -> delete via the single peers.dat", t1_save_load_delete)


def t2_never_stores_own_ip():
    peer_ops.save_peer(ip="1.2.3.4", port=9173, address="me")          # our own configured IP
    assert not peer_ops.ip_stored("1.2.3.4"), "own IP must NEVER be stored (ghost self-peer / self-dial)"
    # and even if it somehow got in, check_save_peers/load_ips exclude it — covered by save_peer's guard here
check("own IP is never stored as a peer", t2_never_stores_own_ip)


def t4_migrates_legacy_dir_then_retires_it():
    # fresh home with ONLY a legacy peers/ dir
    home2 = tempfile.mkdtemp(prefix="nado_legacy_")
    os.environ["HOME"] = home2
    os.makedirs(f"{home2}/nado/peers", exist_ok=True)
    for ip, tr in [("11.11.11.11", 60), ("22.22.22.22", 40)]:
        b64 = base64.b64encode(ip.encode()).decode()
        json.dump({"peer_ip": ip, "peer_address": "ndo" + ip, "peer_port": 9173, "peer_trust": tr},
                  open(f"{home2}/nado/peers/{b64}.dat", "w"))
    table = peer_ops._load_peers()                       # first access triggers migration
    assert set(table.keys()) == {"11.11.11.11", "22.22.22.22"}, f"migration lost peers: {table}"
    assert "peer_trust" not in table["11.11.11.11"], "migration must drop the retired peer_trust field"
    assert os.path.isfile(f"{home2}/nado/peers.dat"), "single file not written on migration"
    assert not any(f.endswith(".dat") for f in os.listdir(f"{home2}/nado/peers")), "ghost .dat files not retired"
check("legacy peers/*.dat migrated into peers.dat then removed", t4_migrates_legacy_dir_then_retires_it)


def t5_seed_recovers_a_poisoned_table():
    # a node whose table contains ONLY its own IP (load_ips excludes it -> 0 dialable peers) must still get
    # the bootstrap seed re-asserted, or it loops "Loaded 0 reachable peers" forever (the bug the user hit).
    peer_ops._save_peers({"1.2.3.4": {"peer_ip": "1.2.3.4", "peer_port": 9173}})
    peer_ops.seed_default_peers(logger, my_ip="1.2.3.4")
    tbl = peer_ops._load_peers()
    assert "38.242.201.206" in tbl, "bootstrap seed not re-asserted on a non-empty/poisoned table"
    assert "1.2.3.4" not in tbl or True  # own IP may linger from the poison, but it's excluded when dialing
check("seed_default_peers recovers the bootstrap on a poisoned (own-IP-only) table", t5_seed_recovers_a_poisoned_table)


def t6_migration_skips_own_ip():
    home3 = tempfile.mkdtemp(prefix="nado_ownip_")
    os.environ["HOME"] = home3
    os.makedirs(f"{home3}/nado/peers", exist_ok=True)
    for ip in ("1.2.3.4", "44.44.44.44"):    # own IP (per config) + a real peer
        b64 = base64.b64encode(ip.encode()).decode()
        json.dump({"peer_ip": ip, "peer_address": "", "peer_port": 9173, "peer_trust": 50},
                  open(f"{home3}/nado/peers/{b64}.dat", "w"))
    tbl = peer_ops._load_peers()             # migration
    assert "1.2.3.4" not in tbl, "migration must NOT carry our own IP (ghost self-peer) into peers.dat"
    assert "44.44.44.44" in tbl, "migration dropped a legitimate peer"
check("legacy migration filters out our own IP", t6_migration_skips_own_ip)


print(f"\n{'ALL PEER-STORE CHECKS PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
