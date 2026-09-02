#!/usr/bin/env python3
# _pool_e2e.py — LIVE smoke test of the Pool contract, end to end on the real chain.
#
# Three frames, in order:
#   1. STAKED — the node key opens with a stake, a freshly generated funded key joins, and the two play
#      REAL engine-legal shots (each one computed by tests/pool_next_move.mjs, which replays the on-chain
#      log through the browser's actual physics against the actual pinned rack seed) until the 8 goes
#      down or the shot budget runs out. Then the engine's LOSER concedes and the pot moves.
#   2. FREE — the same lifecycle with value 0 on both sides. Pool's open() has no `value > 0` require, so
#      this is the path that proves a stakeless frame really does escrow, log, settle and refund nothing.
#   3. CANCEL — an unjoined frame is cancelled and the stake comes back.
import sys, json, time, urllib.request, random, subprocess
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from signatures import generate_keydict
from ops.transaction_ops import (construct_blob_tx, construct_bridge_deposit_tx,
                                 draft_transaction, create_transaction)
from config import get_timestamp_seconds
from protocol import MIN_TX_FEE

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
CID = "685a84e20bfd86c5bfc767ecc1ccaf0f"
NADO = 10**10
STAKE = NADO // 100
SHOT_BUDGET = int(sys.argv[1]) if len(sys.argv) > 1 else 40
ok_all = True


def ck(n, c):
    global ok_all
    print(("  PASS " if c else "  FAIL ") + n, flush=True)
    if not c: ok_all = False


def j(u): return json.load(urllib.request.urlopen(u, timeout=8))


def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(),
                               headers={"Content-Type": "application/json"})
    try: return json.load(urllib.request.urlopen(r, timeout=12))
    except urllib.error.HTTPError as e: return {"result": False, "message": e.read().decode()[:200]}


def tip(): return j(L1 + "/get_latest_block")["block_number"]


def l1bal(a):
    try: return int(j(L1 + f"/get_account?address={a}").get("balance", 0))
    except Exception: return 0


