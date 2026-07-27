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
import sys, json, time, urllib.request, subprocess
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
    (0, "f4a8e6155c694430fdd3c2b85b10ac51", "banked"),   # dice
    (1, "629dd7da4c8b84222abe334afe40f32c", "duel"),      # scrapline
    (2, "0b6a833377a99fc1e524af3c1d0329c0", "duel"),      # stormhold
    (3, "f082c9405c23022ca9e67fb73465757b", "banked"),    # farkle
    (4, "8975204a5017538e8387a7c2af33ebc6", "banked"),    # blackjack
    (5, "eaf6878ade7725c112089992e8f62df8", "battleship-daily"),  # battleship Daily Salvo (free hunt-&-sink, replay-verified)
    (6, "0bc996d9b087cedff92d60c6fac7b3b0", "banked"),     # slots
    (7, "7eb0aea6093def505d2f83957b2333cc", "banked"),     # mines
    (8, "cb551157945fb81aa873ab3e571254cd", "hexholm-daily"),  # hexholm daily island (free airdrop play, replay-verified)
    (9, "71ea1f3c09837a8265ebd05759ddf957", "hamster-daily"),  # hamster Daily Derby (free handicapping, replay-verified)
    (10, "aaee53d5afc487aa3af78b6913fbea80", "connect4-daily"),   # connect four Daily Drop (free solo-vs-bot, replay-verified)
    (11, "1a3c9d3ddebb2233af31cef9cb345202", "reversi-daily"),    # reversi Daily Flip (free solo-vs-bot, replay-verified)
    (12, "abbcc4340b05a77482f0cb07a5d915c5", "tictactoe-daily"),  # tic-tac-toe Daily Three (free solo-vs-bot, replay-verified)
    (13, "66cbdaae8c6c868805c8834945bacf4e", "autogame-daily"),   # autogame Daily Gauntlet (free 124-step march, replay-verified)
]
# Provable free-play boards: kind -> the node replay oracle that ranks yesterday's verified claims.
# The value is an ARGV PREFIX (cid + day are appended), so one oracle can serve several games — the three
# board games share a harness and differ only by their pure rule set, so they share an oracle too.
DAILY_VERIFY = {"hexholm-daily": ["tests/hexholm_daily_verify.mjs"],
                "hamster-daily": ["tests/hamster_daily_verify.mjs"],
                "battleship-daily": ["tests/battleship_daily_verify.mjs"],
                "tictactoe-daily": ["tests/board_daily_verify.mjs", "tictactoe"],
                "connect4-daily": ["tests/board_daily_verify.mjs", "connect4"],
                "reversi-daily": ["tests/board_daily_verify.mjs", "reversi"],
                "autogame-daily": ["tests/autogame_daily_verify.mjs"]}
