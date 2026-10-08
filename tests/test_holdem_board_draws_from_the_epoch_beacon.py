"""Hold'em deals from the EPOCH BEACON, not from block hashes (release B, game rule consistency).

Pins, on an isolated ExecState through the same apply_blob path the exec node runs:
  * a beacon hand: start() pins tg = cursor//60 + 2; each street close c_k pins p_k = c_k//60 + 2; the hole cards
    equal hole_ref(BEACON(tg), 0, x) and the board equals board_ref computed from BEACON(p_1..p_3) — with NO block
    hash in the state at all (a BHASH read would revert);
  * the street gates wait for the beacon: no bet before b0 = tg*60, and after street k closes no bet and no
    close_street until a_k = p_k*60, the first height whose epoch carries the street's beacon;
  * a legacy hand (tg == 0: a table dealt by the old code, which never wrote field 18) keeps the block-hash rule
    and the old timeline exactly;
  * a seat that does not reveal by the showdown deadline cannot win any pot layer, even holding the better hand,
    and cannot block settlement;
  * tg is exposed in `_view.maps` and no 800..999 scratch survives a call.

Run: python3 tests/test_holdem_board_draws_from_the_epoch_beacon.py
"""
import os, sys, tempfile, shutil, atexit

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-holdem-beacon-")      # assign, never setdefault
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
import traceback
from execnode.state import ExecState
from execnode.games import holdem as hd
from execnode.stark import alghash

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


H = "ndoHH" + "H" * 43
X = "ndoXX" + "X" * 43
BAL = 10 ** 12


def _table(cursor=100):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json")); st.cursor = cursor
    code = hd.build()
    for a in (H, X):
        st.credit_deposit(a, BAL)
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": hd.ABI, "nonce": "n"}, H, "d")
    cid = st.contract_id(H, code, "n")
    slots = lambda: st.contracts[cid]["storage"].setdefault("slots", {})
    rd = lambda f, k: int(slots().get(str(f * (1 << 32) + k), 0))
    n = [0]

    def call(who, m, args, val=0):
        n[0] += 1
        return st.apply_blob({"op": "call", "contract": cid, "method": m, "args": args,
                              **({"value": val} if val else {})}, who, f"c{n[0]}")
    return st, cid, rd, call, slots


def _no_scratch(slots):
    leaked = [k for k in slots() if 800 <= (int(k) >> 32) < 1000]
    assert not leaked, f"scratch leaked: {leaked[:5]}"


def _seat_two(call, T, G1, G2, x1, x2):
    assert "ok" in call(H, "open", [T, G1, alghash.hashn([x1]), 1000], 10000)
    assert "ok" in call(X, "join", [T, G2, alghash.hashn([x2])], 10000)
    assert "ok" in call(H, "start", [T])


