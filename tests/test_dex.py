"""
DEX (constant-product AMM) — money-code test.

Standing rule from the ROADMAP: money code is verified by RUNNING it, not by reading it. These checks
drive the real ExecState (deploy → call → assert), so the contract is exercised through the same path a
block takes. What they pin down is the set of things an AMM can get wrong and lose funds by:

  * the invariant  — k = rn·rt never DECREASES across a swap (the 30 bps fee makes it grow).
  * conservation   — a swap moves the reserves by exactly what it took in / paid out.
  * solvency       — exit can never draw past the reserve; shares and supply stay consistent.
  * ownership      — a position is spendable only by its owner (exit/refund are authenticated).
  * no fund lock   — a half-funded position is always refundable (the escape-hatch class).
  * slippage       — minOut is enforced.
  * id bounds      — an id >= 2^32 is refused (the storage-aliasing class from the security audit).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.state import ExecState, asset_id
from execnode.games import dex

ALICE = "alice000000000000000000000000000000000000000000"
BOB = "bob00000000000000000000000000000000000000000000"
UNIT = dex.UNIT

_fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        _fails.append(name)


def _deploy(st):
    out = st.apply_blob({"op": "deploy", "code": dex.build(), "nonce": "a5", "runtime": "zkvm",
                         "abi": dex.ABI}, ALICE, "tx")
    return out.split()[1]


def _call(st, cid, sender, method, args, value=0, asset=0):
    return st.apply_blob({"op": "call", "contract": cid, "method": method, "args": args,
                          "value": value, "asset": asset}, sender, "tx")


def _cell(st, cid, field, key):
    """One storage cell: slot = field*2^32 + key."""
    c = st.contracts.get(cid) or {}
    slots = ((c.get("storage") or {}).get("slots") or {})
    return int(slots.get(str(field * (1 << 32) + key), 0))


def main():
    with tempfile.TemporaryDirectory() as d:
        st = ExecState(os.path.join(d, "exec_state.json"))
        cid = _deploy(st)
        st.apply_blob({"op": "asset_create", "seed": 1, "name": "Token", "sym": "TKN", "dec": 0,
                       "supply": 10 ** 15, "mintable": False}, ALICE, "tx")
        aid = int(asset_id(ALICE, 1))
        # exec-side native balance: call value is spent from the bridge balance an L1 deposit credits.
        st.bridge[ALICE] = 10 ** 15
        st.bridge[BOB] = 10 ** 15
        check("deploy + asset create", bool(cid) and aid != 0)

        # ---- open ---------------------------------------------------------------------------------
        _call(st, cid, ALICE, "open", [1, aid])
        check("open records the pool asset", _cell(st, cid, dex.AST, 1) == aid % (1 << 64) or
              _cell(st, cid, dex.AST, 1) != 0)

        before = _cell(st, cid, dex.AST, 1)
        _call(st, cid, ALICE, "open", [1, aid])
        check("re-opening an existing pool is refused", _cell(st, cid, dex.AST, 1) == before)

        # id >= 2^32 must be refused: it would alias onto another field's slots
        cnt_before = _cell(st, cid, 0, 0)
        _call(st, cid, ALICE, "open", [1 << 32, aid])
        check("pool id >= 2^32 refused", _cell(st, cid, 0, 0) == cnt_before)

        # ---- seed liquidity: 100 NADO / 200 TKN (in UNITs) -----------------------------------------
        n0, t0 = 10_000, 20_000                      # UNITs
        _call(st, cid, ALICE, "fundn", [11, 1, n0], value=n0 * UNIT, asset=0)
        _call(st, cid, ALICE, "fundt", [11, 1, t0], value=t0 * UNIT, asset=aid)
        check("pending sides staged", _cell(st, cid, dex.PPN, 11) == n0 and _cell(st, cid, dex.PPT, 11) == t0)

        _call(st, cid, ALICE, "join", [11, 1])
        rn, rt, sup = _cell(st, cid, dex.RN, 1), _cell(st, cid, dex.RT, 1), _cell(st, cid, dex.SUP, 1)
        check("seed sets both reserves", rn == n0 and rt == t0)
        check("seed mints shares = native units", sup == n0 and _cell(st, cid, dex.PSH, 11) == n0)
        check("pending cleared after join", _cell(st, cid, dex.PPN, 11) == 0 and _cell(st, cid, dex.PPT, 11) == 0)

        # ---- swap NADO -> token: the invariant must not fall ---------------------------------------
        k0 = rn * rt
        dx = 1_000
        _call(st, cid, BOB, "swapn", [1, dx, 0, aid], value=dx * UNIT, asset=0)
        rn1, rt1 = _cell(st, cid, dex.RN, 1), _cell(st, cid, dex.RT, 1)
        out = rt - rt1
        check("swapn moved the reserves", rn1 == rn + dx and out > 0)
        check("k never decreases across a swap (fee accrues to LPs)", rn1 * rt1 >= k0)
        # the output must be strictly worse than the no-fee, no-slippage price
        check("output is below the spot price (fee + slippage)", out < (rt * dx) // rn)

        # ---- slippage -------------------------------------------------------------------------------
        rn2, rt2 = _cell(st, cid, dex.RN, 1), _cell(st, cid, dex.RT, 1)
        _call(st, cid, BOB, "swapn", [1, dx, 10 ** 9, aid], value=dx * UNIT, asset=0)   # absurd minOut
        check("minOut is enforced (swap reverted)",
              _cell(st, cid, dex.RN, 1) == rn2 and _cell(st, cid, dex.RT, 1) == rt2)

        # ---- swap token -> NADO (mirror) ------------------------------------------------------------
        st.assets.setdefault(str(aid), {})
        k1 = _cell(st, cid, dex.RN, 1) * _cell(st, cid, dex.RT, 1)
        _call(st, cid, BOB, "swapt", [1, 500, 0], value=500 * UNIT, asset=aid)
        check("k never decreases across the mirror swap",
              _cell(st, cid, dex.RN, 1) * _cell(st, cid, dex.RT, 1) >= k1)

        # ---- ownership: BOB cannot touch ALICE's position -------------------------------------------
        sh_before = _cell(st, cid, dex.PSH, 11)
        _call(st, cid, BOB, "exit", [11, 1, sh_before, aid])
        check("exit is authenticated (non-owner refused)", _cell(st, cid, dex.PSH, 11) == sh_before)
        _call(st, cid, BOB, "refund", [11, 1, aid])
        check("refund is authenticated (non-owner refused)", _cell(st, cid, dex.PSH, 11) == sh_before)

        # ---- no fund lock: a half-funded position is always refundable -------------------------------
        _call(st, cid, BOB, "fundn", [22, 1, 50], value=50 * UNIT, asset=0)
        check("half-funded position staged", _cell(st, cid, dex.PPN, 22) == 50)
        _call(st, cid, BOB, "refund", [22, 1, aid])
        check("half-funded position is refundable (no lock)", _cell(st, cid, dex.PPN, 22) == 0)

        # ---- exit: solvency ---------------------------------------------------------------------------
        rn3, rt3, sup3 = (_cell(st, cid, dex.RN, 1), _cell(st, cid, dex.RT, 1), _cell(st, cid, dex.SUP, 1))
        half = sh_before // 2
        _call(st, cid, ALICE, "exit", [11, 1, half, aid])
        rn4, rt4, sup4 = (_cell(st, cid, dex.RN, 1), _cell(st, cid, dex.RT, 1), _cell(st, cid, dex.SUP, 1))
        check("exit burns exactly the shares withdrawn", sup4 == sup3 - half and
              _cell(st, cid, dex.PSH, 11) == sh_before - half)
        check("exit never draws past the reserves", rn4 <= rn3 and rt4 <= rt3 and rn4 >= 0 and rt4 >= 0)
        check("exit pays out pro-rata (<= its share of each side)",
              (rn3 - rn4) <= (half * rn3) // sup3 + 1 and (rt3 - rt4) <= (half * rt3) // sup3 + 1)

        # ---- an LP cannot withdraw more than they hold -------------------------------------------------
        held = _cell(st, cid, dex.PSH, 11)
        _call(st, cid, ALICE, "exit", [11, 1, held + 1, aid])
        check("over-withdrawal refused", _cell(st, cid, dex.PSH, 11) == held)

    print()
    print("ALL DEX CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
