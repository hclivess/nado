#!/usr/bin/env python3
# _faucet_enroll_hexholm.py — enroll Hexholm (idx 8) in the faucet's airdrop-play registry, mirroring the
# live parameters of the other enrolled games (grant 0.5 NADO, cap 20/day, same PoW target). Operator-only
# (the faucet contract requires the game-fleet deployer key). Idempotent: re-running rewrites the same slot.
import sys, json, time, urllib.request
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from ops.transaction_ops import construct_blob_tx
from protocol import MIN_TX_FEE

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
IDX = 8
CID = "13b92dc630e513f11a68df9f405d7b2d"                    # hexholm (static/hexholm.js)
DIG = int(CID[:16], 16)                                     # the registry's low-64 cid digest convention
GRANT, CAP, POW = 5_000_000_000, 20, 70_368_744             # match the live idx 0-7 parameters

def j(u): return json.load(urllib.request.urlopen(u, timeout=10))
def tip(): return j(L1 + "/get_latest_block")["block_number"]

kd = load_keys()
blob = {"op": "call", "contract": "faucet", "method": "set_game", "args": [IDX, DIG, GRANT, CAP, POW]}
tx = construct_blob_tx(kd, blob, tip() + 25, MIN_TX_FEE)
req = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(),
                             headers={"Content-Type": "application/json"})
print("submit:", json.load(urllib.request.urlopen(req, timeout=12)))
for _ in range(40):
    time.sleep(5)
    sto = j(EX + "/exec/contract?ns=default&cid=faucet&provisional=1").get("storage", {})
    if int(sto.get("gdig", {}).get(str(IDX), 0)) == DIG:
        print(f"ENROLLED: idx {IDX} dig {DIG} grant {GRANT} cap {CAP}/day")
        sys.exit(0)
print("TIMEOUT waiting for the enrollment to land")
sys.exit(1)
