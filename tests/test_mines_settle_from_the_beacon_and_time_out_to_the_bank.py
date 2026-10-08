"""Mines settles each round from the epoch beacon and times an abandoned game out to the BANK.

  * a pick binds the round to its beacon epoch (gb = epoch(cursor) + 2, gh = gb * 60 - 1); resolve refuses before
    epoch gb begins and then draws from BEACON(gb) + g, exactly the in-clear reference (round_seed / resolve_hit);
  * every pick re-binds, so a second round draws from its own later epoch;
  * a round picked by the code BEFORE the upgrade (gb == 0) still resolves from BHASH(gh) + BHASH(gh + 1) + g;
  * reap inside the 18,000-block window reverts, and a winning round resolved late in the window still cashes out;
  * reap after the window pays NOBODY: the stake stays in the pot and joins the bankroll, the reservation (gq while
    a round is pending, gv otherwise) is released, gd = 2, no hit; resolve / cashout after a reap revert;
  * the view exposes the beacon epoch as "gb" and the hit as "gx"; tc returns to 0 once every game is settled.

Offline: a throwaway ExecState, the old contract taken from git (PRE_RELEASE) and upgraded in place to the new one.
Run: python3 tests/test_mines_settle_from_the_beacon_and_time_out_to_the_bank.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-mines-beacon-")    # never the live database (assign, not setdefault)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the last commit before the beacon / commit-reveal release: HEAD stops being "the old code" once it lands, and
# main only ever fast-forwards, so this commit stays readable
PRE_RELEASE = "29dfdc7e"
sys.path.insert(0, ROOT)

import importlib.util                                                  # noqa: E402
import subprocess                                                      # noqa: E402

from execnode.state import ExecState                                   # noqa: E402
from execnode.stark import field as F                                  # noqa: E402
from execnode.games import mines                                       # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


# the contract as it was before the beacon / timeout-to-bank rule (fallback: the current module, which still
# exercises everything but the legacy-round case through the old code path)
def _old_module():
    try:
        src = subprocess.run(["git", "-C", ROOT, "show", PRE_RELEASE + ":execnode/games/mines.py"], capture_output=True,
                             text=True, check=True).stdout
    except Exception:
        return None
    if "beacon_bind" in src:          # that commit already carries the new rule: no old code to replay
        return None
    path = os.path.join(os.environ["HOME"], "mines_old.py")
    with open(path, "w") as f:
        f.write(src)
    spec = importlib.util.spec_from_file_location("mines_old", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


A = "ndoAAAA" + "A" * 41      # bank
B = "ndoBBBB" + "B" * 41      # player
C = "ndoCCCC" + "C" * 41      # a third party who reaps
T = 5

old = _old_module()
st = ExecState(os.path.join(os.environ["HOME"], "s.json"))
st.cursor = 6000 + 17                                                  # epoch 100
st.credit_deposit(A, 10 ** 12); st.credit_deposit(B, 10 ** 10); st.credit_deposit(C, 10 ** 6)
first = old or mines
code0 = first.build()
st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code0, "abi": first.ABI, "nonce": "n"}, A, "d")
cid = st.contract_id(A, code0, "n")
_n = [0]


def call(m, args, who=B, value=None):
    _n[0] += 1
    blob = {"op": "call", "contract": cid, "method": m, "args": args}
    if value:
        blob["value"] = value
    return str(st.apply_blob(blob, who, f"{m}-{_n[0]}"))


def rd(f, k):
    return int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))


def reverts(r):
    return "revert" in r.lower() or r.startswith("skip")


call("open", [T], A, 10 ** 11)
STAKE = 1_000_000

# ---- a round picked under the OLD code, pending when the upgrade lands --------------------------------------
GL = 501
call("bet", [GL, T, 3], B, STAKE)
call("pick", [GL, 2])
legacy_gh = rd(mines.GH, GL)
if old is not None:
    check("old code stamped gh = cursor + 2 and no beacon epoch", legacy_gh == st.cursor + 2 and rd(mines.GB, GL) == 0,
          (legacy_gh, rd(mines.GB, GL)))
    r = st.apply_blob({"op": "upgrade", "contract": cid, "code": mines.build(), "abi": mines.ABI}, A, "up")
    check("the contract upgrades in place (same cid, storage kept)", "upgrade" in str(r) and rd(mines.GG, GL) == T, r)
else:
    # no old code to replay: write the legacy round's shape straight into storage (gh = cursor + 2, gb = 0)
    slots = st.contracts[cid]["storage"]["slots"]
    slots[str(mines.GB * (1 << 32) + GL)] = "0"
    legacy_gh = st.cursor + 2
    slots[str(mines.GH * (1 << 32) + GL)] = str(legacy_gh)

st.block_hashes[legacy_gh] = (1 << 200) + 77
st.block_hashes[legacy_gh + 1] = (1 << 190) + 99
st.cursor = legacy_gh + 2
call("resolve", [GL])
q_legacy = mines.round_seed(GL, bh0=st.block_hashes[legacy_gh], bh1=st.block_hashes[legacy_gh + 1])
want = mines.resolve_hit(q_legacy, 0, 3, 2)
check("a round picked before the upgrade (gb == 0) resolves from BHASH(gh) + BHASH(gh+1) + g",
      rd(mines.GX, GL) == want and (rd(mines.GD, GL) == 1 if want else rd(mines.GP, GL) == 2),
      (rd(mines.GX, GL), want, rd(mines.GD, GL), rd(mines.GP, GL)))
if not want:                                        # safe: take it home so the table settles to tc == 0
    call("cashout", [GL])

# ---- a beacon round ----------------------------------------------------------------------------------------
st.cursor = 6600 + 5                                                  # epoch 110
GN, NM, CNT = 502, 5, 4
call("bet", [GN, T, NM], B, STAKE)
call("pick", [GN, CNT])
gb = rd(mines.GB, GN)
check("pick binds gb = epoch(cursor) + 2", gb == 112, gb)
check("pick sets gh = gb * 60 - 1", rd(mines.GH, GN) == gb * 60 - 1, rd(mines.GH, GN))
check("pick reserves the round's potential gq", rd(mines.GQ, GN) == mines.multiplier(STAKE, 0, NM, CNT), rd(mines.GQ, GN))
st.cursor = gb * 60 - 1
r = call("resolve", [GN])
check("resolve refuses before the beacon epoch begins", reverts(r) and rd(mines.GH, GN) != 0, r)


def beacon_with(g, gp, n, cnt, safe):
    for k in range(1, 5000):
        b = (1 << 255) + k * 7919
        hit = mines.resolve_hit(mines.round_seed(g, beacon=b), gp, n, cnt)
        if (hit == 0) == safe:
            return b, hit
    raise RuntimeError("no beacon found")


# a SAFE outcome, resolved late in the window (the beacon is known; nobody resolved) — still the player's win
B1, _ = beacon_with(GN, 0, NM, CNT, True)
st.beacons[gb] = B1
st.block_hashes.clear()            # a beacon round must not need any block hash
ge = rd(mines.GE, GN)
st.cursor = ge + 18000
r = call("reap", [GN], C)
check("reap inside the 18,000-block window reverts", reverts(r) and rd(mines.GD, GN) == 0, r)
call("resolve", [GN], C)                                              # permissionless
check("a beacon round resolves from BEACON(gb) + g (reference: safe)",
      rd(mines.GX, GN) == 0 and rd(mines.GP, GN) == CNT and rd(mines.GH, GN) == 0 and rd(mines.GV, GN) == mines.multiplier(STAKE, 0, NM, CNT),
      (rd(mines.GX, GN), rd(mines.GP, GN), rd(mines.GV, GN)))

# a second round re-binds to its own epoch and draws a mine
st.cursor = ge + 18000 + 30
call("pick", [GN, 3])
gb2 = rd(mines.GB, GN)
check("every pick re-binds to a fresh epoch", gb2 == st.cursor // 60 + 2 and gb2 > gb, (gb2, gb))
B2, hit2 = beacon_with(GN, CNT, NM, 3, False)
st.beacons[gb2] = B2
st.cursor = gb2 * 60
tk0 = rd(mines.TK, T)
call("resolve", [GN])
check("the second round's draws are BEACON(gb2) + g at pick indexes gp + i (reference: hit at %d)" % hit2,
      rd(mines.GX, GN) == hit2 and rd(mines.GD, GN) == 1 and rd(mines.TK, T) == tk0 + STAKE,
      (rd(mines.GX, GN), hit2, rd(mines.GD, GN)))

# ---- a winning round cashes out inside the window ----------------------------------------------------------
GW_ = 503
call("bet", [GW_, T, 2], B, STAKE)
call("pick", [GW_, 2])
gbw = rd(mines.GB, GW_)
Bw, _ = beacon_with(GW_, 0, 2, 2, True)
st.beacons[gbw] = Bw
st.cursor = rd(mines.GE, GW_) + 17999
call("resolve", [GW_], C)
bal = st.bridge.get(B, 0)
call("cashout", [GW_])
check("a win resolved late in the window still cashes out its full value",
      st.bridge.get(B, 0) - bal == mines.multiplier(STAKE, 0, 2, 2) and rd(mines.GD, GW_) == 1, st.bridge.get(B, 0) - bal)

# ---- TIMEOUT -> BANK: a pending round nobody resolved ------------------------------------------------------
GT = 504
call("bet", [GT, T, 4], B, STAKE)
call("pick", [GT, 3])
gq = rd(mines.GQ, GT)
tp0, tc0, tk0 = rd(mines.TP, T), rd(mines.TC, T), rd(mines.TK, T)
pb, cb = st.bridge.get(B, 0), st.bridge.get(C, 0)
st.cursor = rd(mines.GE, GT) + 18001
call("reap", [GT], C)
check("timeout: nobody is paid (player and reaper balances unchanged)",
      st.bridge.get(B, 0) == pb and st.bridge.get(C, 0) == cb, (st.bridge.get(B, 0) - pb, st.bridge.get(C, 0) - cb))
check("timeout: the stake stays in the pot (tp unchanged) and joins the bankroll (tk += gs)",
      rd(mines.TP, T) == tp0 and rd(mines.TK, T) == tk0 + STAKE, (rd(mines.TP, T) - tp0, rd(mines.TK, T) - tk0))
check("timeout: a pending round's reservation gq is released", rd(mines.TC, T) == tc0 - gq, (tc0 - rd(mines.TC, T), gq))
check("timeout: the game is marked gd = 2 with no hit", rd(mines.GD, GT) == 2 and rd(mines.GX, GT) == 0,
      (rd(mines.GD, GT), rd(mines.GX, GT)))
st.beacons[rd(mines.GB, GT)] = (1 << 255) + 3
check("a reaped game cannot be resolved", reverts(call("resolve", [GT], C)))
check("a reaped game cannot be cashed out", reverts(call("cashout", [GT])))
check("a reaped game cannot be reaped twice", reverts(call("reap", [GT], C)))

# ---- TIMEOUT -> BANK: an idle game holding a won value (no round pending) ---------------------------------
GI = 505
call("bet", [GI, T, 1], B, STAKE)
call("pick", [GI, 1])
Bi, _ = beacon_with(GI, 0, 1, 1, True)
st.beacons[rd(mines.GB, GI)] = Bi
st.cursor = rd(mines.GH, GI) + 1
call("resolve", [GI])
gv = rd(mines.GV, GI)
tp0, tc0, tk0, pb = rd(mines.TP, T), rd(mines.TC, T), rd(mines.TK, T), st.bridge.get(B, 0)
st.cursor = rd(mines.GE, GI) + 18001
call("reap", [GI], C)
check("timeout of an idle game: value gv is released from tc, stake to the bank, nobody paid",
      rd(mines.TC, T) == tc0 - gv and rd(mines.TK, T) == tk0 + STAKE and rd(mines.TP, T) == tp0
      and st.bridge.get(B, 0) == pb and rd(mines.GD, GI) == 2, (tc0 - rd(mines.TC, T), gv))

check("the table balances: tc == 0 once every game is settled", rd(mines.TC, T) == 0, rd(mines.TC, T))
maps = mines.ABI["_view"]["maps"]
check('the view exposes the beacon epoch as "gb" and the hit as "gx"',
      maps["gb"]["field"] == mines.GB == 12 and maps["gx"]["field"] == mines.GX == 22, (maps["gb"], maps["gx"]))
used = {v["field"] for k, v in maps.items() if v.get("index") == "games"}
check("gb sits on a field no other game map uses", list(v["field"] for v in maps.values()).count(mines.GB) == 1, used)

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
