# _launch_e2e.py — LIVE end-to-end exercise of the DEX launchpad (execnode/games/dex.py, doc/launchpad.md) with real
# transactions on the running node: two wallets deposit; A issues a small fixed-supply coin, pays the launch fee and
# launches it at the smallest scale (VN_MIN: it graduates after a raise of ~4 NADO); both buy in the opening window and
# claim (one price); B sells in a later batch; buys carry the curve to graduation; B swaps on the graduated, share-less
# pool; the contract's holdings cover everything it owes; B's leftover L1 NADO goes back to A.
# Run: nado_venv/bin/python scripts/live/_launch_e2e.py   (runs against the LIVE node and spends real NADO from the
# operator key: ~10 NADO sealed launch fee + a few NADO of trades + fees; doc/launchpad.md L4)
import json, urllib.request, time, sys
import os
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from execnode.games.redeploy import target_cids
from execnode.games import dex as D
from execnode.state import asset_id
from ops.key_ops import load_keys
from signatures import generate_keydict, sign, unhex
from ops.transaction_ops import construct_blob_tx, construct_bridge_deposit_tx, create_txid
from hashing import create_nonce
from config import get_timestamp_seconds
from protocol import MIN_TX_FEE, CHAIN_ID

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
CID = target_cids()["dex"]            # derived, never pasted
NADO = 10 ** 10; U = D.UNIT


def j(u): return json.load(urllib.request.urlopen(u, timeout=10))  # nosec B310 # operator CLI: the operator's own node URL, never peer input
def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(), headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(r, timeout=12))  # nosec B310 # operator CLI: the operator's own node URL, never peer input
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"  [reject {e.code}] {body}", flush=True)
        return {"result": False, "message": body}
def tip(): return j(L1 + "/get_latest_block")["block_number"]
def cursor(): return int(j(EX + "/exec/root?ns=default&provisional=1").get("cursor", 0))
def exbal(a):
    try: return int(j(EX + "/exec/bridge?ns=default").get("balances", {}).get(a, 0))
    except Exception as e: raise SystemExit(f"exec balance read failed ({e}) — refusing to move funds blind")
def contract(): return j(EX + f"/exec/contract?ns=default&cid={CID}")
def M(m, k):
    try: return int((contract().get("storage") or {}).get(m, {}).get(str(k), 0))
    except Exception: return 0
def abal(aid, who):
    try:
        for a in j(EX + f"/exec/assets?ns=default&holder={who}").get("assets", []):
            if str(a.get("id")) == str(aid): return int(a.get("balance", 0))
    except Exception: pass
    return 0
def send(kd, recipient, amount):
    for _ in range(8):
        if recipient == "bridge":
            r = post(construct_bridge_deposit_tx(kd, amount, tip() + 8, MIN_TX_FEE))
        else:
            t = {"sender": kd["address"], "recipient": recipient, "amount": int(amount), "timestamp": get_timestamp_seconds(),
                 "data": "", "nonce": create_nonce(), "public_key": kd["public_key"], "max_block": tip() + 8, "chain_id": CHAIN_ID, "fee": MIN_TX_FEE}
            t["txid"] = create_txid(t); t["signature"] = sign(private_key=kd["private_key"], message=unhex(t["txid"]))
            r = post(t)
        if r.get("result"): return r
        time.sleep(12)
    print(f"  [GIVEUP] send {recipient} {amount}", flush=True); sys.exit(1)
def blob(kd, p):
    for _ in range(8):
        r = post(construct_blob_tx(kd, p, tip() + 8, MIN_TX_FEE))
        if r.get("result"): return r
        time.sleep(12)
    print(f"  [GIVEUP] {p.get('op')} {p.get('method', '')}", flush=True); sys.exit(1)
def call(kd, method, args, value=0, asset=None):
    p = {"op": "call", "contract": CID, "method": method, "args": args}
    if value: p["value"] = int(value)
    if asset: p["asset"] = str(asset)
    return blob(kd, p)
