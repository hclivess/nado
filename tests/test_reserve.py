"""
The Reserve contract (doc/reserve.md): native value locked behind an asset, redeemable pro-rata by any
holder, releasable by the creator only after a notice period they committed to up front.

Every assertion here RUNS the contract through ExecState — the economics are checked by executing calls and
reading the ledger afterwards, never by reading the source. What it pins, in the order the money can go
wrong:

  * the FLOOR is what the doc claims — a redeemer gets amt·res/out, and both terms fall together so the
    ratio the remaining holders face is EXACTLY unchanged (floor-neutral, not a ratchet: the one property
    most likely to be mis-stated, and the reason the doc says so explicitly);
  * redemption really BURNS — the asset's total supply falls, so the floor is not diluted by exits;
  * the NOTICE is load-bearing — release is refused before the deadline, re-announcing RESTARTS the clock,
    and redemption stays open for the whole window (a notice you cannot act on is decoration);
  * AUTHORITY — only the owner can announce/cancel/release, and nobody can move the reserve any other way;
  * the DIVMODW budget is enforced by `require`, not assumed: out-of-range operands would not revert, they
    would emit a trace no prover can close.

Run: python3 tests/test_reserve.py
"""
import os
import sys
import tempfile
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState, asset_id
from execnode.games import reserve
from execnode.games.reserve import UNIT, MIN_NOTICE, BOUND, OWN, AST, RES, OUT, NTC, PND, RDY

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


ALICE = "mldsa44" + "a" * 42          # the creator
BOB = "mldsa44" + "b" * 42            # a holder
CAROL = "mldsa44" + "c" * 42          # a bystander


def fresh():
    d = tempfile.mkdtemp()
    st = ExecState(os.path.join(d, "exec_state.json"))
    for who in (ALICE, BOB, CAROL):
        st.bridge[who] = 10 ** 20   # richly funded, so a BOUND check is what fails, never the balance
    return st


def deploy(st):
    st.apply_blob({"op": "deploy", "code": reserve.build(), "nonce": 1}, ALICE, "tx")
    return next(iter(st.contracts))


def mkasset(st, sender=ALICE, seed=1, supply=1000):
    st.apply_blob({"op": "asset_create", "seed": seed, "name": "Token", "sym": "TKN",
                   "dec": 0, "supply": supply, "mintable": False}, sender, "tx")
    return str(asset_id(sender, seed))


def call(st, cid, method, args, sender=ALICE, value=0, asset=None):
    p = {"op": "call", "contract": cid, "method": method, "args": args}
    if value:
        p["value"] = value
    if asset:
        p["asset"] = asset
    return st.apply_blob(p, sender, "tx")


def sload(st, cid, field, vid):
    """One composite slot. Contract storage is nested under "slots", and reading the wrapper instead
    silently returns 0 for every field — which reads exactly like a contract that stored nothing."""
    return st.contracts[cid]["storage"]["slots"].get(str(field * (1 << 32) + vid), 0)


def index(st, cid):
    return st.contracts[cid]["storage"]["slots"].get("0", 0)


def setup(st=None, supply=1000, res_units=500, notice=MIN_NOTICE):
    """A vault holding `res_units` UNITs behind `supply` tokens — floor = res_units/supply."""
    st = st or fresh()
    cid = deploy(st)
    aid = mkasset(st, supply=supply)
    r = call(st, cid, "open", [1, int(aid), supply, notice, res_units], value=res_units * UNIT)
    assert r.endswith("-> ok") or "ok" in r, f"open failed: {r}"
    return st, cid, aid


# ---- 1. opening ------------------------------------------------------------------------------------
def t_open_records_the_vault():
    st, cid, aid = setup()
    assert sload(st, cid, RES, 1) == 500, sload(st, cid, RES, 1)
    assert sload(st, cid, OUT, 1) == 1000
    assert sload(st, cid, NTC, 1) == MIN_NOTICE
    assert sload(st, cid, AST, 1) == int(aid)
    assert sload(st, cid, PND, 1) == 0 and sload(st, cid, RDY, 1) == 0
    assert sload(st, cid, OWN, 1) != 0, "owner digest not recorded"
    assert index(st, cid) == 1, "vault not appended to the index"
    # the seed really moved: the contract holds it
    assert st.bridge.get(cid, 0) == 500 * UNIT, st.bridge.get(cid, 0)


