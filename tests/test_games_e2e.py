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
                            slots, mines, reversi as rv, chess, farkle as fk, blackjack as bj, bet as bt,
                            battleship as bs, pets as ptz, holdem as hd, stormhold as sh, scrapline as sc)

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
    # tc reserves the FULL payout (solvency fix): pot must cover every open bet's max win, not just the net.
    _banked(dice, [88, 3, 50], 100_000 * 99 // 50)
def t_roulette():
    _banked(roulette, [88, 3, (1 << 7) | (1 << 17)], 100_000 * 36 // 2)

def t_dice_overbet_reverts():
    # After a bet reserves its full payout, a second bet whose payout would push tc past the pot MUST revert
    # (the "bet above balance" the contract now rejects). And close with an open bet (tc>0) must revert.
    st, code, cid, rd = _fresh(dice, deployer=A)
    st.credit_deposit(A, 100_000_000)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [3], "value": 70}, A, "1")
    r = st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [88, 3, 25], "value": 20}, A, "2")
    assert "revert" not in r and rd(dice.TP, 3) == 90 and rd(dice.TC, 3) == 20 * 99 // 25   # full payout 79 reserved
    r2 = st.apply_blob({"op": "call", "contract": cid, "method": "bet", "args": [89, 3, 25], "value": 20}, A, "3")
    assert "revert" in r2, "over-bet past the pot must revert"                 # tc 158 > tp 110
    assert rd(dice.TP, 3) == 90 and rd(dice.TC, 3) == 79                        # state unchanged by the reverted bet
    rc = st.apply_blob({"op": "call", "contract": cid, "method": "close", "args": [3]}, A, "4")
    assert "revert" in rc, "close with an open bet (tc>0) must revert"

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


def t_stormhold():
    # chess-model escrow + move log, PLUS: free actor order (engine referees turns), per-move seed heights
    # mh = (cursor+GAP)*4+side, and the join-time kingdom seed height kh — the shuffle randomness anchors.
    st, code, cid, rd = _fresh(sh, deployer=A)
    st.credit_deposit(A, 1_000_000); st.credit_deposit(B, 1_000_000)
    G = 77
    MASK = 0b1010101010101010101 & ((1 << 26) - 1)   # any 26-bit cfg word — contract stores it verbatim
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [G, MASK], "value": 100_000}, A, "o")
    assert rd(sh.CFG, G) == MASK, "creator's kingdom-mask cfg word stored at open"
    st.cursor = 150
    st.apply_blob({"op": "call", "contract": cid, "method": "join", "args": [G], "value": 100_000}, B, "j")
    assert rd(sh.KH, G) == 150 + sh.GAP, "kingdom seed height pinned at join"
    assert rd(sh.DL, G) == 150 + sh.MOVE_CLOCK
    # moves in a NON-alternating order (A, A, B, A) — Dominion turns are many moves + interposed decisions
    st.cursor = 151
    st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, 17, 0]}, A, "m0")
    st.cursor = 153
    st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, 33, 1]}, A, "m1")
    st.cursor = 155
    st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, 85, 2]}, B, "m2")
    st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, 4, 3]}, A, "m3")
    v = st.decode_view(st.contracts[cid])
    assert v["mv"][str(G * 10000 + 0)] == 17 and v["mv"][str(G * 10000 + 2)] == 85
    assert v["mh"][str(G * 10000 + 0)] == (151 + sh.GAP) * 4 + 1     # A = side 1
    assert v["mh"][str(G * 10000 + 2)] == (155 + sh.GAP) * 4 + 2     # B = side 2
    assert rd(sh.MC, G) == 4 and rd(sh.DL, G) == 155 + sh.MOVE_CLOCK
    # reverts: outsider move, wrong ply, enc 0
    C = "ndoCCCC" + "C" * 41
    assert "revert" in st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, 9, 4]}, C, "x1")
    assert "revert" in st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, 9, 7]}, A, "x2")
    assert "revert" in st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, 0, 4]}, A, "x3")
    # settle: mutual agree on p2 win pays B the pot
    st.apply_blob({"op": "call", "contract": cid, "method": "agree", "args": [G, 2]}, A, "a1")
    bb = st.bridge.get(B, 0)
    st.apply_blob({"op": "call", "contract": cid, "method": "agree", "args": [G, 2]}, B, "a2")
    assert rd(sh.SD, G) == 1 and st.bridge.get(B, 0) == bb + 200_000 and st.bridge.get(cid, 0) == 0
    # a second game: resign path + move-log cap sanity
    G2 = 78
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [G2], "value": 50_000}, A, "o2")
    st.apply_blob({"op": "call", "contract": cid, "method": "join", "args": [G2], "value": 50_000}, B, "j2")
    ab = st.bridge.get(A, 0)
    st.apply_blob({"op": "call", "contract": cid, "method": "resign", "args": [G2]}, B, "r2")
    assert rd(sh.WR, G2) == 1 and st.bridge.get(A, 0) == ab + 100_000
    # back-compat: a cfg-less open (old clients / rematch of a pre-upgrade game) reads cfg = 0 (random)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [790], "value": 100_000}, A, "o790")
    assert rd(sh.CFG, 790) == 0, "cfg-less open must default to 0 (random kingdom)"
    assert rd(sh.C1, 790) == 0, "commit-less open must default to 0 (open-hand)"

    # HIDDEN HANDS: commits stored at open/join; reveal requires alghash(x) == commit; a wrong x reverts
    from execnode.stark import alghash
    XA, XB = 123456789, 987654321
    ca, cb = alghash.hashn([XA]), alghash.hashn([XB])
    G3 = 79
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [G3, 0, ca], "value": 10_000}, A, "oh")
    assert rd(sh.C1, G3) == ca, "opener commit stored"
    st.apply_blob({"op": "call", "contract": cid, "method": "join", "args": [G3, cb], "value": 10_000}, B, "jh")
    assert rd(sh.C2, G3) == cb, "joiner commit stored"
    assert "revert" in st.apply_blob({"op": "call", "contract": cid, "method": "reveal", "args": [G3, XA + 1]}, A, "rv0")
    assert "revert" in st.apply_blob({"op": "call", "contract": cid, "method": "reveal", "args": [G3, XA]}, C, "rv1")
    st.apply_blob({"op": "call", "contract": cid, "method": "reveal", "args": [G3, XA]}, A, "rv2")
    st.apply_blob({"op": "call", "contract": cid, "method": "reveal", "args": [G3, XB]}, B, "rv3")
    assert rd(sh.R1H, G3) * 2**32 + rd(sh.R1L, G3) == XA, "p1 reveal stored (hi/lo)"
    assert rd(sh.R2H, G3) * 2**32 + rd(sh.R2L, G3) == XB, "p2 reveal stored (hi/lo)"
    # an OPEN-HAND game (commit 0) cannot reveal (nothing committed)
    assert "revert" in st.apply_blob({"op": "call", "contract": cid, "method": "reveal", "args": [G2, 5]}, A, "rv4")