def wait(cond, label, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond(): print(f"  [ok] {label}", flush=True); return True
        except Exception: pass
        time.sleep(8)
    print(f"  [TIMEOUT] {label}", flush=True); sys.exit(1)

FAILS = []
def ck(n, c, info=""): print(("  PASS " if c else "  FAIL ") + n + (f"  [{info}]" if info and not c else ""), flush=True); (None if c else FAILS.append(n))

A = load_keys("/root/nado/private/keys.dat")
BK = "/root/nado/private/_launch_e2e_b.json"     # persist the second trader so a rerun never strands its deposits
try: B = json.load(open(BK))
except Exception: B = generate_keydict(); json.dump(B, open(BK, "w"))
T = int(time.time()) % 10 ** 9
PID, SEED, SUPPLY = 900_000_000 + T % 90_000_000, T, 10_000
AID = int(asset_id(A["address"], SEED))
print(f"A={A['address'][:16]} B={B['address'][:16]} launch pid {PID}, coin {str(AID)[:16]}…", flush=True)

wait(lambda: "launch" in (contract().get("abi") or {}), "the upgraded dex (with the launchpad) is live on the exec node", 600)

def l1bal(a):
    try: return int(j(L1 + f"/get_account?address={a}").get("balance", 0))
    except Exception: return 0
if exbal(B["address"]) < 15 * NADO and l1bal(B["address"]) < 20 * NADO:
    send(A, B["address"], 25 * NADO)
    wait(lambda: l1bal(B["address"]) >= 20 * NADO, "B funded on L1")
if exbal(A["address"]) < 30 * NADO:
    send(A, "bridge", 40 * NADO)
    wait(lambda: exbal(A["address"]) >= 30 * NADO, "A bridge deposit landed")
if exbal(B["address"]) < 15 * NADO:
    send(B, "bridge", 20 * NADO)
    wait(lambda: exbal(B["address"]) >= 15 * NADO, "B bridge deposit landed")

# ---- create: issue, fee, launch -------------------------------------------------------------------------------
blob(A, {"op": "asset_create", "seed": SEED, "name": "E2E Launch", "sym": "LPE2E", "dec": 8, "supply": SUPPLY * U, "mintable": False})
wait(lambda: abal(AID, A["address"]) == SUPPLY * U, "the coin is issued, fixed supply, all A's")
call(A, "prelaunch", [PID], value=D.CREATE_FEE * U)
wait(lambda: M("creator", PID) != 0, "the launch fee reserved the id")
call(A, "launch", [PID, SUPPLY, D.VN_MIN], value=SUPPLY * U, asset=AID)
wait(lambda: M("kind", PID) == D.CURVE, "the curve is live")
ck("the curve holds the whole supply and the creator's scale", M("ct", PID) == SUPPLY and M("vn", PID) == D.VN_MIN)
L0 = M("lblk", PID)

# ---- the opening window: one price ----------------------------------------------------------------------------
call(A, "buy", [PID, 1, 150], value=150 * U)
call(B, "buy", [PID, 2, 150], value=150 * U)
wait(lambda: M("open", PID) != 0, "the opening batch holds the orders")
wait(lambda: cursor() >= L0 + D.WINDOW + 1, "the opening window has passed", 600)
a0, b0 = abal(AID, A["address"]), abal(AID, B["address"])
call(A, "claim", [1, AID])
call(B, "claim", [2, AID])
wait(lambda: abal(AID, B["address"]) > b0 and abal(AID, A["address"]) > a0, "both opening orders claimed")
ga, gb = abal(AID, A["address"]) - a0, abal(AID, B["address"]) - b0
ck("both opening buyers got exactly the same coins for the same NADO (one price)", ga == gb and ga > 0, (ga, gb))

# ---- a later batch: B sells half --------------------------------------------------------------------------------
half = gb // U // 2
nb0 = exbal(B["address"])
call(B, "sell", [PID, 3, half], value=half * U, asset=AID)
wait(lambda: M("open", PID) != 0, "B's sell is in a batch")
c1 = cursor()
wait(lambda: cursor() > c1 + 1, "its block has passed")
call(B, "claim", [3, AID])
wait(lambda: exbal(B["address"]) > nb0 - 2 * NADO and exbal(B["address"]) != nb0, "B's sell claimed")
ck("B's sell paid NADO", exbal(B["address"]) > nb0 - MIN_TX_FEE * 4, (exbal(B["address"]), nb0))

# ---- to graduation ----------------------------------------------------------------------------------------------
o = 10
while M("kind", PID) == D.CURVE and o < 30:
    call(A, "buy", [PID, o, 120], value=120 * U)
    c = cursor()
    wait(lambda: cursor() > c + 1, f"buy {o} batched")
    call(A, "claim", [o, AID])
    wait(lambda: M("kind", PID) != D.CURVE or M("open", PID) == 0, f"buy {o} cleared")
    o += 1
ck("the curve graduated", M("kind", PID) == D.GRADUATED, M("kind", PID))
rn, rt = M("rn", PID), M("rt", PID)
ck("…into a pool with reserves and no shares", rn > 0 and rt > 0 and M("sup", PID) == 0, (rn, rt, M("sup", PID)))
bt0 = abal(AID, B["address"])
call(B, "swapn", [PID, 50, 1, AID], value=50 * U)
wait(lambda: abal(AID, B["address"]) > bt0, "B swapped on the graduated pool")
ck("the graduated pool trades", M("rn", PID) > rn)

# ---- the contract holds what it owes (the launchpad's part) --------------------------------------------------------
c = contract()
held_coins = abal(AID, CID)
ck("the contract holds at least the pool's coins", held_coins >= M("rt", PID) * U, (held_coins, M("rt", PID) * U))

# ---- give B's leftover L1 NADO back to A ---------------------------------------------------------------------------
left = l1bal(B["address"])
if left > 2 * MIN_TX_FEE:
    send(B, A["address"], left - MIN_TX_FEE)
print(f"B keeps {exbal(B['address']) / NADO:.4f} NADO on the exec layer (cash out later: bridge_withdraw), coins {abal(AID, B['address']) / U:.0f}", flush=True)

if FAILS:
    print(f"{len(FAILS)} FAILURES: {FAILS}"); sys.exit(1)
print("ALL PASS — the launchpad works end to end on the live chain")