def t_beacon_hand_board_and_hole_come_from_the_beacon():
    st, cid, rd, call, slots = _table(100)
    rnd = random.Random(7)
    T, G1, G2 = 500, 501, 502
    x1, x2 = rnd.randint(1, 2 ** 60), rnd.randint(1, 2 ** 60)
    _seat_two(call, T, G1, G2, x1, x2)
    td, tg = rd(hd.TD, T), rd(hd.TG, T)
    assert td == 102 and tg == 100 // 60 + 2, f"deal pins tg = epoch(cursor)+2, got td={td} tg={tg}"
    assert st.decode_view(st.contracts[cid])["tg"][str(T)] == tg, "tg is exposed in _view.maps"
    st.beacons[tg] = rnd.randint(1, 2 ** 62)
    # four streets checked around, the host fast-forwarding each one the moment it opens
    for k in range(1, 5):
        sc = [rd(hd.SCL_BASE + j, T) for j in range(1, 5)]
        b0, cs, opens, pins = hd.timeline_ref(td, tg, sc)
        st.cursor = b0 if k == 1 else opens[k - 2]
        if k > 1:
            st.beacons[pins[k - 2]] = rnd.randint(1, 2 ** 62)
        assert "ok" in call(H, "close_street", [T])
        _no_scratch(slots)
    sc = [rd(hd.SCL_BASE + j, T) for j in range(1, 5)]
    b0, cs, opens, pins = hd.timeline_ref(td, tg, sc)
    assert all(pins) and pins == [c // 60 + 2 for c in cs[:3]], "street k pins epoch(c_k)+2"
    assert not st.block_hashes, "no block hash is ever needed by a beacon hand"
    st.cursor = cs[3]
    board = hd.board_ref_beacon(st.beacons, pins[0], pins[1], pins[2], T)
    vals = {}
    for g, who, x in ((G1, H, x1), (G2, X, x2)):
        ref = hd.eval7_ref(hd.hole_ref(st.beacons[tg], 0, x) + board)
        assert "ok" in call(who, "reveal", [g, x]), "reveal resolves from the beacons alone"
        assert rd(hd.GSC, g) == ref, f"seat {g}: contract {rd(hd.GSC, g)} != board_ref from the beacon {ref}"
        vals[g] = ref
        _no_scratch(slots)
    # the legacy formula over the same epochs would be a different deal — the beacon is what was used
    assert board == hd._board_from(*(st.beacons[p] % hd.F.P for p in pins), T)
    assert "ok" in call(H, "settle", [T])
    assert rd(hd.TZ, T) == 1 and st.bridge.get(cid, 0) == 0, "the table settles and drains"


def t_street_gates_wait_for_the_beacon_epoch():
    st, cid, rd, call, slots = _table(100)
    T, G1, G2 = 600, 601, 602
    _seat_two(call, T, G1, G2, 11, 22)
    td, tg = rd(hd.TD, T), rd(hd.TG, T)
    b0, cs, opens, pins = hd.timeline_ref(td, tg)
    assert b0 == tg * 60 and b0 > td + hd.F0, "pre-flop opens at the deal's beacon epoch"
    st.cursor = b0 - 1
    assert "revert" in call(H, "bet", [G1, 100]), "no bet before BEACON(tg) exists"
    st.cursor = b0
    assert "ok" in call(H, "bet", [G1, 100]) and "ok" in call(X, "bet", [G2, 100])
    # street 1 runs its scheduled course; street 2 opens only at a_1 = p_1*60, not at c_1
    c1, a1 = cs[0], opens[0]
    assert a1 == pins[0] * 60 and a1 - c1 >= 60, f"the flop waits a full epoch past the close ({c1} -> {a1})"
    for cur in (c1, (c1 + a1) // 2, a1 - 1):
        st.cursor = cur
        assert "revert" in call(H, "bet", [G1, 100]), f"no flop bet at {cur} before the flop's beacon epoch"
        assert "revert" in call(H, "close_street", [T]), f"no close of a street that has not opened ({cur})"
    st.cursor = a1
    assert "ok" in call(H, "bet", [G1, 100]), "the flop opens at p_1*60"
    assert rd(hd.CS_BASE + 2, G1) == 100, "the bet landed on street 2"
    # forcing the flop closed re-pins the turn from the FORCED close height
    st.cursor = a1 + 1
    assert "ok" in call(X, "bet", [G2, 100])
    assert "ok" in call(H, "close_street", [T])
    sc = [rd(hd.SCL_BASE + j, T) for j in range(1, 5)]
    assert sc[1] == a1 + 3, "forced close = cursor + 2"
    _b0, cs2, opens2, pins2 = hd.timeline_ref(td, tg, sc)
    assert pins2[1] == sc[1] // 60 + 2 and opens2[1] == pins2[1] * 60
    st.cursor = opens2[1] - 1
    assert "revert" in call(H, "bet", [G1, 100]), "turn waits for its beacon epoch"
    st.cursor = opens2[1]
    assert "ok" in call(H, "bet", [G1, 100])
    _no_scratch(slots)


def t_legacy_hand_keeps_the_block_hash_rule():
    st, cid, rd, call, slots = _table(100)
    rnd = random.Random(3)
    T, G1, G2 = 700, 701, 702
    x1, x2 = rnd.randint(1, 2 ** 60), rnd.randint(1, 2 ** 60)
    _seat_two(call, T, G1, G2, x1, x2)
    # a table dealt by the pre-upgrade code: it never wrote field 18, so tg reads 0
    slots().pop(str(hd.TG * (1 << 32) + T))
    assert rd(hd.TG, T) == 0 and st.decode_view(st.contracts[cid]).get("tg", {}).get(str(T)) in (None, 0)
    td = rd(hd.TD, T)
    b0, cs, opens, pins = hd.timeline_ref(td, 0)
    assert b0 == td + hd.F0 and opens == cs[:3] and pins == [0, 0, 0], "legacy timeline is the old one"
    st.block_hashes[td] = rnd.randint(1, 2 ** 60); st.block_hashes[td + 1] = rnd.randint(1, 2 ** 60)
    st.cursor = b0 - 1
    assert "revert" in call(H, "bet", [G1, 100]), "legacy shuffle gate unchanged"
    st.cursor = b0
    assert "ok" in call(H, "bet", [G1, 100]) and "ok" in call(X, "bet", [G2, 100])
    st.cursor = cs[0]                                   # legacy: the flop street opens AT c_1 (no beacon gap)
    assert "ok" in call(H, "bet", [G1, 50]) and "ok" in call(X, "bet", [G2, 50])
    for c in cs[:3]:
        st.block_hashes[c] = rnd.randint(1, 2 ** 60); st.block_hashes[c + 1] = rnd.randint(1, 2 ** 60)
    assert not st.beacons, "no beacon is ever needed by a legacy hand"
    st.cursor = cs[3]
    board = hd.board_ref(st.block_hashes, cs[0], cs[1], cs[2], T)
    for g, who, x in ((G1, H, x1), (G2, X, x2)):
        ref = hd.eval7_ref(hd.hole_ref(st.block_hashes[td], st.block_hashes[td + 1], x) + board)
        assert "ok" in call(who, "reveal", [g, x]), "legacy reveal resolves from block hashes"
        assert rd(hd.GSC, g) == ref, "legacy showdown equals board_ref over block hashes"
    _no_scratch(slots)
    assert "ok" in call(X, "settle", [T]) and rd(hd.TZ, T) == 1


def t_a_non_revealer_cannot_win_even_with_the_better_hand():
    rnd = random.Random(11)
    # find secrets where the seat that will NOT reveal holds the strictly better hand
    for _ in range(200):
        st, cid, rd, call, slots = _table(100)
        T, G1, G2 = 800, 801, 802
        x1, x2 = rnd.randint(1, 2 ** 60), rnd.randint(1, 2 ** 60)
        _seat_two(call, T, G1, G2, x1, x2)
        td, tg = rd(hd.TD, T), rd(hd.TG, T)
        b0, cs, opens, pins = hd.timeline_ref(td, tg)
        st.beacons[tg] = rnd.randint(1, 2 ** 62)
        for p in pins:
            st.beacons[p] = rnd.randint(1, 2 ** 62)
        board = hd.board_ref_beacon(st.beacons, *pins, T)
        v1 = hd.eval7_ref(hd.hole_ref(st.beacons[tg], 0, x1) + board)
        v2 = hd.eval7_ref(hd.hole_ref(st.beacons[tg], 0, x2) + board)
        if v2 > v1:
            break
    else:
        raise AssertionError("no deal found where the non-revealer holds the better hand")
    st.cursor = b0
    assert "ok" in call(H, "bet", [G1, 2000]) and "ok" in call(X, "bet", [G2, 2000])
    st.cursor = cs[3]
    assert "ok" in call(H, "reveal", [G1, x1])
    assert "revert" in call(H, "settle", [T]), "settle waits for the window while a seat is unrevealed"
    st.cursor = cs[3] + hd.R
    assert "revert" in call(X, "reveal", [G2, x2]), "no reveal after the showdown deadline"
    stack_h, stack_x = rd(hd.GK, G1), rd(hd.GK, G2)
    before = {w: st.bridge[w] for w in (H, X)}
    assert "ok" in call(X, "settle", [T]), "a non-revealer cannot block settlement (anyone settles)"
    pot = 2 * (1000 + 2000)
    assert st.bridge[H] - before[H] == pot + stack_h, "the only revealed hand takes every layer"
    assert st.bridge[X] - before[X] == stack_x, "the non-revealer gets only the unbet stack back"
    assert rd(hd.TZ, T) == 1 and st.bridge.get(cid, 0) == 0
    _no_scratch(slots)


if __name__ == "__main__":
    check("beacon hand: hole + board equal the reference computed from BEACON(tg), BEACON(p_k)",
          t_beacon_hand_board_and_hole_come_from_the_beacon)
    check("street gates wait for the beacon epoch (b0 = tg*60, a_k = p_k*60)", t_street_gates_wait_for_the_beacon_epoch)
    check("legacy hand (tg == 0) keeps the block-hash rule and timeline", t_legacy_hand_keeps_the_block_hash_rule)
    check("a non-revealer at showdown cannot win, even with the better hand", t_a_non_revealer_cannot_win_even_with_the_better_hand)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
