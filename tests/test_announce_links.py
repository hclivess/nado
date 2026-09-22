"""AN ANNOUNCED PEER MUST BE LINKED (ops/peer_ops.check_save_peers <- loops/peer_loop.sniff_buffered_peers).

2026-09-16: /announce_peer persists a validated peer and then buffers it; check_save_peers skipped every
table-known address before any I/O AND left it out of `success`, so the sniff never added it to the dial set.
The loopback split scenario's heal is announce-driven and stopped converging with that filter (2026-09-01).
Pins: a known address is returned as success with NO probe; an unknown one is probed, persisted and returned;
fails/unreachable/own addresses are still excluded.  Run: python3 tests/test_announce_links.py
"""
import os, sys, tempfile, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_announce_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)   # leave no /tmp home behind (9,600 leaked by 2026-09-22)
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(f"{os.environ['HOME']}/nado/private", exist_ok=True)
import json
json.dump({"port": 19173, "ip": "127.0.0.2", "protocol": 2}, open(f"{os.environ['HOME']}/nado/private/config.json", "w"))
from ops import peer_ops as PO

fails = []
def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond: fails.append(label)

log = logging.getLogger("t"); log.addHandler(logging.NullHandler())
probed = []
async def fake_pool(ips, port, fail_storage, logger, semaphore):
    probed.extend(sorted(ips))
    return {ip: {"address": "addr-" + ip} for ip in ips}
PO.compound_get_status_pool = fake_pool

PO.save_peer("127.0.0.3", 19173, "addr3")                       # what /announce_peer does first
r = PO.check_save_peers(["127.0.0.3"], log, fails=[], unreachable={})
check("127.0.0.3" in r["success"], "a table-known buffered peer is returned as success (the announce path links again)")
check(probed == [], "...and it cost no probe (it was validated when it was saved)")
r = PO.check_save_peers(["127.0.0.4", "127.0.0.3"], log, fails=[], unreachable={})
check(sorted(r["success"]) == ["127.0.0.3", "127.0.0.4"] and probed == ["127.0.0.4"], f"an unknown address is probed and joins the known one in success ({probed})")
check("127.0.0.4" in PO._load_peers(), "...and the probed address is persisted")
r = PO.check_save_peers(["127.0.0.3", "127.0.0.5"], log, fails=["127.0.0.5"], unreachable={"127.0.0.3": 1})
check(r["success"] == [], "a benched or failed address is still excluded, known or not")
r = PO.check_save_peers(["127.0.0.2"], log, fails=[], unreachable={})
check(r["success"] == [], "our own address never links")
print(("\nFAILED: " + "; ".join(fails)) if fails else "\nall checks passed")
sys.exit(1 if fails else 0)