def t_faucet():
    # the fixed-name system contract (doc/faucet.md): donations credited by the exec node, operator-
    # curated registry, PoW-gated once-per-(address,game) claims under per-window budgets, solvent PAY.
    from execnode.games import faucet as fc
    from execnode.stark import alghash
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = 100_000
    code = fc.build()
    OP = fc.OPERATOR
    r = st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": fc.ABI, "nonce": "f", "at": "faucet"}, OP, "d")
    assert "deploy faucet" in r, r
    assert "not authorized" in st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "nonce": "g", "at": "faucet"}, A, "d2")
    st.credit_deposit("faucet", 1_000_000)                    # what the L1 `faucet` reserved tx mirrors
    EASY = 1 << 63
    assert "ok" in st.apply_blob({"op": "call", "contract": "faucet", "method": "set_game", "args": [0, 1234, 500, 2, EASY]}, OP, "s0")
    assert "revert" in st.apply_blob({"op": "call", "contract": "faucet", "method": "set_game", "args": [0, 1, 1, 1, 1]}, A, "s1")
    slots = st.contracts["faucet"]["storage"]["slots"]
    assert int(slots.get("0", 0)) == 1, "gcnt"
    def grind(addr, idx, easy=EASY, want_below=True):
        d = runtimes.zkvm_addr_digest(addr); n = 0
        while (alghash.hashn([d, idx, n]) < easy) != want_below: n += 1
        return n
    n1 = grind(A, 0)
    assert "paid=500" in st.apply_blob({"op": "call", "contract": "faucet", "method": "claim", "args": [0, n1]}, A, "c1")
    assert st.bridge.get(A) == 500 and st.bridge.get("faucet") == 999_500
    assert "revert" in st.apply_blob({"op": "call", "contract": "faucet", "method": "claim", "args": [0, n1]}, A, "c2"), "double claim"
    assert "revert" in st.apply_blob({"op": "call", "contract": "faucet", "method": "claim", "args": [0, grind(B, 0, want_below=False)]}, B, "c3"), "bad PoW"
    assert "paid=500" in st.apply_blob({"op": "call", "contract": "faucet", "method": "claim", "args": [0, grind(B, 0)]}, B, "c4")
    C2 = "ndoCCCC" + "C" * 41
    assert "revert" in st.apply_blob({"op": "call", "contract": "faucet", "method": "claim", "args": [0, grind(C2, 0)]}, C2, "c5"), "window cap"
    st.cursor += 14_400
    assert "paid=500" in st.apply_blob({"op": "call", "contract": "faucet", "method": "claim", "args": [0, grind(C2, 0)]}, C2, "c6"), "window reset"
    # pause + underfunded fail closed
    assert "ok" in st.apply_blob({"op": "call", "contract": "faucet", "method": "set_game", "args": [0, 1234, 0, 2, EASY]}, OP, "s2")
    D2 = "ndoDDDD" + "D" * 41
    assert "revert" in st.apply_blob({"op": "call", "contract": "faucet", "method": "claim", "args": [0, grind(D2, 0)]}, D2, "c7"), "paused"
    assert "ok" in st.apply_blob({"op": "call", "contract": "faucet", "method": "set_game", "args": [1, 99, 10 ** 9, 2, EASY]}, OP, "s3")
    assert "revert" in st.apply_blob({"op": "call", "contract": "faucet", "method": "claim", "args": [1, grind(D2, 1)]}, D2, "c8"), "underfunded"


def t_faucet_claim_proves():
    from execnode.games import faucet as fc
    from execnode.stark import alghash
    code = fc.build()
    EASY = 1 << 63
    d = runtimes.zkvm_addr_digest(A); n = 0
    while alghash.hashn([d, 0, n]) >= EASY: n += 1
    S = lambda f, k: f * (1 << 32) + k
    slots = {S(fc.GGRANT, 0): 500, S(fc.GCAP, 0): 5, S(fc.GPOW, 0): EASY}
    _prove(code, "claim", A, [0, n], slots, cursor=100_000)


def t_scrapline():
    # the same duel contract as stormhold with a tighter move-log cap — assert the shared paths + the cap
    st, code, cid, rd = _fresh(sc, deployer=A)
    st.credit_deposit(A, 1_000_000); st.credit_deposit(B, 1_000_000)
    G = 99
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [G], "value": 40_000}, A, "o")
    st.cursor = 200
    st.apply_blob({"op": "call", "contract": cid, "method": "join", "args": [G], "value": 40_000}, B, "j")
    assert rd(sc.KH, G) == 200 + sc.GAP
    st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, 17, 0]}, B, "m0")   # joiner may move first
    st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, 33, 1]}, A, "m1")
    v = st.decode_view(st.contracts[cid])
    assert v["mv"][str(G * 10000 + 0)] == 17 and v["mh"][str(G * 10000 + 0)] % 4 == 2
    # the cap: a move at ply >= MAXMOVES reverts even with the right ply
    st.contracts[cid]["storage"]["slots"][str(sc.MC * (1 << 32) + G)] = sc.MAXMOVES
    r = st.apply_blob({"op": "call", "contract": cid, "method": "move", "args": [G, 5, sc.MAXMOVES]}, A, "mx")
    assert "revert" in r
    st.contracts[cid]["storage"]["slots"][str(sc.MC * (1 << 32) + G)] = 2
    ab = st.bridge.get(A, 0)
    st.apply_blob({"op": "call", "contract": cid, "method": "agree", "args": [G, 1]}, A, "a1")
    st.apply_blob({"op": "call", "contract": cid, "method": "agree", "args": [G, 1]}, B, "a2")
    assert rd(sc.SD, G) == 1 and st.bridge.get(A, 0) == ab + 80_000
    # solo daily highscore posts: append log + day window vs chain time + bounds
    st.block_ts = 20650 * 86400 + 5000
    st.apply_blob({"op": "call", "contract": cid, "method": "post",
                   "args": [20650, 7, 12, 111, 222, 0, 0, 0, 0, 0, 5]}, A, "p0")
    st.apply_blob({"op": "call", "contract": cid, "method": "post",
                   "args": [20649, 3, 4, 99, 0, 0, 0, 0, 0, 0, 0]}, B, "p1")            # yesterday: inside ±1 window
    v = st.decode_view(st.contracts[cid])
    assert v["eday"]["0"] == 20650 and v["escore"]["0"] == 7 and v["en"]["0"] == 12 and v["ea0"]["0"] == 111
    assert v["ea7"]["0"] == 5
    assert v["eaddr"]["0"] == A and v["eaddr"]["1"] == B and v["eday"]["1"] == 20649
    assert "revert" in st.apply_blob({"op": "call", "contract": cid, "method": "post",
                                      "args": [20600, 7, 12, 1, 0, 0, 0, 0, 0, 0, 0]}, A, "px1")   # stale day
    assert "revert" in st.apply_blob({"op": "call", "contract": cid, "method": "post",
                                      "args": [20650, 7, 99, 1, 0, 0, 0, 0, 0, 0, 0]}, A, "px2")   # n > cap
    assert "revert" in st.apply_blob({"op": "call", "contract": cid, "method": "post",
                                      "args": [20650, 7, 0, 1, 0, 0, 0, 0, 0, 0, 0]}, A, "px3")    # n = 0


def t_stormhold_move_proves():
    code = sh.build(); S = lambda f, k: f * (1 << 32) + k
    slots = {S(sh.NN, 77): 2, S(sh.MC, 77): 3, S(sh.P1, 77): runtimes.zkvm_addr_digest(A),
             S(sh.P2, 77): runtimes.zkvm_addr_digest(B)}
    _prove(code, "move", B, [77, 12345, 3], slots, cursor=200)


