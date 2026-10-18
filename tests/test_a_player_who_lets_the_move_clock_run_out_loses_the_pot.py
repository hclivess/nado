"""A player who lets the move clock run out loses the pot to the one who was waiting (tictactoe, connect4, reversi —
the shared abort in execnode/games/tictactoe.py; audit 2026-09-24 #26, confirmed 2026-10-18).

abort used to refund BOTH stakes once the clock ran out, so a player about to lose simply stopped moving and got their
stake back. Now the pot goes to whoever was waiting — the player whose turn it was NOT, by the move count's parity, the
same rule move enforces (a reversi pass counts as a move) — and wr names them, exactly as a resign would. Pinned on the
real ExecState with the deployed contracts, for each game: p2 stalls after p1's move -> p1 takes the pot; p1 stalls on
the first move -> p2 takes it; the clock not yet run out -> abort refused; anyone may settle, the payout never moves.

Run: python3 tests/test_a_player_who_lets_the_move_clock_run_out_loses_the_pot.py
"""
import _harness
HOME = _harness.isolate("nado-test-move-clock-")
import os
os.environ["NADO_ALLOW_PYTHON_KERNELS"] = "1"
import tempfile
from execnode.state import ExecState
from execnode.games import tictactoe, connect4, reversi

T = _harness.Report()
A, B, C = "ndoAAAA" + "A" * 41, "ndoBBBB" + "B" * 41, "ndoCCCC" + "C" * 41
STAKE = 50_000
FIRST = {"tictactoe": 4, "connect4": 3, "reversi": reversi.PASS}     # a legal first move for p1 in each game


def fresh(mod):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=HOME), "s.json")); st.cursor = 100
    code = mod.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    for who in (A, B, C): st.credit_deposit(who, 1_000_000)
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    call = lambda who, n, method, args, value=0: st.apply_blob(
        {"op": "call", "contract": cid, "method": method, "args": args, **({"value": value} if value else {})}, who, n)
    return st, rd, call


for name, mod in (("tictactoe", tictactoe), ("connect4", connect4), ("reversi", reversi)):
    # p1 moves, then p2 stalls -> p1 takes the pot
    st, rd, call = fresh(mod)
    call(A, "1", "open", [7], STAKE); call(B, "2", "join", [7], STAKE)
    r = call(A, "3", "move", [7, FIRST[name], 0])
    T.check(f"{name}: setup — p1's first move applies", r.endswith("-> ok"), r)
    early = call(C, "4", "abort", [7])
    T.check(f"{name}: abort is refused while the clock still runs", "revert" in early and rd(tictactoe.SD, 7) == 0, early)
    st.cursor = 100 + tictactoe.MOVE_CLOCK + 5
    a0, b0 = st.bridge[A], st.bridge[B]
    r = call(C, "5", "abort", [7])                       # a third party settles the dead game
    T.check(f"{name}: p2 stalled -> p1 (who was waiting) takes the whole pot", r.endswith("-> ok")
            and st.bridge[A] == a0 + 2 * STAKE and st.bridge[B] == b0, (r, st.bridge[A] - a0, st.bridge[B] - b0))
    T.check(f"{name}: ...the game is settled with p1 the winner", rd(tictactoe.SD, 7) == 1 and rd(tictactoe.WR, 7) == 1,
            (rd(tictactoe.SD, 7), rd(tictactoe.WR, 7)))
    # p1 never moves -> p2 takes the pot
    st, rd, call = fresh(mod)
    call(A, "1", "open", [8], STAKE); call(B, "2", "join", [8], STAKE)
    st.cursor = 100 + tictactoe.MOVE_CLOCK + 5
    a0, b0 = st.bridge[A], st.bridge[B]
    r = call(A, "3", "abort", [8])                       # even the staller calling it pays the opponent
    T.check(f"{name}: p1 stalled on the first move -> p2 takes the pot, whoever calls abort",
            r.endswith("-> ok") and st.bridge[B] == b0 + 2 * STAKE and st.bridge[A] == a0 and rd(tictactoe.WR, 8) == 2,
            (r, st.bridge[A] - a0, st.bridge[B] - b0, rd(tictactoe.WR, 8)))
T.done("ALL PASS — a player who lets the move clock run out loses the pot")
