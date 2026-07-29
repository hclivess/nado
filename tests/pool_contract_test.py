"""
Offline lifecycle test of the Pool contract (execnode/games/pool.py) on a fresh ExecState — the same
apply_blob path the live exec node runs.

The point of interest is FREE PLAY: pool is the one duel contract whose `open` does not require a stake,
so this exercises the whole escrow with value 0 (open/join/move/agree/resign/abort/cancel) side by side
with the staked path and asserts the two behave identically apart from the money. A zero pot must never
mint, never lock, and never revert a settle.

Run: python3 tests/pool_contract_test.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.games import pool as P

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

A = "ndoAAAA" + "A" * 41
B = "ndoBBBB" + "B" * 41
C = "ndoCCCC" + "C" * 41


def _fresh(cursor=100):
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json")); st.cursor = cursor
    code = P.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": P.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    for who in (A, B, C): st.credit_deposit(who, 1_000_000)
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    call = lambda who, n, method, args, value=0: st.apply_blob(
        {"op": "call", "contract": cid, "method": method, "args": args, **({"value": value} if value else {})}, who, n)
    return st, cid, rd, call


def t_free_game_full_lifecycle():
    """open(0) -> join(0) -> shots -> agree/agree: a stakeless game runs the entire escrow."""
    st, cid, rd, call = _fresh()
    G = 4242
    call(A, "1", "open", [G, 0], 0)
    assert rd(P.NN, G) == 1, "free open must seat p1"
    assert rd(P.ST, G) == 0 and rd(P.PT, G) == 0, "free game has no stake and no pot"
    assert cid not in st.bridge or st.bridge[cid] == 0, "a free open must not move money"
    assert st.bridge[A] == 1_000_000, "opener keeps every coin"
    call(B, "2", "join", [G], 0)
    assert rd(P.NN, G) == 2 and rd(P.KH, G) == 100 + P.GAP, "join seats p2 and pins the rack seed"
    assert rd(P.DL, G) == 100 + P.MOVE_CLOCK
    assert st.bridge[B] == 1_000_000
    st.cursor = 101
    call(A, "3", "move", [G, 1 + 12345 * 16, 0])
    assert rd(P.MC, G) == 1 and rd(P.MV_BASE, G) == 1 + 12345 * 16
    assert rd(P.MH_BASE, G) == (101 + P.GAP) * 4 + 1, "mh records (seed height, side=1)"
    call(A, "4", "move", [G, 999, 0])                       # stale ply -> revert
    assert rd(P.MC, G) == 1, "ply binding must reject a replayed ply"
    st.cursor = 102
    call(B, "5", "move", [G, 1 + 777 * 16, 1])
    assert rd(P.MC, G) == 2 and rd(P.MH_BASE + 1, G) == (102 + P.GAP) * 4 + 2
    call(C, "6", "move", [G, 1 + 5 * 16, 2])                # stranger -> revert
    assert rd(P.MC, G) == 2, "only the two seated players may log a shot"
    call(A, "7", "agree", [G, 2])
    assert rd(P.A1, G) == 2 and rd(P.SD, G) == 0, "one-sided agreement does not settle"
    call(B, "8", "agree", [G, 2])
    assert rd(P.SD, G) == 1 and rd(P.WR, G) == 2, "matching agreement settles to p2"
    assert st.bridge[A] == 1_000_000 and st.bridge[B] == 1_000_000, "nothing minted, nothing burned"


def t_staked_game_pays_the_pot():
    st, cid, rd, call = _fresh()
    G = 7
    call(A, "1", "open", [G, 0], 500)
    assert rd(P.ST, G) == 500 and rd(P.PT, G) == 500 and st.bridge[cid] == 500
    call(B, "2", "join", [G], 400)                          # mismatched stake -> revert
    assert rd(P.NN, G) == 1 and st.bridge[cid] == 500
    call(B, "3", "join", [G], 500)
    assert rd(P.NN, G) == 2 and rd(P.PT, G) == 1000 and st.bridge[cid] == 1000
    call(A, "4", "agree", [G, 1]); call(B, "5", "agree", [G, 1])
    assert rd(P.SD, G) == 1 and rd(P.WR, G) == 1
    assert st.bridge[A] == 1_000_500 and st.bridge[B] == 999_500, "winner takes the pot"
    assert st.bridge.get(cid, 0) == 0, "escrow fully drained"


def t_free_resign_abort_cancel():
    """The three non-agreement exits must all work with a zero pot."""
    st, cid, rd, call = _fresh()
    call(A, "1", "open", [11, 0], 0); call(B, "2", "join", [11], 0)
    call(B, "3", "resign", [11])
    assert rd(P.SD, 11) == 1 and rd(P.WR, 11) == 1, "resign hands the (empty) pot to the opponent"

    call(A, "4", "open", [12, 0], 0); call(B, "5", "join", [12], 0)
    st.cursor = 100 + P.MOVE_CLOCK + 1
    call(A, "6", "abort", [12])
    assert rd(P.SD, 12) == 1 and rd(P.WR, 12) == 3, "stall refund closes the game as a draw"

    st.cursor = 100
    call(A, "7", "open", [13, 0], 0)
    call(B, "8", "cancel", [13])                            # not the opener -> revert
    assert rd(P.SD, 13) == 0
    call(A, "9", "cancel", [13])
    assert rd(P.SD, 13) == 1, "opener may cancel an unjoined free game"
    assert st.bridge[A] == 1_000_000 and st.bridge[B] == 1_000_000


def t_free_and_staked_share_one_lobby():
    """A stakeless game must be indexed in the same lobby list as a staked one (nn is the existence
    flag, not st) — otherwise free games would be invisible to the lobby renderer."""
    st, cid, rd, call = _fresh()
    call(A, "1", "open", [21, 0], 0)
    call(B, "2", "open", [22, 0], 250)
    cnt = int((st.contracts[cid]["storage"].get("slots") or {}).get("0", 0))
    assert cnt == 2, f"both games indexed, got cnt={cnt}"
    assert rd(P.LIST, 0) == 21 and rd(P.LIST, 1) == 22
    call(A, "3", "open", [21, 0], 0)                        # re-open an existing id -> revert
    assert int((st.contracts[cid]["storage"].get("slots") or {}).get("0", 0)) == 2


def t_move_bounds():
    st, cid, rd, call = _fresh()
    G = 5
    call(A, "1", "open", [G, 0], 0); call(B, "2", "join", [G], 0)
    call(A, "3", "move", [G, 0, 0])                         # enc 0 is the storage-empty sentinel -> revert
    assert rd(P.MC, G) == 0
    # a 48-bit shot payload survives the log intact (angle|power|spin|call|placement)
    enc = 1 + ((1 << 48) - 1) * 16
    call(A, "4", "move", [G, enc, 0])
    assert rd(P.MV_BASE, G) == enc, "a full-width shot encoding must round-trip through storage"
    # the log cap holds even at the right ply
    st.contracts[cid]["storage"]["slots"][str(P.MC * (1 << 32) + G)] = P.MAXMOVES
    r = call(A, "5", "move", [G, 5, P.MAXMOVES])
    assert "revert" in r, "a move past MAXMOVES must revert"


if __name__ == "__main__":
    check("free game: full lifecycle with a zero pot", t_free_game_full_lifecycle)
    check("staked game: winner takes the pot", t_staked_game_pays_the_pot)
    check("free game: resign / abort / cancel", t_free_resign_abort_cancel)
    check("free and staked games share one lobby index", t_free_and_staked_share_one_lobby)
    check("move bounds: enc>0, ply binding, 48-bit payload, log cap", t_move_bounds)
    print("\n" + ("%d FAILED" % fails if fails else "ALL PASS"))
    sys.exit(1 if fails else 0)
