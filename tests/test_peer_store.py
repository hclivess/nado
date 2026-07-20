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

OWN_IP = "1.2.3.4"

def fresh_home(prefix):
    """A brand-new node home, WITH a config. Every scenario that needs a clean peer table swaps HOME, and
    each one must bring a config with it: get_config() raises on a missing file by deliberate design ("a
    node without a config must not limp along on invented defaults"), so a home without one does not
    exercise the peer store — it just makes every peer call blow up, and the surrounding assertion then
    grades an exception instead of the behaviour it names. Two scenarios here used to do exactly that, and
    leaked the broken HOME into the one between them as well."""
    home = tempfile.mkdtemp(prefix=prefix)
    os.environ["HOME"] = home
    os.makedirs(f"{home}/nado/private", exist_ok=True)
    _cfg.create_config(ip=OWN_IP)
    return home

from ops import peer_ops
from ops.data_ops import get_home

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def t1_save_load_delete():
    """Prove a peer round-trips through the single peers.dat (no peer_trust) and deletes cleanly."""
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
    """Prove save_peer refuses our own configured IP (the ghost self-peer / self-dial bug)."""
    peer_ops.save_peer(ip="1.2.3.4", port=9173, address="me")          # our own configured IP
    assert not peer_ops.ip_stored("1.2.3.4"), "own IP must NEVER be stored (ghost self-peer / self-dial)"
    # and even if it somehow got in, check_save_peers/load_ips exclude it — covered by save_peer's guard here
check("own IP is never stored as a peer", t2_never_stores_own_ip)


def t4_migrates_legacy_dir_then_retires_it():
    """Prove legacy peers/<b64>.dat files migrate into peers.dat (dropping peer_trust) and are removed."""
    # fresh home with ONLY a legacy peers/ dir
    home2 = fresh_home("nado_legacy_")
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
    """Prove seed_default_peers re-asserts the bootstrap seed on a poisoned own-IP-only table."""
    # a node whose table contains ONLY its own IP (load_ips excludes it -> 0 dialable peers) must still get
    # the bootstrap seed re-asserted, or it loops "Loaded 0 reachable peers" forever (the bug the user hit).
    seed = peer_ops.DEFAULT_SEED_PEERS[0]        # DERIVED, not pinned: a changed seed must not silently
                                                 # turn this into an assertion about a retired IP
    peer_ops._save_peers({OWN_IP: {"peer_ip": OWN_IP, "peer_port": 9173}})
    peer_ops.seed_default_peers(logger, my_ip=OWN_IP)
    tbl = peer_ops._load_peers()
    assert seed in tbl, "bootstrap seed not re-asserted on a non-empty/poisoned table"
check("seed_default_peers recovers the bootstrap on a poisoned (own-IP-only) table", t5_seed_recovers_a_poisoned_table)


def t6_migration_skips_own_ip():
    """Prove the legacy migration filters out our own IP but keeps legitimate peers."""
    home3 = fresh_home("nado_ownip_")
    os.makedirs(f"{home3}/nado/peers", exist_ok=True)
    for ip in (OWN_IP, "44.44.44.44"):       # own IP (per config) + a real peer
        b64 = base64.b64encode(ip.encode()).decode()
        json.dump({"peer_ip": ip, "peer_address": "", "peer_port": 9173, "peer_trust": 50},
                  open(f"{home3}/nado/peers/{b64}.dat", "w"))
    tbl = peer_ops._load_peers()             # migration
    assert OWN_IP not in tbl, "migration must NOT carry our own IP (ghost self-peer) into peers.dat"
    assert "44.44.44.44" in tbl, "migration dropped a legitimate peer"
check("legacy migration filters out our own IP", t6_migration_skips_own_ip)


print(f"\n{'ALL PEER-STORE CHECKS PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
