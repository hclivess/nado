"""Trio daily-board contract test — anchor (two-phase) + post, on the three board games that just gained
a free Daily Challenge (tic-tac-toe / connect four / reversi). Checks the shared _lib board is wired to
each contract's own field block and readable through its _view, WITHOUT disturbing the PvP game maps.
Run: HOME=/root python tests/trio_daily_contract_test.py
"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.games import tictactoe as TTT, connect4 as C4, reversi as REV

A, B = "ndoAAA", "ndoBBB"
passed = failed = 0
def ok(c, m):
    global passed, failed
    if c: passed += 1
    else: failed += 1; print("  FAIL:", m)


def fresh(mod, cursor=100):
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = cursor
    code = mod.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": "n"}, A, "d")
    return st, st.contract_id(A, code, "n")


def check(mod, name):
    st, cid = fresh(mod)
    day = int(time.time()) // 86400
    st.block_ts = day * 86400 + 100
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))

    # anchor phase 1: pins a FUTURE height (so nobody can steer the day's seed by timing the call)
    st.apply_blob({"op": "call", "contract": cid, "method": "anchor", "args": [day]}, A, "a1")
    ah = rd(mod.A_H, day)
    ok(ah > st.cursor, f"{name}: anchor pins a future height ({ah} > {st.cursor})")
    # phase 2: once that block exists its hash is stored forever
    st.block_hashes[ah] = 0xC0FFEE
    st.cursor = ah + 1
    st.apply_blob({"op": "call", "contract": cid, "method": "anchor", "args": [day]}, A, "a2")
    ok(rd(mod.A_V, day) != 0, f"{name}: anchor resolves av[day]")

    # post a claim: day, score, n, then DAILY_WORDS packed move words
    words = [12345 + i for i in range(mod.DAILY_WORDS)]
    st.apply_blob({"op": "call", "contract": cid, "method": "post",
                   "args": [day, 137, 5] + words}, B, "p")
    v = st.decode_view(st.contracts[cid])
    ents = [e for e, d in (v.get("eday") or {}).items() if d == day]
    ok(len(ents) == 1, f"{name}: one entry recorded (got {len(ents)})")
    if ents:
        e = ents[0]
        ok(v["escore"][e] == 137 and v["en"][e] == 5, f"{name}: score/n stored")
        ok(v["eaddr"][e] == B, f"{name}: entry bound to the poster's address")
        ok(all(v[f"ew{k}"][e] == words[k] for k in range(mod.DAILY_WORDS)),
           f"{name}: all {mod.DAILY_WORDS} move words stored")
    # a wrong-day post is rejected (day must track the chain's own clock)
    st.apply_blob({"op": "call", "contract": cid, "method": "post",
                   "args": [day + 5, 999, 5] + words}, B, "p2")
    v2 = st.decode_view(st.contracts[cid])
    ok(not [d for d in (v2.get("eday") or {}).values() if d == day + 5], f"{name}: wrong-day post rejected")
    # an over-cap score is rejected (the real check is the verifier's replay, this is the sanity bound)
    st.apply_blob({"op": "call", "contract": cid, "method": "post",
                   "args": [day, 99999, 5] + words}, A, "p3")
    v3 = st.decode_view(st.contracts[cid])
    ok(len([d for d in (v3.get("eday") or {}).values() if d == day]) == 1, f"{name}: absurd score rejected")

    # the PvP side must be untouched by the daily wiring (open stakes real value, so fund the opener)
    st.credit_deposit(A, 5_000_000)
    st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [7], "value": 1_000_000}, A, "o")
    v4 = st.decode_view(st.contracts[cid])
    ok("7" in (v4.get("nn") or {}) or 7 in (v4.get("nn") or {}), f"{name}: PvP open still works alongside the daily board")


for mod, name in ((TTT, "tictactoe"), (C4, "connect4"), (REV, "reversi")):
    check(mod, name)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
