"""Battleship, Hexholm and Scrapline cross a reroll once nothing is in flight; a Sovereign world with a log REFUSES it
(tools/carry.py, tools/alphanet6_carryforward.exec_genesis, doc/stwo/g5-carry.md). Operator rule: everything is carried
losslessly, and what cannot be carried refuses — never a reset.

This is the v2 -> v2 carry every reroll from generation 29 on runs: live-shaped exec states (zkvm2, the BLAKE2s exec
root) driven through the REAL contracts, carried by the builder's exec_genesis at the old chain's tip and by
tools/carry.py on a saved copy, the new chain loaded by the real genesis loader. (Replaces the gen-28 -> gen-29 test G9
slice 3a retired with the field VM; SCHEDULED_CLEANUPS.md 2026-10-27.)
  * battleship: an open lobby, a game in play (its board roots still checked shot by shot) and a decided-but-unpaid
    game (the winner's fleet still to be proven against its root) each block the carry, naming the call that ends it;
    claimed / cancelled, the contract carries — every slot unchanged: the settled roots, stake, the daily board's
    resolved anchor and its claim word (>= 2^32);
  * hexholm: a lobby and a game in play block; settled (one seat's commitment left unrevealed — a paid game's audit,
    which does not block), it carries with a recorded move >= 2^32 and the commitments kept verbatim, and the daily
    board's UNRESOLVED anchor re-pinned to a new-chain block (the one slot that moves); on the new chain that anchor
    resolves from the new chain's own block hash;
  * scrapline: a lobby and a game in play block; agreed, it carries with its split-run claim words and a large move;
  * sovereign: a world with a log re-derives every raid from old-chain block hashes and settles its economy against
    the live cursor, so it refuses the carry (no carry rule) through both entry points; an empty world carries as its
    build.

Run: python3 tests/test_battleship_hexholm_and_scrapline_cross_a_reroll_at_rest_and_a_sovereign_world_refuses_it.py
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-carry-hidden-boards-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
HOME = os.environ["HOME"]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["NADO_EXEC_GENESIS"] = os.path.join(HOME, "exec_genesis.json")
import json
import random
import subprocess
import time

import protocol as PR
from execnode.state import ExecState
from execnode.games import battleship as BS, hexholm as HX, scrapline as SC, sovereign as SV, _lib
from execnode import exec_genesis as EG
from tools import carry
import tools.alphanet6_carryforward as C

import _harness
T = _harness.Report()
A, B = "ndoA" + "a" * 44, "ndoB" + "b" * 44
NOW = int(time.time())
DAY = NOW // 86400
_n = [0]


def old_chain():
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=HOME), "old.json"))
    st.cursor, st.block_ts = 150_000, NOW
    st.block_hashes = {h: h * 1_000_003 + 9 for h in range(140_000, 160_000)}     # values > 2^32, like real hashes
    for w in (A, B):
        st.credit_deposit(w, 10 ** 12)
    return st


def deploy(st, mod):
    code = mod.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": mod.ABI, "nonce": "n"}, A, "d" + mod.__name__)
    return st.contract_id(A, code, "n")


def call(st, cid, who, m, args, value=None):
    _n[0] += 1
    p = {"op": "call", "contract": cid, "method": m, "args": args}
    if value:
        p["value"] = value
    r = st.apply_blob(p, who, f"{m}-{_n[0]}")
    return "ok" in str(r), r


def slots(st, cid):
    return {int(k): int(v) for k, v in (st.contracts[cid]["storage"].get("slots") or {}).items()}


def rd(st, cid, f, k):
    return slots(st, cid).get((f << 32) + k, 0)


def try_carry(st, cid):
    """(record, None) or (None, the refusal) — the reroll builder's carry of this contract at the old chain's tip."""
    try:
        recs, _kept, _reg = C.exec_genesis({cid: st.contracts[cid]}, {cid: int(st.bridge.get(cid, 0))}, st.zk_addrs,
                                           st.cursor)
        return recs[cid], None
    except carry.Refused as e:
        return None, str(e)


def carry_cli(st):
    """tools/carry.py exactly as the operator runs it: on a saved COPY of the exec node's state file. (exit, output)"""
    st.save()
    cp = st.path + ".copy.json"
    shutil.copyfile(st.path, cp)
    p = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "carry.py"), cp], capture_output=True, text=True,
                       timeout=900)
    return p.returncode, p.stdout + p.stderr


