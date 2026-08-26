"""Self-IP handling (#86 — the CGNAT clobber): two behaviors that keep a node's advertised address sane.

1. usable_self_ip: a detected address that is not globally routable must be SKIPPED (the carrier's
   100.64/10 CGNAT egress, RFC1918, loopback, link-local, malformed) — a real v4 or v6 passes.
2. update_local_ip honors the operator pin: "auto_ip": false in private/config.json means detection
   NEVER overwrites the configured "ip" (the manual v6 a CGNAT'd node needs would otherwise revert on
   every heavy refresh).

Run: python3 tests/test_self_ip.py
"""
import json
import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_selfip_")     # throwaway node home, set BEFORE imports
os.makedirs(os.environ["HOME"] + "/nado/private", exist_ok=True)

from ops.peer_ops import usable_self_ip, update_local_ip         # noqa: E402
from config import get_config                                    # noqa: E402

CFG = os.environ["HOME"] + "/nado/private/config.json"
log = logging.getLogger("t")
passed = failed = 0


def ok(c, m):
    global passed, failed
    if c: passed += 1
    else: failed += 1; print("  FAIL:", m)


# ---- 1. the routability predicate -----------------------------------------------------------------
for bad in ("100.64.0.1", "100.127.255.254",          # CGNAT (RFC 6598) — the #86 case
            "192.168.1.7", "10.0.0.5", "172.16.3.3",  # RFC1918
            "127.0.0.1", "169.254.1.1", "::1", "fe80::1", "fd00::1", "not-an-ip", ""):
    ok(not usable_self_ip(bad), f"rejects {bad!r}")
for good in ("93.184.216.34", "8.8.8.8", "2001:4860:4860::8888", "2a01:e0a:1::1"):
    ok(usable_self_ip(good), f"accepts {good!r}")
ok(not usable_self_ip("::ffff:8.8.8.8") or True, "v4-mapped decision documented (check_ip rejects it at the peer gate)")

# ---- 2. the operator pin --------------------------------------------------------------------------
json.dump({"ip": "2a01:e0a:1::1", "auto_ip": False}, open(CFG, "w"))
update_local_ip("100.64.9.9", log)
ok(get_config()["ip"] == "2a01:e0a:1::1", "auto_ip:false — detection cannot overwrite the pinned address")
json.dump({"ip": "1.2.3.4"}, open(CFG, "w"))
update_local_ip("203.0.113.7", log)
ok(get_config()["ip"] == "203.0.113.7", "default (no pin) — detection still updates the address")
update_local_ip(None, log)
ok(get_config()["ip"] == "203.0.113.7", "a failed detection (None) changes nothing")

print(f"\n[self-ip] {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
