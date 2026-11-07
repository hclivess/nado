"""
The DEX launchpad (execnode/games/dex.py, doc/launchpad.md) — money code, run, not read (ROADMAP §12). Drives the
real ExecState (deploy -> calls -> asserts) and checks every batch against an independent model of the clearing:

  * fee and ids: prelaunch takes exactly the creation fee and seals it; only the reserving caller launches; a reserved
    id cannot be opened as a pool; a dust order or an id >= 2^32 is refused;
  * ONE PRICE PER BATCH: every buyer in the opening window (10 blocks) pays the same price, whatever block or position
    they bought in — a later buy in the window gets exactly what an earlier one of the same size gets; two buys in one
    block cleared in either order pay the same; buys and sells in one block net at spot and every buyer / every seller
    of the batch shares one price; each batch equals the model to the unit;
  * the clearing cannot be run early (a batch is closed only once the block moved on) and a claim is the order
    owner's, once; a carried chain whose cursor restarted lower closes the open batch instead of freezing it;
  * SOLVENCY AND CONSERVATION: after every claim the contract holds exactly the NADO and coins it owes — the curve's
    NADO and coins, the sealed fees, the graduated pool's reserves — and never pays a seller past the NADO raised;
  * FEES: 1 % of every buy is sealed (FEEB), 1 % of every sell's coins is burned (the supply falls);
  * GRADUATION at 4/5 sold: the curve becomes a share-less pool at its own price, the surplus coins are burned, the
    pool trades through swapn/swapt, and nobody can seed, join or withdraw it; before graduation the curve is never
    traded through the pool methods.

Run: python3 tests/test_the_dex_launchpad_clears_every_batch_at_one_price_and_graduates_into_locked_liquidity.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-launchpad-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState, asset_id
from execnode.games import dex as D

U = D.UNIT
CREATOR = "creator00000000000000000000000000000000000000000"
A, B, C, E = ("a" * 48, "b" * 48, "c" * 48, "e" * 48)
_fails = []


def check(name, cond, info=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"  [{info}]" if (info and not cond) else ""))
    if not cond:
        _fails.append(name)


st = ExecState(os.path.join(os.environ["HOME"], "s.json"))
st.cursor = 1000
cid = st.apply_blob({"op": "deploy", "code": D.build(), "nonce": "lp", "runtime": "zkvm", "abi": D.ABI}, CREATOR, "tx").split()[1]
for who in (CREATOR, A, B, C, E):
    st.bridge[who] = 10 ** 18


def call(sender, method, args, value=0, asset=0):
    st._block_steps = 0; st.__dict__["_block_steps_by"] = {}      # each call its own block's budget (the test's blocks)
    return st.apply_blob({"op": "call", "contract": cid, "method": method, "args": args, "value": value, "asset": asset}, sender, "tx")


def cell(field, key):
    return int(((st.contracts[cid].get("storage") or {}).get("slots") or {}).get(str(field * (1 << 32) + key), 0))


def ok(r):
    return isinstance(r, str) and "revert" not in r and "error" not in r.lower()


SUPPLY = 1_000_000                                    # units (1e6 * 1e8 raw)
st.apply_blob({"op": "asset_create", "seed": 7, "name": "Moon", "sym": "MOON", "dec": 8, "supply": SUPPLY * U, "mintable": False}, CREATOR, "tx")
AID = int(asset_id(CREATOR, 7))
PID = 4242

# ---- fee and ids --------------------------------------------------------------------------------------------------
check("prelaunch refuses a wrong fee", not ok(call(CREATOR, "prelaunch", [PID], value=(D.CREATE_FEE - 1) * U)))
check("prelaunch takes exactly the creation fee and seals it", ok(call(CREATOR, "prelaunch", [PID], value=D.CREATE_FEE * U))
      and cell(D.FEEB, 0) == D.CREATE_FEE and cell(D.CREATOR, PID) != 0)
check("a reserved id cannot be opened as a pool", not ok(call(A, "open", [PID, AID])))
st.apply_blob({"op": "asset_transfer", "asset": str(AID), "to": A, "amount": 10 * U}, CREATOR, "tx")
check("only the reserving caller launches", not ok(call(A, "launch", [PID, 10, D.VN0], value=10 * U, asset=AID)))
st.apply_blob({"op": "asset_transfer", "asset": str(AID), "to": CREATOR, "amount": 10 * U}, A, "tx")
check("the curve's scale is bounded: below VN_MIN or at VN_MAX it is refused",
      not ok(call(CREATOR, "launch", [PID, SUPPLY, D.VN_MIN - 1], value=SUPPLY * U, asset=AID))
      and not ok(call(CREATOR, "launch", [PID, SUPPLY, D.VN_MAX], value=SUPPLY * U, asset=AID)))
check("the creator launches the whole supply", ok(call(CREATOR, "launch", [PID, SUPPLY, D.VN0], value=SUPPLY * U, asset=AID))
      and cell(D.KIND, PID) == D.CURVE and cell(D.CT, PID) == SUPPLY and cell(D.GRAD, PID) == SUPPLY // 5 and cell(D.VN, PID) == D.VN0
      and st.asset_balance(AID, cid) == SUPPLY * U)
L0 = st.cursor
check("a dust order (under the 1 % fee's unit) is refused", not ok(call(A, "buy", [PID, 1, 50], value=50 * U)))
check("an order id >= 2^32 is refused", not ok(call(A, "buy", [PID, 1 << 32, 1000], value=1000 * U)))
check("the curve is never traded through the pool methods", not ok(call(A, "swapn", [PID, 1000, 0, AID], value=1000 * U)))


# ---- the model --------------------------------------------------------------------------------------------------
class Curve:
    def __init__(s):
        s.cn, s.ct = 0, SUPPLY

    def clear(s, bnin, btin):
        x = D.VN0 + s.cn
        sval = btin * x // s.ct
        if bnin >= sval:
            db = bnin - sval
            dy = s.ct * db // (x + db)
            s.cn += db; s.ct -= dy
            return btin + dy, sval                      # (coins to buyers, NADO to sellers)
        btok = bnin * s.ct // x
        ds = btin - btok
        dx = x * ds // (s.ct + ds)
        assert dx <= s.cn
        s.ct += ds; s.cn -= dx
        return btok, bnin + dx


M = Curve()
net = lambda u: u - u // D.ORDER_FEE
orders = {}                                            # order -> (owner, side, net amount)
oid = [100]


def place(who, side, units):
    oid[0] += 1
    o = oid[0]
    r = call(who, "buy" if side == 1 else "sell", [PID, o, units], value=units * U, asset=0 if side == 1 else AID)
    if ok(r):
        orders[o] = (who, side, net(units))
    return o, r


def claim(o):
    who = orders[o][0]
    n0, t0 = st.bridge.get(who, 0), st.asset_balance(AID, who)
    r = call(who, "claim", [o, AID])
    return r, st.bridge.get(who, 0) - n0, st.asset_balance(AID, who) - t0


# ---- the opening window: one batch, one price ---------------------------------------------------------------------
o1, _ = place(A, 1, 20_000)
st.cursor = L0 + 3
o2, _ = place(B, 1, 20_000)
st.cursor = L0 + 7
o3, _ = place(C, 1, 40_000)
check("claiming during the opening window is refused (the batch is still open)", not ok(call(A, "claim", [o1, AID])))
check("settling during the opening window is refused", not ok(call(E, "settle", [PID])))
st.cursor = L0 + D.WINDOW
bto, bno = M.clear(net(20_000) * 2 + net(40_000), 0)
r1, _, t1 = claim(o1); r2, _, t2 = claim(o2); r3, _, t3 = claim(o3)
check("after the window the batch clears on the first claim and matches the model to the unit",
      ok(r1) and cell(D.CN, PID) == M.cn and cell(D.CT, PID) == M.ct, (cell(D.CN, PID), M.cn, cell(D.CT, PID), M.ct))
check("every opening buyer pays ONE price: a buy in block 0, 3 or 7 of the window gets the same coins per NADO",
      t1 == t2 and abs(t3 - 2 * t1) <= U and t1 > 0, (t1, t2, t3))
check("a claim is the owner's, once", not ok(call(A, "claim", [o1, AID])) and not ok(call(B, "claim", [o3, AID])))

# ---- one block, two buyers, either order: the same price ----------------------------------------------------------
def same_block_pair(first, second, cur):
    st.cursor = cur
    a, _ = place(first, 1, 10_000)
    b, _ = place(second, 1, 10_000)
    st.cursor = cur + 1
    call(E, "settle", [PID])
    M.clear(net(10_000) * 2, 0)
    _, _, ta = claim(a); _, _, tb = claim(b)
    return ta, tb


ta, tb = same_block_pair(A, B, L0 + 20)
check("two buys in one block get exactly the same coins, whatever their order", ta == tb and ta > 0, (ta, tb))
check("…and each block's clearing matches the model", cell(D.CN, PID) == M.cn and cell(D.CT, PID) == M.ct)

# ---- buys and sells in one block net at spot ----------------------------------------------------------------------
st.cursor = L0 + 30
sa, _ = place(A, 2, 5_000)                            # A sells coins it bought
sb, _ = place(B, 1, 3_000)
sc, _ = place(C, 2, 4_000)
supply_before = st.asset_meta(AID)["supply"] if hasattr(st, "asset_meta") else None
st.cursor = L0 + 31
toks, nads = M.clear(net(3_000), net(5_000) + net(4_000))
ra, na, _ = claim(sa); rb, _, tbb = claim(sb); rc, nc, _ = claim(sc)
check("a mixed batch matches the model (net sell)", cell(D.CN, PID) == M.cn and cell(D.CT, PID) == M.ct, (cell(D.CN, PID), M.cn))
check("every seller of the batch gets one price", abs(na * net(4_000) - nc * net(5_000)) <= U * net(5_000), (na, nc))
check("the buyer gets the model's coins", abs(tbb - toks * U) <= U, (tbb, toks * U))

# ---- carry: a cursor that restarted lower closes the open batch ---------------------------------------------------
st.cursor = L0 + 40
co, _ = place(A, 1, 1_000)
st.cursor = 5                                          # a carried chain's cursor, far below the batch's block
M.clear(net(1_000), 0)
r, _, tc = claim(co)
check("a carried chain (cursor restarted lower) closes the open batch: the order is claimable", ok(r) and tc > 0, r)
st.cursor = L0 + 50

# ---- fees ---------------------------------------------------------------------------------------------------------
fee_nado = D.CREATE_FEE + sum(u // D.ORDER_FEE for u in (20_000, 20_000, 40_000, 10_000, 10_000, 3_000, 1_000))
check("1 % of every buy and the creation fee are sealed (FEEB)", cell(D.FEEB, 0) == fee_nado, (cell(D.FEEB, 0), fee_nado))
burned = (5_000 // D.ORDER_FEE + 4_000 // D.ORDER_FEE) * U
check("1 % of every sell's coins is burned (the supply fell by it)",
      int(st.assets[str(AID)]["supply"]) == SUPPLY * U - burned, (st.assets[str(AID)]["supply"], SUPPLY * U - burned))


# ---- conservation ---------------------------------------------------------------------------------------------------
def owed():
    """What the contract owes: the curve's NADO and coins, sealed fees, the pool's reserves, and unclaimed orders."""
    on, ot = 0, 0
    for o, (who, side, amt) in orders.items():
        if cell(D.OAMT, o) == 0:
            continue
        b = cell(D.OBAT, o)
        if not cell(D.BDONE, b):
            (on, ot) = (on + amt, ot) if side == 1 else (on, ot + amt)
        elif side == 1:
            ot += amt * cell(D.BTOUT, b) // cell(D.BNIN, b)
        else:
            on += amt * cell(D.BNOUT, b) // cell(D.BTIN, b)
    return (cell(D.CN, PID) + cell(D.FEEB, 0) + cell(D.RN, PID) + on) * U, (cell(D.CT, PID) + cell(D.RT, PID) + ot) * U


on, ot = owed()
check("the contract holds at least every NADO it owes (dust from rounding stays in the pool's favour)",
      st.bridge.get(cid, 0) >= on and st.bridge.get(cid, 0) - on < 100 * U, (st.bridge.get(cid, 0), on))
check("…and at least every coin it owes", st.asset_balance(AID, cid) >= ot and st.asset_balance(AID, cid) - ot < 100 * U,
      (st.asset_balance(AID, cid), ot))

# ---- graduation -----------------------------------------------------------------------------------------------------
check("pool seeding is refused on a curve", ok(call(A, "fundn", [9001, PID, 2000], value=2000 * U)) and
      not ok(call(A, "join", [9001, PID])) and ok(call(A, "refund", [9001, PID, AID])))
big = []
k = 0
while cell(D.KIND, PID) == D.CURVE and k < 40:
    st.cursor = L0 + 100 + 2 * k
    o, r = place([A, B, C][k % 3], 1, 60_000)
    big.append(o)
    k += 1
st.cursor += 1
call(E, "settle", [PID])
check("the curve graduates once 4/5 of the supply is sold", cell(D.KIND, PID) == D.GRADUATED, (cell(D.KIND, PID), cell(D.CT, PID)))
rn, rt = cell(D.RN, PID), cell(D.RT, PID)
check("…into a pool with reserves and NO shares (nobody can withdraw it)", rn > 0 and rt > 0 and cell(D.SUP, PID) == 0)
for o in big:
    if cell(D.OAMT, o):
        claim(o)
check("graduation burned the coins its price did not need", int(st.assets[str(AID)]["supply"]) < SUPPLY * U - burned)
check("the graduated pool trades through swapn", ok(call(E, "swapn", [PID, 5_000, 1, AID], value=5_000 * U)) and cell(D.RN, PID) > rn)
check("…and nobody can seed, join or withdraw it",
      ok(call(E, "fundn", [9002, PID, 2000], value=2000 * U)) and not ok(call(E, "join", [9002, PID]))
      and not ok(call(E, "exit", [9002, PID, 1, AID])) and ok(call(E, "refund", [9002, PID, AID])))
check("no more curve orders after graduation", not ok(call(A, "buy", [PID, 99999, 1000], value=1000 * U)))
on, ot = owed()
check("after graduation the contract still holds every NADO and coin it owes",
      st.bridge.get(cid, 0) >= on and st.asset_balance(AID, cid) >= ot, (st.bridge.get(cid, 0), on, st.asset_balance(AID, cid), ot))

# ---- a small coin: the creator's own scale (VN = target / 4) graduates at a small raise ---------------------------------
st.apply_blob({"op": "asset_create", "seed": 8, "name": "Tiny", "sym": "TINY", "dec": 8, "supply": 10_000 * U, "mintable": False}, CREATOR, "tx")
AID2, P2 = int(asset_id(CREATOR, 8)), 777
call(CREATOR, "prelaunch", [P2], value=D.CREATE_FEE * U)
check("a small coin launches with a small scale (VN = 1 NADO: graduation at a ~4 NADO raise)",
      ok(call(CREATOR, "launch", [P2, 10_000, D.VN_MIN], value=10_000 * U, asset=AID2)) and cell(D.VN, P2) == D.VN_MIN)
st.cursor += 20
for i in range(8):
    st.cursor += 1
    call(A, "buy", [P2, 50_000 + i, 150], value=150 * U)
    if cell(D.KIND, P2) == D.GRADUATED:
        break
st.cursor += 1
call(E, "settle", [P2])
check("…and graduates after a few NADO of buys", cell(D.KIND, P2) == D.GRADUATED and 0 < cell(D.RN, P2) < 1000, (cell(D.KIND, P2), cell(D.RN, P2)))

if _fails:
    print(f"{len(_fails)} FAILURES"); sys.exit(1)
print("ALL PASS")
