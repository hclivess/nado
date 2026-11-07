# land_first_wave.py — the Land planet's FIRST WAVE on the live chain (doc/land.md "Decisions"; issues #116 #121 #122),
# signed by the issuer — this server's wallet (execnode/games/land.py ISSUER):
#   1. deploy the land title contract (upgradable, at its derived address) if it is not there;
#   2. mint the 100 titles of the landing site (face 0, rows 4995–5004, cols 3435–3444) — asset_create, supply 1,
#      never mintable, its seed land.plot_seed(plot) — to the issuer;
#   3. a "Land · planet 0" collection on the NFT market and each title registered there with the 5 % royalty;
#   4. every title but the TOWN — the central 2 × 2 plots around the landing (rows 4999–5000, cols 3439–3440), kept by
#      the server wallet for the roads and the town hall (#123) — listed at 5 NADO.
# Idempotent: a step already done on chain (a title minted, registered, listed) is skipped, so a rerun finishes the wave.
# Run from a worktree, as the operator: HOME=/root python3 scripts/land_first_wave.py [--dry-run]
import json, os, sys, time, urllib.request
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from execnode.games import land as L
from execnode.games.redeploy import target_cids
from execnode.state import asset_id
from ops.key_ops import load_keys
from ops.transaction_ops import construct_blob_tx
from protocol import MIN_TX_FEE

L1, EX = "http://127.0.0.1:9173", "http://127.0.0.1:9273"
NADO = 10 ** 10
PRICE, ROYALTY_BPS = 5 * NADO, 500
ROWS, COLS = range(4995, 5005), range(3435, 3445)
TOWN = {(r, c) for r in (4999, 5000) for c in (3439, 3440)}
COLL_ID = 0x4C414E44                                 # "LAND": the collection's id on the market
DRY = "--dry-run" in sys.argv


def j(u): return json.load(urllib.request.urlopen(u, timeout=15))  # nosec B310 # operator CLI: the operator's own node URL
def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(), headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(r, timeout=15))  # nosec B310 # operator CLI: the operator's own node URL
    except urllib.error.HTTPError as e:
        return {"result": False, "message": e.read().decode()[:200]}
def tip(): return j(L1 + "/get_latest_block")["block_number"]


def plot_of(r, c): return (0 * L.FACE_N + r) * L.FACE_N + c
PLOTS = [(r, c, plot_of(r, c)) for r in ROWS for c in COLS]
KD = load_keys("/root/nado/private/keys.dat")
assert KD["address"] == L.ISSUER, "the issuer's key is this server's wallet"
CIDS = target_cids()
LAND, NFT = CIDS["land"], CIDS["nft"]
AID = {p: int(asset_id(L.ISSUER, L.plot_seed(p))) for _, _, p in PLOTS}


def send(payloads, label):
    """Submit blobs in waves of 20 and wait until each wave's effect shows (the caller's check)."""
    print(f"{label}: {len(payloads)} to send" + (" (dry run)" if DRY else ""), flush=True)
    if DRY:
        for p in payloads[:3]:
            print("   ", json.dumps(p)[:200])
        return
    for i in range(0, len(payloads), 20):
        for p in payloads[i:i + 20]:
            for _ in range(6):
                r = post(construct_blob_tx(KD, p, tip() + 30, MIN_TX_FEE, min_block=tip() + 2))
                if r.get("result"):
                    break
                print("   retry:", r.get("message"), flush=True); time.sleep(8)
        time.sleep(30)


def contract(cid):
    try:
        return j(EX + f"/exec/contract?ns=default&cid={cid}&provisional=1")
    except Exception:
        return {}


def wait(cond, label, timeout=1200):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            print(f"  [ok] {label}", flush=True); return
        time.sleep(10)
    sys.exit(f"  [TIMEOUT] {label}")


# 1. the land contract
if not contract(LAND).get("code"):
    from execnode.games import deploy as Dp
    print("land contract: deploying at", LAND, "(dry run)" if DRY else "", flush=True)
    if not DRY:
        Dp.deploy_one("land", L1, "a5", MIN_TX_FEE)
        wait(lambda: bool(contract(LAND).get("code")), "the land contract is on chain")
else:
    print("land contract: on chain at", LAND)

# 2. the titles
def minted():
    try:
        return {str(a["id"]) for a in j(EX + f"/exec/assets?ns=default&issuer={L.ISSUER}").get("assets", [])}
    except Exception:
        return set()
have = minted()
todo = [{"op": "asset_create", "seed": L.plot_seed(p), "name": f"Land plot 0·{r}·{c}", "sym": "PLOT", "dec": 0, "supply": 1,
         "mintable": False, "uri": f"https://land.nadochain.com/?plot={p}"} for r, c, p in PLOTS if str(AID[p]) not in have]
send(todo, "titles to mint")
if not DRY and todo:
    wait(lambda: all(str(AID[p]) in minted() for _, _, p in PLOTS), "all 100 titles minted")

# 3. the collection and the royalty
def nft_maps():
    return (contract(NFT).get("storage") or {})
sto = nft_maps()
if str(COLL_ID) not in (sto.get("c_owner") or {}):
    send([{"op": "call", "contract": NFT, "method": "create_collection",
           "args": [COLL_ID, "Land · planet 0", "Plots of the first wave of the Land planet (land.nadochain.com)"]}], "the collection")
    if not DRY:
        wait(lambda: str(COLL_ID) in (nft_maps().get("c_owner") or {}), "the collection exists")
registered = lambda: {str(v) for v in (nft_maps().get("t_asset") or {}).values()}
reg = registered()
todo = [{"op": "call", "contract": NFT, "method": "register", "args": [0x504C0000 + i, AID[p], L.plot_seed(p), ROYALTY_BPS, COLL_ID]}
        for i, (_, _, p) in enumerate(PLOTS) if str(AID[p]) not in reg]
send(todo, "titles to register (5 % royalty)")
if not DRY and todo:
    wait(lambda: all(str(AID[p]) in registered() for _, _, p in PLOTS), "every title registered")

# 4. the sale (the town stays with the server wallet)
def listed():
    s = nft_maps()
    return {str(a) for k, a in (s.get("l_asset") or {}).items() if int((s.get("l_left") or {}).get(k, 0)) > 0}
lst = listed()
todo = [{"op": "call", "contract": NFT, "method": "list", "args": [0x4C530000 + i, AID[p], PRICE], "value": 1, "asset": str(AID[p])}
        for i, (r, c, p) in enumerate(PLOTS) if (r, c) not in TOWN and str(AID[p]) not in lst]
send(todo, f"titles to list at {PRICE // NADO} NADO")
if not DRY and todo:
    wait(lambda: len(listed() & {str(AID[p]) for r, c, p in PLOTS if (r, c) not in TOWN}) == 96, "96 titles listed")
print("town (kept by the server wallet):", sorted(plot_of(r, c) for r, c in TOWN))
print("land contract:", LAND, " — wire it into static/land.js (const CID) and restart nado-land")
