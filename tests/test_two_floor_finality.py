"""TWO-FLOOR FINALITY: the un-crossable floor is the quorum checkpoint, not a 45-block observation.

WHY. `finalized_height` advances at tip - FINALITY_DEPTH — a LOCAL observation. Treating it as immutable
meant two branches of any >45-block fork each locked their own floor within minutes, no rollback could
reach the ancestor, and recovery had to CROSS floors (the escalated floor=0 re-anchor) — the entire
"finality revert" class. Measured 2026-08-17: eight floor-crossing recoveries, two archive truncations, in
one day. Meanwhile the FFG machinery — committee, 2/3-seat quorum, two-consecutive justification,
slashable attestations — was fully built and, as core_loop's own comment measured, could NEVER win the
floor max(): quorum finality was observational.

NOW: `hard_finality` (FFG checkpoint folded with a wide liveness backstop, tip - FINALITY_HARD_BACKSTOP)
is what rollback refuses, what classifies a fork DEAD vs recoverable, and the floor no recovery may cross.
`finalized_height` keeps its depth cadence for exec/pruning/status — the L1->exec latency does not move —
but is legally lowered when a reorg crosses it (the exec layer absorbs that with its rewind checkpoints).

DEPLOYMENT is by the /update wave (operator decision: no height gate), so the MIXED-FLEET section is the
load-bearing one: the new meta key must be invisible to the consensus root, or the wave itself would fork
the fleet exactly like the h10047 index-watermark row did.

Run: python3 tests/test_two_floor_finality.py
"""
import os
import subprocess
import sys
import tempfile

if os.environ.get("_TWO_FLOOR_CHILD") != "1":
    tmp = tempfile.mkdtemp(prefix="two_floor_")
    env = dict(os.environ, HOME=tmp, _TWO_FLOOR_CHILD="1", NADO_ALLOW_PYTHON_KERNELS="1",
               PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, os.path.abspath(__file__)], env=env)
    sys.exit(r.returncode)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.makedirs(os.path.expanduser("~/nado/index"), exist_ok=True)

from ops import kv_ops, snapshot_ops                                        # noqa: E402
from ops.account_ops import (get_finalized_height, set_finalized_height,     # noqa: E402
                             get_hard_finality, set_hard_finality)
from ops import fork_resolution                                              # noqa: E402
from protocol import EPOCH_LENGTH, FINALITY_DEPTH, FINALITY_HARD_BACKSTOP    # noqa: E402

FAILS = []
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        import traceback; traceback.print_exc()
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


def src(path):
    return open(os.path.join(ROOT, path), encoding="utf8").read()


# ---- the floors themselves ---------------------------------------------------------------------------
def t_hard_floor_persists_and_defaults_to_zero():
    assert get_hard_finality() == 0, "a fresh chain has no immutable prefix"
    set_hard_finality(1200)
    assert get_hard_finality() == 1200


def t_backstop_is_wide_and_ffg_normally_wins():
    """The whole point of the backstop width: an honest fork must be able to persist for many epochs
    before floors lock, and the FFG lag (~1-2 epochs) sits comfortably inside it."""
    assert FINALITY_HARD_BACKSTOP >= 5 * EPOCH_LENGTH, "backstop narrower than a real outage"
    assert FINALITY_HARD_BACKSTOP > 2 * EPOCH_LENGTH, "backstop would beat a live FFG — FFG must lead"
    assert FINALITY_HARD_BACKSTOP > FINALITY_DEPTH, "the hard floor must sit below the depth floor"


# ---- MIXED FLEET: the /update-wave deployment is only safe if the root cannot see the new key --------
def t_hard_finality_is_outside_the_consensus_root():
    assert b"hard_finality" in snapshot_ops.ROOT_EXCLUDED_META_KEYS, \
        "hard_finality in the root => the update wave itself forks the fleet (the h10047 class)"