def carried_whole(st, cid, rec, mod, kept, moved=()):
    """every old slot crossed under its own key with its own value (one VM: nothing re-encoded) except the (field, id)
    heights in `moved`; `kept` {(f, k): v} present verbatim; the code is the module's build"""
    old, new = slots(st, cid), {int(k): int(v) for k, v in rec["storage"]["slots"].items()}
    skip = {(f << 32) + k for f, k in moved}
    return (set(old) == set(new) and all(new[k] == v for k, v in old.items() if k not in skip)
            and all(new.get((f << 32) + k) == v for (f, k), v in kept.items())
            and rec["code"] == json.loads(json.dumps(mod.build())))


# ---- battleship -----------------------------------------------------------------------------------------------------
st = old_chain()
bc = deploy(st, BS)
rng = random.Random(7)
shipsA = [(0, 0), (10, 0), (20, 0), (30, 0), (40, 0)]
shipsB = [(55, 0), (4, 1), (9, 1), (77, 0), (90, 0)]
bA, bB = BS.board_from_ships(shipsA), BS.board_from_ships(shipsB)
seedA, seedB = rng.randint(1, 2 ** 60), rng.randint(1, 2 ** 60)
sB = BS.salts_from_seed(seedB)
rootA, rootB = BS.build_root(bA, BS.salts_from_seed(seedA))[0], BS.build_root(bB, sB)[0]
G, L = 42, 7
call(st, bc, A, "open", [L, rootA], 300)
call(st, bc, A, "open", [G, rootA], 500)
why = BS.carry_in_flight(st.contracts[bc]["storage"])
T.check("battleship: an open lobby blocks the carry, naming cancel()",
        len(why) == 2 and all("waits for an opponent" in w for w in why) and "cancel(7)" in why[0], why)
code, out = carry_cli(st)
T.check("battleship: tools/carry.py on the saved state refuses the lobby", code != 0 and "cancel(7)" in out, out[-600:])
call(st, bc, A, "cancel", [L])
call(st, bc, B, "join", [G, rootB], 500)
cell = [c for c in range(100) if bB[c]][0]
call(st, bc, A, "fire", [G, cell])
isS, salt, flat = BS.make_proof(bB, sB, cell)
ok, r = call(st, bc, B, "answer", [G, isS, salt] + flat)
why = BS.carry_in_flight(st.contracts[bc]["storage"])
_, msg = try_carry(st, bc)
T.check("battleship: a game in play blocks — its roots are still checked shot by shot — and the carry refuses",
        ok and why == [why[0]] and "game 42 is in play" in why[0] and "resign(42)" in why[0]
        and msg is not None and "in flight" in msg and "game 42" in msg, (r, why, msg))
call(st, bc, B, "resign", [G])
why = BS.carry_in_flight(st.contracts[bc]["storage"])
_, msg = try_carry(st, bc)
T.check("battleship: decided but unpaid blocks (the winner's fleet is still to be proven against its root)",
        len(why) == 1 and "decided but unpaid" in why[0] and "claim(42" in why[0] and "forfeit(42)" in why[0]
        and msg is not None, (why, msg))
ok, r = call(st, bc, A, "claim", [G] + [x for ao in shipsA for x in ao] + [seedA])
words = [(1 << 40) + 3] + [0] * (BS.DAILY_WORDS - 1)
okp, rp = call(st, bc, A, "post", [DAY, 500, 5] + words)
call(st, bc, A, "anchor", [DAY])
pin = rd(st, bc, BS.A_H, DAY)
st.cursor = pin + 1
call(st, bc, B, "anchor", [DAY])
av = rd(st, bc, BS.A_V, DAY)
T.check("battleship: claimed and cancelled, at rest: a daily claim with a word >= 2^32 and a resolved anchor",
        ok and okp and rd(st, bc, BS.SD, G) == 1 and BS.carry_in_flight(st.contracts[bc]["storage"]) == []
        and av != 0 and av >= 1 << 32, (r, rp, av))