def t_farkle():
    st, code, cid, rd = _fresh(fk, deployer=A)
    st.credit_deposit(A, 50_000_000)
    pack = lambda k: sum(k[f] << (3 * (f - 1)) for f in range(1, 7))
    T, G = 5, 100
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [T, G], "value": 50_000}, A, "o")
    import random as _r
    _r.seed(3)
    n = 0
    for trial in range(20):
        if rd(fk.GFIN, G):
            break
        st.cursor = 200 + trial * 40
        st.apply_blob({"op": "call", "contract": cid, "method": "roll", "args": [G]}, A, "r")
        grh = rd(fk.GRH, G); grn = rd(fk.GRN, G); gdl = rd(fk.GDL, G)
        if grh == 0:
            continue
        h0 = _r.randint(1, 2**60); h1 = _r.randint(1, 2**60)
        st.block_hashes[grh] = h0; st.block_hashes[grh + 1] = h1; st.cursor = grh + 2
        dice = fk.roll_dice(h0, h1, G, grn, gdl); rolled = {f: sum(1 for d in dice if d == f) for f in range(1, 7)}
        straight = gdl == 6 and all(rolled[f] == 1 for f in range(1, 7))
        is_f = fk.score_counts(rolled, straight) == 0
        keep = {f: (rolled[f] if f in (1, 5) or rolled[f] >= 3 else 0) for f in range(1, 7)}
        gts_b = rd(fk.GTS, G)
        st.apply_blob({"op": "call", "contract": cid, "method": "hold", "args": [G, pack(keep), 1]}, A, f"h{trial}")
        n += 1
        if not is_f:
            ks = fk.score_counts(keep, gdl == 6 and all(keep[f] == 1 for f in range(1, 7)))
            assert rd(fk.GTS, G) == gts_b + ks, "farkle push score must match"
    assert n >= 3


# ---- blackjack (banked, dealer S17, ace-soft) --------------------------------------------------
def t_blackjack():
    import random as _r
    st, code, cid, rd = _fresh(bj, deployer=A)
    st.credit_deposit(A, 10_000_000_000); st.credit_deposit(B, 10_000_000)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [5], "value": 5_000_000_000}, A, "o")
    _r.seed(5); stake = 100_000; wins = pushes = losses = nats = 0
    for trial in range(30):
        g = 100 + trial; st.cursor = 200 + trial * 60
        st.apply_blob({"op": "call", "contract": cid, "method": "deal", "args": [g, 5], "value": stake}, B, "d")
        gh = rd(bj.GH, g); h0 = _r.randint(1, 2**60); h1 = _r.randint(1, 2**60)
        st.block_hashes[gh] = h0; st.block_hashes[gh + 1] = h1; st.cursor = gh + 2
        up = bj.card_at(h0, h1, g * 64, 16)
        c0 = bj.card_at(h0, h1, g * 64, 0); c1 = bj.card_at(h0, h1, g * 64, 1)
        ptot, _, _, natural = bj.hand_total([c0, c1])
        pb = st.bridge.get(B, 0)
        st.apply_blob({"op": "call", "contract": cid, "method": "reveal", "args": [g]}, B, "r")
        assert rd(bj.DU, g) - 1 == up, "dealer up card must match reference"
        if natural:
            nats += 1
            assert rd(bj.GD, g) == 1 and st.bridge.get(B, 0) - pb == stake * 5 // 2, "natural pays 5:2"
            continue
        st.apply_blob({"op": "call", "contract": cid, "method": "stand", "args": [g]}, B, "s")
        gh2 = rd(bj.GH, g); h2 = _r.randint(1, 2**60); h3 = _r.randint(1, 2**60)
        st.block_hashes[gh2] = h2; st.block_hashes[gh2 + 1] = h3; st.cursor = gh2 + 2
        pb = st.bridge.get(B, 0)
        st.apply_blob({"op": "call", "contract": cid, "method": "settle", "args": [g]}, B, "e")
        dtot = bj.dealer_play(h2, h3, g, up)
        exp = stake * 2 if (dtot > 21 or ptot > dtot) else (stake if ptot == dtot else 0)
        assert rd(bj.GR, g) == dtot, f"dealer total {rd(bj.GR,g)} != ref {dtot}"
        assert st.bridge.get(B, 0) - pb == exp, f"payout {st.bridge.get(B,0)-pb} != {exp}"
        wins += exp == stake * 2 and ptot != dtot; pushes += ptot == dtot; losses += exp == 0
    assert wins and losses and nats, f"want a mix (w={wins} p={pushes} l={losses} n={nats})"
    v = st.decode_view(st.contracts[cid])
    assert "pc" in v and "gr" in v and v["ta"]["5"] == A

def t_blackjack_hit_bust():
    import random as _r
    st, code, cid, rd = _fresh(bj, deployer=A)
    st.credit_deposit(A, 10_000_000_000); st.credit_deposit(B, 10_000_000)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [5], "value": 5_000_000_000}, A, "o")
    _r.seed(7); busted = 0
    for g in range(900, 990):
        st.cursor = (g + 1) * 100
        st.apply_blob({"op": "call", "contract": cid, "method": "deal", "args": [g, 5], "value": 100_000}, B, "d")
        gh = rd(bj.GH, g); st.block_hashes[gh] = _r.randint(1, 2**60); st.block_hashes[gh + 1] = _r.randint(1, 2**60); st.cursor = gh + 2
        st.apply_blob({"op": "call", "contract": cid, "method": "reveal", "args": [g]}, B, "r")
        if rd(bj.GD, g):
            continue
        pb = st.bridge.get(B, 0)
        st.apply_blob({"op": "call", "contract": cid, "method": "hit", "args": [g]}, B, "h")
        gh2 = rd(bj.GH, g); st.block_hashes[gh2] = _r.randint(1, 2**60); st.block_hashes[gh2 + 1] = _r.randint(1, 2**60); st.cursor = gh2 + 2
        st.apply_blob({"op": "call", "contract": cid, "method": "draw", "args": [g]}, B, "w")
        if rd(bj.GD, g) == 1 and rd(bj.GW, g) == 2:
            busted += 1
            assert st.bridge.get(B, 0) == pb, "a bust pays nothing"
        if busted >= 2:
            break
    assert busted >= 2, "expected some hit-then-bust hands"

def t_blackjack_prove():
    import random as _r
    st, code, cid, rd = _fresh(bj, deployer=A)
    st.credit_deposit(A, 10_000_000_000); st.credit_deposit(B, 10_000_000)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [5], "value": 5_000_000_000}, A, "o")
    _r.seed(3); g = 100; st.cursor = 500
    st.apply_blob({"op": "call", "contract": cid, "method": "deal", "args": [g, 5], "value": 100_000}, B, "d")
    gh = rd(bj.GH, g); st.block_hashes[gh] = _r.randint(1, 2**60); st.block_hashes[gh + 1] = _r.randint(1, 2**60); st.cursor = gh + 2
    st.apply_blob({"op": "call", "contract": cid, "method": "reveal", "args": [g]}, B, "r")
    assert not rd(bj.GD, g)
    st.apply_blob({"op": "call", "contract": cid, "method": "stand", "args": [g]}, B, "s")
    gh2 = rd(bj.GH, g); st.block_hashes[gh2] = _r.randint(1, 2**60); st.block_hashes[gh2 + 1] = _r.randint(1, 2**60); st.cursor = gh2 + 2
    slots = {int(k): int(vv) for k, vv in st.contracts[cid]["storage"]["slots"].items()}
    cf, fa = runtimes.zkvm_statement(B, [g], {})
    proof, io, ret, ns = V.prove_call(code, "settle", cf, fa, slots, num_queries=NQ, cursor=st.cursor, block_hashes=st.block_hashes)
    ok, why = V.verify_call(proof, code, "settle", cf, fa, io, num_queries=NQ, cursor=st.cursor)
    assert ok, f"settle proof: {why}"


