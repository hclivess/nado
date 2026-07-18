"""
Offline lifecycle test of the Hexholm contract (execnode/games/hexholm.py) on a fresh ExecState — the
same apply_blob path the live exec node runs. Exercises every method: the 2-4 seat lobby (open/join/
leave/cancel), the KH pin on the filling join, ply-bound free-actor move() with per-move seed records,
the unanimous-alive agree() payout, the resign cascade (last seat standing takes the pot), the move-clock
abort() with equal alive-split + remainder-to-caller, and commit-verified reveal(). Reverts must leave
state untouched. One representative method is STARK-proven (a call is provable).

Run: python3 tests/hexholm_contract_test.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode import runtimes
from execnode.stark import vm_circuit as V, alghash, field as F
from execnode.games import hexholm as hx

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

A = "ndoAAAA" + "A" * 41
B = "ndoBBBB" + "B" * 41
C = "ndoCCCC" + "C" * 41
D = "ndoDDDD" + "D" * 41
XB = 0x123456789ABCDEF0                       # B's reveal secret
CB = alghash.hashn([XB % F.P])                # its commit

def _fresh(cursor=100):
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = cursor
    code = hx.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": hx.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    for who in (A, B, C, D): st.credit_deposit(who, 1_000_000)
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    call = lambda who, n, method, args, value=0: st.apply_blob(
        {"op": "call", "contract": cid, "method": method, "args": args, **({"value": value} if value else {})}, who, n)
    return st, code, cid, rd, call

def t_lobby_and_agree():
    st, code, cid, rd, call = _fresh()
    G = 777
    call(A, "1", "open", [G, 3, 111], 500)
    assert rd(hx.NN, G) == 1 and rd(hx.CAP, G) == 3 and rd(hx.ST, G) == 500 and rd(14, G) == 111
    call(B, "2", "join", [G, CB], 500)
    assert rd(hx.NN, G) == 2 and st.bridge[cid] == 1000
    call(B, "3", "leave", [G])                             # last joiner pops
    assert rd(hx.NN, G) == 1 and rd(5, G) == 0 and st.bridge[cid] == 500 and st.bridge[B] == 1_000_000
    call(B, "4", "join", [G, CB], 500)
    call(B, "4b", "join", [G, CB], 500)                    # double-join reverts (already seated)
    assert rd(hx.NN, G) == 2
    assert rd(hx.KH, G) == 0                               # not pinned until FULL
    st.cursor = 200
    call(C, "5", "join", [G, 333], 500)
    assert rd(hx.NN, G) == 3 and rd(hx.KH, G) == 202 and rd(hx.DL, G) == 200 + hx.MOVE_CLOCK
    call(D, "6", "join", [D and G, 444], 500)              # full -> revert
    assert rd(hx.NN, G) == 3 and st.bridge[cid] == 1500
    # moves: ply binding + free actor + seed record
    st.cursor = 210
    call(A, "7", "move", [G, 5, 0])
    assert rd(hx.MC, G) == 1
    assert rd(1000, G) == 5 and rd(2000, G) == 212 * 8 + 1          # mv[0]=enc, mh[0]=(cursor+GAP)*8+side
    call(C, "8", "move", [G, 9, 1])
    assert rd(hx.MC, G) == 2 and rd(2001, G) == 212 * 8 + 3
    call(A, "9", "move", [G, 7, 5])                        # wrong ply -> revert
    assert rd(hx.MC, G) == 2
    call(D, "10", "move", [G, 7, 2])                       # not seated -> revert
    assert rd(hx.MC, G) == 2
    # unanimous agree pays the named seat
    call(A, "11", "agree", [G, 2])
    call(B, "12", "agree", [G, 2])
    assert rd(hx.SD, G) == 0                               # C outstanding
    call(C, "13", "agree", [G, 2])
    assert rd(hx.SD, G) == 1 and rd(hx.WR, G) == 2 and st.bridge.get(cid, 0) == 0
    assert st.bridge[B] == 1_000_000 - 500 + 1500
    call(A, "14", "move", [G, 5, 2])                       # settled -> move reverts
    assert rd(hx.MC, G) == 2
    # reveal still works after settle; halves reconstruct the secret
    call(B, "15", "reveal", [G, XB])
    assert rd(29, G) * (1 << 32) + rd(30, G) == XB
    call(C, "16", "reveal", [G, 999])                      # wrong secret -> revert
    assert rd(31, G) == 0 and rd(32, G) == 0
    v = st.decode_view(st.contracts[cid])
    assert v["p1"][str(G)] == A and v["p3"][str(G)] == C and v["mv"][str(G * 10000 + 1)] == 9

def t_resign_cascade():
    st, code, cid, rd, call = _fresh()
    G = 42
    call(A, "1", "open", [G, 3, 0], 400)
    call(B, "2", "join", [G, 0], 400)
    call(C, "3", "join", [G, 0], 400)
    call(A, "4", "resign", [G])
    assert rd(hx.RC, G) == 1 and rd(23, G) == 1 and rd(hx.SD, G) == 0
    call(A, "5", "resign", [G])                            # double resign -> revert
    assert rd(hx.RC, G) == 1
    call(A, "6", "agree", [G, 3])                          # resigned seat cannot vote
    assert rd(18, G) == 0
    call(B, "7", "resign", [G])                            # last alive (C) auto-paid
    assert rd(hx.SD, G) == 1 and rd(hx.WR, G) == 3
    assert st.bridge[C] == 1_000_000 - 400 + 1200 and st.bridge.get(cid, 0) == 0

def t_agree_excludes_resigned():
    st, code, cid, rd, call = _fresh()
    G = 43
    call(A, "1", "open", [G, 3, 0], 100)
    call(B, "2", "join", [G, 0], 100)
    call(C, "3", "join", [G, 0], 100)
    call(C, "4", "resign", [G])
    call(A, "5", "agree", [G, 2])
    assert rd(hx.SD, G) == 0
    call(B, "6", "agree", [G, 2])                          # A+B unanimous among alive -> paid
    assert rd(hx.SD, G) == 1 and rd(hx.WR, G) == 2
    assert st.bridge[B] == 1_000_000 - 100 + 300
    st2, _, cid2, rd2, call2 = _fresh()
    call2(A, "1", "open", [44, 2, 0], 100); call2(B, "2", "join", [44, 0], 100)
    call2(A, "3", "resign", [44])                          # 2-seat resign == classic: other seat wins
    assert rd2(hx.SD, 44) == 1 and rd2(hx.WR, 44) == 2

def t_cancel_refunds():
    st, code, cid, rd, call = _fresh()
    G = 9
    call(A, "1", "open", [G, 4, 0], 300)
    call(B, "2", "join", [G, 0], 300)
    call(B, "3", "cancel", [G])                            # only the creator cancels
    assert rd(hx.SD, G) == 0
    call(A, "4", "cancel", [G])
    assert rd(hx.SD, G) == 1 and rd(hx.WR, G) == 5 and st.bridge.get(cid, 0) == 0
    assert st.bridge[A] == 1_000_000 and st.bridge[B] == 1_000_000
    call(C, "5", "join", [G, 0], 300)                      # cancelled table refuses joiners
    assert rd(hx.NN, G) == 2 and st.bridge.get(cid, 0) == 0

def t_abort_split():
    st, code, cid, rd, call = _fresh()
    G = 55
    call(A, "1", "open", [G, 3, 0], 501)
    call(B, "2", "join", [G, 0], 501)
    call(C, "3", "join", [G, 0], 501)                      # pot 1503, DL = cursor + clock
    call(B, "4", "resign", [G])                            # alive = A, C
    call(A, "5", "abort", [G])                             # clock not lapsed -> revert
    assert rd(hx.SD, G) == 0
    st.cursor = 100 + hx.MOVE_CLOCK + 10
    call(A, "6", "abort", [G])                             # q=751 each to A+C, rem 1 to caller A
    assert rd(hx.SD, G) == 1 and rd(hx.WR, G) == 5 and st.bridge.get(cid, 0) == 0
    assert st.bridge[A] == 1_000_000 - 501 + 751 + 1
    assert st.bridge[C] == 1_000_000 - 501 + 751
    assert st.bridge[B] == 1_000_000 - 501                 # the resigner forfeited

def t_prove_move():
    code = hx.build()
    S = lambda f, k: f * (1 << 32) + k
    slots = {S(hx.NN, 1): 2, S(hx.CAP, 1): 2, S(hx.MC, 1): 0,
             S(4, 1): runtimes.zkvm_addr_digest(A), S(5, 1): runtimes.zkvm_addr_digest(B)}
    cf, fa = runtimes.zkvm_statement(A, [1, 5, 0], {})
    proof, io, ret, ns = V.prove_call(code, "move", cf, fa, slots, num_queries=6, cursor=300)
    ok, why = V.verify_call(proof, code, "move", cf, fa, io, num_queries=6, cursor=300)
    assert ok, f"move proof: {why}"

def t_anchor():
    st, code, cid, rd, call = _fresh(cursor=500)
    day = 20600
    st.block_ts = 86400 * day + 3600
    cnt = lambda: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(hx.DCNT_SLOT), 0))
    call(A, "a0", "anchor", [day - 1])                     # not today -> revert
    assert rd(hx.A_H, day - 1) == 0 and cnt() == 0
    call(A, "a1", "anchor", [day])                         # phase 1: pin cursor+GAP
    assert rd(hx.A_H, day) == 500 + hx.GAP and rd(hx.A_V, day) == 0
    assert cnt() == 1 and rd(hx.DLIST, 0) == day
    call(B, "a2", "anchor", [day])                         # pinned block still future -> revert
    assert rd(hx.A_V, day) == 0 and cnt() == 1
    st.cursor = 510
    st.block_hashes[500 + hx.GAP] = 0xDEADBEEF12345
    call(B, "a3", "anchor", [day])                         # phase 2: hash VALUE stored forever
    assert rd(hx.A_V, day) == 0xDEADBEEF12345 % F.P
    call(C, "a4", "anchor", [day])                         # already anchored -> revert, unchanged
    assert rd(hx.A_V, day) == 0xDEADBEEF12345 % F.P and cnt() == 1
    day2 = day + 1                                         # stale-pin re-pin path
    st.block_ts = 86400 * day2 + 50
    call(A, "b1", "anchor", [day2])
    assert rd(hx.A_H, day2) == 510 + hx.GAP
    st.cursor = 510 + hx.GAP + 18001                       # retention window blown, never resolved
    call(B, "b2", "anchor", [day2])
    assert rd(hx.A_H, day2) == st.cursor + hx.GAP and rd(hx.A_V, day2) == 0
    st.cursor += 5
    st.block_hashes[st.cursor - 5 + hx.GAP] = 77
    call(C, "b3", "anchor", [day2])
    assert rd(hx.A_V, day2) == 77 and cnt() == 2 and rd(hx.DLIST, 1) == day2

for t in (t_lobby_and_agree, t_resign_cascade, t_agree_excludes_resigned, t_cancel_refunds,
          t_abort_split, t_prove_move, t_anchor):
    check(t.__name__, t)
print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
