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
    (0, "28da34f204923d91f6486edfa4504427", "banked"),   # dice
    (1, "d624fe09b631773a607ddfaecb9e5191", "duel"),      # scrapline
    (2, "9fcfa11f570cb3b2d720e3db71c602d8", "duel"),      # stormhold
    (3, "92d2e33c094528aa4cf13fd531e1bba8", "banked"),    # farkle
    (4, "7d3d1f539b9dc228c359a52efc460c49", "banked"),    # blackjack
    (5, "1751614b80de7257db8821c611fc5d40", "battleship-daily"),  # battleship Daily Salvo (free hunt-&-sink, replay-verified)
    (6, "13b82a08e3278cc56f50c14b092804d4", "banked"),     # slots
    (7, "31691dd8ff6ed950aab4440278d38351", "banked"),     # mines
    (8, "00cc28b5073fe6f26ced661dc5347c6e", "hexholm-daily"),  # hexholm daily island (free airdrop play, replay-verified)
    (9, "3d9b9eeb0c7116f1461bc2b6cadcfe7a", "hamster-daily"),  # hamster Daily Derby (free handicapping, replay-verified)
    (10, "bd455ca1756f1fdfb37675b3abb0e6c5", "connect4-daily"),   # connect four Daily Drop (free solo-vs-bot, replay-verified)
    (11, "c3e4ec9b40aa6784fcfeac6aa26eb75f", "reversi-daily"),    # reversi Daily Flip (free solo-vs-bot, replay-verified)
    (12, "532ca2459a8685d614e9a2af5754bb7f", "tictactoe-daily"),  # tic-tac-toe Daily Three (free solo-vs-bot, replay-verified)
    (13, "f6ccb08e979e1989516f35c4bfb7dea1", "autogame-daily"),   # autogame Daily Gauntlet (free 124-step march, replay-verified)
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

def j(u): return json.load(urllib.request.urlopen(u, timeout=12))  # nosec B310 # operator CLI: the operator's own node URL (literal http:// default or their flag), never peer input
def post(tx):
    r = urllib.request.Request(L1 + "/submit_transaction", data=json.dumps(tx).encode(), headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=15))  # nosec B310 # operator CLI: the operator's own node URL (literal http:// default or their flag), never peer input
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
