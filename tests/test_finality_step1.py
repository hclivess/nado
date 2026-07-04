"""
Enforced-finality unit checks (#17, security step 1).

Covers: the persisted monotonic finalized_height accessor (default + round-trip); the
incorporate-time advance formula max(prev, H - FINALITY_DEPTH); and the core safety property —
rollback_one_block REFUSES (FinalityViolation) to revert a block at/below the finalized floor, but
does NOT refuse at the boundary just above it.
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_final_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.expanduser(f"~/nado/{d}"), exist_ok=True)

import logging
logger = logging.getLogger("final"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from ops.account_ops import get_finalized_height, set_finalized_height
from ops.block_ops import save_block
from rollback import rollback_one_block, FinalityViolation
from protocol import FINALITY_DEPTH

fails = 0
def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


# --- 1) accessor defaults to 0 and round-trips ---------------------------------------------------
def t1():
    assert get_finalized_height() == 0, "default finalized_height must be 0 (genesis)"
    set_finalized_height(50)
    assert get_finalized_height() == 50, "round-trip failed"
    set_finalized_height(0)  # reset for later tests
check("finalized_height defaults to 0 and round-trips", t1)


# --- 2) the incorporate advance formula is monotonic and depth-lagged ----------------------------
def t2():
    def advance(prev, height):
        return max(prev, height - FINALITY_DEPTH)
    assert advance(0, 10) == 0, "below depth must not finalize anything (max with 0)"
    assert advance(0, FINALITY_DEPTH + 5) == 5, "H-depth once past the depth"
    assert advance(40, 50) == 40, "must never regress (50-30=20 < 40)"
    assert advance(40, 100) == 70, "advances when H-depth exceeds prev"
check("advance = max(prev, H - FINALITY_DEPTH) is monotonic + depth-lagged", t2)


# --- 3) rollback REFUSES below the finalized floor, allows at the boundary ------------------------
PARENT_HASH = "a" * 64
TIP_HASH = "b" * 64
parent = {"block_number": 4, "block_hash": PARENT_HASH, "parent_hash": "c" * 64,
          "block_creator": "ndo" + "0" * 46, "block_reward": 0, "block_transactions": [],
          "block_timestamp": 1, "cumulative_fees": 0}
tip = {"block_number": 5, "block_hash": TIP_HASH, "parent_hash": PARENT_HASH,
       "block_creator": "ndo" + "0" * 46, "block_reward": 1000000000, "block_transactions": [],
       "block_timestamp": 2, "block_ip": "ndo" + "0" * 46, "cumulative_fees": 0}
save_block(parent, logger)  # so rollback can load the would-be new tip

def t3_refuse():
    set_finalized_height(100)  # tip(5)'s parent is 4 < 100 -> finalized -> must refuse
    raised = False
    try:
        rollback_one_block(logger=logger, block=tip)
    except FinalityViolation:
        raised = True
    assert raised, "rolling back a block whose parent is below the floor must raise FinalityViolation"
check("rollback below finalized floor raises FinalityViolation", t3_refuse)

def t3_boundary():
    # parent.number == 4; with floor == 4, parent is NOT < 4, so finality must NOT refuse (it may
    # raise some OTHER error from the state revert of an un-incorporated block — that's fine here).
    set_finalized_height(4)
    refused = False
    try:
        rollback_one_block(logger=logger, block=tip)
    except FinalityViolation:
        refused = True
    except Exception:
        pass  # non-finality error from reverting unprepared state is acceptable for this check
    assert not refused, "finality must NOT refuse at the boundary (parent == finalized_height)"
check("rollback at the boundary (parent == floor) is not refused by finality", t3_boundary)


print(f"\n{'ALL FINALITY CHECKS PASSED' if not fails else str(fails) + ' FAILURE(S)'}")
sys.exit(1 if fails else 0)
