# _autogame_e2e.py — LIVE end-to-end of the deployed Autogame contract against the running node.
#
# Proves the whole loop on real chain data rather than in a test harness: set out, read the committed
# terrain the way the browser does, queue a plan against it, wait for the rolling height, settle, and check
# that what the chain computed is exactly what the reference model says it should have computed.
#
# Run: HOME=/root python3 _autogame_e2e.py
import json, sys, time, urllib.error, urllib.request

sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from ops.address_ops import make_address
from ops.transaction_ops import construct_blob_tx
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY
from execnode.games import autogame as A
from execnode.stark import alghash, field as F
from tests import autogame_model as M

L1 = "http://127.0.0.1:9173"
EX = "http://127.0.0.1:9273"
CID = "e1642eac82cb17f08b43dc427ac2df1f"


def j(u):
    return json.load(urllib.request.urlopen(u, timeout=15))


def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(),
                               headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(r, timeout=20))
    except urllib.error.HTTPError as e:
        return {"result": False, "message": e.read().decode()[:200]}


def tip():
    return j(L1 + "/get_latest_block")["block_number"]


def sto():
    return j(EX + f"/exec/contract?ns=default&cid={CID}&provisional=1").get("storage", {})


def cursor():
    return int(j(EX + "/exec/root?ns=default&provisional=1").get("cursor", 0))


def blockhash(h):
    """BHASH(h) as the contract sees it — the L1 block hash reduced into the field."""
    b = j(L1 + f"/get_block_number?block_number={h}")
    return int(b["block_hash"], 16) % F.P


K = load_keys()
K["address"] = make_address(K["public_key"])
ME = K["address"]

FAILS = []


def ck(name, cond, extra=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {extra}" if extra else ""), flush=True)
    if not cond:
        FAILS.append(name)


def call(method, args, value=0):
    p = {"op": "call", "contract": CID, "method": method, "args": args}
    if value:
        p["value"] = int(value)
    for _ in range(8):
        r = post(construct_blob_tx(K, p, tip() + 12, MIN_TX_FEE, min_block=tip() + TX_INCLUSION_DELAY))
        if r.get("result"):
            return r
        print("   retry", method, r.get("message"), flush=True)
        time.sleep(12)
    print("   [GIVEUP]", method, flush=True)
    sys.exit(1)


def wait(cond, label, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond():
                print("  [ok]", label, flush=True)
                return True
        except Exception:
            pass
        time.sleep(8)
    print("  [TIMEOUT]", label, flush=True)
    sys.exit(1)


def field(s, name, rid, default=0):
    return int((s.get(name) or {}).get(str(rid), (s.get(name) or {}).get(rid, default)) or default)


print("autogame e2e as", ME, flush=True)
wait(lambda: j(EX + f"/exec/contract?ns=default&cid={CID}").get("cid") == CID, "contract live", 180)

RID = int(time.time()) % 900000000 + 1
print(f"\n1. set out (run {RID})", flush=True)
call("begin", [RID])
wait(lambda: field(sto(), "ra", RID) != 0 or (sto().get("hp") or {}).get(str(RID)), "run exists")
s = sto()
lh, nh = field(s, "lh", RID), field(s, "nh", RID)
ck("starts at full health", field(s, "hp", RID) == A.HP0, f"hp={field(s, 'hp', RID)}")
ck("terrain height is in the FUTURE at begin", lh > cursor() - 3, f"lh={lh} cursor={cursor()}")
ck("rolling height is one leg later", nh == lh + A.LEG, f"lh={lh} nh={nh}")

print("\n2. wait for the terrain block, then read the road the way the browser does", flush=True)
wait(lambda: cursor() >= lh, f"terrain height {lh} mined")
th = blockhash(lh)
road = []
for i in range(A.LEG):
    tw = alghash.hashn([th, RID, i]) & 0xFFFFFFFF
    a, b, c, _sc = M.slice_tile(tw)
    road.append(M.tile_of(a, i))
names = [["road", "monster", "elite", "hazard", "cache", "shrine", "forge", "fork", "relic", "boss"][t]
         for t in road]
print("   road ahead:", " ".join(names), flush=True)
ck("the committed road is readable before the dice exist", len(road) == A.LEG and cursor() < nh,
   f"cursor={cursor()} nh={nh}")

print("\n3. queue a plan against terrain we can see", flush=True)
acts = [A.A_STRIKE if t in (M.MONSTER, M.ELITE) else A.A_GUARD if t == M.HAZARD else 0 for t in road]
word = 0
for i, a in enumerate(acts):
    word |= (a & 7) << (3 * i)
AGG = 3
call("plan", [RID, 0, word, AGG])
time.sleep(20)

print("\n4. wait for the rolling height and settle", flush=True)
wait(lambda: cursor() >= nh, f"rolling height {nh} mined", timeout=900)
rh = blockhash(nh)
call("advance", [RID])
wait(lambda: field(sto(), "dp", RID) > 0, "leg settled")

print("\n5. does the chain agree with the reference model?", flush=True)
s = sto()
run = M.Run()
for i in range(A.LEG):
    if not run.alive or run.done:
        break
    tw = alghash.hashn([th, RID, i]) & 0xFFFFFFFF
    rw = alghash.hashn([rh, RID, i]) & 0xFFFFFFFF
    M.step(run, tw, rw, acts[i], AGG)

got = {k: field(s, v, RID) for k, v in
       (("hp", "hp"), ("maxhp", "mx"), ("stam", "st"), ("potions", "po"), ("xp", "xp"), ("banked", "bk"),
        ("streak", "sk"), ("depth", "dp"), ("kills", "ki"), ("alive", "av"), ("wlevel", "wl"),
        ("alevel", "al"))}
want = {"hp": run.hp, "maxhp": run.maxhp, "stam": run.stam, "potions": run.potions, "xp": run.xp,
        "banked": run.banked, "streak": run.streak, "depth": run.depth, "kills": run.kills,
        "alive": run.alive, "wlevel": run.wlevel, "alevel": run.alevel}
for k in want:
    ck(f"{k} matches the model", got[k] == want[k], f"chain={got[k]} model={want[k]}")
gear = [field(s, f"g{i}", RID) for i in range(A.NSLOT)]
ck("gear matches the model", gear == list(run.gear), f"chain={gear} model={list(run.gear)}")
print(f"   depth {run.depth}  hp {run.hp}/{run.maxhp}  renown {run.xp}  kills {run.kills}", flush=True)

print("\n6. the leg window slid forward", flush=True)
s = sto()
ck("leg counter advanced", field(s, "lg", RID) == 1, f"lg={field(s, 'lg', RID)}")
ck("terrain height became the old rolling height", field(s, "lh", RID) == nh)
ck("next rolling height is one leg on", field(s, "nh", RID) == nh + A.LEG)

print("\n7. a stale plan is refused (the fairness window)", flush=True)
p = {"op": "call", "contract": CID, "method": "plan", "args": [RID, 0, word, AGG]}
r = post(construct_blob_tx(K, p, tip() + 12, MIN_TX_FEE, min_block=tip() + TX_INCLUSION_DELAY))
time.sleep(25)
ck("planning an already-settled leg does not move the run", field(sto(), "lg", RID) == 1)

print("\n" + ("ALL PASS" if not FAILS else f"{len(FAILS)} FAILURES: " + ", ".join(FAILS)), flush=True)
sys.exit(1 if FAILS else 0)
