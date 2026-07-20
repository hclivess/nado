"""
Rolling-mode history pruning (doc/rolling-mode-and-da.md) over the append-only SEGMENT store:
prune_block_bodies UNREFERENCES old block bodies (drops their hash->locator entries) while KEEPING
the number<->hash index (beacon/FFG still resolve), never prunes within the reward/rollback window,
is idempotent + incremental via the meta watermark — and reclaims whole segment FILES once every
body in them is unreferenced (the active segment is never deleted). Fake bodies + index entries —
no real chain.

Run: python3 tests/test_rolling_prune.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_prune_")
os.environ["NADO_SEGMENT_BYTES"] = "4096"   # tiny segments so the whole-segment GC path actually rolls over
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("prune"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import (REWARD_WINDOW, FINALITY_DEPTH, POSW_ANCHOR_OFFSET, POSW_DIFF_TRAIL, EPOCH_LENGTH)
from ops import kv_ops, segment_store
from ops.block_ops import prune_block_bodies
from ops.data_ops import get_home

HOME = get_home()
# The hard safety floor inside prune_block_bodies, DERIVED exactly as the code derives it. This used to
# read `REWARD_WINDOW + FINALITY_DEPTH + 1` (146) and stopped describing the code the moment the v2
# registration-difficulty read window was added as a second floor: a rolling node that prunes a body inside
# that window under-counts registers, derives a lower difficulty than archive nodes, and wedges. The real
# floor is now ~24k blocks, so every scenario below was silently computing prune_below <= 0 and asserting
# against a prune that never happened — five checks red, all of them measuring nothing.
FLOOR = max(REWARD_WINDOW + FINALITY_DEPTH + 1,
            POSW_ANCHOR_OFFSET + POSW_DIFF_TRAIL * EPOCH_LENGTH + FINALITY_DEPTH)
RET = FLOOR + 150            # a configured retention comfortably ABOVE the floor, so the floor is not what
                             # binds in t1-t3 (t4 is the one that deliberately tests the floor binding)

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def body_exists(h):
    """True if the block BODY for height h is still referenced (segment locator present)."""
    bh = kv_ops.hash_by_number(h)
    return bool(bh) and kv_ops.block_loc_get(bh) is not None

def indexed(h):
    """True if height h still has a number->hash index entry."""
    return kv_ops.hash_by_number(h) is not None

def segment_files():
    return sorted(n for n in os.listdir(f"{HOME}/blocks") if n.startswith("seg-") and n.endswith(".dat"))

# Build fake blocks 1..600: an index entry (number<->hash) + a segment-store body each. Payloads are
# opaque bytes (not decodable blocks) — the prune blob-check load fails CLOSED to "not a blob" (same
# as before with raw body files), so eviction proceeds exactly like a plain value-transfer block.
# The fixture is SPARSE, in two bands, and that is not a shortcut — it is what keeps the test runnable.
# The floor is ~24k blocks, so a contiguous 1..FLOOR+600 chain means ~24,700 index+segment writes: 15
# minutes of wall time on a busy box for 87 seconds of CPU, i.e. pure I/O. It buys nothing, because
# prune_block_bodies skips any height with no index entry (`if not bh: continue`) and caps each call at
# start+4000 heights. Only two ranges are ever touched: the LOW band the scans actually walk, and the HIGH
# band around `finalized` that the "must still be present" assertions probe.
LOW_HI = 700                       # prune zone: t1 takes 1..249, t3 250..449, t4 450..599
HIGH_LO, HIGH_HI = RET + 100, RET + 500      # covers RET+150/250/350/405/450 — every high probe below
HEIGHTS = list(range(1, LOW_HI + 1)) + list(range(HIGH_LO, HIGH_HI + 1))
for h in HEIGHTS:
    bh = f"{h:064x}"
    kv_ops.block_index_put(block_number=h, block_hash=bh)
    seg, off, ln = segment_store.append(bh, b"body-%d" % h)
    kv_ops.block_loc_put(bh, seg, off, ln)
SEGS_BEFORE = segment_files()

def t1_prunes_below_window_keeps_index():
    """Prove pruning unreferences bodies below finalized-retention, keeps the number<->hash index and reward-window body, and advances the watermark."""
    # finalized = RET+250, retention = RET -> prune_below = 250
    n = prune_block_bodies(RET + 250, RET, logger)
    assert n == 249, f"expected 249 pruned (heights 1..249), got {n}"
    assert not body_exists(1) and not body_exists(249), "old bodies must be unreferenced"
    assert body_exists(250) and body_exists(RET + 250), "bodies within retention must remain"
    # index is KEPT even for pruned heights (beacon/FFG resolve hashes without the body)
    assert indexed(1) and indexed(249), "number<->hash index must survive a body prune"
    # correctness floor: the reward-window body (finalized - REWARD_WINDOW = 300) must still be present
    assert body_exists(RET + 250 - REWARD_WINDOW), "reward-window body must never be pruned"
    assert kv_ops.meta_get_int("pruned_below", -1) == 250, "watermark advances to prune_below"

def t1b_dead_segments_reclaimed():
    """Prove whole segment FILES are deleted once every body in them is unreferenced, and the active segment always survives."""
    now = segment_files()
    assert len(now) < len(SEGS_BEFORE), f"expected dead segments reclaimed ({len(SEGS_BEFORE)} -> {len(now)})"
    active_name = f"seg-{segment_store.active_segment():08x}.dat"
    assert active_name in now, "the active segment must never be deleted"
    # every surviving non-active segment still holds live bodies
    live = kv_ops.seg_live_counts()
    for name in now:
        seg = int(name[4:-4], 16)
        assert seg == segment_store.active_segment() or live.get(seg, 0) > 0, \
            f"{name} survived with zero live bodies"

def t2_idempotent_noop():
    """Prove a second identical prune call is a no-op (watermark makes it idempotent)."""
    n = prune_block_bodies(RET + 250, RET, logger)  # same inputs -> nothing new
    assert n == 0, f"second identical call must be a no-op, pruned {n}"
    assert kv_ops.meta_get_int("pruned_below", -1) == 250

def t3_incremental_on_new_finality():
    """Prove advancing finality prunes only the delta between the old and new watermark."""
    # finalized advances to RET+450 -> prune_below = 450; prunes only the delta 250..449
    n = prune_block_bodies(RET + 450, RET, logger)
    assert n == 200, f"expected 200 pruned (heights 250..449), got {n}"
    assert not body_exists(449), "newly-out-of-window body gone"
    assert body_exists(450) and body_exists(RET + 450), "bodies within the new window remain"
    assert kv_ops.meta_get_int("pruned_below", -1) == 450

def t4_safety_floor_protects_reward_and_rollback_window():
    """Prove a tiny misconfigured retention is floored at FLOOR so reward and rollback bodies survive."""
    fin = RET + 450
    n = prune_block_bodies(fin, 1, logger)          # retention=1 -> effective floor FLOOR
    expected_prune_below = fin - FLOOR              # never above this
    assert body_exists(fin - REWARD_WINDOW), "reward-window body must survive even a tiny retention"
    assert body_exists(fin - FINALITY_DEPTH), "rollback-window body must survive"
    assert kv_ops.meta_get_int("pruned_below", -1) == expected_prune_below, \
        f"floor must cap prune_below at {expected_prune_below}"

def t5_nothing_to_prune_on_short_chain():
    """Prove a chain no taller than the safety floor prunes nothing."""
    kv_ops.meta_set_int("pruned_below", 0)          # reset watermark
    assert prune_block_bodies(FLOOR, 150, logger) == 0, "finalized <= floor -> nothing prunable"

for name, fn in sorted((n, f) for n, f in list(globals().items())
                       if n.startswith("t") and callable(f) and n[1].isdigit()):
    check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
