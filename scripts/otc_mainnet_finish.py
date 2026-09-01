#!/usr/bin/env python3
"""Finish a mainnet swap from its persisted record: read the secret back from Ethereum the way the
watchtower does, claim the NADO on L1 as the taker, settle the order. Run: HOME=/srv/nado-home python3 scripts/otc_mainnet_finish.py <oid>"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
# explicit, not `import *`: a star import hides every unbound name from pyflakes and the
# tests/test_no_undefined_names.py gate (which is how a typo here would reach a mainnet swap unnoticed)
from otc_mainnet_eth_e2e import (ROOT, W, ETH_RPC, L1, OTC, O, order, ok, get, wait, l1_bal,
                                 submit_l1, submit_blob, passed, failed)
oid = int(sys.argv[1]); rec = json.load(open(os.path.join(ROOT, "private", f"otc_mainnet_swap_{oid}.json")))
taker = json.load(open(os.path.join(ROOT, "private", "otc_e2e_taker.json")))
found = None
try:
    got = W.eth_claim_secrets(ETH_RPC, rec["htlc"], [(oid, rec["hashlock"])], {}, "eth"); found = got.get(oid)
except Exception as e:
    print(f"  (log scan failed: {str(e)[:80]})", flush=True)
ok(found == rec["secret"], "7. the secret read back from the mainnet Claimed log equals the one on disk")
if not found:
    found = rec["secret"]; print("     continuing with the secret from disk", flush=True)
h = get(L1 + f"/get_htlc?id={rec['l1_lock']}")["htlc"]
if h["status"] == "open":
    tbal0 = l1_bal(taker["address"])
    submit_l1(taker, "htlc_claim", 0, {"htlc_id": rec["l1_lock"], "preimage": found}, "htlc_claim", fee=0)
    ok(wait(lambda: get(L1 + f"/get_htlc?id={rec['l1_lock']}")["htlc"]["status"] == "claimed", "NADO claimed"), f"   taker claimed the {rec['nado_amt']/1e10} NADO on L1 with it")
else:
    ok(h["status"] == "claimed", f"   NADO lock already {h['status']}")
if int(order(oid)["st"] or 0) == 2:
    submit_blob(taker, {"op": "call", "contract": OTC, "method": "settle", "args": [oid] + O.preimage_limbs(found)}, "settle")
    ok(wait(lambda: int(order(oid)["st"] or 0) == 3, "settled"), "   order settled on the book")
else:
    ok(int(order(oid)["st"] or 0) == 3, "   order already settled")
print(f"\n[mainnet finish] {passed} passed, {failed} failed", flush=True)
