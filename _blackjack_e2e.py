#!/usr/bin/env python3
# _blackjack_e2e.py — LIVE smoke test of the blackjack contract with real (tiny) NADO from the node key:
# bank a table, deal a hand, reveal it, play a fixed strategy (hit under 15), stand, settle — and assert
# the exact contract outcome + payout against the inlined reference.
import sys, json, time, urllib.request, random
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from ops.transaction_ops import construct_blob_tx, construct_bridge_deposit_tx
from protocol import MIN_TX_FEE
import hashlib
def vm_hash(v): return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")
def card_val(c):
    r = c % 13
    return (1 if r == 12 else 10 if r >= 9 else r + 2), (1 if r == 12 else 0)
def best(h, a): return h + (10 if a > 0 and h + 10 <= 21 else 0)
def ref_dealer(bh, sh, g, up):
    dq = bh[sh] + bh[sh + 1] + g * 64 + 32
    v, a = card_val(up); hh, aa = v, a
    v, a = card_val(vm_hash(dq + 0) % 52); hh += v; aa += a
    j = 1
    while best(hh, aa) < 17:
        v, a = card_val(vm_hash(dq + j) % 52); hh += v; aa += a; j += 1
    return best(hh, aa), (j == 1 and best(hh, aa) == 21)
def ref_outcome(stake, pb, pnat, db, dnat):
    if pnat and dnat: return stake, 2
    if pnat: return stake * 5 // 2, 3
    if dnat: return 0, 4
    if db > 21 or db < pb: return stake * 2, 1
    if db == pb: return stake, 2
    return 0, 4

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
CID = "7b240c833702a4124b7891bf8006e39a"
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
print("blackjack E2E as", A[:16] + "…", flush=True)
if exbal(A) < 15 * NADO:
    post(construct_bridge_deposit_tx(kd, 20 * NADO, tip() + 25, MIN_TX_FEE))
    wait(lambda: exbal(A) >= 15 * NADO, "bridge deposit landed")

TBL = random.randrange(10**8, 10**9)
call(kd, "open", [TBL], 10 * NADO)
wait(lambda: M("ta", TBL) == A, f"table #{TBL} open with a 10-NADO bank")

G = random.randrange(10**8, 10**9)
STAKE = NADO // 10
call(kd, "deal", [G, TBL], STAKE)
wait(lambda: M("gg", G) == TBL, "hand dealt (bound to future blocks)")
gh = M("gh", G)
wait(lambda: bh2(gh) is not None, f"deal blocks {gh},{gh+1} minted")
bh = bh2(gh)
q = bh[gh] + bh[gh + 1] + G * 64
c0, c1, up = vm_hash(q + 0) % 52, vm_hash(q + 1) % 52, vm_hash(q + 16) % 52
call(kd, "reveal", [G])
wait(lambda: M("gf", G) == 2, "hand revealed on-chain")
ck("cards stored on-chain match the reference", M("pc", G * 16) == c0 + 1 and M("pc", G * 16 + 1) == c1 + 1 and M("du", G) == up + 1)
(v0, a0), (v1, a1) = card_val(c0), card_val(c1)
ph, pa, pn = v0 + v1, a0 + a1, 2
print(f"  hand: cards {c0},{c1} (best {best(ph,pa)}) vs dealer up {up}", flush=True)

while best(ph, pa) < 15 and ph <= 21:
    call(kd, "hit", [G])
    wait(lambda: M("gf", G) == 3, "hit bound")
    hh = M("gh", G)
    wait(lambda: bh2(hh) is not None, f"hit blocks {hh},{hh+1} minted")
    bhh = bh2(hh)
    c = vm_hash(bhh[hh] + bhh[hh + 1] + G * 64 + pn) % 52
    call(kd, "draw", [G])
    wait(lambda: M("gn", G) == pn + 1 or M("gd", G) == 1, "card drawn on-chain")
    v, a = card_val(c); ph += v; pa += a; pn += 1
    ck(f"drawn card {c} matches (hard {ph})", M("gp", G) == ph)
    if ph > 21:
        ck("bust settled to the bank", M("gd", G) == 1 and M("gw", G) == 5)
        break

if ph <= 21:
    call(kd, "stand", [G])
    wait(lambda: M("gf", G) == 4, "stand bound — dealer draws next")
    sh = M("gh", G)
    wait(lambda: bh2(sh) is not None, f"dealer blocks {sh},{sh+1} minted")
    db, dnat = ref_dealer(bh2(sh), sh, G, up)
    pay, res = ref_outcome(STAKE, best(ph, pa), pn == 2 and best(ph, pa) == 21, db, dnat)
    print(f"  dealer plays to {db}{' (natural)' if dnat else ''} → expect pay {pay}", flush=True)
    b0 = exbal(A)
    call(kd, "settle", [G])
    wait(lambda: M("gd", G) == 1, "hand settled on-chain")
    ck("outcome + payout match the reference", exbal(A) == b0 + pay and M("gw", G) == res and M("gr", G) == db)

call(kd, "close", [TBL])
wait(lambda: M("tz", TBL) == 1, "table closed, pool reclaimed")
print("\nBLACKJACK E2E " + ("ALL PASS" if ok_all else "FAILED"), flush=True)
sys.exit(0 if ok_all else 1)
