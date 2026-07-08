"""Staked coin-flip betting module (execnode/state.py) — money-critical invariants.

Verifies: escrow debits the bettor's bridge balance; the pot is conserved (no NADO minted or lost across a
game's whole life); the winner is paid exactly the pot once; a withheld reveal forfeits to the revealer after
the deadline; no-opponent / no-reveal games refund; bad secrets and stake mismatches are rejected; and two
nodes replaying the same blob sequence reach the same state_root (determinism)."""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState, FLIP_REVEAL_WINDOW
from execnode.vm import _hash_value

FAIL = []
def check(name, cond):
    print(("  ok  " if cond else " FAIL ") + name)
    if not cond: FAIL.append(name)

def fresh():
    return ExecState(tempfile.mktemp(prefix="nado_flip_", suffix=".json"))

def total_bridge(s):
    return sum(s.bridge.values())

def pots(s):
    return sum(g["pot"] for g in s.games.values())

A, B, C = "ndoAAA...aaa", "ndoBBB...bbb", "ndoCCC...ccc"
sA, sB = 111, 222   # (scalars fine for the test; the dApp uses 256-bit secrets)

# ---------------------------------------------------------------- 1. full game, both reveal, winner paid once
s = fresh()
s.cursor = 100
s.bridge = {A: 5000, B: 5000}
before = total_bridge(s)
s.apply_blob({"op": "flip_bet", "game": 7, "commit": _hash_value(sA), "stake": 1000}, A, "t1")
s.apply_blob({"op": "flip_bet", "game": 7, "commit": _hash_value(sB), "stake": 1000}, B, "t2")
check("both stakes escrowed out of bridge", total_bridge(s) == before - 2000 and pots(s) == 2000)
check("bridge debited per player", s.bridge[A] == 4000 and s.bridge[B] == 4000)
s.apply_blob({"op": "flip_reveal", "game": 7, "secret": sA}, A, "t3")
s.apply_blob({"op": "flip_reveal", "game": 7, "secret": sB}, B, "t4")
s.apply_blob({"op": "flip_settle", "game": 7}, C, "t5")   # anyone can trigger settle
g = s.games["7"]
check("game settled, pot emptied", g["settled"] and g["pot"] == 0)
check("conservation: total NADO unchanged across the whole game", total_bridge(s) + pots(s) == before)
winners = [a for a in (A, B) if s.bridge.get(a, 0) == 5000 + 1000]
losers = [a for a in (A, B) if s.bridge.get(a, 0) == 5000 - 1000]
check("exactly one winner (+pot) and one loser (-stake)", len(winners) == 1 and len(losers) == 1)
# double-settle must not pay twice
wbal = s.bridge.copy()
s.apply_blob({"op": "flip_settle", "game": 7}, C, "t6")
check("double-settle is a no-op (no double pay)", s.bridge == wbal)

# ---------------------------------------------------------------- 2. determinism: replay -> identical root
s2 = fresh(); s2.cursor = 100; s2.bridge = {A: 5000, B: 5000}
for p, snd, t in [({"op":"flip_bet","game":7,"commit":_hash_value(sA),"stake":1000}, A, "t1"),
                  ({"op":"flip_bet","game":7,"commit":_hash_value(sB),"stake":1000}, B, "t2"),
                  ({"op":"flip_reveal","game":7,"secret":sA}, A, "t3"),
                  ({"op":"flip_reveal","game":7,"secret":sB}, B, "t4"),
                  ({"op":"flip_settle","game":7}, C, "t5")]:
    s2.apply_blob(p, snd, t)
check("determinism: identical blob sequence -> identical state_root", s.state_root() == s2.state_root())