def exbal(a):
    try: return int(j(EX + "/exec/bridge?ns=default&provisional=1").get("balances", {}).get(a, 0))
    except Exception as e: raise SystemExit(f"exec balance read failed ({e}) — refusing to move funds blind")


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
    r = subprocess.run(["node", "tests/pool_next_move.mjs", str(g), CID, str(seed)],
                       capture_output=True, text=True, cwd="/root/nado", timeout=120)
    if r.returncode != 0: sys.exit("oracle failed: " + r.stderr[-400:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def play_frame(g, seed, p1, p2, budget):
    """Drive a joined frame with engine-legal shots. Returns the oracle's final verdict."""
    played, stall = 0, 0
    while played < budget:
        o = oracle(g, seed)
        if o.get("waiting") or o.get("blocked"):
            stall += 1
            if stall > 80: sys.exit("stuck waiting: " + json.dumps(o))
            time.sleep(4); continue
        if o.get("corrupt"): sys.exit("ENGINE FLAGGED CORRUPT: " + o["why"])
        if o.get("over"): break
        stall = 0
        kd = p1 if o["actor"] == 0 else p2
        tag = ("8-ball " if o.get("onEight") else "") + ("[ball in hand] " if o.get("inHand") else "")
        call(kd, "move", [g, o["enc"], o["ply"]])
        wait(lambda: M("mc", g) > o["ply"],
             f"shot {o['ply']} p{o['actor'] + 1} {tag}{o['group']} left {o['left']}")
        played += 1
    fin = oracle(g, seed)
    print(f"  played {played} engine-legal shots (final mc {M('mc', g)}); "
          f"{'8-BALL — frame over, winner p%d' % fin['result'] if fin.get('over') else 'budget reached'}", flush=True)
    return fin


P1 = load_keys(); A1 = P1["address"]
print("pool E2E — p1 (node key):", A1[:16] + "…", flush=True)
if exbal(A1) < 4 * NADO:
    post(construct_bridge_deposit_tx(P1, 8 * NADO, tip() + 25, MIN_TX_FEE))
    wait(lambda: exbal(A1) >= 4 * NADO, "p1 bridge deposit landed")
P2 = generate_keydict(); A2 = P2["address"]
print("pool E2E — p2 (fresh key):", A2[:16] + "…", flush=True)
transfer(P1, A2, 4 * NADO)
wait(lambda: l1bal(A2) >= 2 * NADO, "p2 funded on L1")
post(construct_bridge_deposit_tx(P2, 2 * NADO, tip() + 25, MIN_TX_FEE))
wait(lambda: exbal(A2) >= NADO, "p2 bridge deposit landed")

# ---- frame 1: STAKED -----------------------------------------------------------------------------
G = random.randrange(10**8, 10**9)
SEED = random.randrange(1, 10**6)
print(f"\n== STAKED frame #{G} (bot seed {SEED}) ==", flush=True)
b1, b2 = exbal(A1), exbal(A2)
call(P1, "open", [G, 0], STAKE)
wait(lambda: M("p1", G) == A1, "opened + escrowed")
call(P2, "join", [G], STAKE)
wait(lambda: M("nn", G) == 2, "joined — pot is 2 stakes")
ck("pot escrowed", M("pt", G) == 2 * STAKE)
ck("rack seed height pinned", M("kh", G) > 0)

fin = play_frame(G, SEED, P1, P2, SHOT_BUDGET)
ck("final on-chain log replays engine-legal", not fin.get("corrupt") and M("mc", G) > 0)

res = fin.get("result") or 2
loser = P2 if res == 1 else P1
la, wa, lb, wb = (A2, A1, b2, b1) if res == 1 else (A1, A2, b1, b2)
call(loser, "resign", [G])
wait(lambda: M("sd", G) == 1, "conceded — settled")
ck("winner recorded", M("wr", G) == (1 if res == 1 else 2))
wait(lambda: exbal(wa) == wb + STAKE, "pot paid out")
ck("winner nets exactly one stake", exbal(wa) == wb + STAKE)
ck("loser is down exactly one stake", exbal(la) == lb - STAKE)

# ---- frame 2: FREE (no stake at all) -------------------------------------------------------------
GF = G + 1
print(f"\n== FREE frame #{GF} — value 0 on both sides ==", flush=True)
f1, f2 = exbal(A1), exbal(A2)
call(P1, "open", [GF, 0], 0)
wait(lambda: M("p1", GF) == A1, "free frame opened")
ck("a free frame has no stake", M("st", GF) == 0 and M("pt", GF) == 0)
call(P2, "join", [GF], 0)
wait(lambda: M("nn", GF) == 2, "free frame joined")
ck("rack seed pinned on the free frame too", M("kh", GF) > 0)
finf = play_frame(GF, SEED + 1, P1, P2, min(8, SHOT_BUDGET))
ck("free frame's log replays engine-legal", not finf.get("corrupt") and M("mc", GF) > 0)
call(P2, "resign", [GF])
wait(lambda: M("sd", GF) == 1, "free frame conceded — settled")
ck("free frame settles to the opponent", M("wr", GF) == 1)
ck("no money moved in a free frame", exbal(A1) == f1 and exbal(A2) == f2)

# ---- frame 3: CANCEL -----------------------------------------------------------------------------
G2 = G + 2
print(f"\n== CANCEL frame #{G2} ==", flush=True)
c1 = exbal(A1)
call(P1, "open", [G2, 0], STAKE)
wait(lambda: M("p1", G2) == A1, "third frame opened")
call(P1, "cancel", [G2])
wait(lambda: M("sd", G2) == 1, "cancelled")
ck("cancel refunds the stake", exbal(A1) == c1)

print("\nPOOL E2E " + ("ALL PASS" if ok_all else "FAILED"), flush=True)
sys.exit(0 if ok_all else 1)
