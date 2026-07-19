# _fund_faucet.py — top up the leaderboard prize bank: bridge-deposit from L1 into the operator's exec
# balance, then call faucet.fund() escrowing that VALUE into the fixed-name `faucet` contract.
# Usage: HOME=/root python3 _fund_faucet.py [NADO]   (default 50)
import json, sys, time, urllib.request
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from ops.address_ops import make_address
from ops.transaction_ops import construct_blob_tx, construct_bridge_deposit_tx
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
NADO = 10 ** 10
AMT = int(float(sys.argv[1]) * NADO) if len(sys.argv) > 1 else 50 * NADO

def j(u):
    with urllib.request.urlopen(u, timeout=15) as r: return json.loads(r.read().decode())
def post(tx):
    req = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r: return json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return {"result": False, "message": e.read().decode()[:160]}
def tip(): return int(j(L1 + "/get_latest_block")["block_number"])
def exbal(a):
    try: return int(j(EX + "/exec/bridge?ns=default").get("balances", {}).get(a, 0))
    except Exception: return 0
def faucetbal():
    try: return int(j(EX + "/exec/bridge?ns=default").get("balances", {}).get("faucet", 0))
    except Exception: return 0
def wait(cond, label, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond(): print("  [ok]", label, flush=True); return True
        except Exception: pass
        time.sleep(8)
    print("  [TIMEOUT]", label, flush=True); sys.exit(1)

K = load_keys(); K["address"] = make_address(K["public_key"]); ME = K["address"]
print(f"funding faucet with {AMT/NADO:.2f} NADO as {ME}", flush=True)

# 1) bridge-deposit L1 -> exec (only what's missing)
have = exbal(ME)
if have < AMT:
    need = AMT - have
    for attempt in range(6):
        r = post(construct_bridge_deposit_tx(K, need, tip() + 12, MIN_TX_FEE))
        if r.get("result"): break
        print("  deposit retry:", r.get("message"), flush=True); time.sleep(12)
    else:
        print("  [GIVEUP] bridge deposit"); sys.exit(1)
    wait(lambda: exbal(ME) >= AMT, f"bridge deposit landed ({AMT/NADO:.2f} NADO in exec)")
else:
    print("  exec balance already sufficient", flush=True)

# 2) faucet.fund() with the VALUE escrowed into the prize bank
before = faucetbal()
for attempt in range(6):
    r = post(construct_blob_tx(K, {"op": "call", "contract": "faucet", "method": "fund", "args": [], "value": AMT},
                               tip() + 12, MIN_TX_FEE, min_block=tip() + TX_INCLUSION_DELAY))
    if r.get("result"): break
    print("  fund retry:", r.get("message"), flush=True); time.sleep(12)
else:
    print("  [GIVEUP] faucet.fund"); sys.exit(1)
wait(lambda: faucetbal() >= before + AMT, f"faucet prize bank funded (+{AMT/NADO:.2f} NADO)")
print(f"DONE — faucet bank = {faucetbal()/NADO:.4f} NADO", flush=True)
