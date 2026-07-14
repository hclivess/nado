#!/usr/bin/env python3
# _mines_e2e.py — LIVE smoke test of the mines contract with real (tiny) NADO from the node key:
# bank a field, start a round, reveal a batch, resolve it permissionlessly, and assert the exact
# contract math (bust folds the stake; a clean batch banks the re-priced value and cashes out).
import sys, json, time, urllib.request, random
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from ops.transaction_ops import construct_blob_tx, construct_bridge_deposit_tx
from protocol import MIN_TX_FEE
import hashlib
# reference formulas inlined (importing tests/test_*.py would EXECUTE the whole test)
def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
T = 25
def ref_batch_value(v, gp, n_mines, count):
    for i in range(count):
        rem = T - gp - i
        v = v * rem * 99 // ((rem - n_mines) * 100)
    return v
def ref_draws(bh, gh, g, gp, count, n_mines):
    q = bh[gh] + bh[gh + 1] + g * 100
    for i in range(count):
        if vm_hash(q + gp + i) % (T - gp - i) < n_mines:
            return i + 1
    return 0

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
CID = "ecb7f71c9149e272f537a80bd3392474"
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
def bh2(h):
    v = j(EX + f"/exec/blockhash?ns=default&provisional=1&heights={h},{h+1}").get("hashes", {})
    a, b = v.get(str(h)), v.get(str(h + 1))
    return {h: int(a, 16), h + 1: int(b, 16)} if a and b else None

kd = load_keys()
A = kd["address"]
print("mines E2E as", A[:16] + "…", flush=True)
if exbal(A) < 15 * NADO:
    post(construct_bridge_deposit_tx(kd, 20 * NADO, tip() + 25, MIN_TX_FEE))
    wait(lambda: exbal(A) >= 15 * NADO, "bridge deposit landed")

TBL = random.randrange(10**8, 10**9)
call(kd, "open", [TBL], 10 * NADO)
wait(lambda: M("ta", TBL) == A, f"field #{TBL} open with a 10-NADO bank")

G = random.randrange(10**8, 10**9)
STAKE = NADO // 10                                   # 0.1 NADO round, 3 mines
call(kd, "bet", [G, TBL, 3], STAKE)
wait(lambda: M("gg", G) == TBL, "round seated (3 mines)")
ck("value starts at the stake", M("gv", G) == STAKE)

call(kd, "pick", [G, 2])                             # reveal a 2-tile batch
wait(lambda: M("gh", G) != 0, "batch bound to future blocks")
gh = M("gh", G)
want_nv = ref_batch_value(STAKE, 0, 3, 2)
ck("pending value re-priced exactly (x{:.3f})".format(want_nv / STAKE), M("gq", G) == want_nv)
wait(lambda: bh2(gh) is not None, f"draw blocks {gh},{gh+1} minted")
bust = ref_draws(bh2(gh), gh, G, 0, 2, 3)
print(f"  reference draw: {'BUST at step %d' % bust if bust else 'ALL SAFE'}", flush=True)
b0 = exbal(A)
call(kd, "resolve", [G])
if bust:
    wait(lambda: M("gd", G) == 1, "bust resolved on-chain")
    ck("bust recorded at the right step", M("gb", G) == bust)
    ck("stake folded into the bankroll", M("tk", TBL) == 10 * NADO + STAKE)
else:
    wait(lambda: M("gp", G) == 2, "clean batch banked on-chain")
    ck("banked value == reference", M("gv", G) == want_nv)
    b0 = exbal(A)
    call(kd, "cashout", [G])
    wait(lambda: M("gd", G) == 1, "cashed out on-chain")
    ck("cashout paid exactly the banked value", exbal(A) == b0 + want_nv and M("gw", G) == 1)

call(kd, "close", [TBL])
wait(lambda: M("tz", TBL) == 1, "field closed, pool reclaimed")
print("\nMINES E2E " + ("ALL PASS" if ok_all else "FAILED"), flush=True)
sys.exit(0 if ok_all else 1)