def t_open_guards():
    st, cid, aid = setup()
    # the same vid cannot be claimed twice
    assert "revert" in call(st, cid, "open", [1, int(aid), 10, MIN_NOTICE, 1], value=UNIT)
    # dust: a value that is not a whole number of UNITs must be refused, never silently floored
    assert "revert" in call(st, cid, "open", [2, int(aid), 10, MIN_NOTICE, 1], value=UNIT + 1)
    # a notice below the minimum
    assert "revert" in call(st, cid, "open", [3, int(aid), 10, MIN_NOTICE - 1, 1], value=UNIT)
    # supply must stay inside the DIVMODW divisor budget
    assert "revert" in call(st, cid, "open", [4, int(aid), BOUND, MIN_NOTICE, 1], value=UNIT)
    # and a reserve big enough to break the quotient budget
    assert "revert" in call(st, cid, "open", [5, int(aid), 10, MIN_NOTICE, BOUND], value=BOUND * UNIT)
    # zero supply / zero asset / zero seed
    assert "revert" in call(st, cid, "open", [6, int(aid), 0, MIN_NOTICE, 1], value=UNIT)
    assert "revert" in call(st, cid, "open", [7, 0, 10, MIN_NOTICE, 1], value=UNIT)
    assert "revert" in call(st, cid, "open", [8, int(aid), 10, MIN_NOTICE, 0], value=0)


# ---- 2. the floor ----------------------------------------------------------------------------------
def t_redeem_pays_the_floor():
    st, cid, aid = setup()                          # 500 units behind 1000 tokens -> 0.5 units/token
    before = st.bridge.get(BOB, 0)
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 400}, ALICE, "tx")
    r = call(st, cid, "redeem", [1], sender=BOB, value=400, asset=aid)
    assert "revert" not in r, r
    got = st.bridge.get(BOB, 0) - before
    assert got == 200 * UNIT, f"expected 200 UNITs, got {got / UNIT}"
    assert st.asset_balance(aid, BOB) == 0, "redeemed tokens were not consumed"


def t_redemption_is_floor_NEUTRAL():
    """The property the doc commits to, and the one I got wrong first: a pro-rata exit leaves the ratio
    the REMAINING holders face exactly where it was. Not a ratchet — there is no exit fee."""
    st, cid, aid = setup()
    before = sload(st, cid, RES, 1) / sload(st, cid, OUT, 1)
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 400}, ALICE, "tx")
    call(st, cid, "redeem", [1], sender=BOB, value=400, asset=aid)
    after = sload(st, cid, RES, 1) / sload(st, cid, OUT, 1)
    assert after == before, f"floor moved on a redemption: {before} -> {after}"
    assert (sload(st, cid, RES, 1), sload(st, cid, OUT, 1)) == (300, 600)
    # and again, from the new state — it holds at every size
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": CAROL, "amount": 300}, ALICE, "tx")
    call(st, cid, "redeem", [1], sender=CAROL, value=300, asset=aid)
    assert sload(st, cid, RES, 1) / sload(st, cid, OUT, 1) == before
    assert (sload(st, cid, RES, 1), sload(st, cid, OUT, 1)) == (150, 300)


def t_redeem_burns_supply():
    """If exits did not burn, the floor would be diluted by every redemption."""
    st, cid, aid = setup()
    assert st.assets[aid]["supply"] == 1000
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 400}, ALICE, "tx")
    call(st, cid, "redeem", [1], sender=BOB, value=400, asset=aid)
    assert st.assets[aid]["supply"] == 600, st.assets[aid]["supply"]
    assert st.asset_balance(aid, cid) == 0, "the vault must not sit on redeemed tokens"


def t_back_raises_the_floor():
    st, cid, aid = setup()
    assert sload(st, cid, RES, 1) / sload(st, cid, OUT, 1) == 0.5
    r = call(st, cid, "back", [1, 500], sender=CAROL, value=500 * UNIT)     # a bystander may back it
    assert "revert" not in r, r
    assert sload(st, cid, RES, 1) == 1000
    assert sload(st, cid, RES, 1) / sload(st, cid, OUT, 1) == 1.0, "backing did not raise the floor"
    # dust and the bound apply here too — this is the one path that GROWS the reserve
    assert "revert" in call(st, cid, "back", [1, 1], value=UNIT + 1)
    assert "revert" in call(st, cid, "back", [1, BOUND], value=BOUND * UNIT)