rec, msg = try_carry(st, bc)
T.check("battleship: the carry succeeds — every slot unchanged; roots, stake, resolved anchor and claim word verbatim",
        msg is None and carried_whole(st, bc, rec, BS, {(BS.R1, G): rootA, (BS.R2, G): rootB, (BS.ST, G): 500,
                                                         (BS.A_V, DAY): av, (BS.EW_BASE, 0): words[0], (BS.A_H, DAY): pin}),
        msg)
code, out = carry_cli(st)
T.check("battleship: ...and tools/carry.py carries the saved state", code == 0 and "contracts carried: 1" in out, out[-600:])

# ---- hexholm ----------------------------------------------------------------------------------------------------------
st = st_hx = old_chain()
hc = deploy(st, HX)
XA, XB = 0x1234_5678_9ABC_DEF0, 0x0FED_CBA9_8765_4321
CA, CB = _lib.vm_hash([XA % _lib.vm_mod()]), _lib.vm_hash([XB % _lib.vm_mod()])
G = 77
call(st, hc, A, "open", [G, 2, CA], 1000)
why = HX.carry_in_flight(st.contracts[hc]["storage"])
T.check("hexholm: a lobby blocks the carry, naming cancel()",
        len(why) == 1 and "lobby (1 of 2 seats)" in why[0] and "cancel(77)" in why[0], why)
call(st, hc, B, "join", [G, CB], 1000)
ENC = (1 << 45) + 11
ok, r = call(st, hc, A, "move", [G, ENC, 0])
why = HX.carry_in_flight(st.contracts[hc]["storage"])
_, msg = try_carry(st, hc)
T.check("hexholm: a game in play blocks (stakes on an old-chain clock, commitments unrevealed) and the carry refuses",
        ok and len(why) == 1 and "game 77 is in play" in why[0] and "abort(77)" in why[0] and msg is not None,
        (r, why, msg))
call(st, hc, B, "resign", [G])
okr, rr = call(st, hc, A, "reveal", [G, XA])                  # B never reveals: a paid game's audit, not a blocker
hwords = [(1 << 33) + 5] + [0] * (HX.CLAIM_WORDS - 1)
okp, rp = call(st, hc, A, "post", [DAY, 100, 3] + hwords)
call(st, hc, A, "anchor", [DAY])                             # pinned on the old chain, left unresolved
pin = rd(st, hc, HX.A_H, DAY)
T.check("hexholm: settled by resignation, it is at rest although one seat's commitment is unrevealed",
        okr and okp and rd(st, hc, HX.SD, G) == 1 and rd(st, hc, HX.RL_BASE + 2, G) == XA & 0xFFFFFFFF
        and rd(st, hc, HX.RL_BASE + 4, G) == 0 and HX.carry_in_flight(st.contracts[hc]["storage"]) == []
        and pin > 100_000 and rd(st, hc, HX.A_V, DAY) == 0, (rr, rp, pin))
hx_rec, msg = try_carry(st, hc)
new_pin = int(hx_rec["storage"]["slots"].get(str((HX.A_H << 32) + DAY), 0)) if hx_rec else None
T.check("hexholm: the carry succeeds — move, commitments and claim word verbatim; only the unresolved anchor re-pinned",
        msg is None and carried_whole(st, hc, hx_rec, HX, {(HX.MV_BASE, G): ENC, (HX.C_BASE + 1, G): CA,
                                                            (HX.C_BASE + 2, G): CB, (HX.EW_BASE, 0): hwords[0]},
                                      moved=[(HX.A_H, DAY)])
        and _lib.CARRY_PIN_FLOOR <= new_pin < 100, (msg, new_pin))

