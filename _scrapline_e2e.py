#!/usr/bin/env python3
# _scrapline_e2e.py — LIVE smoke test of the Stormhold contract with real (tiny) NADO: the node key
# opens, a freshly generated funded key joins, and both play REAL engine-legal moves for a while — each
# move computed by tests/scrapline_next_move.mjs, which replays the on-chain log through the browser's
# actual rules engine with the actual pinned block hashes. Exercises the full loop on-chain: open/join
# escrow, the kh kingdom seed, ply-bound free-actor move() with per-move seed heights, blocked-shuffle
# waits, and the resign settle (loser pays winner). A second game asserts the cancel refund.
import sys, json, time, urllib.request, random, subprocess
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from signatures import generate_keydict
from ops.transaction_ops import (construct_blob_tx, construct_bridge_deposit_tx,
                                 draft_transaction, create_transaction)
from config import get_timestamp_seconds
from protocol import MIN_TX_FEE

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
CID = "72a195822ef32caa9680eee51eb95dc9"
NADO = 10**10
STAKE = NADO // 100
MOVES_TO_PLAY = 18
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
def sto(): return j(EX + f"/exec/contract?ns=default&cid={CID}&provisional=1").get("storage", {})
def M(m, k): return sto().get(m, {}).get(str(k), 0)
def wait(cond, what, tries=60):
    for _ in range(tries):
        try:
            if cond(): print("  [ok] " + what, flush=True); return
        except Exception: pass
        time.sleep(5)
    print("  [TIMEOUT] " + what, flush=True); sys.exit(1)
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
def oracle(g, seed):
    r = subprocess.run(["node", "tests/scrapline_next_move.mjs", str(g), CID, str(seed)],
                       capture_output=True, text=True, cwd="/root/nado", timeout=60)
    if r.returncode != 0: sys.exit("oracle failed: " + r.stderr[-400:])
    return json.loads(r.stdout.strip().splitlines()[-1])

P1 = load_keys(); A1 = P1["address"]
print("scrapline E2E — p1 (node key):", A1[:16] + "…", flush=True)
if exbal(A1) < NADO:
    post(construct_bridge_deposit_tx(P1, 2 * NADO, tip() + 25, MIN_TX_FEE))
    wait(lambda: exbal(A1) >= NADO, "p1 bridge deposit landed")
P2 = generate_keydict(); A2 = P2["address"]
print("scrapline E2E — p2 (fresh key):", A2[:16] + "…", flush=True)
transfer(P1, A2, 2 * NADO)
wait(lambda: l1bal(A2) >= NADO, "p2 funded on L1")
post(construct_bridge_deposit_tx(P2, NADO, tip() + 25, MIN_TX_FEE))
wait(lambda: exbal(A2) >= NADO // 2, "p2 bridge deposit landed")

G = random.randrange(10**8, 10**9)
SEED = random.randrange(1, 10**6)
print(f"\n== SCRAPLINE game #{G} (bot seed {SEED}) ==", flush=True)
b1, b2 = exbal(A1), exbal(A2)
call(P1, "open", [G], STAKE)
wait(lambda: M("p1", G) == A1, "opened + escrowed")
call(P2, "join", [G], STAKE)
wait(lambda: M("nn", G) == 2, "joined — pot is 2 stakes")
ck("pot escrowed", M("pt", G) == 2 * STAKE)
ck("kingdom seed height pinned", M("kh", G) > 0)

played = 0
stall = 0
while played < MOVES_TO_PLAY:
    o = oracle(G, SEED)
    if o.get("waiting") or o.get("blocked"):
        stall += 1
        if stall > 80: sys.exit("stuck waiting: " + json.dumps(o))
        time.sleep(4); continue
    if o.get("corrupt"): sys.exit("ENGINE FLAGGED CORRUPT: " + o["why"])
    if o.get("over"):
        print("  draft complete — combat resolved:", o, flush=True); break
    stall = 0
    kd = P1 if o["actor"] == 0 else P2
    call(kd, "move", [G, o["enc"], o["ply"]])
    wait(lambda: M("mc", G) > o["ply"], f"move {o['ply']} (actor p{o['actor'] + 1}, enc {o['enc']}) landed")
    played += 1
# NOTE: `played` may exceed the final mc — an L1 reorg can roll moves back and the driver replays them
# (ply binding makes that safe). The invariant that matters: the FINAL on-chain log replays engine-legal.
fin = oracle(G, SEED)
print(f"  played {played} engine-legal moves (final mc {M('mc', G)}); VP: {fin.get('vp')}", flush=True)
ck("final on-chain log is engine-legal", not fin.get("corrupt") and M("mc", G) > 0)

# settle: the engine's LOSER concedes (draw -> p2 resigns anyway to close the wager)
res = fin.get("result") or 2
loser, winner = (P2, P1) if res == 1 else (P1, P2)
la, wa, lb, wb = (A2, A1, b2, b1) if res == 1 else (A1, A2, b1, b2)
call(loser, "resign", [G])
wait(lambda: M("sd", G) == 1, "conceded — settled")
ck("winner recorded", M("wr", G) == (1 if res == 1 else 2))
wait(lambda: exbal(wa) == wb + STAKE, "pot paid out")
ck("winner nets exactly one stake", exbal(wa) == wb + STAKE)
ck("loser is down exactly one stake", exbal(la) == lb - STAKE)

# cancel path
G2 = G + 1
b1 = exbal(A1)
call(P1, "open", [G2], STAKE)
wait(lambda: M("p1", G2) == A1, "second game opened")
call(P1, "cancel", [G2])
wait(lambda: M("sd", G2) == 1, "cancelled")
ck("cancel refunds the stake", exbal(A1) == b1)

print("\nSCRAPLINE E2E " + ("ALL PASS" if ok_all else "FAILED"), flush=True)
sys.exit(0 if ok_all else 1)
