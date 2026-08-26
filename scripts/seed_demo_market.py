#!/usr/bin/env python3
"""Seed a live demo AMM market so the DEX has real price/depth/stats to show (operator-funded, small).
Deposits a little NADO L1->exec, mints a test token, opens+seeds a NADO/token pool, then trades it a few
times to move the price. Run: HOME=/srv/nado-home python3 scripts/seed_demo_market.py"""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.key_ops import load_keys
from ops.transaction_ops import construct_blob_tx, construct_bridge_deposit_tx
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY
from execnode.state import ExecState, asset_id

L1, EX = "http://127.0.0.1:9173", "http://127.0.0.1:9273"
CID = "7e97163299583191d40d8676f43d5cfe"
UNIT = 10 ** 8
kd = load_keys(); OP = kd["address"]
def get(u):
    with urllib.request.urlopen(u, timeout=10) as r: return json.loads(r.read().decode())
def post(u, b):
    rq = urllib.request.Request(u, data=json.dumps(b).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(rq, timeout=20) as r: return json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return {"result": False, "message": e.read().decode()[:200]}
def tip(): return int(get(L1 + "/get_latest_block")["block_number"])
def bridge(a): return int(get(EX + "/exec/bridge?ns=default&provisional=1").get("balances", {}).get(a, 0))
def submit(payload, label, value_tx=None):
    t = tip()
    tx = value_tx or construct_blob_tx(kd, payload, max_block=t + 40, fee=MIN_TX_FEE, min_block=t + TX_INCLUSION_DELAY)
    r = post(L1 + "/submit_transaction", tx)
    print(f"  {label}: {'ok ' + tx['txid'][:12] if r.get('result') else r.get('message')}", flush=True)
    return r.get("result")
def wait(fn, label, secs=120):
    d = time.time() + secs
    while time.time() < d:
        try:
            if fn(): return True
        except Exception: pass
        time.sleep(3)
    print(f"  TIMEOUT: {label}", flush=True); return False
def sto(): return get(EX + f"/exec/contract?ns=default&cid={CID}&provisional=1").get("storage", {})
def pool(pid): 
    s = sto(); g = lambda m: (s.get(m) or {}).get(str(pid))
    return {"ast": g("ast"), "rn": int(g("rn") or 0), "rt": int(g("rt") or 0), "sup": int(g("sup") or 0)}

print(f"operator {OP}", flush=True)
NEED_EXEC = 60 * UNIT           # 0.6 NADO of exec liquidity headroom
if bridge(OP) < NEED_EXEC:
    dep = NEED_EXEC - bridge(OP) + 5 * UNIT
    print(f"depositing {dep/1e10} NADO L1->exec…", flush=True)
    submit(None, "deposit", construct_bridge_deposit_tx(kd, dep, tip() + 40, MIN_TX_FEE))
    wait(lambda: bridge(OP) >= NEED_EXEC, "exec deposit", 180)
print(f"exec balance: {bridge(OP)/1e10} NADO", flush=True)

aid = int(asset_id(OP, 7))
print(f"minting token (asset {aid})…", flush=True)
submit({"op": "asset_create", "seed": 7, "name": "Demo Token", "sym": "DEMO", "dec": 0, "supply": 10 ** 15, "mintable": False}, "asset_create")
wait(lambda: int(get(EX + f"/exec/asset?ns=default&aid={aid}").get("supply", 0) or 0) > 0 if False else True, "asset", 30)
time.sleep(8)

PID, POS = 7, 77
N0, T0 = 40, 4000               # 0.4 NADO paired with 4000 token units -> opening price 100 TKN/NADO
print("opening + seeding the pool…", flush=True)
submit({"op": "call", "contract": CID, "method": "open", "args": [PID, aid]}, "open")
wait(lambda: pool(PID)["ast"], "pool open", 90)
submit({"op": "call", "contract": CID, "method": "fundn", "args": [POS, PID, N0], "value": N0 * UNIT}, "fundn")
wait(lambda: True, "fundn", 20); time.sleep(10)
submit({"op": "call", "contract": CID, "method": "fundt", "args": [POS, PID, T0], "value": T0 * UNIT, "asset": str(aid)}, "fundt")
wait(lambda: True, "fundt", 20); time.sleep(10)
submit({"op": "call", "contract": CID, "method": "join", "args": [POS, PID]}, "join")
wait(lambda: pool(PID)["sup"] > 0, "join (liquidity live)", 90)
p = pool(PID); print(f"  pool live: rn={p['rn']} rt={p['rt']} price={p['rt']/max(p['rn'],1):.2f} TKN/NADO", flush=True)

print("trading to move the price…", flush=True)
trades = [("swapn", 3), ("swapt", 200), ("swapn", 5), ("swapt", 120), ("swapn", 2)]
for i, (m, amt) in enumerate(trades):
    args = [PID, amt, 0, aid] if m == "swapn" else [PID, amt, 0]
    payload = {"op": "call", "contract": CID, "method": m, "args": args, "value": amt * UNIT}
    if m == "swapt": payload["asset"] = str(aid)
    submit(payload, f"trade {i+1}: {m} {amt}")
    time.sleep(14)
    p = pool(PID); print(f"    -> price {p['rt']/max(p['rn'],1):.2f} TKN/NADO", flush=True)
print(f"\nDONE. Pool #{PID} (DEMO/NADO) is live. exec left: {bridge(OP)/1e10} NADO", flush=True)