def t_the_root_triples_actually_filter_it():
    """Not just the constant — the filter: a node with the row and a node without must commit the same."""
    with_row = [("meta", b"hard_finality", b"123"), ("meta", b"supply", b"9"), ("accounts", b"a", b"1")]
    without = [("meta", b"supply", b"9"), ("accounts", b"a", b"1")]
    assert snapshot_ops._root_triples(with_row) == snapshot_ops._root_triples(without), \
        "the consensus commitment differs between a new-code and an old-code node"


# ---- fork classification: what is recoverable ---------------------------------------------------------
def t_a_fork_between_depth_and_hard_floor_is_a_reorg_not_dead():
    """The exact geometry that produced every wedge recovery today: ancestor deeper than 45 blocks but
    far above the quorum floor. It must classify as an ordinary rollback."""
    tip, hard = 61_000, 60_400
    ancestor = tip - 100                        # deeper than FINALITY_DEPTH=45, above hard
    assert fork_resolution.classify(ancestor, tip, hard) == fork_resolution.REORG
    assert fork_resolution.classify(hard - 1, tip, hard) == fork_resolution.DEAD_FORK, \
        "below the quorum floor is genuinely dead"
    assert fork_resolution.classify(tip, tip, hard) == fork_resolution.BEHIND


# ---- source pins: every consumer moved to the right floor ---------------------------------------------
def t_rollback_refuses_at_the_hard_floor_and_lowers_the_depth_floor():
    s = src("rollback.py")
    assert "hard = get_hard_finality()" in s, "rollback no longer reads the hard floor"
    assert 'previous_block["block_number"] < hard' in s, "rollback no longer refuses at the hard floor"
    assert "set_finalized_height(max(hard, previous_block[\"block_number\"]))" in s, \
        "crossing the depth floor no longer lowers it — incorporate would resurrect the old branch's floor"
    fn = s[s.index("def rollback_one_block"):]
    assert fn.index("< hard") < fn.index("set_finalized_height"), "the refusal must precede the lowering"


def t_incorporate_reads_the_persisted_depth_floor_not_the_mirror():
    s = src("loops/core_loop.py")
    assert "prev_depth = get_finalized_height()" in s, \
        "advancing from the memserver mirror re-raises a floor a rollback just legally lowered"
    assert "new_hard = max(prev_hard, ffg_final, backstop_final)" in s, "the hard floor no longer advances"
    blk = s[s.index("TWO-FLOOR ADVANCE"):]
    blk = blk[:blk.index("set_hard_finality(new_hard)")]
    assert "backstop_final = 0" in blk and "ffg_final = 0" in blk and "depth_final = 0" in blk, \
        "the corroboration gate must zero ALL floor terms — minority self-finalize is worse now"


def t_reanchor_floor_is_the_hard_floor_and_zero_is_gone():
    s = src("loops/core_loop.py")
    assert "floor = get_hard_finality()" in s, "the re-anchor floor is no longer the hard floor"
    assert "floor = 0 if allow_below_floor" not in s, \
        "the floor=0 escalated re-anchor is back — the mechanism that truncated the archive twice"


def t_dead_fork_machinery_probes_the_hard_floor():
    s = src("loops/core_loop.py")
    fs = s[s.index("def _fork_state"):]
    fs = fs[:fs.index("def _maybe_escape_dead_fork")]
    assert "finalized=_ghf()" in fs, "fork classification uses the crossable depth floor again"
    esc = s[s.index("def _maybe_escape_dead_fork"):]
    esc = esc[:esc.index("\n    def ")]
    assert "height = get_hard_finality()" in esc, "the purge escape probes the crossable floor"
    assert "if height <= 0:" in esc, "a node with no immutable prefix has nothing to escape from"


def t_status_exposes_the_hard_floor():
    assert '"hard_finality"' in src("nado.py"), "operators cannot see the floor that actually binds"


for name, fn in [(n, f) for n, f in list(globals().items()) if n.startswith("t_")]:
    check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "THE UN-CROSSABLE FLOOR IS THE QUORUM CHECKPOINT")
sys.exit(1 if FAILS else 0)