# ---- scrapline --------------------------------------------------------------------------------------------------------
st = old_chain()
sc = deploy(st, SC)
G = 9
call(st, sc, A, "open", [G], 700)
why = SC.carry_in_flight(st.contracts[sc]["storage"])
T.check("scrapline: a lobby blocks the carry, naming cancel()", why == [why[0]] and "cancel(9)" in why[0], why)
call(st, sc, B, "join", [G], 700)
ENC = (1 << 40) + 1
ok, r = call(st, sc, B, "move", [G, ENC, 0])
why = SC.carry_in_flight(st.contracts[sc]["storage"])
_, msg = try_carry(st, sc)
T.check("scrapline: a game in play blocks and the carry refuses",
        ok and len(why) == 1 and "game 9 is in play" in why[0] and "abort(9)" in why[0] and msg is not None,
        (r, why, msg))
call(st, sc, A, "agree", [G, 2])
call(st, sc, B, "agree", [G, 2])
swords = [(1 << 49) + 1, 0, 0, 0, 0, (1 << 48) + 2, 0, 0]
okp, rp = call(st, sc, A, "post", [DAY, 100, 12] + swords)
call(st, sc, A, "anchor", [DAY])
pin = rd(st, sc, SC.A_H, DAY)
st.cursor = pin + 1
call(st, sc, A, "anchor", [DAY])
av = rd(st, sc, SC.A_V, DAY)
T.check("scrapline: agreed, at rest, with claim words in both runs and a resolved anchor",
        okp and rd(st, sc, SC.SD, G) == 1 and SC.carry_in_flight(st.contracts[sc]["storage"]) == []
        and av >= 1 << 32, (rp, av))
rec, msg = try_carry(st, sc)
T.check("scrapline: the carry succeeds — every slot unchanged; move, claim words and anchor verbatim",
        msg is None and carried_whole(st, sc, rec, SC, {(SC.MV_BASE, G): ENC, (SC.E_A, 0): swords[0],
                                                         (SC.E_A2, 0): swords[5], (SC.A_V, DAY): av}), msg)

# ---- sovereign --------------------------------------------------------------------------------------------------------
st = old_chain()
vc = deploy(st, SV)
rec, msg = try_carry(st, vc)
T.check("sovereign: an empty world carries as its build",
        msg is None and rec["code"] == json.loads(json.dumps(SV.build())) and not rec["storage"].get("slots"),
        (msg, rec and rec["storage"]))
ok, r = call(st, vc, A, "act", [5, 0, 0])
rec, msg = try_carry(st, vc)
T.check("sovereign: a world with a log refuses (its fold reads old-chain block hashes and the live cursor)",
        ok and msg is not None and "no carry rule" in msg and not hasattr(SV, "CARRY_STORAGE")
        and not hasattr(SV, "carry_in_flight") and not hasattr(SV, "carry_rebase"), (r, msg))
code, out = carry_cli(st)
T.check("sovereign: ...and tools/carry.py on the saved state refuses it, naming the contract",
        code != 0 and "no carry rule" in out and vc in out, out[-600:])

# ---- the new chain: the carried hexholm's re-pinned anchor resolves from the new chain's own blocks --------------------
json.dump({"generation": PR.CHAIN_GENERATION, "contracts": {hc: hx_rec},
           "bridge": {hc: str(int(st_hx.bridge.get(hc, 0)))} if int(st_hx.bridge.get(hc, 0)) else {},
           "zk_addrs": carry.digest_map(st_hx.zk_addrs)[1]}, open(os.environ["NADO_EXEC_GENESIS"], "w"))
EG._CACHE.clear()
new = ExecState(os.path.join(HOME, "new.json"))
T.check("new chain: the carried genesis loads and its root is genesis_root()",
        EG.apply(new) and list(new.contracts) == [hc] and new.state_root() == EG.genesis_root())
new.block_ts = NOW
new.block_hashes = {h: h * 7_000_001 + 3 for h in range(0, 200)}
new.cursor = new_pin + 1
new.credit_deposit(A, 10 ** 12)
ok, r = call(new, hc, A, "anchor", [DAY])
T.check("new chain: the re-pinned hexholm anchor resolves from the new chain's own block hash",
        ok and rd(new, hc, HX.A_V, DAY) not in (0, None) and rd(new, hc, HX.A_V, DAY) != rd(st_hx, hc, HX.A_V, DAY), r)
T.done("ALL PASS — battleship, hexholm and scrapline cross a reroll at rest; a sovereign world refuses it")
