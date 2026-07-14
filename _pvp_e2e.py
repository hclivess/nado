#!/usr/bin/env python3
# _pvp_e2e.py — LIVE smoke test of the PvP board contracts (connect4 + reversi) with real (tiny)
# NADO: the node key opens, a freshly generated funded key joins, both play a scripted game to a
# win, and the pot payout is asserted to the raw unit. Exercises the whole pvp skeleton on-chain:
# open/join escrow, ply-bound move(), the on-chain referee (4-in-a-row / flip+disc-count) and payout.
import sys, json, time, urllib.request, random
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from signatures import generate_keydict
from ops.transaction_ops import (construct_blob_tx, construct_bridge_deposit_tx,
                                 draft_transaction, create_transaction)
from config import get_timestamp_seconds
from protocol import MIN_TX_FEE

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
C4 = "87eac9c1be9bdfa84c013d7a72f6997d"
RV = "017fd842c55254328c4133dc283fcea5"
NADO = 10**10
STAKE = NADO // 100                                   # 0.01 NADO a side
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
def l1bal(a):
    try: return int(j(L1 + f"/get_account?address={a}").get("balance", 0))
    except Exception: return 0
def exbal(a):
    try: return int(j(EX + "/exec/bridge?ns=default&provisional=1").get("balances", {}).get(a, 0))
    except Exception: return 0
def sto(cid): return j(EX + f"/exec/contract?ns=default&cid={cid}&provisional=1").get("storage", {})
def M(cid, m, k): return sto(cid).get(m, {}).get(str(k), 0)
def wait(cond, what, tries=40):
    for _ in range(tries):
        try:
            if cond(): print("  [ok] " + what, flush=True); return
        except Exception: pass
        time.sleep(6)
    print("  [TIMEOUT] " + what, flush=True); sys.exit(1)
def call(kd, cid, method, args, value=0):
    blob = {"op": "call", "contract": cid, "method": method, "args": args}
    if value: blob["value"] = value
    for _ in range(6):
        r = post(construct_blob_tx(kd, blob, tip() + 25, MIN_TX_FEE))
        if r.get("result"): return
        time.sleep(10)
    sys.exit("call gave up: " + method)
def transfer(kd, to, amount):
    draft = draft_transaction(kd["address"], to, int(amount), kd["public_key"],
                              get_timestamp_seconds(), "", tip() + 25)
    return post(create_transaction(draft, kd["private_key"], MIN_TX_FEE))

P1 = load_keys()
A1 = P1["address"]
print("pvp E2E — p1 (node key):", A1[:16] + "…", flush=True)
if exbal(A1) < NADO:
    post(construct_bridge_deposit_tx(P1, 2 * NADO, tip() + 25, MIN_TX_FEE))
    wait(lambda: exbal(A1) >= NADO, "p1 bridge deposit landed")

P2 = generate_keydict()
A2 = P2["address"]
print("pvp E2E — p2 (fresh key):", A2[:16] + "…", flush=True)
transfer(P1, A2, 2 * NADO)
wait(lambda: l1bal(A2) >= NADO, "p2 funded on L1")
post(construct_bridge_deposit_tx(P2, NADO, tip() + 25, MIN_TX_FEE))
wait(lambda: exbal(A2) >= NADO // 2, "p2 bridge deposit landed")

def play(cid, name, moves, want_wr):
    g = random.randrange(10**8, 10**9)
    print(f"\n== {name} game #{g} ==", flush=True)
    b1, b2 = exbal(A1), exbal(A2)
    call(P1, cid, "open", [g], STAKE)
    wait(lambda: M(cid, "p1", g) == A1, "opened + escrowed")
    call(P2, cid, "join", [g], STAKE)
    wait(lambda: M(cid, "nn", g) == 2, "joined — pot is 2 stakes")
    ck("pot escrowed", M(cid, "pt", g) == 2 * STAKE)
    for ply, arg in enumerate(moves):
        kd = P1 if ply % 2 == 0 else P2
        call(kd, cid, "move", [g, arg, ply])
        wait(lambda: M(cid, "mc", g) > ply or M(cid, "sd", g) == 1, f"ply {ply} (arg {arg}) landed")
    wait(lambda: M(cid, "sd", g) == 1, "game settled")
    ck("winner recorded", M(cid, "wr", g) == want_wr)
    win, lose = (A1, A2) if want_wr == 1 else (A2, A1)
    wait(lambda: exbal(win) == (b1 if win == A1 else b2) + STAKE, "pot paid out")
    ck("winner nets exactly one stake", exbal(win) == (b1 if win == A1 else b2) + STAKE)
    ck("loser is down exactly one stake", exbal(lose) == (b1 if lose == A1 else b2) - STAKE)

# connect4: p1 stacks column 0 (plies 0/2/4/6), p2 wastes column 1 — vertical four wins for p1
play(C4, "CONNECT4", [0, 1, 0, 1, 0, 1, 0], want_wr=1)

# reversi: B plays c4 (pos 2*8+3=19, flips d4), then both pass — B 4 discs vs W 1, B takes the pot
play(RV, "REVERSI", [19, 64, 64], want_wr=1)

print("\nPVP E2E " + ("ALL PASS" if ok_all else "FAILED"), flush=True)
sys.exit(0 if ok_all else 1)
