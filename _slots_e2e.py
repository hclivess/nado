#!/usr/bin/env python3
# _slots_e2e.py — LIVE smoke test of the slots contract with real (tiny) NADO from the node key:
# open a machine, spin it, settle permissionlessly, and assert the exact paytable payout on-chain.
import sys, json, time, urllib.request, random
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from ops.transaction_ops import create_txid, construct_blob_tx, construct_bridge_deposit_tx
from signatures import sign, unhex
from hashing import create_nonce
from config import get_timestamp_seconds
from protocol import MIN_TX_FEE, CHAIN_ID
import hashlib
# reference formulas inlined (importing tests/test_slots_contract.py would EXECUTE the whole test)
def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
def sym_of(stop): return (stop>=16)+(stop>=30)+(stop>=42)+(stop>=52)+(stop>=58)+(stop>=62)
TRIP2 = [16, 20, 24, 30, 60, 100, 300]
def m2_of(s0, s1, s2):
    if s0 == s1 == s2: return TRIP2[s0]
    c7 = (s0==6)+(s1==6)+(s2==6)
    if c7 == 2: return 10
    if c7 == 1: return 3
    return 6 if (s0==0)+(s1==0)+(s2==0) == 2 else 0
def ref_spin(bh, sh, g):
    q = bh[sh] + bh[sh+1] + g
    stops = [vm_hash(q + i) % 64 for i in range(3)]
    syms = [sym_of(r) for r in stops]
    return stops, syms, m2_of(*syms)

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
CID = "f976149cd5e8de62b24ee3ed13179c15"
NADO = 10**10
ok_all = True
def ck(n, c):
    global ok_all
    print(("  PASS " if c else "  FAIL ") + n, flush=True)
    if not c: ok_all = False
def j(u): return json.load(urllib.request.urlopen(u, timeout=8))
def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(), headers={"Content-Type": "application/json"})
    try: return json.load(urllib.request.urlopen(r, timeout=12))
    except urllib.error.HTTPError as e: return {"result": False, "message": e.read().decode()[:200]}
def tip(): return j(L1 + "/get_latest_block")["block_number"]
def exbal(a):
    try: return int(j(EX + "/exec/bridge?ns=default&provisional=1").get("balances", {}).get(a, 0))
    except Exception: return 0
def sto(): return j(EX + f"/exec/contract?ns=default&cid={CID}&provisional=1").get("storage", {})
def M(m, k): return sto().get(m, {}).get(str(k), 0)
def wait(cond, what, tries=40):
    for _ in range(tries):
        try:
            if cond(): print("  [ok] " + what, flush=True); return
        except Exception: pass
        time.sleep(6)
    print("  [TIMEOUT] " + what, flush=True); sys.exit(1)
def call(kd, method, args, value=0):
    blob = {"op": "call", "contract": CID, "method": method, "args": args}
    if value: blob["value"] = value
    for _ in range(6):
        r = post(construct_blob_tx(kd, blob, tip() + 25, MIN_TX_FEE))
        if r.get("result"): return
        time.sleep(10)
    sys.exit("call gave up: " + method)

kd = load_keys()
A = kd["address"]
print("slots E2E as", A[:16] + "…", flush=True)
if exbal(A) < 40 * NADO:
    post(construct_bridge_deposit_tx(kd, 60 * NADO, tip() + 25, MIN_TX_FEE))
    wait(lambda: exbal(A) >= 40 * NADO, "bridge deposit landed")

T = random.randrange(10**8, 10**9)
call(kd, "open", [T], 30 * NADO)                    # bank 30 NADO -> max bet ~0.2 NADO
wait(lambda: M("ta", T) == A, f"machine #{T} open with a 30-NADO bank")
G = random.randrange(10**8, 10**9)
STAKE = NADO // 10                                   # 0.1 NADO spin (cover 14.9 <= 30)
call(kd, "spin", [G], 0) if False else call(kd, "spin", [G, T], STAKE)
wait(lambda: M("gg", G) == T, "spin landed")
sh = M("gh", G)
def bh2(h):
    v = j(EX + f"/exec/blockhash?ns=default&provisional=1&heights={h},{h+1}").get("hashes", {})
    a, b = v.get(str(h)), v.get(str(h+1))
    return {h: int(a, 16), h+1: int(b, 16)} if a and b else None
wait(lambda: bh2(sh) is not None, f"spin blocks {sh},{sh+1} minted")
bh = bh2(sh)
stops, syms, m2 = ref_spin(bh, sh, G)
print(f"  reels: stops={stops} syms={syms} multiplier={m2/2}x", flush=True)
b0 = exbal(A)
call(kd, "settle", [G])
wait(lambda: M("gd", G) == 1, "spin settled on-chain")
ck("payout matches the paytable exactly", exbal(A) == b0 + STAKE * m2 // 2 and M("gw", G) == m2)
ck("stored reels match the reference", M("gr", G) == stops[0] + 64*stops[1] + 4096*stops[2] + 1)
call(kd, "close", [T])
wait(lambda: M("tz", T) == 1, "machine closed, bank cashed out")
print("\nSLOTS E2E " + ("ALL PASS" if ok_all else "FAILED"), flush=True)
sys.exit(0 if ok_all else 1)
