"""A peer's /status is admitted only with the SHAPES honest peers send (review 2026-09-25).

This node re-serves every admitted status on /status_pool, and the wallet's Stats tab renders several fields. The
check used to be types only, so one hostile peer could put markup in history_retention (not checked at all) or in a
hash field and have it run in every wallet that opened Stats. Honest peers send hex hashes, rolling/archive,
integer retention, plain version/chain-id tokens and a bare http(s) relay URL — anything else is refused.

Run: python3 tests/test_status_field_shapes.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-status-shapes-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.peer_ops import status_fields_well_typed as ok

HONEST = {"latest_block_hash": "ab" * 32, "earliest_block_hash": "cd" * 32, "latest_block_height": 231000,
          "snapshot_hash": "ef" * 32, "snapshot_height": 230000, "node_type": "rolling", "history_retention": 100800,
          "version": "v1.0.0-beta.4-672-g1234abc", "chain_id": "betanet-7", "relay_url": "https://psychz.nadochain.com",
          "address": "ab" * 23}
fails = []
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails.append(name)

check("an honest status is admitted", ok(HONEST))
check("absent fields are fine (a mid-restart peer)", ok({"latest_block_height": 5}))
check("archive nodes and a relay with a port are admitted",
      ok(dict(HONEST, node_type="archive", relay_url="https://relay.example.org:8443/")))
PAYLOAD = "<iframe srcdoc='<script src=https://cdn.jsdelivr.net/gh/x/y@1/x.js></script>'></iframe>"
for field in ("history_retention", "latest_block_hash", "snapshot_hash", "node_type", "version", "chain_id",
              "relay_url", "address", "earliest_block_hash", "upcoming_block_hash", "transaction_pool_hash"):
    check(f"markup in {field} is refused", not ok(dict(HONEST, **{field: PAYLOAD})))
check("a non-hex hash is refused", not ok(dict(HONEST, latest_block_hash='"><img src=x>')))
check("a string retention is refused", not ok(dict(HONEST, history_retention="100800")))
check("a javascript: relay url is refused", not ok(dict(HONEST, relay_url="javascript:alert(1)")))
check("a relay url with a path is refused", not ok(dict(HONEST, relay_url="https://x.org/evil?<b>")))
print("ALL PASS" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