# ---- bet (parimutuel — the whole pot splits pro-rata among the winning outcome's backers) --------
def t_bet():
    U = bt.UNIT
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = 100
    T0 = 1_000_000; st.block_ts = T0
    code = bt.build()
    ADM, X, Y, Z, W = A, "ndoXXXX" + "X" * 41, "ndoYYYY" + "Y" * 41, "ndoZZZZ" + "Z" * 41, "ndoWWWW" + "W" * 41
    for a in (ADM, X, Y, Z, W):
        st.credit_deposit(a, 10_000 * U)
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": bt.ABI, "nonce": "n"}, ADM, "d")
    cid = st.contract_id(ADM, code, "n")
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    call = lambda m, args, val, who: st.apply_blob(
        {"op": "call", "contract": cid, "method": m, "args": args, "value": val or 0}, who,
        m + str(args) + who + str(st.block_ts))
    bal = lambda a: st.bridge.get(a, 0)
    CM = lambda m, nout, lk, dl, desc, thr=0, res=(): [m, nout, lk, dl, desc, "thesportsdb", "133602", thr] \
        + (list(res) + [0, 0, 0])[:3]

    # market 1: creator (ADM) names no resolver -> resolves it personally
    M1 = 5001
    DESC = "Arsenal vs Chelsea\nArsenal\nDraw\nChelsea"
    assert "ok" in call("create_market", CM(M1, 3, T0 + 100, T0 + 400, DESC), None, ADM)
    assert rd(bt.MK, M1) == 1 and rd(bt.NO, M1) == 3 and rd(bt.LK, M1) == T0 + 100
    v = st.decode_view(st.contracts[cid])
    assert v["ds"][str(M1)] == DESC and v["so"][str(M1)] == "thesportsdb", "digests resolve to text"
    assert "revert" in call("create_market", CM(M1, 2, T0 + 100, T0 + 400, "x"), None, ADM), "dup id"
    assert "revert" in call("create_market", CM(5099, 1, T0 + 100, T0 + 400, "x"), None, ADM), "<2 outcomes"
    assert "revert" in call("create_market", CM(5098, 2, T0 - 1, T0 + 400, "x"), None, ADM), "lock in past"
    assert "revert" in call("create_market", CM(5097, 2, T0 + 100, T0 + 100, "x"), None, ADM), "deadline<=lock"
    assert "revert" in call("create_market", CM(5096, 2, T0 + 100, T0 + 400, "x", thr=2, res=(W,)), None, ADM)

    # bets: X 300 on 0, Y 700 on 2, Z 500 on 0 (in UNIT multiples)
    bx, by, bz = bal(X), bal(Y), bal(Z)
    call("bet", [M1, 0], 300 * U, X); call("bet", [M1, 2], 700 * U, Y); call("bet", [M1, 0], 500 * U, Z)
    assert bal(X) == bx - 300 * U and st.bridge[cid] == 1500 * U, "escrowed"
    assert rd(bt.PL_BASE + 0, M1) == 800 and rd(bt.PL_BASE + 2, M1) == 700 and rd(bt.TOT, M1) == 1500
    assert st.view(cid, "stake_of", [M1, 0, X]) == 300 * U and st.view(cid, "total_of", [M1, X]) == 300 * U
    assert "revert" in call("bet", [M1, 0], 0, X), "zero stake"
    assert "revert" in call("bet", [M1, 0], 100 * U + 5, X), "non-UNIT stake"
    assert "revert" in call("bet", [M1, 3], 100 * U, X), "bad outcome"
    assert "revert" in call("bet", [9999, 0], 100 * U, X), "no market"

    # resolve gates
    assert "revert" in call("resolve", [M1, 0], None, ADM), "before lock"
    st.block_ts = T0 + 120
    assert "revert" in call("bet", [M1, 0], 100 * U, X), "after lock"
    assert "revert" in call("resolve", [M1, 0], None, X), "non-resolver"
    call("resolve", [M1, 0], None, ADM)
    assert rd(bt.RS, M1) == 1 and rd(bt.DN, M1) == 1 and rd(bt.VD, M1) == 0
    assert "revert" in call("resolve", [M1, 2], None, ADM), "double resolve"

    # claims: X and Z split the whole 1500 pro-rata to the 800 pool; Y gets nothing
    bx, by, bz = bal(X), bal(Y), bal(Z)
    assert st.view(cid, "claimable_of", [M1, X]) == 300 * 1500 // 800 * U
    call("claim", [M1], None, X); call("claim", [M1], None, Z)
    assert bal(X) == bx + 300 * 1500 // 800 * U and bal(Z) == bz + 500 * 1500 // 800 * U
    assert "revert" in call("claim", [M1], None, Y) and bal(Y) == by, "loser gets nothing"
    assert "revert" in call("claim", [M1], None, X), "double claim"

    # custom resolver: X lists, W resolves (creator can't)
    MC = 5010
    call("create_market", CM(MC, 2, T0 + 150, T0 + 400, "Fight\nRed\nBlue", res=(W,)), None, X)
    call("bet", [MC, 0], 100 * U, Y); call("bet", [MC, 1], 100 * U, Z)
    st.block_ts = T0 + 160
    assert "revert" in call("resolve", [MC, 0], None, X), "creator not a resolver"
    call("resolve", [MC, 0], None, W)
    assert rd(bt.DN, MC) == 1 and rd(bt.RS, MC) == 1

    # void by resolver -> 1:1 refunds
    M2 = 5002
    call("create_market", CM(M2, 2, T0 + 200, T0 + 500, "B\nH\nA"), None, ADM)
    call("bet", [M2, 0], 400 * U, X); call("bet", [M2, 1], 600 * U, Y)
    bx, by = bal(X), bal(Y)
    assert "revert" in call("void", [M2], None, X), "non-resolver early void"
    call("void", [M2], None, ADM)
    assert rd(bt.VD, M2) == 1 and "revert" in call("bet", [M2, 0], 100 * U, Z)
    call("claim", [M2], None, X); call("claim", [M2], None, Y)
    assert bal(X) == bx + 400 * U and bal(Y) == by + 600 * U, "void refunds 1:1"

    # deadline void by ANYONE
    M3 = 5003
    call("create_market", CM(M3, 2, T0 + 300, T0 + 600, "C\nH\nA"), None, ADM)
    call("bet", [M3, 0], 250 * U, Z)
    st.block_ts = T0 + 590
    assert "revert" in call("void", [M3], None, Z)
    st.block_ts = T0 + 620; bz = bal(Z)
    assert "ok" in call("void", [M3], None, Z), "anyone voids past deadline"
    call("claim", [M3], None, Z)
    assert bal(Z) == bz + 250 * U

    # auto-void: posted winner had no backers
    M4 = 5004
    st.block_ts = T0 + 700
    call("create_market", CM(M4, 3, T0 + 750, T0 + 900, "D\nH\nX\nA"), None, ADM)
    call("bet", [M4, 0], 100 * U, X); call("bet", [M4, 1], 100 * U, Y)
    st.block_ts = T0 + 760; bx, by = bal(X), bal(Y)
    call("resolve", [M4, 2], None, ADM)
    assert rd(bt.VD, M4) == 1 and rd(bt.DN, M4) == 0, "unbacked winner auto-voids"
    call("claim", [M4], None, X); call("claim", [M4], None, Y)
    assert bal(X) == bx + 100 * U and bal(Y) == by + 100 * U

    # 2-of-3 resolver panel
    M5 = 5005
    st.block_ts = T0 + 800
    call("create_market", CM(M5, 2, T0 + 850, T0 + 1000, "E\nH\nA", thr=2, res=(ADM, W, X)), None, ADM)
    assert rd(bt.MRC, M5) == 3 and rd(bt.MTH, M5) == 2
    call("bet", [M5, 0], 1000 * U, Y); call("bet", [M5, 1], 1000 * U, Z)
    st.block_ts = T0 + 860
    assert "revert" in call("resolve", [M5, 0], None, Z), "non-panel"
    call("resolve", [M5, 0], None, ADM)
    assert rd(bt.DN, M5) == 0 and rd(bt.VC_BASE + 0, M5) == 1, "one vote does not finalize"
    assert "revert" in call("resolve", [M5, 0], None, ADM), "no double vote"
    call("resolve", [M5, 0], None, W)
    assert rd(bt.DN, M5) == 1 and rd(bt.RS, M5) == 1, "second matching vote finalizes"
    by = bal(Y); call("claim", [M5], None, Y)
    assert bal(Y) == by + 1000 * 2000 // 1000 * U

    # split votes never finalize until a tie-breaker
    M6 = 5006
    call("create_market", CM(M6, 2, T0 + 900, T0 + 1100, "F\nH\nA", thr=2, res=(ADM, W, X)), None, ADM)
    call("bet", [M6, 0], 500 * U, Y); call("bet", [M6, 1], 500 * U, Z)
    st.block_ts = T0 + 910
    call("resolve", [M6, 0], None, ADM); call("resolve", [M6, 1], None, W)
    assert rd(bt.DN, M6) == 0 and rd(bt.VD, M6) == 0, "split votes hold"
    call("resolve", [M6, 0], None, X)
    assert rd(bt.DN, M6) == 1 and rd(bt.RS, M6) == 1, "third vote breaks the tie"

    # views expose everything the frontend renders
    v = st.decode_view(st.contracts[cid])
    assert str(M1) in v["mk"] and v["pl"][str(M1 * 8 + 0)] == 800 and v["mcr"][str(M1)] == ADM


