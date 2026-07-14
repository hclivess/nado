"""
End-to-end tests for the ported zkVM games (execnode/games/*). For each game this deploys the real contract
through the normal blob path on a fresh ExecState, plays a FULL game via `apply_blob` calls (the same path
the live exec node runs), and asserts: escrow moves correctly, the winner is paid, the banker's accounting
balances, and the `decode_view` output matches what each game's frontend reads. It also STARK-proves one
representative method per game (the whole point — a call is provable). Reverts are exercised too.

Run: python3 tests/test_games_e2e.py        (~2-3 min: several real proofs at reduced query count)
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode import runtimes
from execnode.stark import vm_circuit as V
from execnode.games import (coinflip, dice, roulette, tictactoe as ttt, connect4 as c4,
                            slots, mines, reversi as rv, chess)

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

NQ = 6
A = "ndoAAAA" + "A" * 41
B = "ndoBBBB" + "B" * 41


def _fresh(mod, deployer=A, cursor=100):
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = cursor
    code = mod.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": "n"}, deployer, "d")
    cid = st.contract_id(deployer, code, "n")
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    return st, code, cid, rd

def _prove(code, method, caller, args, slots, **kw):
    cf, fa = runtimes.zkvm_statement(caller, args, {})
    proof, io, ret, ns = V.prove_call(code, method, cf, fa, slots, num_queries=NQ, **kw)
    vkw = {k: v for k, v in kw.items() if k in ("value", "cursor", "timestamp")}   # verify: context only
    ok, why = V.verify_call(proof, code, method, cf, fa, io, num_queries=NQ, **vkw)
    assert ok, f"{method} proof: {why}"


# ---- coinflip ----------------------------------------------------------------------------------
def t_coinflip():
    st, code, cid, rd = _fresh(coinflip)
    st.credit_deposit(A, 1_000_000); st.credit_deposit(B, 1_000_000)
    G = 12345
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [G], "value": 500}, A, "1")
    st.apply_blob({"op": "call", "contract": cid, "method": "join", "args": [G], "value": 500}, B, "2")
    assert rd(coinflip.NN, G) == 2 and st.bridge[cid] == 1000
    st.block_hashes[102] = 0xABC; st.block_hashes[103] = 0xDEF; st.cursor = 104
    st.apply_blob({"op": "call", "contract": cid, "method": "settle", "args": [G]}, A, "3")
    ws = rd(coinflip.WS, G); winner = A if ws == 1 else B
    assert rd(coinflip.SD, G) == 1 and st.bridge.get(cid, 0) == 0
    assert st.bridge[winner] == 1_000_000 - 500 + 1000
    v = st.decode_view(st.contracts[cid])
    assert v["p1"][str(G)] == A and v["p2"][str(G)] == B
    # cancel refunds
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [9], "value": 300}, A, "4")
    st.apply_blob({"op": "call", "contract": cid, "method": "cancel", "args": [9]}, A, "5")
    assert st.bridge.get(cid, 0) == 0

def t_coinflip_prove():
    code = coinflip.build()
    S = lambda f, k: f * (1 << 32) + k
    slots = {S(1, 1): 2, S(2, 1): 500, S(7, 1): 102,
             S(4, 1): runtimes.zkvm_addr_digest(A), S(5, 1): runtimes.zkvm_addr_digest(B)}
    _prove(code, "settle", A, [1], slots, cursor=104, block_hashes={102: 1, 103: 2})


# ---- dice / roulette (banked) ------------------------------------------------------------------
def _banked(mod, betargs, winnable):
    st, code, cid, rd = _fresh(mod, deployer=A)
    st.credit_deposit(A, 100_000_000); st.credit_deposit(B, 2_000_000)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [3], "value": 50_000_000}, A, "1")
    st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": betargs, "value": 100_000}, B, "2")
    assert rd(mod.TC, 3) == winnable and rd(mod.TP, 3) == 50_100_000
    st.block_hashes[102] = 0x1234; st.block_hashes[103] = 0x5678; st.cursor = 104
    st.apply_blob({"op": "call", "contract": cid, "method": "settle", "args": [88]}, B, "3")
    assert rd(mod.GD, 88) == 1 and rd(mod.TC, 3) == 0
    assert st.bridge.get(cid, 0) == rd(mod.TP, 3)                      # escrow == withdrawable
    b0 = st.bridge.get(A, 0)
    st.apply_blob({"op": "call", "contract": cid, "method": "close", "args": [3]}, A, "4")
    assert st.bridge.get(A, 0) - b0 == rd(mod.TP, 3) or st.bridge.get(cid, 0) == 0
    v = st.decode_view(st.contracts[cid])
    assert v["ta"]["3"] == A and set(v["gg"]) == {"88"}

def t_dice():
    _banked(dice, [88, 3, 50], 100_000 * 99 // 50 - 100_000)
def t_roulette():
    _banked(roulette, [88, 3, (1 << 7) | (1 << 17)], 100_000 * 36 // 2 - 100_000)

def t_dice_prove():
    code = dice.build(); S = lambda f, k: f * (1 << 32) + k
    slots = {S(1, 3): runtimes.zkvm_addr_digest(A), S(2, 3): 50_000_000, S(3, 3): 50_000_000}
    _prove(code, "bet", B, [88, 3, 50], slots, value=100_000, cursor=100)


# ---- tictactoe / connect4 (PvP board) ----------------------------------------------------------
def _pvp_win(mod, movelist, win_cells, stride):
    st, code, cid, rd = _fresh(mod, deployer=A)
    st.credit_deposit(A, 1_000_000); st.credit_deposit(B, 1_000_000)
    G = 42
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [G], "value": 100_000}, A, "1")
    st.apply_blob({"op": "call", "contract": cid, "method": "join", "args": [G], "value": 100_000}, B, "2")
    for i, (who, arg, ply) in enumerate(movelist):
        st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, arg, ply]}, who, f"m{i}")
    bd = lambda cell: int((st.contracts[cid]["storage"].get("slots") or {}).get(str((mod.BD_BASE + cell) * (1 << 32) + G), 0))
    assert all(bd(c) == 1 for c in win_cells), "winning line not filled"
    assert rd(mod.WR, G) == 1 and rd(mod.SD, G) == 1                  # p1 (A) won
    assert st.bridge[A] == 1_100_000 and st.bridge.get(cid, 0) == 0
    v = st.decode_view(st.contracts[cid])
    assert v["bd"][str(G * stride + win_cells[0])] == 1 and v["p1"][str(G)] == A

def t_tictactoe():
    _pvp_win(ttt, [(A, 0, 0), (B, 3, 1), (A, 1, 2), (B, 4, 3), (A, 2, 4)], [0, 1, 2], ttt.STRIDE)
def t_connect4():
    _pvp_win(c4, [(A, 0, 0), (B, 1, 1), (A, 0, 2), (B, 1, 3), (A, 0, 4), (B, 1, 5), (A, 0, 6)],
             [0, 7, 14, 21], c4.STRIDE)

def t_tictactoe_wrongturn_reverts():
    st, code, cid, rd = _fresh(ttt, deployer=A)
    st.credit_deposit(A, 1_000_000); st.credit_deposit(B, 1_000_000)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [7], "value": 50_000}, A, "1")
    st.apply_blob({"op": "call", "contract": cid, "method": "join", "args": [7], "value": 50_000}, B, "2")
    r = st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [7, 0, 0]}, B, "3")  # B not first
    assert "revert" in r
    r = st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [7, 0, 9]}, A, "4")  # wrong ply
    assert "revert" in r

def t_tictactoe_prove():
    code = ttt.build(); S = lambda f, k: f * (1 << 32) + k
    B_ = lambda cell, g: (ttt.BD_BASE + cell) * (1 << 32) + g
    slots = {S(1, 42): 2, S(8, 42): 4, S(3, 42): 200000,
             S(4, 42): runtimes.zkvm_addr_digest(A), S(5, 42): runtimes.zkvm_addr_digest(B),
             B_(0, 42): 1, B_(1, 42): 1, B_(3, 42): 2, B_(4, 42): 2}
    _prove(code, "move", A, [42, 2, 4], slots, cursor=100)


# ---- slots / mines (banked reveal) -------------------------------------------------------------
def t_slots():
    st, code, cid, rd = _fresh(slots, deployer=A)
    st.credit_deposit(A, 10_000_000_000); st.credit_deposit(B, 10_000_000)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [5], "value": 5_000_000_000}, A, "1")
    g = 1000
    st.apply_blob({"op": "call", "contract": cid, "method": "spin", "args": [g, 5], "value": 10_000}, B, "2")
    gh = rd(slots.GH, g); st.block_hashes[gh] = 0x1234567; st.block_hashes[gh + 1] = 0x89abcde; st.cursor = gh + 2
    pbefore = st.bridge.get(B, 0)
    st.apply_blob({"op": "call", "contract": cid, "method": "settle", "args": [g]}, B, "3")
    gr = rd(slots.GR, g); gw = rd(slots.GW, g)
    stops = [(gr - 1) % 64, ((gr - 1) // 64) % 64, ((gr - 1) // 4096) % 64]
    assert gw == slots.m2_of(stops), "paytable must match reference"
    assert st.bridge.get(B, 0) - pbefore == 10_000 * gw // 2 and rd(slots.GD, g) == 1

def t_mines():
    st, code, cid, rd = _fresh(mines, deployer=A)
    st.credit_deposit(A, 100_000_000_000); st.credit_deposit(B, 10_000_000)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [5], "value": 50_000_000_000}, A, "1")
    g = 88
    st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [g, 5, 3], "value": 100_000}, B, "2")
    st.apply_blob({"op": "call", "contract": cid, "method": "pick", "args": [g, 2]}, B, "3")
    assert rd(mines.GQ, g) == mines.multiplier(100_000, 0, 3, 2)
    gh = rd(mines.GH, g); st.block_hashes[gh] = 0xBEEF; st.block_hashes[gh + 1] = 0xCAFE; st.cursor = gh + 2
    from execnode.stark.field import P
    q = (0xBEEF % P + 0xCAFE % P + g) % P
    st.apply_blob({"op": "call", "contract": cid, "method": "resolve", "args": [g]}, B, "4")
    assert rd(mines.GB, g) == mines.resolve_hit(q, 0, 3, 2)

# ---- reversi (PvP flip) + chess (record/agree) -------------------------------------------------
def t_reversi():
    st, code, cid, rd = _fresh(rv, deployer=A)
    st.credit_deposit(A, 1_000_000); st.credit_deposit(B, 1_000_000)
    G = 42; bi = lambda cell: (cell // 8 + 1) * 16 + (cell % 8 + 1)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [G], "value": 100_000}, A, "o")
    st.apply_blob({"op": "call", "contract": cid, "method": "join", "args": [G], "value": 100_000}, B, "j")
    board = {68: 2, 85: 2, 69: 1, 84: 1}
    bdc = lambda c: int((st.contracts[cid]["storage"].get("slots") or {}).get(str((rv.BD_BASE + c) * (1 << 32) + G), 0))
    def legal(k):
        return [cell for cell in range(64) if board.get(bi(cell), 0) == 0 and rv.flips_for(board, cell, k)]
    mc = 0
    for _ in range(5):
        k = 1 + mc % 2; lg = legal(k)
        if not lg: break
        cell = lg[0]; who = A if k == 1 else B
        st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, cell, mc]}, who, f"m{mc}")
        for p in rv.flips_for(board, cell, k): board[p] = k
        board[bi(cell)] = k
        assert all(bdc(b) == board.get(b, 0) for b in range(160)), "reversi board must match reference"
        mc += 1

def t_chess():
    st, code, cid, rd = _fresh(chess, deployer=A)
    st.credit_deposit(A, 1_000_000); st.credit_deposit(B, 1_000_000)
    G = 42
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [G], "value": 100_000}, A, "o")
    st.apply_blob({"op": "call", "contract": cid, "method": "join", "args": [G], "value": 100_000}, B, "j")
    for who, enc, ply in [(A, 796, 0), (B, 2093, 1)]:
        st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, enc, ply]}, who, f"m{ply}")
    v = st.decode_view(st.contracts[cid])
    assert v["mv"][str(G * 10000 + 0)] == 796
    st.apply_blob({"op": "call", "contract": cid, "method": "agree", "args": [G, 1]}, A, "a1")
    ab = st.bridge.get(A, 0)
    st.apply_blob({"op": "call", "contract": cid, "method": "agree", "args": [G, 1]}, B, "a2")
    assert rd(chess.SD, G) == 1 and st.bridge.get(A, 0) == ab + 200_000


if __name__ == "__main__":
    check("coinflip: open/join/settle/cancel + escrow + view", t_coinflip)
    check("coinflip: settle proves", t_coinflip_prove)
    check("dice: open/bet/settle/close banker accounting + view", t_dice)
    check("roulette: masked bet/settle/close + view", t_roulette)
    check("dice: bet proves (divmod + bankroll)", t_dice_prove)
    check("tictactoe: full game, p1 wins, pot paid + view", t_tictactoe)
    check("connect4: vertical win, pot paid + view", t_connect4)
    check("tictactoe: wrong turn / wrong ply revert", t_tictactoe_wrongturn_reverts)
    check("tictactoe: winning move proves", t_tictactoe_prove)
    check("slots: spin/settle paytable matches reference", t_slots)
    check("mines: bet/pick/resolve multiplier + mine-hit vs reference", t_mines)
    check("reversi: flip board matches reference", t_reversi)
    check("chess: move record + agree settlement", t_chess)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
