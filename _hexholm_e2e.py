#!/usr/bin/env python3
# _hexholm_e2e.py — LIVE smoke test of the Hexholm contract with real (tiny) NADO on the running chain.
# A 3-seat table: the node key + two freshly funded keys play REAL engine-legal moves for a stretch —
# each move computed by tests/hexholm_next_move.mjs, which replays the on-chain log through the browser's
# actual rules engine with the actual pinned block hashes (all three secrets passed, so scroll buys are
# exercised end to end). Then the settle paths run for real: reveal (commit-verified halves), the resign
# cascade (last seat standing is paid the pot), a cancel refund, and a 2-seat unanimous-agree payout.
# The full play-to-10-points path is proven headless (tests/hexholm_engine_test.mjs plays whole games);
# this driver proves the CHAIN half: seeds, escrow, free-actor ply binding, payouts.
import sys, json, time, urllib.request, random, subprocess
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from signatures import generate_keydict
from ops.transaction_ops import (construct_blob_tx, construct_bridge_deposit_tx,
                                 draft_transaction, create_transaction)
from config import get_timestamp_seconds
from protocol import MIN_TX_FEE
from execnode.stark import alghash, field as F

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
CID = "c532e36ac30f61619e9ac989a1c0994e"
NADO = 10**10
STAKE = NADO // 100
MOVES_TO_PLAY = 30
ok_all = True
def ck(n, c):
    global ok_all
    print(("  PASS " if c else "  FAIL ") + n, flush=True)
    if not c: ok_all = False
def j(u): return json.load(urllib.request.urlopen(u, timeout=8))
def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(), headers={"Content-Type": "application/json"})
    try: out = json.load(urllib.request.urlopen(r, timeout=12))
    except urllib.error.HTTPError as e: out = {"result": False, "message": e.read().decode()[:200]}
    if not out.get("result"): print("  [submit REJECTED]", str(out.get("message"))[:160], flush=True)
    return out
def tip(): return j(L1 + "/get_latest_block")["block_number"]
def l1bal(a):
    try: return int(j(L1 + f"/get_account?address={a}").get("balance", 0))
    except Exception: return 0
def exbal(a):
    try: return int(j(EX + "/exec/bridge?ns=default&provisional=1").get("balances", {}).get(a, 0))
    except Exception: return 0
def sto(): return j(EX + f"/exec/contract?ns=default&cid={CID}&provisional=1").get("storage", {})
def M(mp, k): return sto().get(mp, {}).get(str(k), 0)
def wait(cond, what, tries=60):
    for _ in range(tries):
        try:
            if cond(): print("  [ok] " + what, flush=True); return
        except Exception: pass
        time.sleep(5)
    print("  [TIMEOUT] " + what, flush=True); sys.exit(1)
def wait_soft(cond, what, tries=24):
    for _ in range(tries):
        try:
            if cond(): print("  [ok] " + what, flush=True); return True
        except Exception: pass
        time.sleep(5)
    print("  [retry] " + what + " — ply race consumed the tx; re-polling the oracle", flush=True)
    return False
def call(kd, method, args, value=0):
    blob = {"op": "call", "contract": CID, "method": method, "args": args}
    if value: blob["value"] = value
    for _ in range(6):
        r = post(construct_blob_tx(kd, blob, tip() + 25, MIN_TX_FEE))
        if r.get("result"): return
        time.sleep(8)
    sys.exit("call gave up: " + method)
def transfer(kd, to, amount):
    draft = draft_transaction(kd["address"], to, int(amount), kd["public_key"],
                              get_timestamp_seconds(), "", tip() + 25)
    return post(create_transaction(draft, kd["private_key"], MIN_TX_FEE))
def oracle(g, seed, secrets):
    extra = [str(x) for x in secrets]
    r = subprocess.run(["node", "tests/hexholm_next_move.mjs", str(g), CID, str(seed), EX] + extra,
                       capture_output=True, text=True, cwd="/root/nado", timeout=60)
    if r.returncode != 0: sys.exit("oracle failed: " + r.stderr[-400:])
    return json.loads(r.stdout.strip().splitlines()[-1])

P1 = load_keys(); A1 = P1["address"]
print("hexholm E2E — p1 (node key):", A1[:16] + "…", flush=True)
if exbal(A1) < NADO:
    post(construct_bridge_deposit_tx(P1, 2 * NADO, tip() + 25, MIN_TX_FEE))
    wait(lambda: exbal(A1) >= NADO, "p1 bridge deposit landed")