def t_bet_prove():
    # prove BOTH new-VM capabilities inside a real contract: create_market's 11 args ride the ARG bus,
    # claim's pro-rata payout rides DIVMODW.
    U = bt.UNIT
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = 100
    T0 = 1_000_000; st.block_ts = T0
    code = bt.build()
    st.credit_deposit(A, 10_000 * U); st.credit_deposit(B, 10_000 * U)
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": bt.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    call = lambda m, args, val, who: st.apply_blob(
        {"op": "call", "contract": cid, "method": m, "args": args, "value": val or 0}, who, m + who)
    M = 7001
    cargs = [M, 2, T0 + 100, T0 + 400, "P\nH\nA", "src", "ev", 0, 0, 0, 0]
    # prove create_market against the PRE state (fresh slots)
    cf, fa = runtimes.zkvm_statement(A, cargs, {})
    proof, io, ret, ns = V.prove_call(code, "create_market", cf, fa, {}, num_queries=NQ, timestamp=T0)
    ok, why = V.verify_call(proof, code, "create_market", cf, fa, io, num_queries=NQ, timestamp=T0)
    assert ok, f"create_market proof: {why}"
    # play the market for real, then prove the claim (DIVMODW payout)
    call("create_market", cargs, None, A)
    call("bet", [M, 0], 300 * U, B); call("bet", [M, 1], 700 * U, A)
    st.block_ts = T0 + 120
    call("resolve", [M, 0], None, A)
    slots = {int(k): int(vv) for k, vv in st.contracts[cid]["storage"]["slots"].items()}
    cf, fa = runtimes.zkvm_statement(B, [M], {})
    proof, io, ret, ns = V.prove_call(code, "claim", cf, fa, slots, num_queries=NQ, timestamp=st.block_ts)
    assert ret == 300 * 1000 // 300 * U, "pro-rata payout"
    ok, why = V.verify_call(proof, code, "claim", cf, fa, io, num_queries=NQ, timestamp=st.block_ts)
    assert ok, f"claim proof: {why}"


# ---- battleship (hidden boards, merkle-sum proofs per shot, reveal-at-claim fleet check) ----------
def _bs_setup():
    import random as _r
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = 100
    code = bs.build()
    st.credit_deposit(A, 1_000_000); st.credit_deposit(B, 1_000_000)
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": bs.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    _r.seed(7)
    shipsA = [(0, 0), (10, 0), (20, 0), (30, 0), (40, 0)]
    shipsB = [(55, 0), (4, 1), (9, 1), (77, 0), (90, 0)]
    bA, bB = bs.board_from_ships(shipsA), bs.board_from_ships(shipsB)
    seedA, seedB = _r.randint(1, 2**60), _r.randint(1, 2**60)
    sA, sB = bs.salts_from_seed(seedA), bs.salts_from_seed(seedB)
    return (st, code, cid, shipsA, shipsB, bA, bB, seedA, seedB, sA, sB,
            bs.build_root(bA, sA)[0], bs.build_root(bB, sB)[0])

def t_battleship():
    st, code, cid, shipsA, shipsB, bA, bB, seedA, seedB, sA, sB, rootA, rootB = _bs_setup()
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    call = lambda m, args, val, who: st.apply_blob(
        {"op": "call", "contract": cid, "method": m, "args": args, "value": val or 0}, who,
        m + str(args)[:40] + who + str(st.cursor))
    G = 42
    assert "ok" in call("open", [G, rootA], 500, A) and "ok" in call("join", [G, rootB], 500, B)
    cell0 = [c for c in range(100) if bB[c]][0]
    assert "ok" in call("fire", [G, cell0], None, A)
    isS, salt, flat = bs.make_proof(bB, sB, cell0)
    assert "revert" in call("answer", [G, 0, salt] + flat, None, B), "lying about a hit must revert"
    assert "revert" in call("answer", [G, 1, salt + 1] + flat, None, B), "wrong salt must revert"
    assert "ok" in call("answer", [G, 1, salt] + flat, None, B)
    assert rd(bs.H1, G) == 1 and rd(bs.TF, G) == 2
    b_cells = [c for c in range(100) if bB[c]][1:]
    a_water = [c for c in range(100) if not bA[c]]
    for n, cell in enumerate(b_cells):                          # B fires water, A sinks everything
        st.cursor += 1
        assert "ok" in call("fire", [G, a_water[n]], None, B)
        i2, s2, f2 = bs.make_proof(bA, sA, a_water[n])
        assert "ok" in call("answer", [G, i2, s2] + f2, None, A)
        st.cursor += 1
        assert "ok" in call("fire", [G, cell], None, A)
        i3, s3, f3 = bs.make_proof(bB, sB, cell)
        assert "ok" in call("answer", [G, i3, s3] + f3, None, B)
    assert rd(bs.DC, G) == 1 and rd(bs.WR, G) == 1 and rd(bs.H1, G) == 17
    flatA = [x for ao in shipsA for x in ao]
    assert "revert" in call("claim", [G] + flatA + [seedA], None, B), "loser can't claim"
    assert "revert" in call("claim", [G] + [0, 0, 0, 0, 20, 0, 30, 0, 40, 0] + [seedA], None, A), "overlap"
    b0 = st.bridge.get(A, 0)
    assert "ok" in call("claim", [G] + flatA + [seedA], None, A)
    assert st.bridge.get(A, 0) - b0 == 1000, "winner takes the pot"
    assert not [k for k in st.contracts[cid]["storage"]["slots"] if int(k) >> 32 >= 600], "scratch leaked"
    v = st.decode_view(st.contracts[cid])
    assert v["wr"][str(G)] == 1 and v["p1"][str(G)] == A and str(G * 100 + cell0) in v["rs1"]

