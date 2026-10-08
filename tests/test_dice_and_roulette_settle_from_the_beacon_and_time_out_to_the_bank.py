"""Dice and roulette (Release B, rule consistency): a bet settles from the epoch BEACON it was bound to at bet time,
a seat placed before that rule (gb == 0) still settles from BHASH(gh) + BHASH(gh+1), and a bet nobody settles within
its 18,000-block window resolves IN FAVOUR OF THE BANK — while a winning bet stays settleable (permissionlessly) for
the whole window.

Pinned, for each of execnode/games/dice.py and execnode/games/roulette.py, against the real contract on an isolated
ExecState through the normal apply_blob path:
  * bet binds gb = cursor // 60 + 2 and gh = gb * 60 - 1 (exposed in _view as "gb"/"gh");
  * settle before gh + 1 reverts; settle with the beacon missing reverts (no silent fallback to block hashes);
  * the paid result equals the reference HASH((BEACON(gb) mod P + seat id) mod P) LO32 % mod — the seat id, not the
    table id, is the salt;
  * a legacy seat (gb == 0, written into storage the way the pre-upgrade code left it) settles from block hashes;
  * reclaim reverts at gh + 18000 (window still open) and succeeds at gh + 18001: stake stays in tp, tc released,
    gd = 1, gw = 0, the player is paid nothing, the escrow still equals tp, and close() then returns the pot;
  * a WINNING bet settled by a stranger at gh + 18000 (last block of the window) still pays the player;
  * a settled seat can no longer be reclaimed, and a reclaimed seat can no longer be settled.

Run: python3 tests/test_dice_and_roulette_settle_from_the_beacon_and_time_out_to_the_bank.py
"""
import os, tempfile, shutil, atexit
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-dice-roul-beacon-")          # assign, never setdefault
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)

import sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.stark import alghash, field as F
from execnode.games import dice, roulette, _lib

A = "ndoBANK" + "A" * 41          # banker / deployer
B = "ndoPLAY" + "B" * 41          # player
C = "ndoSTRA" + "C" * 41          # an uninvolved stranger (settle is permissionless)
TP, TC = _lib.TP, _lib.TC
WINDOW = 18000
passed = failed = 0


def ok(cond, msg):
    global passed, failed
    if cond:
        passed += 1; print("PASS ", msg)
    else:
        failed += 1; print("FAIL ", msg)


def ref(seed, salt, mod):
    """The contract's draw: alghash.hashn([(seed + salt) mod P]) low 32 bits, % mod (settle: add r3 r0; hash; lo32)."""
    return (alghash.hashn([(seed % F.P + salt) % F.P]) & 0xFFFFFFFF) % mod


class Game:
    def __init__(self, mod, name, bet_arg, mod_n, wins, reserve):
        self.mod, self.name, self.bet_arg, self.N, self.wins, self.reserve = mod, name, bet_arg, mod_n, wins, reserve

    def fresh(self, cursor=100):
        st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json")); st.cursor = cursor
        code = self.mod.build()
        st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": self.mod.ABI, "nonce": "n"}, A, "d")
        cid = st.contract_id(A, code, "n")
        for w in (A, B, C):
            st.credit_deposit(w, 100_000_000)
        st.apply_blob({"op": "call", "contract": cid, "method": "open", "args": [3], "value": 50_000_000}, A, "o")
        self.st, self.cid, self._n = st, cid, 0
        return st

    def slots(self):
        return self.st.contracts[self.cid]["storage"].setdefault("slots", {})

    def rd(self, f, k):
        return int(self.slots().get(str(f * (1 << 32) + k), 0))

    def wr(self, f, k, v):
        key = str(f * (1 << 32) + k)
        if v:
            self.slots()[key] = v
        else:
            self.slots().pop(key, None)

    def call(self, who, method, args, value=None):
        self._n += 1
        p = {"op": "call", "contract": self.cid, "method": method, "args": args}
        if value:
            p["value"] = value
        return str(self.st.apply_blob(p, who, f"{method}-{self._n}"))

    def bet(self, g, stake=100_000):
        return self.call(B, "bet", [g, 3, self.bet_arg], stake)

    def snap(self):
        return json.dumps({"s": self.st.contracts[self.cid]["storage"], "b": self.st.bridge}, sort_keys=True, default=str)

    def refused(self, who, method, args):
        before = self.snap()
        r = self.call(who, method, args)
        return "revert" in r.lower() and self.snap() == before


def beacon_for(G, g, want_win):
    """A beacon value whose draw for seat g wins (or loses) at this game's bet."""
    for x in range(1, 100_000):
        v = 0xBEAC0 + x * 7919
        if G.wins(ref(v, g, G.N)) == want_win:
            return v
    raise AssertionError("no beacon found")