def t_redeem_guards():
    st, cid, aid = setup()
    other = mkasset(st, sender=BOB, seed=9, supply=50)
    # the wrong token
    assert "revert" in call(st, cid, "redeem", [1], sender=BOB, value=10, asset=other)
    # native value is not a redemption
    assert "revert" in call(st, cid, "redeem", [1], value=UNIT)
    # More than the OUTSTANDING DECLARATION. This needs a holder who really has that many, or the call is
    # refused at escrow ("skip: insufficient") and the contract's own guard is never exercised — so declare
    # a vault over only half the real supply and try to redeem past it.
    st2 = fresh()
    cid2 = deploy(st2)
    aid2 = mkasset(st2, supply=1000)
    call(st2, cid2, "open", [1, int(aid2), 500, MIN_NOTICE, 500], value=500 * UNIT)
    assert st2.asset_balance(aid2, ALICE) == 1000, "the holder must out-hold the declaration"
    assert "revert" in call(st2, cid2, "redeem", [1], value=501, asset=aid2)
    assert "revert" not in call(st2, cid2, "redeem", [1], value=500, asset=aid2)
    # a vault that does not exist
    assert "revert" in call(st, cid, "redeem", [77], value=10, asset=aid)


# ---- 3. the notice ---------------------------------------------------------------------------------
def t_high_asset_ids_are_backable():
    """REGRESSION. Asset ids are field elements, uniform in [0, P) with P ~ 2^64, while RANGE reverts at
    2^62 — so an `arg > 0` on the id refused about three of every four real assets. Only an id in the top
    range reproduces it; a small hand-picked one passes either way, which is exactly why this test uses
    real derived ids and asserts on their magnitude."""
    st = fresh()
    cid = deploy(st)
    high = None
    for seed in range(1, 40):
        a = mkasset(st, seed=seed, supply=100)
        if int(a) >= (1 << 62):
            high = a
            break
    assert high is not None, "no id landed above 2^62 — the regression cannot be reproduced"
    r = call(st, cid, "open", [1, int(high), 100, MIN_NOTICE, 10], value=10 * UNIT)
    assert "revert" not in r, f"an asset with id >= 2^62 could not be backed: {r}"
    assert sload(st, cid, AST, 1) == int(high)
    # and it redeems, so the id round-trips through the equality check too
    assert "revert" not in call(st, cid, "redeem", [1], value=50, asset=high)


def t_release_needs_the_notice():
    st, cid, aid = setup()
    st.cursor = 100
    assert "revert" in call(st, cid, "release", [1]), "released with nothing announced"
    r = call(st, cid, "announce", [1, 200])
    assert "revert" not in r, r
    assert sload(st, cid, PND, 1) == 200
    assert sload(st, cid, RDY, 1) == 100 + MIN_NOTICE

    st.cursor = 100 + MIN_NOTICE - 1
    assert "revert" in call(st, cid, "release", [1]), "released one block EARLY"
    before = st.bridge.get(ALICE, 0)
    st.cursor = 100 + MIN_NOTICE
    r = call(st, cid, "release", [1])
    assert "revert" not in r, r
    assert st.bridge.get(ALICE, 0) - before == 200 * UNIT
    assert sload(st, cid, RES, 1) == 300
    assert (sload(st, cid, PND, 1), sload(st, cid, RDY, 1)) == (0, 0), "announcement not cleared"
    # and it cannot be replayed
    assert "revert" in call(st, cid, "release", [1])


def t_reannounce_restarts_the_clock():
    """Otherwise: announce 1 unit, let the timer run out, then swap in the whole reserve and take it
    with no notice at all."""
    st, cid, aid = setup()
    st.cursor = 100
    call(st, cid, "announce", [1, 1])
    st.cursor = 100 + MIN_NOTICE                 # the small one is now releasable
    call(st, cid, "announce", [1, 500])          # swap in the whole reserve
    assert sload(st, cid, RDY, 1) == 100 + 2 * MIN_NOTICE, "the clock did not restart"
    assert "revert" in call(st, cid, "release", [1]), "the swapped amount escaped its notice"
    st.cursor = 100 + 2 * MIN_NOTICE
    assert "revert" not in call(st, cid, "release", [1])