def t_battleship_stall_paths():
    st, code, cid, shipsA, shipsB, bA, bB, seedA, seedB, sA, sB, rootA, rootB = _bs_setup()
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    call = lambda m, args, val, who: st.apply_blob(
        {"op": "call", "contract": cid, "method": m, "args": args, "value": val or 0}, who,
        m + str(args)[:40] + who + str(st.cursor))
    G = 43
    assert "ok" in call("open", [G, rootA], 300, A) and "ok" in call("join", [G, rootB], 300, B)
    assert "ok" in call("fire", [G, 5], None, A)                # B never answers
    assert "revert" in call("timeout", [G], None, A), "too early"
    st.cursor += bs.WINDOW + 1
    assert "revert" in call("timeout", [G], None, B), "the staller can't win by timeout"
    assert "ok" in call("timeout", [G], None, A) and rd(bs.WR, G) == 1
    st.cursor += bs.WINDOW + 1                                  # winner never proves a fleet -> loser forfeits
    b0 = st.bridge.get(B, 0)
    assert "ok" in call("forfeit", [G], None, B)
    assert st.bridge.get(B, 0) - b0 == 600

def t_battleship_answer_proves():
    st, code, cid, shipsA, shipsB, bA, bB, seedA, seedB, sA, sB, rootA, rootB = _bs_setup()
    call = lambda m, args, val, who: st.apply_blob(
        {"op": "call", "contract": cid, "method": m, "args": args, "value": val or 0}, who, m + who)
    G = 42
    call("open", [G, rootA], 500, A); call("join", [G, rootB], 500, B)
    cell0 = [c for c in range(100) if bB[c]][0]
    call("fire", [G, cell0], None, A)
    isS, salt, flat = bs.make_proof(bB, sB, cell0)
    slots = {int(k): int(v) for k, v in st.contracts[cid]["storage"]["slots"].items()}
    cf, fa = runtimes.zkvm_statement(B, [G, isS, salt] + flat, {})
    proof, io, ret, ns = V.prove_call(code, "answer", cf, fa, slots, num_queries=NQ, cursor=st.cursor)
    ok, why = V.verify_call(proof, code, "answer", cf, fa, io, num_queries=NQ, cursor=st.cursor)
    assert ok, f"answer proof (17 ARG args): {why}"


# ---- pets (tamagotchi NFTs: gene/tier/stats, feeding, training, battles, marketplace) -------------
def t_pets():
    import random as _r
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = 100
    code = ptz.build()
    st.credit_deposit(A, 10**13); st.credit_deposit(B, 10**13)
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": ptz.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    call = lambda m, args, val, who: st.apply_blob(
        {"op": "call", "contract": cid, "method": m, "args": args, "value": val or 0}, who,
        m + str(args)[:30] + who + str(st.cursor))
    _r.seed(11)
    genes = {}
    for i, pid in enumerate((1, 2, 3, 4)):
        who = A if i % 2 == 0 else B
        assert "ok" in call("mint", [pid], ptz.MINT_FEE, who)
        gh = rd(ptz.BH, pid)
        h0, h1 = _r.randint(1, 2**60), _r.randint(1, 2**60)
        st.block_hashes[gh] = h0; st.block_hashes[gh + 1] = h1; st.cursor = max(st.cursor, gh + 2)
        assert "ok" in call("hatch", [pid], None, who)
        gene = ptz.ref_gene(h0, h1, pid); sp = ptz.ref_tier(gene)
        assert rd(ptz.GL, pid) == (gene & 0xFFFFFFFF) and rd(ptz.GH, pid) == (gene >> 32)
        assert rd(ptz.SP, pid) == sp and rd(ptz.SI, pid) == ptz.ref_si(gene, sp)
        assert rd(ptz.AP, pid) == ptz.ref_stat(gene, sp, 9) and rd(ptz.PW, pid) == ptz.ref_power(gene, sp)
        genes[pid] = (gene, sp)
    # feed math + training differential (one success or fail, exact)
    st.cursor = rd(ptz.FU, 1) - 200000
    fu0 = rd(ptz.FU, 1)
    assert "ok" in call("feed", [1], 7 * 10**9, A)
    assert rd(ptz.FU, 1) == fu0 + 7 * 10**9 // (rd(ptz.AP, 1) * ptz.FEED_DIV), "feed math"
    for t in range(6):
        stat = t % 10
        assert "ok" in call("train", [1, stat], ptz.TRAIN_FEE, A)
        th = rd(ptz.TH, 1)
        h0, h1 = _r.randint(1, 2**60), _r.randint(1, 2**60)
        st.block_hashes[th] = h0; st.block_hashes[th + 1] = h1; st.cursor = max(st.cursor, th + 2)
        tb0 = rd(ptz.TB_BASE + stat, 1)
        cur = ptz.ref_stat(*genes[1], stat) + tb0
        ok_ref = ptz.ref_train_ok(ptz.ref_train_roll(h0, h1, 1, stat), cur, genes[1][1])
        assert "ok" in call("train_resolve", [1], None, A)
        assert rd(ptz.TB_BASE + stat, 1) - tb0 == (1 if ok_ref else 0), "train differential"
    # battles: several fights, each turn-engine result differentially checked vs ref_battle_turns
    fights = 0
    for bid in range(100, 108):
        st.cursor += ptz.EXHAUST + 10
        alive = lambda p_: rd(ptz.FU, p_) > st.cursor
        mine = {p_: st.zk_addrs.get(str(rd(ptz.OW, p_))) for p_ in (1, 2, 3, 4)}
        a_p = [p_ for p_, o in mine.items() if o == A and alive(p_)]
        b_p = [p_ for p_, o in mine.items() if o == B and alive(p_)]
        if not a_p or not b_p:
            continue
        pa, pb = a_p[0], b_p[0]
        call("feed", [pa], 5 * 10**9, A); call("feed", [pb], 5 * 10**9, B)
        if "revert" in call("challenge", [bid, pa, pb], 1000, A):
            continue
        if "revert" in call("accept", [bid], 1000, B):
            continue
        wh = rd(ptz.WH, bid)
        h0, h1 = _r.randint(1, 2**60), _r.randint(1, 2**60)
        st.block_hashes[wh] = h0; st.block_hashes[wh + 1] = h1; st.cursor = max(st.cursor, wh + 2)
        effA = [ptz.ref_stat(*genes[pa], i) + rd(ptz.TB_BASE + i, pa) for i in range(10)]
        effB = [ptz.ref_stat(*genes[pb], i) + rd(ptz.TB_BASE + i, pb) for i in range(10)]
        a_wins, dies, _h0, _h1, _log = ptz.ref_battle_turns(h0, h1, bid, effA, effB)
        assert "ok" in call("resolve_battle", [bid], None, B)
        assert rd(ptz.WW, bid) == (pa if a_wins else pb), "battle winner differential"
        loser = pb if a_wins else pa
        assert rd(ptz.WD, bid) == (loser if dies else 0), "death differential"
        assert rd(ptz.OW, loser) == rd(ptz.OW, rd(ptz.WW, bid)), "loser claimed"
        # gift back so pairings survive (the test drives both keys)
        back = A if loser == pa else B
        wo = st.zk_addrs.get(str(rd(ptz.OW, loser)))
        if rd(ptz.FU, loser) > st.cursor and wo != back:
            call("transfer", [loser, back], None, wo)
        fights += 1
    assert fights >= 3, f"only {fights} fights"
    # marketplace + naming (fresh pets so they're alive)
    for pid, who in ((20, A), (21, B)):
        call("mint", [pid], ptz.MINT_FEE, who)
        gh = rd(ptz.BH, pid)
        st.block_hashes[gh] = _r.randint(1, 2**60); st.block_hashes[gh + 1] = _r.randint(1, 2**60)
        st.cursor = max(st.cursor, gh + 2)
        call("hatch", [pid], None, who)
    assert "ok" in call("list", [20, 12345], None, A)
    b0 = st.bridge.get(A, 0)
    assert "ok" in call("buy", [20], 12345, B)
    assert st.bridge.get(A, 0) - b0 == 12345
    assert "ok" in call("offer", [900, 21], 5000, A)
    assert "ok" in call("accept_offer", [900], None, B)
    assert "ok" in call("name", [21, "Rex"], None, A)
    assert "revert" in call("name", [21, "Fido"], None, A), "no renames"
    v = st.decode_view(st.contracts[cid])
    assert v["nm"][str(21)] == "Rex" and "tb" in v
    assert not [k for k in st.contracts[cid]["storage"]["slots"] if int(k) >> 32 == ptz.SC], "scratch"

