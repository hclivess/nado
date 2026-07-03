"""
Treasury anti-hoard self-burn (doc/treasury.md §3.2): every TREASURY_SPEND_PERIOD blocks, destroy
TREASURY_BURN_BPS of the treasury balance above TREASURY_RUNWAY_FLOOR. Burned coins leave existence, so the
destruction is booked into the burned-supply counter (totals 'fees'), and the burned amount is stored per
height so rollback restores balance + supply exactly.

Covers: no burn off the period boundary; the boundary burn amount + supply booking; and full revert symmetry.

Run: python3 tests/test_treasury_burn.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_tburn_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("tburn"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import (TREASURY_ADDRESS, TREASURY_SPEND_PERIOD, TREASURY_BURN_BPS, TREASURY_RUNWAY_FLOOR,
                      BPS_DENOM, TREASURY_GENESIS)
from ops import kv_ops
from ops.account_ops import create_account, get_account, fetch_totals
from ops.reward_ops import apply_treasury_burn

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def bal(): return get_account(TREASURY_ADDRESS)["balance"]
def supply():
    t = fetch_totals(); return TREASURY_GENESIS + t["produced"] - t["fees"]

START = 1_000_000_000_000
create_account(TREASURY_ADDRESS, balance=START)
H = TREASURY_SPEND_PERIOD                                   # a burn-boundary height
EXPECT = max(0, START - TREASURY_RUNWAY_FLOOR) * TREASURY_BURN_BPS // BPS_DENOM

def t1_no_burn_off_boundary():
    b, s = bal(), supply()
    apply_treasury_burn({"block_number": H + 1}, logger)   # not a multiple of the period
    apply_treasury_burn({"block_number": 0}, logger)       # genesis never burns
    assert bal() == b and supply() == s, "no burn off the period boundary"

def t2_burn_on_boundary_reduces_balance_and_supply():
    assert EXPECT > 0, "the test amount must actually burn something"
    b0, s0 = bal(), supply()
    apply_treasury_burn({"block_number": H}, logger)
    assert bal() == b0 - EXPECT, f"treasury burned exactly {EXPECT}"
    assert supply() == s0 - EXPECT, "burned coins leave the supply (booked into the burned counter)"
    assert kv_ops.treasury_burn_get(H) == EXPECT, "burned amount stored for revert"

def t3_revert_restores_balance_and_supply():
    b1, s1 = bal(), supply()
    apply_treasury_burn({"block_number": H}, logger, revert=True)
    assert bal() == b1 + EXPECT, "revert restores the treasury balance"
    assert supply() == s1 + EXPECT, "revert restores the supply"
    assert kv_ops.treasury_burn_get(H) == 0, "revert clears the stored burn"

for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and len(name) > 1 and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