def t_redemption_stays_open_during_the_window():
    """The whole point of the notice: holders must be able to leave at the pre-release floor."""
    st, cid, aid = setup()
    st.cursor = 100
    call(st, cid, "announce", [1, 500])           # the creator announces the ENTIRE reserve
    st.cursor = 100 + MIN_NOTICE // 2
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 400}, ALICE, "tx")
    before = st.bridge.get(BOB, 0)
    r = call(st, cid, "redeem", [1], sender=BOB, value=400, asset=aid)
    assert "revert" not in r, "a pending release blocked a redemption"
    assert st.bridge.get(BOB, 0) - before == 200 * UNIT, "the holder did not get the pre-release floor"


def t_release_clamps_to_the_reserve():
    """Redemptions during the window can take the reserve below what was announced. Clamping beats making
    the creator restart the wait for exits the notice existed to enable."""
    st, cid, aid = setup()
    st.cursor = 100
    call(st, cid, "announce", [1, 500])
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 800}, ALICE, "tx")
    call(st, cid, "redeem", [1], sender=BOB, value=800, asset=aid)
    assert sload(st, cid, RES, 1) == 100, sload(st, cid, RES, 1)
    before = st.bridge.get(ALICE, 0)
    st.cursor = 100 + MIN_NOTICE
    r = call(st, cid, "release", [1])
    assert "revert" not in r, r
    assert st.bridge.get(ALICE, 0) - before == 100 * UNIT, "release did not clamp to the reserve"
    assert sload(st, cid, RES, 1) == 0


def t_cancel():
    st, cid, aid = setup()
    st.cursor = 100
    call(st, cid, "announce", [1, 200])
    assert "revert" not in call(st, cid, "cancel", [1])
    assert (sload(st, cid, PND, 1), sload(st, cid, RDY, 1)) == (0, 0)
    st.cursor = 100 + MIN_NOTICE
    assert "revert" in call(st, cid, "release", [1]), "a cancelled release still fired"
    assert "revert" in call(st, cid, "cancel", [1]), "cancelled twice"


def t_announce_guards():
    st, cid, aid = setup()
    assert "revert" in call(st, cid, "announce", [1, 501]), "announced more than the reserve"
    assert "revert" in call(st, cid, "announce", [1, 0])


# ---- 4. authority ----------------------------------------------------------------------------------
def t_only_the_owner_touches_the_reserve():
    st, cid, aid = setup()
    st.cursor = 100
    for who in (BOB, CAROL):
        assert "revert" in call(st, cid, "announce", [1, 100], sender=who), f"{who[:9]} announced"
    call(st, cid, "announce", [1, 100])
    for who in (BOB, CAROL):
        assert "revert" in call(st, cid, "cancel", [1], sender=who), f"{who[:9]} cancelled"
    st.cursor = 100 + MIN_NOTICE
    for who in (BOB, CAROL):
        assert "revert" in call(st, cid, "release", [1], sender=who), f"{who[:9]} released"
    assert st.bridge.get(cid, 0) == 500 * UNIT, "the reserve moved despite every refusal"


def t_reserve_is_conserved():
    """Native value in == native value out. Nothing evaporates and nothing is conjured."""
    st, cid, aid = setup()
    st.cursor = 100
    paid_in = 500 * UNIT
    call(st, cid, "back", [1, 250], sender=CAROL, value=250 * UNIT)
    paid_in += 250 * UNIT
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 500}, ALICE, "tx")
    b0 = st.bridge.get(BOB, 0)
    call(st, cid, "redeem", [1], sender=BOB, value=500, asset=aid)
    out_bob = st.bridge.get(BOB, 0) - b0
    call(st, cid, "announce", [1, sload(st, cid, RES, 1)])
    st.cursor = 100 + MIN_NOTICE
    a0 = st.bridge.get(ALICE, 0)
    call(st, cid, "release", [1])
    out_alice = st.bridge.get(ALICE, 0) - a0
    assert out_bob + out_alice == paid_in, f"{out_bob} + {out_alice} != {paid_in}"
    assert st.bridge.get(cid, 0) == 0, "dust stranded in the vault"