KEYS = [P1]
for i in (2, 3):
    P = generate_keydict(); KEYS.append(P)
    print(f"hexholm E2E — p{i} (fresh key):", P["address"][:16] + "…", flush=True)
    transfer(P1, P["address"], 2 * NADO)
    wait(lambda a=P["address"]: l1bal(a) >= NADO, f"p{i} funded on L1")
    post(construct_bridge_deposit_tx(P, NADO, tip() + 25, MIN_TX_FEE))
    wait(lambda a=P["address"]: exbal(a) >= NADO // 2, f"p{i} bridge deposit landed")
A2, A3 = KEYS[1]["address"], KEYS[2]["address"]

XS = [random.randrange(1, F.P) for _ in range(3)]          # the three seat secrets (driver plays all seats)
CS = [alghash.hashn([x % F.P]) for x in XS]
G = random.randrange(10**8, 10**9)
SEED = random.randrange(1, 10**6)
print(f"\n== HEXHOLM table #{G} cap=3 (bot seed {SEED}) ==", flush=True)
b3_before = exbal(A3)
call(KEYS[0], "open", [G, 3, CS[0]], STAKE)
wait(lambda: M("p1", G) == A1, "opened + escrowed")
call(KEYS[1], "join", [G, CS[1]], STAKE)
wait(lambda: M("nn", G) == 2, "seat 2 joined")
call(KEYS[2], "join", [G, CS[2]], STAKE)
wait(lambda: M("nn", G) == 3, "seat 3 joined — table full")
ck("pot escrowed", M("pt", G) == 3 * STAKE)
ck("board seed height pinned", M("kh", G) > 0)

played = 0
stall = 0
bought_scroll = False
while played < MOVES_TO_PLAY:
    o = oracle(G, SEED, XS)
    if o.get("waiting") or o.get("blocked"):
        stall += 1
        if stall > 80: sys.exit("stuck waiting: " + json.dumps(o))
        time.sleep(4); continue
    if o.get("corrupt"): sys.exit("ENGINE FLAGGED CORRUPT: " + json.dumps(o))
    if o.get("over"):
        print("  game ended naturally:", o, flush=True); break
    stall = 0
    if o["enc"] % 64 == 6: bought_scroll = True
    kd = KEYS[o["actor"]]
    call(kd, "move", [G, o["enc"], o["ply"]])
    if not wait_soft(lambda: M("mc", G) > o["ply"], f"move {o['ply']} (seat {o['actor'] + 1}, enc {o['enc']}) landed"):
        continue
    played += 1
fin = oracle(G, SEED, XS)
ck("final log replays engine-legal", not fin.get("corrupt"))
print("  final oracle state:", json.dumps(fin)[:160], flush=True)

# reveal roundtrip (commit-verified halves land on-chain)
call(KEYS[1], "reveal", [G, XS[1]])
wait(lambda: (M("r2h", G) * (1 << 32) + M("r2l", G)) == XS[1], "seat 2 reveal landed + halves reconstruct")

# resign cascade: seats 1 and 2 resign -> seat 3 takes the whole pot
call(KEYS[0], "resign", [G])
wait(lambda: M("rc", G) == 1, "seat 1 resigned")
call(KEYS[1], "resign", [G])
wait(lambda: M("sd", G) == 1, "second resign settles the table")
ck("last seat standing wins", M("wr", G) == 3)
wait(lambda: exbal(A3) >= b3_before - STAKE + 3 * STAKE, "seat 3 paid the pot")

# cancel refund on an unstarted table
G2 = G + 1
call(KEYS[0], "open", [G2, 3, CS[0]], STAKE)
wait(lambda: M("p1", G2) == A1, "table 2 opened")
call(KEYS[0], "cancel", [G2])
wait(lambda: M("sd", G2) == 1 and M("wr", G2) == 5, "table 2 cancelled + refunded")

# 2-seat unanimous agree payout
G3 = G + 2
b2_before = exbal(A2)
call(KEYS[0], "open", [G3, 2, CS[0]], STAKE)
wait(lambda: M("p1", G3) == A1, "table 3 opened")
call(KEYS[1], "join", [G3, CS[1]], STAKE)
wait(lambda: M("nn", G3) == 2, "table 3 full")
call(KEYS[0], "agree", [G3, 2])
wait(lambda: M("a1", G3) == 2, "seat 1 vote recorded")
ck("one vote does not settle", M("sd", G3) == 0)
call(KEYS[1], "agree", [G3, 2])
wait(lambda: M("sd", G3) == 1, "unanimous agree settles")
ck("agreed winner paid", M("wr", G3) == 2)
wait(lambda: exbal(A2) >= b2_before - STAKE + 2 * STAKE, "seat 2 paid the pot")

print(("\nALL PASS — scroll buys exercised: " + str(bought_scroll)) if ok_all else "\nFAILURES", flush=True)
sys.exit(0 if ok_all else 1)
