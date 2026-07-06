"""
Registration-rate PoSW difficulty (doc/ip-spoofing-and-sybil.md) — the CONSENSUS multiplier scales the required
PoSW work with recent registration volume, keyed off the finalized anchor epoch. This test drives the recert
index directly and checks the multiplier: 1x under normal load, ramps under a flood, and caps.

Run: python3 tests/test_reg_difficulty.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_regdiff_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logging.getLogger().addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import POSW_T, POSW_DIFF_FLOOR, POSW_DIFF_MAX_MULT
from ops import kv_ops
from ops.reg_difficulty import difficulty_multiplier, required_posw_t

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

E = 500                                            # a finalized anchor epoch
def seed(epoch, count):
    """Write `count` synthetic recerts into recert_by_epoch at `epoch` (what difficulty_multiplier reads)."""
    for i in range(count):
        kv_ops.recert_put(f"addr-{epoch}-{i}", epoch)   # writes recert_by_epoch (what the difficulty reads)

def t1_normal_load_is_1x():
    """Prove no recent registrations gives a 1x multiplier and the base POSW_T step count."""
    assert difficulty_multiplier(E) == 1, "no recent registrations -> 1x"
    assert required_posw_t(E) == POSW_T, "1x -> base PoSW steps"

def t2_flood_ramps_difficulty():
    """Prove a registration flood at 5x the floor baseline ramps the multiplier (and required steps) to 5x."""
    seed(E, 5 * POSW_DIFF_FLOOR)                    # recent = 5x the floor baseline (100 with defaults)
    m = difficulty_multiplier(E)
    assert m == 5, f"5x the baseline should give 5x work, got {m}"
    assert required_posw_t(E) == POSW_T * 5, "required steps scale with the multiplier"

def t3_capped_at_max():
    """Prove a huge registration burst is capped at POSW_DIFF_MAX_MULT so honest users aren't priced out."""
    seed(E, 500 * POSW_DIFF_FLOOR)                  # a huge burst
    assert difficulty_multiplier(E) == POSW_DIFF_MAX_MULT, "multiplier is capped so honest users aren't priced out"
    assert required_posw_t(E) == POSW_T * POSW_DIFF_MAX_MULT

def t4_isolated_epoch_unaffected():
    """Prove an anchor epoch far from the flood sees no recent registrations and stays at 1x."""
    assert difficulty_multiplier(E + 10000) == 1, "an epoch with no recent registrations stays at 1x"

for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and len(name) > 1 and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