SHIPS = 17

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
    elif kind in DAILY_VERIFY:
        # the PROVABLE free-play boards (doc/faucet.md + static/provable.js): rank YESTERDAY'S completed
        # UTC day; every claim is replay-VERIFIED by the node oracle before it can rank — a forged or
        # copied claim never pays. (The staked games still rank on their own page; prizes reward the
        # free airdrop play.)
        day = int(time.time()) // 86400 - 1
        try:
            out = subprocess.run(["node", *DAILY_VERIFY[kind], cid, str(day)],
                                 capture_output=True, text=True, cwd="/root/nado", timeout=600)
            rows = json.loads(out.stdout.strip().splitlines()[-1]) if out.returncode == 0 else []
        except Exception:
            rows = []
        # Pay under the UTC day this board is FOR, not the block-day it happened to be paid on. The two
        # clocks tick at the same nominal rate (14400 blocks x 6s = 86400s) but are offset, and drift apart
        # whenever real block time isn't exactly 6s — so a single UTC day's board can straddle two block-days
        # and be paid TWICE under two different idempotency keys. Keying on the ranked day makes
        # "this board has been paid" the thing the marker actually asserts.
        return [(a, s) for a, s in rows], day
    elif kind == "table":
        # N-seat table (hexholm): wr = the winning SEAT 1..4 (5 = dissolved/refunded — no ranking)
        sd, wr = sto.get("sd", {}), sto.get("wr", {})
        seats = {i: sto.get("p" + str(i), {}) for i in (1, 2, 3, 4)}
        for g in wr:
            if not sd.get(g): continue
            w = int(wr[g] or 0)
            if w not in (1, 2, 3, 4): continue
            winner = seats[w].get(g)
            if winner: score[winner] = score.get(winner, 0) + 1
    elif kind == "battleship":
        # efficiency board: fewest shots to SINK the enemy fleet (17 proven hits). Only real sink-wins count.
        sd, wr, p1, p2 = sto.get("sd", {}), sto.get("wr", {}), sto.get("p1", {}), sto.get("p2", {})
        h1, h2, fd1, fd2 = sto.get("h1", {}), sto.get("h2", {}), sto.get("fd1", {}), sto.get("fd2", {})
        best = {}
        for g in wr:
            if not sd.get(g): continue
            w = wr[g]
            if w not in (1, 2): continue
            if int((h1 if w == 1 else h2).get(g, 0) or 0) < SHIPS: continue   # must have sunk the fleet
            winner = (p1 if w == 1 else p2).get(g)
            if not winner: continue
            fmap = fd1 if w == 1 else fd2
            shots = sum(1 for c in range(100) if fmap.get(str(int(g) * 100 + c)))
            if shots < SHIPS: continue
            if winner not in best or shots < best[winner]: best[winner] = shots
        return sorted(best.items(), key=lambda kv: kv[1]), None   # [(addr, shots)] ascending — fewest shots ranks first
    else:  # banked: a won, settled seat
        gd, gw, ga = sto.get("gd", {}), sto.get("gw", {}), sto.get("ga", {})
        for s in gd:
            if gd.get(s) and gw.get(s) and ga.get(s): score[ga[s]] = score.get(ga[s], 0) + 1
    return sorted(score.items(), key=lambda kv: -kv[1]), None   # [(addr, wins)] descending; no day override

def main():
    keys = load_keys()
    ex_cur = int(j(EX + "/exec/root").get("cursor", tip())) if False else tip()
    day = tip() // DAY_BLOCKS
    bal = faucet_balance()
    print(f"faucet balance {bal} · rewarding day {day}", flush=True)
    total_paid = 0
    for idx, cid, kind in GAMES:
        board, board_day = leaderboard(cid, kind)
        day_key = board_day if board_day is not None else day   # per-day boards key on the day they rank
        if not board:
            print(f"  game {idx}: no leaderboard yet", flush=True); continue
        print(f"  game {idx} ({kind}, day {day_key}) top: " + ", ".join(f"{a[:10]}…={w}" for a, w in board[:5]), flush=True)
        for rank, (addr, wins) in enumerate(board[:len(SHARES)], start=1):
            amt = int(BUDGET * SHARES[rank - 1])
            if amt <= 0 or total_paid + amt > bal:
                print(f"    rank {rank}: skip (faucet can't cover)", flush=True); continue
            r = post(construct_blob_tx(keys, {"op": "call", "contract": "faucet", "method": "reward",
                                              "args": [idx, day_key, rank, addr, amt]}, tip() + 25, MIN_TX_FEE))
            ok = bool(r.get("result"))
            print(f"    rank {rank} {addr[:12]}… ({wins} wins) → {amt}: "
                  f"{'submitted (reverts on-chain if this placement was already paid)' if ok else r.get('message','?')[:40]}", flush=True)
            if ok: total_paid += amt
            time.sleep(0.5)
    print(f"submitted rewards totalling {total_paid} raw", flush=True)

if __name__ == "__main__":
    main()
