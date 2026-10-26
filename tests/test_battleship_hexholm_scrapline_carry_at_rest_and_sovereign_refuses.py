"""Battleship, Hexholm and Scrapline cross the gen-29 reroll once nothing is in flight; a Sovereign world with a log
REFUSES it (tools/carry.py, doc/stwo/g5-carry.md). Operator rule: everything is carried losslessly, and what cannot be
carried refuses — never a reset.

Pins, driving the REAL contracts on a gen-28 (v1) ExecState:
  * battleship: an open lobby, a game in play (its board roots still checked shot by shot) and a decided-but-unpaid
    game (the winner's fleet still to be proven against its root) each block the carry, naming the call that ends it;
    claimed / cancelled, the contract carries — every slot accounted for, the settled roots, stake and the daily
    board's resolved anchor and claim words kept verbatim, every owner digest remapped;
  * hexholm: a lobby and a game in play block; settled (one seat's commitment left unrevealed — a paid game's audit,
    which does not block), it carries with a recorded move >= 2^32 and the commitments kept verbatim, and the daily
    board's UNRESOLVED anchor re-pinned to a new-chain block;
  * scrapline: a lobby and a game in play block; agreed, it carries with its split-run claim words and a large move;
  * sovereign: a world with a log re-derives every raid from old-chain block hashes and settles its economy against
    the live cursor, so it refuses the carry (no carry rule); an empty world carries as its v2 build.

Run: python3 tests/test_battleship_hexholm_scrapline_carry_at_rest_and_sovereign_refuses.py
"""
import _harness
HOME = _harness.isolate("nado-test-carry-hidden-boards-")
# THE GEN-28 PHASE RUNS UNDER GENERATION 28'S GATE, EXPLICITLY (gen-29 rehearsal): the state this test carries is a
# generation-28 exec state, which the shipped value no longer describes on a generation-29 tree.
import protocol as _PR
_PR.BLAKE_EXEC_HEIGHT = _harness.gate_at("BLAKE_EXEC_HEIGHT", 28)
import json, os, random, tempfile, time

from execnode.state import ExecState
from execnode.games import battleship as BS, hexholm as HX, scrapline as SC, sovereign as SV, _lib
from tools import carry

T = _harness.Report()
A, B = "ndoA" + "a" * 44, "ndoB" + "b" * 44
NOW = int(time.time())
DAY = NOW // 86400
P = carry.P
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
    """(record, counts, None) or (None, None, the refusal)."""
    try:
        rec, n = carry.carry_contract(cid, st.contracts[cid], carry.digest_map(st.zk_addrs)[0], st.cursor,
                                      src="v1", dst="v2")
        return rec, n, None
    except carry.Refused as e:
        return None, None, str(e)


def carried_whole(st, cid, rec, n, mod, kept):
    """every gen-28 slot has its gen-29 slot; owner digests remapped (no old digest left); `kept` {(f, k): v} verbatim"""
    old, new = slots(st, cid), {int(k): int(v) for k, v in rec["storage"]["slots"].items()}
    dmap = carry.digest_map(st.zk_addrs)[0]
    owners = sum(1 for v in old.values() if v in dmap)
    return (n["slots"] == len(old) == len(new) and n["value_remapped"] == owners >= 1
            and not set(new.values()) & set(dmap)
            and all(new.get((f << 32) + k) == v for (f, k), v in kept.items())
            and rec["code"] == json.loads(json.dumps(mod.build("v2"))))


def declarations_load_bearing(st, cid, mod):
    """without the module's CARRY_WORDS the same carry refuses: every declaration above is reached, none decorative"""
    saved = mod.CARRY_WORDS
    try:
        mod.CARRY_WORDS = {}
        return try_carry(st, cid)[2] is not None and "CARRY_WORDS" in try_carry(st, cid)[2]
    finally:
        mod.CARRY_WORDS = saved


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
call(st, bc, A, "cancel", [L])
call(st, bc, B, "join", [G, rootB], 500)
cell = [c for c in range(100) if bB[c]][0]
call(st, bc, A, "fire", [G, cell])
isS, salt, flat = BS.make_proof(bB, sB, cell)
ok, r = call(st, bc, B, "answer", [G, isS, salt] + flat)
why = BS.carry_in_flight(st.contracts[bc]["storage"])
_, _, msg = try_carry(st, bc)
T.check("battleship: a game in play blocks — its roots are still checked shot by shot — and the carry refuses",
        ok and why == [why[0]] and "game 42 is in play" in why[0] and "resign(42)" in why[0]
        and msg is not None and "in flight" in msg and "game 42" in msg, (r, why, msg))