def run(G):
    M = G.mod
    n = G.name
    # ---- beacon binding + beacon settle -------------------------------------------------------------------------
    st = G.fresh(cursor=100)
    g = 88
    ok("revert" not in G.bet(g).lower(), f"{n}: bet lands")
    gb, gh = G.rd(M.GB, g), G.rd(M.GH, g)
    ok(gb == 100 // 60 + 2 and gh == gb * 60 - 1, f"{n}: bet binds gb = cursor//60 + 2 = {gb}, gh = gb*60 - 1 = {gh}")
    v = st.decode_view(st.contracts[G.cid])
    ok(int(v.get("gb", {}).get(str(g), 0)) == gb, f"{n}: _view exposes the beacon epoch as map 'gb'")
    st.cursor = gh
    ok(G.refused(C, "settle", [g]), f"{n}: settle before gh + 1 reverts")
    st.cursor = gh + 1
    ok(G.refused(C, "settle", [g]), f"{n}: settle with the beacon missing reverts (no fallback to block hashes)")
    st.block_hashes[gh] = 0x1111; st.block_hashes[gh + 1] = 0x2222     # present, but a beacon seat must not use them
    bv = beacon_for(G, g, True)
    st.beacons[gb] = bv
    b0, tp0 = st.bridge[B], G.rd(TP, 3)
    G.call(C, "settle", [g])                                            # a stranger settles: permissionless
    r = ref(bv, g, G.N)
    ok(G.rd(M.GR, g) == r + 1, f"{n}: beacon seat result == HASH(BEACON(gb) + seat id) % {G.N} ({r})")
    ok(G.rd(M.GW, g) == 1 and st.bridge[B] == b0 + G.reserve, f"{n}: a stranger's settle pays the winning PLAYER")
    ok(G.rd(TC, 3) == 0 and G.rd(TP, 3) == tp0 - G.reserve and st.bridge.get(G.cid, 0) == G.rd(TP, 3),
       f"{n}: win accounting: tc released, tp debited the payout, escrow == tp")
    ok(G.refused(A, "reclaim", [g]), f"{n}: a settled seat cannot be reclaimed")

    # ---- legacy seat (gb == 0): keeps the block-hash rule --------------------------------------------------------
    st = G.fresh(cursor=100)
    g = 4242
    G.bet(g)
    G.wr(M.GB, g, 0); G.wr(M.GH, g, 102)                               # what the pre-upgrade bet left: gh = cursor + 2
    st.block_hashes[102] = 0xAAAA1234; st.block_hashes[103] = 0x5678BBBB; st.cursor = 104
    st.beacons[3] = 0xDEAD                                             # a beacon exists, but a legacy seat must ignore it
    G.call(C, "settle", [g])
    r = ref(0xAAAA1234 + 0x5678BBBB, g, G.N)
    ok(G.rd(M.GD, g) == 1 and G.rd(M.GR, g) == r + 1,
       f"{n}: a legacy seat (gb == 0) settles from BHASH(gh) + BHASH(gh+1) + seat id ({r})")
    ok(G.rd(TC, 3) == 0 and st.bridge.get(G.cid, 0) == G.rd(TP, 3), f"{n}: legacy settle keeps escrow == tp")

    # ---- timeout -> bank ----------------------------------------------------------------------------------------
    st = G.fresh(cursor=100)
    g = 77
    G.bet(g)
    gh = G.rd(M.GH, g)
    st.beacons[G.rd(M.GB, g)] = beacon_for(G, g, True)                 # even a WINNING bet goes to the bank once timed out
    st.cursor = gh + WINDOW
    ok(G.refused(A, "reclaim", [g]), f"{n}: reclaim at gh + 18000 reverts (the settle window is still open)")
    st.cursor = gh + WINDOW + 1
    b_play, b_bank, tp0, esc0 = st.bridge[B], st.bridge[A], G.rd(TP, 3), st.bridge.get(G.cid, 0)
    ok(tp0 == 50_100_000 and G.rd(TC, 3) == G.reserve, f"{n}: before the timeout the stake sits in tp, the payout in tc")
    G.call(C, "reclaim", [g])                                           # permissionless
    ok(G.rd(M.GD, g) == 1 and G.rd(M.GW, g) == 0, f"{n}: a timed-out bet is marked settled with no win")
    ok(G.rd(TP, 3) == tp0 and G.rd(TC, 3) == 0, f"{n}: timeout -> bank: the stake stays in tp, the reservation is released")
    ok(st.bridge[B] == b_play and st.bridge.get(G.cid, 0) == esc0 == G.rd(TP, 3),
       f"{n}: the player is paid nothing and the escrow still equals tp")
    ok(G.refused(B, "settle", [g]), f"{n}: a reclaimed seat can no longer be settled")
    G.call(A, "close", [3])
    ok(st.bridge[A] == b_bank + 50_100_000 and st.bridge.get(G.cid, 0) == 0,
       f"{n}: close then returns the whole pot, timed-out stake included, to the bank")

    # ---- a win is still collectable on the LAST block of the window -----------------------------------------------
    st = G.fresh(cursor=1000)
    g = 31337
    G.bet(g)
    gb, gh = G.rd(M.GB, g), G.rd(M.GH, g)
    st.beacons[gb] = beacon_for(G, g, True)
    st.cursor = gh + WINDOW
    b0 = st.bridge[B]
    G.call(C, "settle", [g])
    ok(G.rd(M.GW, g) == 1 and st.bridge[B] == b0 + G.reserve,
       f"{n}: a winning bet settled by anyone at gh + 18000 still pays the player")
    # and a losing bet settles to the bank the ordinary way
    st = G.fresh(cursor=1000)
    G.bet(g)
    st.beacons[G.rd(M.GB, g)] = beacon_for(G, g, False)
    st.cursor = G.rd(M.GH, g) + 1
    b0 = st.bridge[B]
    G.call(C, "settle", [g])
    ok(G.rd(M.GW, g) == 0 and st.bridge[B] == b0 and G.rd(TP, 3) == 50_100_000 and G.rd(TC, 3) == 0,
       f"{n}: a losing beacon bet settles to the bank (stake in tp, tc released)")


MASK = (1 << 7) | (1 << 17)
run(Game(dice, "dice", 50, 100, lambda r: r < 50, 100_000 * 99 // 50))
run(Game(roulette, "roulette", MASK, 37, lambda r: bool((MASK >> r) & 1), 100_000 * 36 // 2))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