def t_two_vaults_do_not_interfere():
    st, cid, aid = setup()
    other = mkasset(st, sender=BOB, seed=7, supply=200)
    r = call(st, cid, "open", [2, int(other), 200, MIN_NOTICE, 100], sender=BOB, value=100 * UNIT)
    assert "revert" not in r, r
    assert (sload(st, cid, RES, 1), sload(st, cid, OUT, 1)) == (500, 1000)
    assert (sload(st, cid, RES, 2), sload(st, cid, OUT, 2)) == (100, 200)
    # redeeming vault 2 must not touch vault 1
    call(st, cid, "redeem", [2], sender=BOB, value=100, asset=other)
    assert (sload(st, cid, RES, 1), sload(st, cid, OUT, 1)) == (500, 1000)
    assert (sload(st, cid, RES, 2), sload(st, cid, OUT, 2)) == (50, 100)
    # and vault 1's asset cannot be redeemed against vault 2
    assert "revert" in call(st, cid, "redeem", [2], value=10, asset=aid)


def t_divmodw_budget_holds_at_the_edges():
    """The bounds are what keep the pro-rata divide PROVABLE. Push right up to them."""
    st = fresh()
    cid = deploy(st)
    aid = mkasset(st, supply=BOUND - 1)
    r = call(st, cid, "open", [1, int(aid), BOUND - 1, MIN_NOTICE, BOUND - 1], value=(BOUND - 1) * UNIT)
    assert "revert" not in r, r
    assert (sload(st, cid, RES, 1), sload(st, cid, OUT, 1)) == (BOUND - 1, BOUND - 1)
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": BOUND - 1}, ALICE, "tx")
    before = st.bridge.get(BOB, 0)
    r = call(st, cid, "redeem", [1], sender=BOB, value=BOUND - 1, asset=aid)
    assert "revert" not in r, r
    assert st.bridge.get(BOB, 0) - before == (BOUND - 1) * UNIT, "full redemption at the bound underpaid"
    assert sload(st, cid, RES, 1) == 0 and sload(st, cid, OUT, 1) == 0


def t_rounding_never_overpays():
    """Integer division must always favour the vault, or the last holder out finds it empty."""
    st, cid, aid = setup(supply=7, res_units=10)          # 10/7 is not an integer
    st.apply_thing = None
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": BOB, "amount": 1}, ALICE, "tx")
    b0 = st.bridge.get(BOB, 0)
    call(st, cid, "redeem", [1], sender=BOB, value=1, asset=aid)
    assert st.bridge.get(BOB, 0) - b0 == 1 * UNIT, "1*10//7 must floor to 1"
    assert (sload(st, cid, RES, 1), sload(st, cid, OUT, 1)) == (9, 6)
    # everyone else can still be paid: the reserve covers the remaining claims
    st.apply_blob({"op": "asset_transfer", "asset": aid, "to": CAROL, "amount": 6}, ALICE, "tx")
    r = call(st, cid, "redeem", [1], sender=CAROL, value=6, asset=aid)
    assert "revert" not in r, "the vault could not honour the last claim — rounding leaked"
    assert sload(st, cid, RES, 1) == 0


if __name__ == "__main__":
    check("open records the vault", t_open_records_the_vault)
    check("open guards", t_open_guards)
    check("redeem pays the floor", t_redeem_pays_the_floor)
    check("redemption is floor-NEUTRAL", t_redemption_is_floor_NEUTRAL)
    check("redeem burns supply", t_redeem_burns_supply)
    check("back raises the floor", t_back_raises_the_floor)
    check("redeem guards", t_redeem_guards)
    check("high asset ids are backable", t_high_asset_ids_are_backable)
    check("release needs the notice", t_release_needs_the_notice)
    check("re-announce restarts the clock", t_reannounce_restarts_the_clock)
    check("redemption stays open during the window", t_redemption_stays_open_during_the_window)
    check("release clamps to the reserve", t_release_clamps_to_the_reserve)
    check("cancel", t_cancel)
    check("announce guards", t_announce_guards)
    check("only the owner touches the reserve", t_only_the_owner_touches_the_reserve)
    check("reserve is conserved", t_reserve_is_conserved)
    check("two vaults do not interfere", t_two_vaults_do_not_interfere)
    check("divmodw budget holds at the edges", t_divmodw_budget_holds_at_the_edges)
    check("rounding never overpays", t_rounding_never_overpays)
    print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
    sys.exit(1 if fails else 0)