def t_pets_hatch_proves():
    import random as _r
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = 100
    code = ptz.build()
    st.credit_deposit(A, 10**12)
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": ptz.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    st.apply_blob({"op": "call", "contract": cid, "method": "mint", "args": [7], "value": ptz.MINT_FEE}, A, "m")
    gh = rd(ptz.BH, 7)
    _r.seed(3)
    bhs = {gh: _r.randint(1, 2**60), gh + 1: _r.randint(1, 2**60)}
    st.block_hashes.update(bhs); st.cursor = gh + 2
    slots = {int(k): int(v) for k, v in st.contracts[cid]["storage"]["slots"].items()}
    cf, fa = runtimes.zkvm_statement(A, [7], {})
    proof, io, ret, ns = V.prove_call(code, "hatch", cf, fa, slots, num_queries=NQ, cursor=st.cursor,
                                      block_hashes=st.block_hashes)
    ok, why = V.verify_call(proof, code, "hatch", cf, fa, io, num_queries=NQ, cursor=st.cursor)
    assert ok, f"hatch proof: {why}"


# ---- hold'em (multiplayer table stakes, side pots, on-chain 7-card showdown) ----------------------
def t_holdem_eval():
    import random as _r
    code = hd.build()
    _r.seed(42)
    for _ in range(300):
        cards = [_r.randrange(52) for _ in range(7)]           # multi-deck: duplicates legal
        cf, fa = runtimes.zkvm_statement("fuzz", cards, {})
        ok, ret, _s, _io = __import__("execnode.zkvm", fromlist=["run"]).run(code, "rank_of", cf, fa, {})
        assert ok and ret == hd.eval7_ref(cards), f"eval7 differential {cards}: {ret} vs {hd.eval7_ref(cards)}"
    for cards in ([0, 13, 26, 39, 1, 2, 3], [8, 9, 10, 11, 12, 20, 33], [0, 2, 4, 6, 8, 10, 12],
                  [12, 0, 1, 2, 3, 30, 40], [0, 0, 13, 13, 26, 26, 39], [5, 5, 5, 5, 18, 31, 44]):
        cf, fa = runtimes.zkvm_statement("fuzz", cards, {})
        ok, ret, _s, _io = __import__("execnode.zkvm", fromlist=["run"]).run(code, "rank_of", cf, fa, {})
        assert ok and ret == hd.eval7_ref(cards), f"shape {cards}"

def _holdem_settle(seats, ante):
    """Drive settle on a hand-built showdown table; returns {who: net}."""
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = 100
    code = hd.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": hd.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    dg = {s["who"]: runtimes.zkvm_addr_digest(s["who"]) for s in seats}
    for w, d in dg.items():
        st.zk_addrs[str(d)] = w
    sl = st.contracts[cid]["storage"]["slots"] = {}
    put = lambda f, k, v: sl.__setitem__(str(f * (1 << 32) + k), v)
    T = 1
    put(hd.TA, T, dg[seats[0]["who"]]); put(hd.TD, T, 50); put(hd.TS, T, ante); put(hd.TN, T, len(seats))
    put(hd.TX, T, sum(1 for s in seats if s["gd"])); sl[str(0)] = 1
    for k in range(1, 5):
        put(hd.SCL_BASE + k, T, 40 + k)
    best_g, best_v, pot = 0, 0, 0
    for i, s in enumerate(seats):
        g = 11 + i
        put(hd.TI_BASE + i, T, g)
        put(hd.GG, g, T); put(hd.GD, g, s["gd"]); put(hd.GK, g, s["gk"]); put(hd.GA, g, dg[s["who"]])
        put(hd.CS_BASE + 1, g, s["cs"]); put(hd.GSC, g, s["gsc"])
        pot += ante + s["cs"]
        if s["gsc"] * s["gd"] > best_v:
            best_v, best_g = s["gsc"] * s["gd"], g
    put(hd.TB, T, best_g); put(hd.TW, T, best_v); put(hd.TP, T, pot)
    st.bridge[cid] = pot + sum(s["gk"] for s in seats)
    st.cursor = 200
    before = {s["who"]: st.bridge.get(s["who"], 0) for s in seats}
    assert "ok" in st.apply_blob({"op": "call", "contract": cid, "method": "settle", "args": [T]}, A, "se")
    assert not [k for k in sl if 800 <= (int(k) >> 32) < 1000], "settle scratch leaked"
    return {s["who"]: st.bridge.get(s["who"], 0) - before[s["who"]] for s in seats}, pot

def t_holdem_sidepots():
    H, X, Y = "ndoHH" + "H" * 43, "ndoXX" + "X" * 43, "ndoYY" + "Y" * 43
    got, pot = _holdem_settle([{"who": H, "gd": 1, "gk": 0, "cs": 100, "gsc": 900},
                               {"who": X, "gd": 1, "gk": 0, "cs": 400, "gsc": 700},
                               {"who": Y, "gd": 1, "gk": 0, "cs": 400, "gsc": 700}], 100)
    assert got[H] == 600 and got[X] == 300 and got[Y] == 300 and sum(got.values()) == pot, "layer+tie"
    got, _ = _holdem_settle([{"who": H, "gd": 1, "gk": 0, "cs": 500, "gsc": 900},
                             {"who": X, "gd": 0, "gk": 0, "cs": 100, "gsc": 0}], 100)
    assert got[H] == 800 and got[X] == 0, "uncalled overbet returns"
    got, _ = _holdem_settle([{"who": H, "gd": 1, "gk": 0, "cs": 300, "gsc": 900},
                             {"who": X, "gd": 0, "gk": 1500, "cs": 300, "gsc": 0}], 100)
    assert got[H] == 800 and got[X] == 1500, "folded seat's stack is still refunded"