call(st, bc, B, "resign", [G])
why = BS.carry_in_flight(st.contracts[bc]["storage"])
_, _, msg = try_carry(st, bc)
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
        and av == st.block_hashes[pin] % P and av >= 1 << 32
        and not [k for k in slots(st, bc) if (k >> 32) in range(BS.O_BASE, BS.SC + 1)], (r, rp, av))
rec, n, msg = try_carry(st, bc)
T.check("battleship: the carry succeeds — every slot accounted for; roots, stake, anchor and claim word kept verbatim",
        msg is None and carried_whole(st, bc, rec, n, BS, {(BS.R1, G): rootA, (BS.R2, G): rootB, (BS.ST, G): 500,
                                                              (BS.A_V, DAY): av, (BS.EW_BASE, 0): words[0],
                                                              (BS.A_H, DAY): pin}),
        (msg, n))

T.check("battleship: its CARRY_WORDS are load-bearing (without them the same carry refuses)",
        declarations_load_bearing(st, bc, BS))

# ---- hexholm ----------------------------------------------------------------------------------------------------------
st = old_chain()
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
_, _, msg = try_carry(st, hc)
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
rec, n, msg = try_carry(st, hc)
new_pin = int(rec["storage"]["slots"].get(str((HX.A_H << 32) + DAY), 0)) if rec else None
T.check("hexholm: the carry succeeds — move, commitments and claim word verbatim; the unresolved anchor re-pinned",
        msg is None and carried_whole(st, hc, rec, n, HX, {(HX.MV_BASE, G): ENC, (HX.C_BASE + 1, G): CA,
                                                              (HX.C_BASE + 2, G): CB, (HX.EW_BASE, 0): hwords[0]})
        and _lib.CARRY_PIN_FLOOR <= new_pin < 100, (msg, n, new_pin))

T.check("hexholm: its CARRY_WORDS are load-bearing (without them the same carry refuses)",
        declarations_load_bearing(st, hc, HX))

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
_, _, msg = try_carry(st, sc)
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
rec, n, msg = try_carry(st, sc)
T.check("scrapline: the carry succeeds — every slot accounted for; move, claim words and anchor verbatim",
        msg is None and carried_whole(st, sc, rec, n, SC, {(SC.MV_BASE, G): ENC, (SC.E_A, 0): swords[0],
                                                              (SC.E_A2, 0): swords[5], (SC.A_V, DAY): av}),
        (msg, n))

T.check("scrapline: its CARRY_WORDS are load-bearing (without them the same carry refuses)",
        declarations_load_bearing(st, sc, SC))

# ---- sovereign --------------------------------------------------------------------------------------------------------
st = old_chain()
vc = deploy(st, SV)
rec, n, msg = try_carry(st, vc)
T.check("sovereign: an empty world carries as its v2 build",
        msg is None and rec["code"] == json.loads(json.dumps(SV.build("v2"))) and not rec["storage"].get("slots"),
        (msg, rec and rec["storage"]))
ok, r = call(st, vc, A, "act", [5, 0, 0])
rec, n, msg = try_carry(st, vc)
T.check("sovereign: a world with a log refuses (its fold reads old-chain block hashes and the live cursor)",
        ok and msg is not None and "no carry rule" in msg and not hasattr(SV, "CARRY_STORAGE")
        and not hasattr(SV, "carry_in_flight"), (r, msg))

T.done("ALL PASS — battleship, hexholm and scrapline carry at rest; a sovereign world refuses")
