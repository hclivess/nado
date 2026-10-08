"""Blackjack (execnode/games/blackjack.py) after the rule-consistency release:

  * TIMEOUT -> BANK in every phase: a hand nobody resolved within 18000 blocks of its last move (ge) is reaped
    with the stake kept by the bank (tk += stake, tp unchanged, cover released, nobody paid) — at gf 1 (dealt),
    2 (player to act), 3 (hit pending) and 4 (stand pending) alike. Reap inside the window reverts, and a winning
    hand is still settleable on the window's last block.
  * BEACON: deal / hit / stand bind the pending draw to gb = epoch(cursor) + 2 (field 23, exposed as view map
    "gb"), gh = gb*60 - 1; reveal / draw / settle draw from BEACON(gb), and every card equals the Python reference
    card_at(beacon, 0, ...) / dealer_play(beacon, 0, ...). A step whose beacon is not out yet does not resolve.
  * LEGACY: a step bound before the upgrade (gb == 0, gh = cursor + 2) still resolves from bh(gh) + bh(gh+1).

Offline: a throwaway ExecState, the real contract deployed through apply_blob.
Run: python3 tests/test_blackjack_settles_from_the_beacon_and_times_out_to_the_bank.py
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-bj-beacon-")       # never the live database (assign, not setdefault)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)   # noqa: E401,E702
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import random                                                          # noqa: E402
from execnode.state import ExecState                                   # noqa: E402
from execnode.games import blackjack as bj                             # noqa: E402

FAILED = []
A = "ndoAAAA" + "A" * 41      # banker
B = "ndoBBBB" + "B" * 41      # player
T = 5
BANKROLL = 5_000_000_000
STAKE = 1_000_000


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"   {detail}"))
    if not cond:
        FAILED.append(name)


def fresh():
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json"))
    st.cursor = 6000
    code = bj.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": bj.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    st.credit_deposit(A, 10 * BANKROLL)
    st.credit_deposit(B, 10_000 * STAKE)
    n = [0]

    def call(m, args, who=B, value=None):
        n[0] += 1
        blob = {"op": "call", "contract": cid, "method": m, "args": args}
        if value is not None:
            blob["value"] = value
        r = st.apply_blob(blob, who, f"{m}-{n[0]}")
        return "revert" not in str(r).lower()

    def rd(f, k):
        return int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))

    def wr(f, k, v):
        st.contracts[cid]["storage"].setdefault("slots", {})[str(f * (1 << 32) + k)] = int(v)

    assert call("open", [T], who=A, value=BANKROLL)
    return st, cid, call, rd, wr


R = random.Random(20261008)
nb = lambda: R.randint(1, 2 ** 255)                 # noqa: E731  — a beacon / block hash, full width


def land_beacon(st, rd, g):
    """Publish the pending step's beacon and move the cursor to the epoch it settles at. Returns the beacon."""
    gb = rd(bj.GB, g)
    v = nb()
    st.beacons[gb] = v
    st.cursor = gb * 60
    return v


