# _pets_e2e.py — LIVE end-to-end exercise of the deployed NADO Pets contract with real txs on the running
# node: two wallets deposit, mint eggs, hatch (chain-decided species vs the reference), feed, name, train +
# resolve, list + buy on the marketplace, then battle to a chain-decided end. Every step is verified against
# /exec/contract storage and the Python reference (tests/pets_ref.py). Run: nado_venv/bin/python _pets_e2e.py
import json, urllib.request, time, sys
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from Curve25519 import generate_keydict, sign, unhex
from ops.transaction_ops import construct_blob_tx, construct_bridge_deposit_tx, create_txid
from hashing import create_nonce
from config import get_timestamp_seconds
from protocol import MIN_TX_FEE, CHAIN_ID
from tests.pets_ref import ref_gene, ref_species, ref_stat, ref_power, ref_train_roll, ref_train_ok, ref_battle

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
CID = "a5099d7f767cfe8e84855a7cb64994cb"
NADO = 10**10; MINT_FEE = NADO; TRAIN_FEE = 5 * 10**9

def j(u): return json.load(urllib.request.urlopen(u, timeout=8))
def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=12))
def tip(): return j(L1 + "/get_latest_block")["block_number"]
def exbal(a):
    try: return int(j(EX + "/exec/bridge?ns=default").get("balances", {}).get(a, 0))
    except Exception: return 0
def sto():
    try: return j(EX + f"/exec/contract?ns=default&cid={CID}").get("storage", {})
    except Exception: return {}
def M(m, k): return sto().get(m, {}).get(str(k), 0)
def bh(h):
    v = j(EX + f"/exec/blockhash?ns=default&heights={h},{h+1}").get("hashes", {})
    a, b = v.get(str(h)), v.get(str(h + 1))
    return (int(a, 16), int(b, 16)) if a and b else None
def send(kd, recipient, amount):
    if recipient == "bridge":
        return post(construct_bridge_deposit_tx(kd, amount, tip() + 8, MIN_TX_FEE))
    t = {"sender": kd["address"], "recipient": recipient, "amount": int(amount), "timestamp": get_timestamp_seconds(),
         "data": "", "nonce": create_nonce(), "public_key": kd["public_key"], "max_block": tip() + 8, "chain_id": CHAIN_ID, "fee": MIN_TX_FEE}
    t["txid"] = create_txid(t); t["signature"] = sign(private_key=kd["private_key"], message=unhex(t["txid"]))
    return post(t)
def call(kd, method, args, value=0):
    p = {"op": "call", "contract": CID, "method": method, "args": args}
    if value: p["value"] = int(value)
    return post(construct_blob_tx(kd, p, tip() + 8, MIN_TX_FEE))
