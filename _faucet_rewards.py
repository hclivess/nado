#!/usr/bin/env python3
"""
_faucet_rewards.py — the LEADERBOARD PRIZE DISTRIBUTOR. The faucet is the prize bank: this operator bot
reads each enrolled game's leaderboard from on-chain state and pays the top finishers from the faucet
balance via faucet.reward(idx, day, rank, addr, amount). Idempotent — the contract lets a (game, day,
rank) be paid at most once, so re-running is safe; the payout is auditable (anyone can recompute the same
board and check the same addresses were paid).

Leaderboard = WINS (a uniform, on-chain-settled metric across both game shapes):
  · duel games (scrapline, stormhold): a settled game's winner (wr = 1→p1, 2→p2)
  · banked games (dice, farkle, blackjack): a settled seat that WON (gw truthy), credited to its player (ga)

Payout: a per-game daily budget split by rank (Webgame's Odměny taper). Run daily (cron / a NADO routine).
"""
import sys, json, time, urllib.request
sys.path.insert(0, "/root/nado")
from ops.key_ops import load_keys
from ops.transaction_ops import construct_blob_tx
from protocol import MIN_TX_FEE

L1 = "http://127.0.0.1:9173"; EX = "http://127.0.0.1:9273"
DAY_BLOCKS = 14400
SHARES = [0.40, 0.25, 0.15, 0.12, 0.08]        # rank 1..5 shares of a game's daily prize budget
BUDGET = 1_000_000_000                          # 0.1 NADO per game per day (tune to the faucet's inflow)

# idx → (cid, kind); mirrors faucet.js FAUCET_GAMES + the live game cids
GAMES = [
    (0, "044be49f754c62fb7222d32ba84db81e", "banked"),   # dice
    (1, "634dc7c3eda3fea16fddfaca47a0c8aa", "duel"),      # scrapline
    (2, "fce697844f9b2b043abcaf4403953f9f", "duel"),      # stormhold
    (3, "b56dd48000707369be1630e41bfb038d", "banked"),    # farkle
    (4, "3d775ee563baae7c20ec39596fcd4f28", "banked"),    # blackjack
]

def j(u): return json.load(urllib.request.urlopen(u, timeout=12))
def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=15))
def tip(): return j(L1 + "/get_latest_block")["block_number"]
def view(cid): return j(EX + f"/exec/contract?ns=default&cid={cid}&provisional=1").get("storage", {})
def faucet_balance(): return int(j(EX + "/exec/bridge?ns=default&provisional=1").get("balances", {}).get("faucet", 0))

def leaderboard(cid, kind):
    sto = view(cid); score = {}
    if kind == "duel":
        sd, wr, p1, p2 = sto.get("sd", {}), sto.get("wr", {}), sto.get("p1", {}), sto.get("p2", {})
        for g in wr:
            if not sd.get(g): continue
            w = wr[g]; winner = p1.get(g) if w == 1 else p2.get(g) if w == 2 else None
            if winner: score[winner] = score.get(winner, 0) + 1
    else:  # banked: a won, settled seat
        gd, gw, ga = sto.get("gd", {}), sto.get("gw", {}), sto.get("ga", {})
        for s in gd:
            if gd.get(s) and gw.get(s) and ga.get(s): score[ga[s]] = score.get(ga[s], 0) + 1
    return sorted(score.items(), key=lambda kv: -kv[1])   # [(addr, wins)] descending

def main():
    keys = load_keys()
    ex_cur = int(j(EX + "/exec/root").get("cursor", tip())) if False else tip()
    day = tip() // DAY_BLOCKS
    bal = faucet_balance()
    print(f"faucet balance {bal} · rewarding day {day}", flush=True)
    total_paid = 0
    for idx, cid, kind in GAMES:
        board = leaderboard(cid, kind)
        if not board:
            print(f"  game {idx}: no leaderboard yet", flush=True); continue
        print(f"  game {idx} ({kind}) top: " + ", ".join(f"{a[:10]}…={w}" for a, w in board[:5]), flush=True)
        for rank, (addr, wins) in enumerate(board[:len(SHARES)], start=1):
            amt = int(BUDGET * SHARES[rank - 1])
            if amt <= 0 or total_paid + amt > bal:
                print(f"    rank {rank}: skip (faucet can't cover)", flush=True); continue
            r = post(construct_blob_tx(keys, {"op": "call", "contract": "faucet", "method": "reward",
                                              "args": [idx, day, rank, addr, amt]}, tip() + 25, MIN_TX_FEE))
            ok = bool(r.get("result"))
            print(f"    rank {rank} {addr[:12]}… ({wins} wins) → {amt}: {'sent' if ok else r.get('message','?')[:40]}", flush=True)
            if ok: total_paid += amt
            time.sleep(0.5)
    print(f"submitted rewards totalling {total_paid} raw", flush=True)

if __name__ == "__main__":
    main()
