"""
Auto-collect economics (loops/core_loop.maybe_auto_collect): the unattended presence-dividend sweep must
be PROFITABLE — it reads the node's exact accrued balance from the local exec node and only burns the
`collect_dividend` fee once accrued >= AUTO_COLLECT_MIN_RAW (= AUTO_MIN_FEE_MULTIPLE x the fee it pays),
never blind. It also auto-CLAIMS collected withdrawals (fee-exempt dividend_withdraw) once their proof
matches the SETTLED root — without that, a headless node's sweeps strand in pending forever.

Run: python3 tests/test_auto_collect.py
"""
import os, sys, tempfile, traceback, types, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_autocollect_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("autocollect"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import MIN_TX_FEE, AUTO_COLLECT_MIN_RAW, AUTO_MIN_FEE_MULTIPLE, EPOCH_LENGTH
from ops.key_ops import generate_keys
from loops.core_loop import CoreClient as Core
import ops.settlement_ops as settlement_ops

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

# ---- a minimal fake memserver + Core self, so we can drive Core.maybe_auto_collect directly --------
class FakeMem:
    def __init__(self, kd):
        """Fake memserver holding keydict kd, auto-collect on, epoch-1 tip, and a submitted-tx log."""
        self.keydict = kd
        self.address = kd["address"]
        self.auto_collect_dividend = True
        self.latest_block = {"block_number": EPOCH_LENGTH}     # epoch 1
        self.submitted = []
    def merge_transaction(self, tx, user_origin=False):
        """Record the submitted tx instead of mempooling it; always report success."""
        self.submitted.append(tx)
        return {"result": True}

def make_core(exec_views):
    """Build a fake Core whose _exec_get serves canned exec-node responses (path-prefix keyed dict;
    missing key = exec node unreachable). Returns (core, mem)."""
    kd = generate_keys()
    mem = FakeMem(kd)
    def exec_get(path):
        for prefix, view in exec_views.items():
            if path.startswith(prefix):
                return view
        return None
    core = types.SimpleNamespace(
        memserver=mem, logger=logger, last_auto_collect_epoch=-1,
        _exec_get=exec_get,
        maybe_auto_collect=lambda: Core.maybe_auto_collect(core))
    return core, mem

def set_epoch(mem, epoch):
    """Advance the fake tip to the first block of the given epoch."""
    mem.latest_block = {"block_number": epoch * EPOCH_LENGTH}

def with_settled_root(root, fn):
    """Run fn with ops.settlement_ops.latest_settled patched to report `root` as the settled exec root."""
    orig = settlement_ops.latest_settled
    settlement_ops.latest_settled = lambda *a, **k: (7, root)
    try: fn()
    finally: settlement_ops.latest_settled = orig

# ---- 1. no local exec node -> never sweep blind ---------------------------------------------------
def t1():
    """Prove an unreachable exec node (unknown accrued amount) emits NO fee-burning tx."""
    core, mem = make_core({})                     # _exec_get -> None for everything
    core.maybe_auto_collect()
    assert mem.submitted == [], "no accrual oracle must mean no blind fee-burning sweep"
    assert core.last_auto_collect_epoch == 1, "the probe is still throttled to once per epoch"
check("no exec node -> no blind sweep", t1)

# ---- 2. dust accrual -> keep accruing fee-free ----------------------------------------------------
def t2():
    """Prove an accrued dividend below the dust floor emits no tx (the fee would dominate the sweep)."""
    core, mem = make_core({"/exec/dividend?": {"accrued": AUTO_COLLECT_MIN_RAW - 1, "pending": []}})
    core.maybe_auto_collect()
    assert mem.submitted == [], "below the dust floor the accrual must keep growing fee-free"
check("dust accrual -> no sweep", t2)

# ---- 3. accrued >= floor -> sweep, and the sweep dwarfs its fee -----------------------------------
def t3():
    """Prove a floor-reaching accrual emits exactly one collect blob whose fee is <= 1/AUTO_MIN_FEE_MULTIPLE of the sweep."""
    accrued = AUTO_COLLECT_MIN_RAW
    core, mem = make_core({"/exec/dividend?": {"accrued": accrued, "pending": []}})
    core.maybe_auto_collect()
    assert len(mem.submitted) == 1, "floor reached -> exactly one sweep"
    tx = mem.submitted[0]
    assert tx["recipient"] == "blob" and tx["data"] == {"op": "collect_dividend"}
    assert tx["fee"] == MIN_TX_FEE, "pays exactly the flat protocol fee"
    assert accrued >= tx["fee"] * AUTO_MIN_FEE_MULTIPLE, \
        "PROFITABILITY: the swept amount must dwarf the fee actually paid"
check("floor reached -> one sweep that dwarfs its fee", t3)

# ---- 4. throttle: one sweep attempt per epoch -----------------------------------------------------
def t4():
    """Prove auto-collect runs at most once per epoch, and again the next epoch."""
    core, mem = make_core({"/exec/dividend?": {"accrued": AUTO_COLLECT_MIN_RAW * 5, "pending": []}})
    core.maybe_auto_collect(); core.maybe_auto_collect()
    assert len(mem.submitted) == 1, "same epoch must not sweep twice"
    set_epoch(mem, 2); core.maybe_auto_collect()
    assert len(mem.submitted) == 2, "a new epoch sweeps again"
check("throttled to one sweep per epoch", t4)

# ---- 5. settled pending withdrawal -> fee-exempt auto-claim ---------------------------------------
def t5():
    """Prove a pending withdrawal whose proof matches the SETTLED root is auto-claimed via a fee-exempt dividend_withdraw."""
    core, mem = make_core({
        "/exec/dividend?": {"accrued": 0, "pending": [{"nonce": "3", "amount": 12345}]},
        "/exec/dividend_proof?": {"proof": [["L", "aa"]], "state_root": "rootX"},
    })
    with_settled_root("rootX", core.maybe_auto_collect)
    assert len(mem.submitted) == 1, "a settled pending withdrawal must be claimed"
    tx = mem.submitted[0]
    assert tx["recipient"] == "dividend_withdraw" and tx["fee"] == 0, "the claim is fee-exempt (always profitable)"
    assert tx["data"]["addr"] == mem.address and tx["data"]["amount"] == 12345 and tx["data"]["nonce"] == "3"
check("settled pending withdrawal -> fee-exempt auto-claim", t5)

# ---- 6. unsettled proof -> wait (no claim yet), dust accrual stays unswept ------------------------
def t6():
    """Prove a proof against a NOT-YET-SETTLED root defers the claim (retry next epoch) and sweeps nothing."""
    core, mem = make_core({
        "/exec/dividend?": {"accrued": 5, "pending": [{"nonce": "3", "amount": 12345}]},
        "/exec/dividend_proof?": {"proof": [["L", "aa"]], "state_root": "rootNEW"},
    })
    with_settled_root("rootOLD", core.maybe_auto_collect)
    assert mem.submitted == [], "an unsettled proof must wait; a dust accrual must not be swept"
check("unsettled proof -> claim deferred", t6)

# ---- 7. kill switch -------------------------------------------------------------------------------
def t7():
    """Prove auto_collect_dividend=False is a complete no-op."""
    core, mem = make_core({"/exec/dividend?": {"accrued": AUTO_COLLECT_MIN_RAW * 10, "pending": []}})
    mem.auto_collect_dividend = False
    core.maybe_auto_collect()
    assert mem.submitted == [] and core.last_auto_collect_epoch == -1, "disabled must be a complete no-op"
check("auto_collect_dividend=False is a no-op", t7)

print(f"\n{'ALL AUTO-COLLECT CHECKS PASSED' if fails==0 else str(fails)+' AUTO-COLLECT CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
