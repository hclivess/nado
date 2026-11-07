"""
AMM SWAPS CLEAR IN BATCHES, ONE PRICE PER BLOCK (execnode/games/dex.py SWAPS — operator, 2026-11-07: per-block batches
over a consensus reorder, because an in-block shuffle cannot stop a sandwich whose legs sit in different blocks).
Driven through the real contract on ExecState, against a Python model of the clearing written from the header:

  1. a single order alone in its batch gets EXACTLY what the old immediate swap paid (out = RT·B'//(RN+B'));
  2. fuzz: random pools and random blocks of buys and sells with random limits — every order the contract accepts or
     refuses is what the model accepts or refuses, every fill (claimed from the next block) is the model's to the unit,
     every fill is at least its minOut, the pool's reserves are the model's, and k = RN·RT never falls;
  3. position in the block is worth nothing: the same orders placed in any order give the same fills and reserves;
  4. a same-block "sandwich" is refused: an order that would push an earlier order past its limit reverts;
  5. the contract always holds what it owes, and an order is claimable only once its block has passed (settle by anyone);
  6. liquidity never moves under a batch still taking orders: join/exit wait out the block's batch, and clear a closed
     one first (its orders then claim what the clearing paid);
  7. the immediate swaps are gone (swapn/swapt are not methods any more).

Run: python3 tests/test_amm_swaps_clear_in_batches_at_one_price_and_honour_every_limit.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-amm-batches-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from execnode.state import ExecState, asset_id
from execnode.games import dex as D

import _harness
_report = _harness.Report()
check = _report.check

U = D.UNIT
LP = "ndoLLLL" + "L" * 41
TRADERS = ["ndoT%03d" % i + "T" * 41 for i in range(6)]
CODE = D.build()


# ---- the model (the header's SWAPS, line for line) -------------------------------------------------------------------
class Refused(Exception):
    pass


def quote(x, y, B, S):
    Bf, Sf = B * D.FEE_NUM // D.FEE_DEN, S * D.FEE_NUM // D.FEE_DEN
    if y < x and not Sf < (y << 31) // x:
        raise Refused("sell side past the budget")
    sv = Sf * x // y
    if Bf <= sv:
        bt = Bf * y // x
        dS = Sf - bt
        return bt, Bf + x * dS // (y + dS)                        # BTOUT, BNOUT
    dB = Bf - sv
    return Sf + y * dB // (x + dB), sv


class Batch:
    def __init__(self):
        self.B = self.S = 0
        self.lb = self.ls = None                                  # tightest (units, minOut) per side
        self.orders = []

    def add(self, x, y, side, u, mo):
        B, S = self.B + (u if side == 1 else 0), self.S + (u if side == 2 else 0)
        if (x + B if side == 1 else y + S) >= D.BOUND:
            raise Refused("reserve bound")
        lb, ls = self.lb, self.ls
        t = (u, mo)
        if side == 1 and (lb is None or mo * lb[0] > lb[1] * u):
            lb = t
        if side == 2 and (ls is None or mo * ls[0] > ls[1] * u):
            ls = t
        bo, no = quote(x, y, B, S)
        if lb and lb[1] * B > lb[0] * bo:
            raise Refused("a buy limit")
        if ls and ls[1] * S > ls[0] * no:
            raise Refused("a sell limit")
        self.B, self.S, self.lb, self.ls = B, S, lb, ls

    def clear(self, x, y):
        bo, no = quote(x, y, self.B, self.S)
        return x + self.B - no, y + self.S - bo, bo, no


# ---- the chain ---------------------------------------------------------------------------------------------------------
def fresh(rn, rt):
    st = ExecState(os.path.join(tempfile.mkdtemp(prefix="nado_amm_"), "s.json"))
    st.cursor = 100
    for w in [LP] + TRADERS:
        st.bridge[w] = 10 ** 18
    cid = st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": CODE, "abi": D.ABI, "nonce": "b"}, LP, "dep").split()[1]
    st.apply_blob({"op": "asset_create", "seed": 1, "name": "T", "sym": "T", "dec": 8, "supply": 10 ** 9 * U, "mintable": False}, LP, "mk")
    aid = int(asset_id(LP, 1))
    for w in TRADERS:
        st.apply_blob({"op": "asset_transfer", "asset": str(aid), "to": w, "amount": 10 ** 7 * U}, LP, "x" + w)
    n = [0]

    def call(who, method, args, value=0, asset=0):
        n[0] += 1
        st._block_steps = 0; st.__dict__["_block_steps_by"] = {}
        return st.apply_blob({"op": "call", "contract": cid, "method": method, "args": args, "value": value,
                              "asset": str(asset) if asset else 0}, who, f"t{n[0]}")
    call(LP, "open", [1, aid])
    call(LP, "fundn", [1, 1, rn], rn * U)
    call(LP, "fundt", [1, 1, rt], rt * U, aid)
    assert "ok" in call(LP, "join", [1, 1])
    return st, cid, aid, call


def cell(st, cid, f, k):
    return int(((st.contracts[cid].get("storage") or {}).get("slots") or {}).get(str(f * (1 << 32) + k), 0))


def order(call, aid, who, side, oid, u, mo):
    r = call(who, "obuy" if side == 1 else "osell", [1, oid, u, mo], u * U, aid if side == 2 else 0)
    return r.endswith("-> ok")


def claim(st, call, aid, who, oid):
    b = (st.bridge.get(who, 0), st.asset_balance(aid, who))
    r = call(who, "claim", [oid, aid])
    a = (st.bridge.get(who, 0), st.asset_balance(aid, who))
    return r.endswith("-> ok"), (a[0] - b[0]) // U, (a[1] - b[1]) // U


# 1. alone in its batch = the old immediate swap
st, cid, aid, call = fresh(50_000, 200_000)
ok = order(call, aid, TRADERS[0], 1, 7, 1_234, 0)
st.cursor += 1
_, _, got = claim(st, call, aid, TRADERS[0], 7)
dxf = 1_234 * D.FEE_NUM // D.FEE_DEN
check("an order alone in its batch gets exactly what the old immediate swap paid", ok and got == 200_000 * dxf // (50_000 + dxf), got)

# 2. fuzz against the model
R = random.Random(20261107)
mism, below, kfell, owes, rounds, accepted, refused = [], 0, 0, 0, 0, 0, 0
for trial in range(14):
    x, y = R.choice([(10_000, 10_000), (3_000, 900_000), (900_000, 2_000), (123_456, 654_321)])
    st, cid, aid, call = fresh(x, y)
    oid = 100
    for blk in range(5):
        bt, mine = Batch(), []
        for k in range(R.randint(1, 7)):
            who, side = R.choice(TRADERS), R.choice([1, 2])
            u = R.choice([1, 10, 500, 5_000, 40_000, R.randint(1, 100_000)])
            try:
                alone_b, alone_n = quote(x, y, u if side == 1 else 0, u if side == 2 else 0)
            except Refused:
                alone_b = alone_n = 0
            alone = alone_b if side == 1 else alone_n
            mo = R.choice([0, alone, alone * 99 // 100, alone * 95 // 100, alone + 1, alone // 2])
            oid += 1
            try:
                bt.add(x, y, side, u, mo); want = True
            except Refused:
                want = False
            got = order(call, aid, who, side, oid, u, mo)
            if got != want:
                mism.append((trial, blk, side, u, mo, got, want))
            if got:
                accepted += 1; mine.append((who, side, oid, u, mo))
            else:
                refused += 1
        st.cursor += 1
        if mine:
            x2, y2, bo, no = bt.clear(x, y)
            for who, side, o, u, mo in mine:
                okc, dn, dt = claim(st, call, aid, who, o)
                want = u * bo // bt.B if side == 1 else u * no // bt.S
                gotf = dt if side == 1 else dn
                if not okc or gotf != want:
                    mism.append(("fill", trial, blk, side, u, gotf, want))
                if gotf < mo:
                    below += 1
            if x2 * y2 < x * y:
                kfell += 1
            if (cell(st, cid, D.RN, 1), cell(st, cid, D.RT, 1)) != (x2, y2):
                mism.append(("reserves", trial, blk))
            x, y = x2, y2
            rounds += 1
        if st.bridge.get(cid, 0) < cell(st, cid, D.RN, 1) * U or st.asset_balance(aid, cid) < cell(st, cid, D.RT, 1) * U:
            owes += 1
check(f"fuzz: the contract accepts and refuses exactly the orders the model does, and fills each to the unit "
      f"({accepted} accepted, {refused} refused over {rounds} batches)", not mism and accepted > 100 and refused > 10, mism[:5])
check("…no fill is below its minOut", below == 0, below)
check("…k = RN·RT never falls across a clearing (the fee stays with the LPs)", kfell == 0, kfell)
check("…and the contract always holds the reserves (every claim paid out of what came in)", owes == 0, owes)


# 3. position in the block is worth nothing
def play(perm):
    st, cid, aid, call = fresh(80_000, 80_000)
    os_ = [(TRADERS[0], 1, 1, 3_000), (TRADERS[1], 2, 2, 2_000), (TRADERS[2], 1, 3, 700), (TRADERS[3], 2, 4, 9_000)]
    for i in perm:
        who, side, o, u = os_[i]
        order(call, aid, who, side, o, u, 0)
    st.cursor += 1
    fills = [claim(st, call, aid, who, o)[1:] for who, side, o, u in os_]
    return fills, (cell(st, cid, D.RN, 1), cell(st, cid, D.RT, 1))
base = play([0, 1, 2, 3])
check("the same orders placed in any order in the block give the same fills and the same reserves",
      all(play(p) == base for p in ([3, 2, 1, 0], [1, 3, 0, 2], [2, 0, 3, 1])), base)

# 4. a same-block sandwich is refused
st, cid, aid, call = fresh(100_000, 100_000)
alone = quote(100_000, 100_000, 5_000, 0)[0]
v = order(call, aid, TRADERS[0], 1, 1, 5_000, alone * 99 // 100)        # the victim: 1 % slippage
big = order(call, aid, TRADERS[1], 1, 2, 20_000, 0)                       # a buy that would push the victim past 1 %
small = order(call, aid, TRADERS[1], 1, 3, 200, 0)                        # one that stays inside it
st.cursor += 1
_, _, vt = claim(st, call, aid, TRADERS[0], 1)
check("a same-block buy that would push an earlier order past its limit is refused; a small one is not",
      v and not big and small and vt >= alone * 99 // 100, (v, big, small, vt, alone))

# 5. claims wait for the block; anyone can settle
st, cid, aid, call = fresh(10_000, 10_000)
B0 = st.cursor                          # the batch key is the cursor its orders apply at (m.cursor())
order(call, aid, TRADERS[0], 2, 1, 300, 0)
v_open, v_none = st.view(cid, "order", [1]), st.view(cid, "order", [999])
early = claim(st, call, aid, TRADERS[0], 1)[0]
st.cursor += 1
s_ok = call(TRADERS[5], "settle", [1]).endswith("-> ok")
late = claim(st, call, aid, TRADERS[0], 1)
again = claim(st, call, aid, TRADERS[0], 1)[0]
check("an order is claimable only once its block has passed; anyone can settle the batch; a claim pays once",
      not early and s_ok and late[0] and late[1] > 0 and not again, (early, s_ok, late, again))
check("a page can read an order: its batch's block while unclaimed, 0 for none or once claimed",
      str(v_open) == str(B0) and str(v_none) == "0" and str(st.view(cid, "order", [1])) == "0", (v_open, v_none, B0))

# 6. liquidity never moves under a live batch
st, cid, aid, call = fresh(20_000, 20_000)
order(call, aid, TRADERS[0], 1, 1, 1_000, 0)
call(LP, "fundn", [1, 1, 500], 500 * U)
call(LP, "fundt", [1, 1, 5_000], 5_000 * U, aid)
same = call(LP, "join", [1, 1]).endswith("-> ok")
ex_same = call(LP, "exit", [1, 1, 10, aid]).endswith("-> ok")
st.cursor += 1
rn0, rt0 = cell(st, cid, D.RN, 1), cell(st, cid, D.RT, 1)
nxt = call(LP, "join", [1, 1]).endswith("-> ok")
_, _, t = claim(st, call, aid, TRADERS[0], 1)
x2, y2, bo, no = (lambda b: (b.add(20_000, 20_000, 1, 1_000, 0), b.clear(20_000, 20_000))[1])(Batch())
check("join and exit wait out the block's batch; the next block's join clears it first and its order claims what the "
      "clearing paid", not same and not ex_same and nxt and t == bo and cell(st, cid, D.OPEN, 1) == 0, (same, ex_same, nxt, t, bo))

# 7.
r = call(TRADERS[0], "swapn", [1, 100, 0, aid], 100 * U)
check("the immediate swaps are gone", "swapn" not in D.ABI and "swapt" not in D.ABI and not r.endswith("-> ok"), r)

_report.done()