# ---------------------------------------------------------------- 3. forfeit: one reveals, opponent withholds
s = fresh(); s.cursor = 100; s.bridge = {A: 5000, B: 5000}; before = total_bridge(s)
s.apply_blob({"op":"flip_bet","game":9,"commit":_hash_value(sA),"stake":2000}, A, "u1")
s.apply_blob({"op":"flip_bet","game":9,"commit":_hash_value(sB),"stake":2000}, B, "u2")
s.apply_blob({"op":"flip_reveal","game":9,"secret":sA}, A, "u3")   # only A reveals
check("cannot claim before deadline", s.apply_blob({"op":"flip_claim","game":9}, A, "u4").startswith("skip"))
s.cursor = 100 + FLIP_REVEAL_WINDOW + 1                            # deadline passes
s.apply_blob({"op":"flip_claim","game":9}, A, "u5")
check("revealer takes the whole pot by forfeit", s.bridge[A] == 5000 + 2000 and s.games["9"]["settled"])
check("forfeit conserves NADO", total_bridge(s) + pots(s) == before)

# ---------------------------------------------------------------- 4. refund: no opponent ever joined
s = fresh(); s.cursor = 100; s.bridge = {A: 5000}; before = total_bridge(s)
s.apply_blob({"op":"flip_bet","game":11,"commit":_hash_value(sA),"stake":3000}, A, "v1")
s.cursor = 100 + FLIP_REVEAL_WINDOW + 1
s.apply_blob({"op":"flip_claim","game":11}, A, "v2")
check("lone bettor refunded after deadline", s.bridge[A] == 5000 and total_bridge(s) == before)

# ---------------------------------------------------------------- 5. refund: both committed, neither revealed
s = fresh(); s.cursor = 100; s.bridge = {A: 5000, B: 5000}; before = total_bridge(s)
s.apply_blob({"op":"flip_bet","game":12,"commit":_hash_value(sA),"stake":1500}, A, "w1")
s.apply_blob({"op":"flip_bet","game":12,"commit":_hash_value(sB),"stake":1500}, B, "w2")
s.cursor = 100 + FLIP_REVEAL_WINDOW + 1
s.apply_blob({"op":"flip_claim","game":12}, C, "w3")
check("both stakes refunded when nobody reveals", s.bridge[A] == 5000 and s.bridge[B] == 5000 and total_bridge(s) == before)

# ---------------------------------------------------------------- 6. rejections
s = fresh(); s.cursor = 100; s.bridge = {A: 5000, B: 5000, C: 5000}
s.apply_blob({"op":"flip_bet","game":20,"commit":_hash_value(sA),"stake":1000}, A, "x1")
check("stake mismatch rejected", s.apply_blob({"op":"flip_bet","game":20,"commit":_hash_value(sB),"stake":999}, B, "x2").startswith("skip"))
check("game still has one player after rejected join", len(s.games["20"]["players"]) == 1 and s.bridge[B] == 5000)
s.apply_blob({"op":"flip_bet","game":20,"commit":_hash_value(sB),"stake":1000}, B, "x3")
check("third player rejected (game full)", s.apply_blob({"op":"flip_bet","game":20,"commit":_hash_value(333),"stake":1000}, C, "x4").startswith("skip") and s.bridge[C] == 5000)
check("wrong secret does not open commit", s.apply_blob({"op":"flip_reveal","game":20,"secret":999}, A, "x5").startswith("skip"))
check("player state unchanged after bad reveal", s.games["20"]["players"][A]["secret"] is None)
check("reveal before both committed is guarded (new game)", s.apply_blob({"op":"flip_reveal","game":77,"secret":sA}, A, "x6").startswith("skip"))

# ---------------------------------------------------------------- 7. insufficient balance
s = fresh(); s.cursor = 100; s.bridge = {A: 500}
check("cannot bet more than bridged balance", s.apply_blob({"op":"flip_bet","game":30,"commit":_hash_value(sA),"stake":1000}, A, "y1").startswith("skip"))
check("no game created + balance untouched on failed bet", "30" not in s.games and s.bridge[A] == 500)

print("\n" + ("ALL PASS" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}"))
sys.exit(1 if FAIL else 0)