def wait(cond, label, timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if cond(): print(f"  [ok] {label}", flush=True); return True
        except Exception: pass
        time.sleep(10)
    print(f"  [TIMEOUT] {label}", flush=True); sys.exit(1)

FAILS = []
def ck(n, c): print(("  PASS " if c else "  FAIL ") + n, flush=True); (None if c else FAILS.append(n))

A = load_keys("/root/nado/private/keys.dat"); B = generate_keydict()
T = int(time.time())
PA, PB = T % 10**9, (T + 1) % 10**9
print(f"A={A['address'][:16]} B={B['address'][:16]} pets A#{PA} B#{PB}", flush=True)

wait(lambda: sto() is not None and j(EX + f"/exec/contract?ns=default&cid={CID}").get("cid") == CID, "pets contract is live on the exec node", 300)

# 1) fund B on L1, both deposit to the exec bridge
send(A, B["address"], 30 * NADO)
send(A, "bridge", 20 * NADO)
wait(lambda: exbal(A["address"]) >= 20 * NADO, "A bridge deposit landed")
send(B, "bridge", 20 * NADO)
wait(lambda: exbal(B["address"]) >= 20 * NADO, "B bridge deposit landed")

# 2) mint both eggs
call(A, "mint", [PA], MINT_FEE); call(B, "mint", [PB], MINT_FEE)
wait(lambda: M("ow", PA) == A["address"] and M("ow", PB) == B["address"], "both eggs minted (NFT records on-chain)")
ck("mint set gene block + 3-day belly", M("bh", PA) > 0 and M("fu", PA) == M("bh", PA) + 43200)

# 3) hatch once the gene blocks are finalized
for P, K in ((PA, A), (PB, B)):
    gb = M("bh", P)
    wait(lambda: bh(gb) is not None, f"gene blocks {gb},{gb+1} of pet #{P} finalized")
    call(K, "hatch", [P])
wait(lambda: M("gs", PA) != 0 and M("gs", PB) != 0, "both hatched")
for P in (PA, PB):
    gb = M("bh", P); h0, h1 = bh(gb)
    g = ref_gene({gb: h0, gb + 1: h1}, gb, P); s = ref_species(g)
    ck(f"pet #{P} gene==reference beacon formula", int(M("gs", P)) == g)
    ck(f"pet #{P} species={s} appetite/power == reference", M("sp", P) == s and M("ap", P) == ref_stat(g, s, 9) and M("pw", P) == ref_power(g, s))

# 4) feed + name
apA, fu0 = M("ap", PA), M("fu", PA)
meal = apA * 14000 * 1000
call(A, "feed", [PA], meal)
wait(lambda: M("fu", PA) == fu0 + 1000, "feeding extended life by exactly value/(appetite*14000) blocks")
call(A, "name", [PA, "Zappy"])
wait(lambda: M("nm", PA) == "Zappy", "named the pet on-chain")

# 5) train stat 3 + resolve, differentially
pw0 = M("pw", PA)
call(A, "train", [PA, 3], TRAIN_FEE)
wait(lambda: M("th", PA) > 0, "training session booked")
th = M("th", PA)
wait(lambda: bh(th) is not None, f"training blocks {th},{th+1} finalized")
h0, h1 = bh(th)
g = int(M("gs", PA)); s = M("sp", PA)
cur = ref_stat(g, s, 3) + 0
ok = ref_train_ok(ref_train_roll({th: h0, th + 1: h1}, th, PA, 3), cur, s)
call(B, "train_resolve", [PA])   # permissionless
wait(lambda: M("th", PA) == 0, "training resolved")
ck(f"training result matches reference (success={ok})", M("tr", PA) == (1 if ok else 2)
   and M("pw", PA) == pw0 + (1 if ok else 0) and M("tb", f"{PA}|3") == (1 if ok else 0))

# 6) marketplace: A lists a second egg, B buys it
PM = (T + 2) % 10**9
call(A, "mint", [PM], MINT_FEE)
wait(lambda: M("ow", PM) == A["address"], "market egg minted")
call(A, "list", [PM, 3 * NADO])
wait(lambda: M("mp", PM) == 3 * NADO, "egg listed at 3 NADO")
ea = exbal(A["address"])
call(B, "buy", [PM], 3 * NADO)
wait(lambda: M("ow", PM) == B["address"], "B bought the egg")
ck("sale paid A exactly the ask", exbal(A["address"]) == ea + 3 * NADO and M("mp", PM) == 0)

# 7) battle: B challenges Zappy with pet B, A accepts, chain resolves
BID = (T + 3) % 10**9
call(B, "challenge", [BID, PB, PA], 2 * NADO)
wait(lambda: M("wn", BID) == 1, "challenge open (consent required)")
call(A, "accept", [BID], 2 * NADO)
wait(lambda: M("wn", BID) == 2, "battle accepted, bound to future blocks")
wh = M("wh", BID)
wait(lambda: bh(wh) is not None, f"battle blocks {wh},{wh+1} finalized")
h0, h1 = bh(wh)
b_wins, dies = ref_battle({wh: h0, wh + 1: h1}, wh, BID, M("pw", PB), M("pw", PA))   # A-side of ref = challenger=PB
winner, loser = (PB, PA) if b_wins else (PA, PB)
w_addr = M("ow", winner); ew = exbal(w_addr)
call(B, "resolve_battle", [BID])
wait(lambda: M("wn", BID) == 3, "battle settled on-chain")
ck(f"winner matches reference (pet #{winner}{', loser DIED' if dies else ''})", M("ww", BID) == winner
   and (M("wd", BID) == (loser if dies else 0)) and exbal(w_addr) == ew + 4 * NADO)
ck("death applied exactly per reference", (M("fu", loser) == 1) == dies)

print(("\nE2E ALL PASS" if not FAILS else f"\nE2E {len(FAILS)} FAILED: {FAILS}"), flush=True)
sys.exit(1 if FAILS else 0)