def t_holdem_full():
    import random as _r
    from execnode.stark import alghash
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = 100
    code = hd.build()
    H, X, Y = "ndoHH" + "H" * 43, "ndoXX" + "X" * 43, "ndoYY" + "Y" * 43
    for a in (H, X, Y):
        st.credit_deposit(a, 10**12)
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": hd.ABI, "nonce": "n"}, H, "d")
    cid = st.contract_id(H, code, "n")
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    call = lambda m, args, val, who: st.apply_blob(
        {"op": "call", "contract": cid, "method": m, "args": args, "value": val or 0}, who,
        m + str(args)[:40] + who + str(st.cursor))
    _r.seed(9)
    T, G1, G2, G3 = 500, 501, 502, 503
    xh, xa, xb = _r.randint(1, 2**60), _r.randint(1, 2**60), _r.randint(1, 2**60)
    assert "ok" in call("open", [T, G1, alghash.hashn([xh]), 1000], 10000, H)
    assert "ok" in call("join", [T, G2, alghash.hashn([xa])], 5000, X)
    assert "ok" in call("join", [T, G3, alghash.hashn([xb])], 3000, Y)
    assert "revert" in call("join", [T, 999, alghash.hashn([1])], 3000, Y), "one seat per address"
    assert "ok" in call("start", [T], None, H)
    d0 = rd(hd.TD, T)
    h0d, h1d = _r.randint(1, 2**60), _r.randint(1, 2**60)
    st.block_hashes[d0] = h0d; st.block_hashes[d0 + 1] = h1d
    assert "revert" in call("bet", [G1, 100], None, H), "no betting before the shuffle"
    st.cursor = d0 + hd.F0 + 1
    assert "ok" in call("bet", [G1, 500], None, H)
    assert "ok" in call("bet", [G2, 500], None, X)
    assert "ok" in call("bet", [G3, 2000], None, Y)          # all-in raise
    assert rd(hd.GK, G3) == 0
    assert "ok" in call("bet", [G1, 1500], None, H)
    assert "ok" in call("bet", [G2, 1500], None, X)
    assert "ok" in call("close_street", [T], None, H)
    cs = [rd(hd.SCL_BASE + k, T) for k in range(1, 5)]
    for k in range(1, 4):
        c = cs[k - 1]
        st.block_hashes[c] = _r.randint(1, 2**60); st.block_hashes[c + 1] = _r.randint(1, 2**60)
        st.cursor = c + 1
        if k == 3:
            assert "ok" in call("bet", [G1, 1000], None, H)
            assert "revert" in call("close_street", [T], None, H), "a pending call blocks the close"
            assert "ok" in call("bet", [G2, 1000], None, X)
        assert "ok" in call("close_street", [T], None, H)
        cs = [rd(hd.SCL_BASE + kk, T) for kk in range(1, 5)]
    c4 = cs[3]
    st.block_hashes[c4] = _r.randint(1, 2**60); st.block_hashes[c4 + 1] = _r.randint(1, 2**60)
    st.cursor = c4 + 1
    board = hd.board_ref(st.block_hashes, cs[0], cs[1], cs[2], T)
    vals = {}
    for g, (who, x) in ((G1, (H, xh)), (G2, (X, xa)), (G3, (Y, xb))):
        ref = hd.eval7_ref(hd.hole_ref(h0d, h1d, x) + board)
        assert "ok" in call("reveal", [g, x], None, who)
        assert rd(hd.GSC, g) == ref, "showdown hand value differential"
        vals[g] = ref
    assert "revert" in call("reveal", [G1, xh], None, H), "no double reveal"
    C = {G1: 1000 + 3000, G2: 1000 + 3000, G3: 1000 + 2000}
    pays = {g: 0 for g in (G1, G2, G3)}
    prev = 0
    for L in sorted(set(C.values())):
        cov = [g for g in (G1, G2, G3) if C[g] >= L]
        amt = (L - prev) * len(cov)
        best = max(vals[g] for g in cov)
        win = [g for g in cov if vals[g] == best]
        share, rem = divmod(amt, len(win))
        for i, g in enumerate(win):
            pays[g] += share + (rem if i == 0 else 0)
        prev = L
    stacks = {g: rd(hd.GK, g) for g in (G1, G2, G3)}
    before = {w: st.bridge.get(w, 0) for w in (H, X, Y)}
    assert "ok" in call("settle", [T], None, H)
    who = {G1: H, G2: X, G3: Y}
    for g in (G1, G2, G3):
        assert st.bridge.get(who[g], 0) - before[who[g]] == pays[g] + stacks[g], "settle differential"
    assert rd(hd.TZ, T) == 1
    v = st.decode_view(st.contracts[cid])
    assert v["ta"][str(T)] == H and "cs" in v

def t_holdem_open_proves():
    # `open` is holdem's representative proof — small + fast. (`reveal` also proves: it fits the 131k gas
    # ceiling at ~16k rows, but the Python prover takes minutes on that trace, so it's exercised natively
    # via the 1500-hand rank_of fuzz + full-game differential rather than proven in the suite.)
    from execnode.stark import alghash
    code = hd.build()
    T, G1 = 7, 71
    args = [T, G1, alghash.hashn([12345]), 1000]
    cf, fa = runtimes.zkvm_statement(A, args, {})
    proof, io, ret, ns = V.prove_call(code, "open", cf, fa, {}, num_queries=NQ, value=5000)
    ok, why = V.verify_call(proof, code, "open", cf, fa, io, num_queries=NQ, value=5000)
    assert ok, f"open proof: {why}"


if __name__ == "__main__":
    check("coinflip: open/join/settle/cancel + escrow + view", t_coinflip)
    check("coinflip: settle proves", t_coinflip_prove)
    check("dice: open/bet/settle/close banker accounting + view", t_dice)
    check("roulette: masked bet/settle/close + view", t_roulette)
    check("dice: bet proves (divmod + bankroll)", t_dice_prove)
    check("dice: over-max bet + unsafe close revert (solvency)", t_dice_overbet_reverts)
    check("tictactoe: full game, p1 wins, pot paid + view", t_tictactoe)
    check("connect4: vertical win, pot paid + view", t_connect4)
    check("tictactoe: wrong turn / wrong ply revert", t_tictactoe_wrongturn_reverts)
    check("tictactoe: winning move proves", t_tictactoe_prove)
    check("slots: spin/settle paytable matches reference", t_slots)
    check("mines: bet/pick/resolve multiplier + mine-hit vs reference", t_mines)
    check("reversi: flip board matches reference", t_reversi)
    check("chess: move record + agree settlement", t_chess)
    check("stormhold: free-actor move log + seed heights + agree/resign", t_stormhold)
    check("stormhold: move proves (seed-height record)", t_stormhold_move_proves)
    check("scrapline: duel contract reuse + move-log cap", t_scrapline)
    check("faucet: fixed-name deploy, PoW claims, budgets, pause, solvency", t_faucet)
    check("faucet: claim proves", t_faucet_claim_proves)
    check("farkle: roll/hold scoring + banking vs reference", t_farkle)
    check("blackjack: deal/reveal/stand/settle vs dealer S17 + payouts + view", t_blackjack)
    check("blackjack: hit-then-bust loses immediately", t_blackjack_hit_bust)
    check("blackjack: settle proves (dealer loop trace)", t_blackjack_prove)
    check("bet: parimutuel markets, resolver panels, voids, pro-rata claims", t_bet)
    check("bet: create (ARG bus) + claim (DIVMODW) prove", t_bet_prove)
    check("battleship: full hidden-board game, lie/overlap rejected, pot paid", t_battleship)
    check("battleship: timeout + forfeit stall paths", t_battleship_stall_paths)
    check("battleship: answer proves (17-arg merkle proof on the ARG bus)", t_battleship_answer_proves)
    check("pets: gene/tier/stat/feed/train/battle differentials + marketplace", t_pets)
    check("pets: hatch proves (12-hash gene derivation)", t_pets_hatch_proves)
    check("holdem: 7-card evaluator differential (300 hands + shapes)", t_holdem_eval)
    check("holdem: layered side pots, ties, uncalled bets, fold refunds", t_holdem_sidepots)
    check("holdem: full table-stakes hand, showdown differential, settle", t_holdem_full)
    check("holdem: open proves (representative call)", t_holdem_open_proves)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