# ---- B2: a beacon hand, dealt / hit / stood / settled ------------------------------------------------------
def beacon_hand():
    st, cid, call, rd, wr = fresh()
    checked = {"bind": False, "early": False, "nobeacon": False, "deal": False, "hit": False, "settle": False,
               "rebind": False, "view": False}
    for g in range(100, 400):
        st.cursor += 7
        cur = st.cursor
        assert call("deal", [g, T], value=STAKE)
        gb = rd(bj.GB, g)
        if not checked["bind"]:
            check("deal binds gb = epoch(cursor) + 2 and gh = gb*60 - 1",
                  gb == cur // 60 + 2 and rd(bj.GH, g) == gb * 60 - 1, (gb, rd(bj.GH, g), cur))
            checked["bind"] = True
        if not checked["early"]:
            st.cursor = gb * 60 - 1
            check("reveal before the beacon epoch begins reverts", not call("reveal", [g]) and rd(bj.GF, g) == 1)
            checked["early"] = True
        if not checked["nobeacon"]:
            st.cursor = gb * 60
            check("reveal while the beacon is not out yet reverts", not call("reveal", [g]) and rd(bj.GF, g) == 1)
            checked["nobeacon"] = True
        b0 = land_beacon(st, rd, g)
        st.block_hashes[rd(bj.GH, g)] = nb()          # decoys: a beacon hand must ignore the block hashes
        st.block_hashes[rd(bj.GH, g) + 1] = nb()
        assert call("reveal", [g], who=A)              # permissionless
        c0, c1, up = bj.card_at(b0, 0, g * 64, 0), bj.card_at(b0, 0, g * 64, 1), bj.card_at(b0, 0, g * 64, 16)
        ok = (rd(bj.PC_BASE + 0, g) - 1 == c0 and rd(bj.PC_BASE + 1, g) - 1 == c1 and rd(bj.DU, g) - 1 == up)
        if not checked["deal"]:
            check("revealed cards == card_at(BEACON(gb), 0, g*64, 0/1/16)", ok,
                  (rd(bj.PC_BASE, g) - 1, rd(bj.PC_BASE + 1, g) - 1, rd(bj.DU, g) - 1, c0, c1, up))
            checked["deal"] = True
        elif not ok:
            check(f"hand {g}: revealed cards follow the beacon", False)
        if rd(bj.GD, g):                               # a natural paid at reveal
            continue
        cards = [c0, c1]
        if not checked["hit"] and bj.hand_total(cards)[0] <= 11:
            gb_prev = gb
            st.cursor += 3
            assert call("hit", [g])
            gb2 = rd(bj.GB, g)
            check("hit re-binds a later beacon epoch", gb2 == st.cursor // 60 + 2 and gb2 > gb_prev
                  and rd(bj.GH, g) == gb2 * 60 - 1, (gb2, gb_prev, st.cursor))
            checked["rebind"] = True
            b1 = land_beacon(st, rd, g)
            assert call("draw", [g])
            c2 = bj.card_at(b1, 0, g * 64 + 2, 0)
            check("the hit card == card_at(BEACON(gb), 0, g*64 + gn, 0)", rd(bj.PC_BASE + 2, g) - 1 == c2,
                  (rd(bj.PC_BASE + 2, g) - 1, c2))
            checked["hit"] = True
            cards.append(c2)
            if rd(bj.GD, g):
                continue
        if not checked["settle"]:
            st.cursor += 3
            assert call("stand", [g])
            b2 = land_beacon(st, rd, g)
            pb = st.bridge.get(B, 0)
            assert call("settle", [g], who=A)
            dtot = bj.dealer_play(b2, 0, g, up)
            ptot = bj.hand_total(cards)[0]
            exp = 2 * STAKE if (dtot > 21 or ptot > dtot) else (STAKE if ptot == dtot else 0)
            dk = []
            for j in range(16):
                v = rd(bj.DK_BASE + j, g)
                if not v:
                    break
                dk.append(v - 1)
            ref = [bj.card_at(b2, 0, g * 64 + 32, j) for j in range(len(dk))]
            check("the dealer's cards == card_at(BEACON(gb), 0, g*64 + 32, j) and gr == dealer_play(beacon, 0)",
                  dk == ref and rd(bj.GR, g) == dtot, (dk, ref, rd(bj.GR, g), dtot))
            check("a beacon hand settles with the reference payout", st.bridge.get(B, 0) - pb == exp,
                  (st.bridge.get(B, 0) - pb, exp))
            checked["settle"] = True
            v = st.decode_view(st.contracts[cid])
            checked["view"] = "gb" in v and int(v["gb"][str(g)]) == rd(bj.GB, g)
            check("_view exposes the beacon epoch as map gb", checked["view"], v.get("gb"))
        if all(checked.values()):
            break
    check("the beacon walk reached every step", all(checked.values()), checked)


# ---- B2 legacy: a step bound before the upgrade (gb == 0) keeps the block-hash rule -------------------------
def legacy_hand():
    st, cid, call, rd, wr = fresh()
    done_reveal = done_settle = False
    for g in range(500, 800):
        st.cursor += 7
        assert call("deal", [g, T], value=STAKE)
        gh = st.cursor + 2                             # the pre-upgrade stamp
        wr(bj.GB, g, 0)
        wr(bj.GH, g, gh)
        h0, h1 = nb(), nb()
        st.block_hashes[gh], st.block_hashes[gh + 1] = h0, h1
        st.cursor = gh + 2
        assert call("reveal", [g])
        c0, c1, up = bj.card_at(h0, h1, g * 64, 0), bj.card_at(h0, h1, g * 64, 1), bj.card_at(h0, h1, g * 64, 16)
        ok = rd(bj.PC_BASE, g) - 1 == c0 and rd(bj.PC_BASE + 1, g) - 1 == c1 and rd(bj.DU, g) - 1 == up
        if not done_reveal:
            check("a gb == 0 deal reveals from bh(gh) + bh(gh+1) (card_at(h0, h1, ...))", ok)
            done_reveal = True
        if rd(bj.GD, g):
            continue
        st.cursor += 3
        assert call("stand", [g])
        gh2 = st.cursor + 2                            # rewrite the stand as the old code stamped it
        wr(bj.GB, g, 0)
        wr(bj.GH, g, gh2)
        h2, h3 = nb(), nb()
        st.block_hashes[gh2], st.block_hashes[gh2 + 1] = h2, h3
        st.cursor = gh2 + 2
        pb = st.bridge.get(B, 0)
        assert call("settle", [g])
        dtot = bj.dealer_play(h2, h3, g, up)
        ptot = bj.hand_total([c0, c1])[0]
        exp = 2 * STAKE if (dtot > 21 or ptot > dtot) else (STAKE if ptot == dtot else 0)
        check("a gb == 0 stand settles from the block hashes (dealer_play(h0, h1) + payout)",
              rd(bj.GR, g) == dtot and st.bridge.get(B, 0) - pb == exp, (rd(bj.GR, g), dtot, exp))
        done_settle = True
        break
    check("the legacy walk reached settle", done_reveal and done_settle)


# ---- B1: the timeout resolves to the bank in every phase --------------------------------------------------------
def reap_phase(phase):
    st, cid, call, rd, wr = fresh()
    for g in range(1000, 1300):
        st.cursor += 7
        assert call("deal", [g, T], value=STAKE)
        if phase >= 2:
            land_beacon(st, rd, g)
            assert call("reveal", [g])
            if rd(bj.GD, g):
                continue                               # a natural resolved at reveal; try another hand
            st.cursor += 3
            if phase == 3:
                assert call("hit", [g])
            elif phase == 4:
                assert call("stand", [g])
        if rd(bj.GF, g) != phase:
            continue
        tk0, tp0, tc0, pb = rd(bj.TK, T), rd(bj.TP, T), rd(bj.TC, T), st.bridge.get(B, 0)
        esc0 = st.bridge.get(cid, 0)
        ge = rd(bj.GE, g)
        st.cursor = ge + 18000
        check(f"phase {phase}: reap on the window's last block reverts", not call("reap", [g], who=A) and not rd(bj.GD, g))
        st.cursor = ge + 18001
        check(f"phase {phase}: reap after the window succeeds (permissionless)", call("reap", [g], who=A))
        cover = STAKE + STAKE // 2
        check(f"phase {phase}: the stake goes to the bank (tk += stake, tp unchanged, cover released, nobody paid)",
              rd(bj.TK, T) == tk0 + STAKE and rd(bj.TP, T) == tp0 and rd(bj.TC, T) == tc0 - cover
              and st.bridge.get(B, 0) == pb and st.bridge.get(cid, 0) == esc0,
              (rd(bj.TK, T) - tk0, rd(bj.TP, T) - tp0, rd(bj.TC, T) - tc0, st.bridge.get(B, 0) - pb))
        closed = rd(bj.GD, g) == 1 and rd(bj.GW, g) == 0 and not call("reap", [g], who=A)
        pb1, tk1, tp1 = st.bridge.get(B, 0), rd(bj.TK, T), rd(bj.TP, T)
        for m in ("reveal", "hit", "draw", "stand", "settle", "reveal", "draw", "settle"):
            if rd(bj.GB, g):
                st.beacons.setdefault(rd(bj.GB, g), nb())
                st.cursor = max(st.cursor, rd(bj.GB, g) * 60)
            call(m, [g])
        check(f"phase {phase}: the reaped hand is closed (gd=1, gw=0); no later call reaps or pays it",
              closed and st.bridge.get(B, 0) == pb1 and rd(bj.TK, T) == tk1 and rd(bj.TP, T) == tp1)
        check(f"phase {phase}: the pot still equals the escrow, so close() pays out exactly",
              rd(bj.TP, T) == st.bridge.get(cid, 0) and call("close", [T], who=A) and st.bridge.get(cid, 0) == 0,
              (rd(bj.TP, T), st.bridge.get(cid, 0)))
        return
    check(f"phase {phase}: found a hand to reap", False)


def win_settles_on_the_last_block():
    st, cid, call, rd, wr = fresh()
    for g in range(2000, 2600):
        st.cursor += 7
        assert call("deal", [g, T], value=STAKE)
        land_beacon(st, rd, g)
        assert call("reveal", [g])
        if rd(bj.GD, g):
            continue
        st.cursor += 3
        assert call("stand", [g])
        b = nb()
        gb = rd(bj.GB, g)
        st.beacons[gb] = b
        ptot = bj.hand_total([rd(bj.PC_BASE, g) - 1, rd(bj.PC_BASE + 1, g) - 1])[0]
        dtot = bj.dealer_play(b, 0, g, rd(bj.DU, g) - 1)
        if not (dtot > 21 or ptot > dtot):
            st.cursor = rd(bj.GE, g) + 18001
            assert call("reap", [g], who=A)            # tidy the losing hand (bank keeps it)
            continue
        st.cursor = rd(bj.GE, g) + 18000               # the window's last block
        pb = st.bridge.get(B, 0)
        check("a winning hand settles on the last block of its window and is paid 2x",
              call("settle", [g]) and st.bridge.get(B, 0) - pb == 2 * STAKE, st.bridge.get(B, 0) - pb)
        st.cursor += 1
        check("a settled hand cannot be reaped afterwards", not call("reap", [g], who=A))
        return
    check("found a winning hand", False)


beacon_hand()
legacy_hand()
for ph in (1, 2, 3, 4):
    reap_phase(ph)
win_settles_on_the_last_block()

print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILURES")
sys.exit(1 if FAILED else 0)
