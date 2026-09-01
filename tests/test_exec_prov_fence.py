"""
The provisional tail may be EXTENDED only across pure block application.

Run: python3 tests/test_exec_prov_fence.py

WHY THIS EXISTS. execnode._refresh_provisional keeps the unfinalized tail up to date incrementally instead
of re-executing the whole finality window every poll, and its correctness rests on one algebraic claim
spelled out in its own docstring: provisional(F+1, T+1) is finalized(F+1) plus blocks F+2..T+1, so
extending the tail by the new block gives the same state a rebuild would. That claim silently assumes the
FINALIZED state moves only by applying blocks.

The presence-dividend accrual breaks that assumption. It runs in the poll loop after a batch of blocks,
fetches the epoch's inflow and weights from L1, and writes state.dividend — a state_root leaf
(exec_root T_DIV_BAL). The tail, forked from an older finalized state and fed nothing but _apply_block,
never receives it, so its root disagrees with a rebuild for every epoch that pays out. Measured live on
this node: eight of eight PROVISIONAL DRIFT reports were preceded by dividend accruals, and none occurred
without one. The audit then discards the tail and rebuilds the whole window, which froze the exec cursor
for 119-206s at a time — players saw the game hang for minutes with their move apparently lost.

Replaying the accrual onto the tail is NOT an equivalent shortcut, which is the trap this test also pins
down: collect_dividend burns the sender's WHOLE accrued balance, so a collect sitting in the unfinalized
tail would burn a pre-accrual balance and then have the replayed share added back on top — a different
dividend map and a different withdrawal amount than the rebuild produces. The only correct order is the
rebuild's.

So the rule under test is exactly: an accrual retires the tail, and nothing else does.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode import execnode as X
from execnode.state import ExecState

fails = 0


def ck(name, cond, extra=""):
    global fails
    if cond:
        print("PASS  " + name)
    else:
        fails += 1
        print("FAIL  " + name + ("  " + str(extra) if extra else ""))


applied = []


async def _fake_get(session, path):
    """Every height exists, carries a body, and hashes predictably — the chain is not what is under test."""
    if "number=" in path:            # /get_block?number= (the /get_block_number alias was removed 2026-08-19)
        h = int(path.split("number=")[1].split("&")[0])
        return {"block_number": h, "block_hash": f"h{h}", "block_transactions": []}
    return {}


async def _fake_apply(session, states_map, default_state, block, verbose=True):
    applied.append(block["block_number"])
    for st in states_map.values():
        st.cursor = block["block_number"]
        st.block_ts = block["block_number"] * 6
    return True


async def main():
    d = tempfile.mkdtemp()
    X.states = {"default": ExecState(os.path.join(d, "s.json"))}
    X.states["default"].cursor = 100
    X.states["default"].last_div_epoch = 5
    X.prov_states = None
    X._prov_key = None
    X._prov_last = None
    X._prov_since_full = 0
    X._prov_div_epoch = None
    X._get_json = _fake_get
    X._apply_block = _fake_apply

    applied.clear()
    await X._refresh_provisional(None, 100, 110, "tipA")
    ck("a cold refresh builds the whole tail", applied == list(range(101, 111)), applied)
    ck("...and records the dividend generation it forked from", X._prov_div_epoch == 5, X._prov_div_epoch)

    applied.clear()
    await X._refresh_provisional(None, 100, 111, "tipB")
    ck("a plain tip advance EXTENDS (the optimisation still works)", applied == [111], applied)

    # THE REGRESSION. The finalized state accrues an epoch out-of-band; the tail is now missing a
    # state_root leaf and may not be extended over it.
    X.states["default"].last_div_epoch = 6
    applied.clear()
    await X._refresh_provisional(None, 100, 112, "tipC")
    ck("an out-of-band accrual RETIRES the tail — the window is rebuilt, not extended",
       applied == list(range(101, 113)), applied)
    ck("...and the new tail records the new generation", X._prov_div_epoch == 6, X._prov_div_epoch)

    applied.clear()
    await X._refresh_provisional(None, 100, 113, "tipD")
    ck("the very next poll extends again from the new fork point", applied == [113], applied)

    print("ALL PASS" if not fails else f"{fails} FAILURES")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
