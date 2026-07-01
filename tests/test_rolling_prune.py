"""
Rolling-mode history pruning (doc/rolling-mode-and-da.md): prune_block_bodies deletes old block BODY
files while KEEPING the number<->hash index (beacon/FFG still resolve), never prunes within the
reward/rollback window (so get_block_reward's tip-REWARD_WINDOW body read is always satisfied), and is
idempotent + incremental via the meta watermark. Fake block files + index entries — no real chain.

Run: python3 tests/test_rolling_prune.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_prune_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("prune"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import REWARD_WINDOW, FINALITY_DEPTH
from ops import kv_ops
from ops.block_ops import prune_block_bodies
from ops.data_ops import get_home

HOME = get_home()
FLOOR = REWARD_WINDOW + FINALITY_DEPTH + 1   # hard safety floor inside prune_block_bodies

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def _body_path(h):
    bh = kv_ops.hash_by_number(h)
    return f"{HOME}/blocks/{bh}.block" if bh else None

def body_exists(h):
    p = _body_path(h)
    return bool(p) and os.path.exists(p)

def indexed(h):
    return kv_ops.hash_by_number(h) is not None

# Build fake blocks 1..600: an index entry (number<->hash) + a tiny body file each.
N = 600
for h in range(1, N + 1):
    bh = f"{h:064x}"
    kv_ops.block_index_put(block_number=h, block_hash=bh)
    with open(f"{HOME}/blocks/{bh}.block", "wb") as f:
        f.write(b"body")

def t1_prunes_below_window_keeps_index():
    # finalized=400, retention=150 (>= FLOOR) -> prune_below = 400 - 150 = 250
    n = prune_block_bodies(400, 150, logger)
    assert n == 249, f"expected 249 pruned (heights 1..249), got {n}"
    assert not body_exists(1) and not body_exists(249), "old bodies must be gone"
    assert body_exists(250) and body_exists(400), "bodies within retention must remain"
    # index is KEPT even for pruned heights (beacon/FFG resolve hashes without the body)
    assert indexed(1) and indexed(249), "number<->hash index must survive a body prune"
    # correctness floor: the reward-window body (finalized - REWARD_WINDOW = 300) must still be present
    assert body_exists(400 - REWARD_WINDOW), "reward-window body must never be pruned"
    assert kv_ops.meta_get_int("pruned_below", -1) == 250, "watermark advances to prune_below"

def t2_idempotent_noop():
    n = prune_block_bodies(400, 150, logger)  # same inputs -> nothing new
    assert n == 0, f"second identical call must be a no-op, pruned {n}"
    assert kv_ops.meta_get_int("pruned_below", -1) == 250

def t3_incremental_on_new_finality():
    # finalized advances to 600 -> prune_below = 600 - 150 = 450; prunes only the delta 250..449
    n = prune_block_bodies(600, 150, logger)
    assert n == 200, f"expected 200 pruned (heights 250..449), got {n}"
    assert not body_exists(449), "newly-out-of-window body gone"
    assert body_exists(450) and body_exists(600), "bodies within the new window remain"
    assert kv_ops.meta_get_int("pruned_below", -1) == 450

def t4_safety_floor_protects_reward_and_rollback_window():
    # A misconfigured tiny retention MUST still be floored at REWARD_WINDOW+FINALITY_DEPTH+1, so the
    # reward lookback (tip-REWARD_WINDOW) and rollback window (FINALITY_DEPTH) are never pruned.
    n = prune_block_bodies(600, 1, logger)          # retention=1 -> effective floor FLOOR
    expected_prune_below = 600 - FLOOR              # never above this
    assert body_exists(600 - REWARD_WINDOW), "reward-window body must survive even a tiny retention"
    assert body_exists(600 - FINALITY_DEPTH), "rollback-window body must survive"
    assert kv_ops.meta_get_int("pruned_below", -1) == expected_prune_below, \
        f"floor must cap prune_below at {expected_prune_below}"

def t5_nothing_to_prune_on_short_chain():
    kv_ops.meta_set_int("pruned_below", 0)          # reset watermark
    assert prune_block_bodies(FLOOR, 150, logger) == 0, "finalized <= floor -> nothing prunable"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
