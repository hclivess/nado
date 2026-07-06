import os, sys, tempfile, traceback, types, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_autobond_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("autobond"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import DENOMINATION, MIN_TX_FEE, AUTO_BOND_MIN_RAW, BOND_CAP, EPOCH_LENGTH
from ops.account_ops import create_account, get_account, change_balance, change_bonded
from ops.key_ops import generate_keys
from loops.core_loop import CoreClient as Core

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

# ---- a minimal fake memserver + Core self, so we can drive Core.maybe_auto_bond directly -----------
class FakeMem:
    def __init__(self, kd, pct):
        """Fake memserver holding keydict kd, auto_bond_percent pct, epoch-1 tip, and a submitted-tx log."""
        self.keydict = kd
        self.address = kd["address"]
        self.auto_bond_percent = pct
        self.latest_block = {"block_number": EPOCH_LENGTH}     # epoch 1
        self.submitted = []
    def merge_transaction(self, tx, user_origin=False):
        """Record the submitted tx instead of mempooling it; always report success."""
        self.submitted.append(tx)
        return {"result": True}

def make_core(pct):
    """Build a fake Core (registered funded miner + FakeMem at pct) whose maybe_auto_bond drives the real logic; returns (core, mem, keydict)."""
    kd = generate_keys()
    # a registered, funded miner account
    create_account(kd["address"], balance=0)
    from ops.kv_ops import account_set
    account_set(kd["address"], "registered", 1)
    mem = FakeMem(kd, pct)
    core = types.SimpleNamespace(
        memserver=mem, logger=logger,
        last_auto_bond_epoch=-1, auto_bond_baseline=None,
        maybe_auto_bond=lambda: Core.maybe_auto_bond(core))
    return core, mem, kd

def set_epoch(mem, epoch):
    """Advance the fake tip to the first block of the given epoch."""
    mem.latest_block = {"block_number": epoch * EPOCH_LENGTH}

def add_reward(addr, nado):
    """Credit addr with a mining reward of `nado` whole NADO."""
    change_balance(addr, int(nado * DENOMINATION), logger=logger)

def apply_bond(addr, raw, fee):
    """Simulate a bond tx landing: move raw from spendable to bonded and destroy the fee."""
    # simulate the bond tx landing: spendable -> bonded, fee destroyed
    change_balance(addr, -(raw + fee), logger=logger)
    change_bonded(addr, raw, logger=logger)

# ---- 1. baseline-then-compound: first call only sets baseline; a later epoch bonds pct of the gain --
def t1():
    """Prove the first call only sets a baseline, then a later epoch bonds pct of the new gain."""
    core, mem, kd = make_core(pct=50)
    add_reward(kd["address"], 5)                 # 5 NADO already present before auto-bond is observed
    core.maybe_auto_bond()
    assert mem.submitted == [], "first call must only establish a baseline (no pre-existing-balance bond)"
    assert core.auto_bond_baseline == 5 * DENOMINATION

    add_reward(kd["address"], 10)                # mined +10 NADO
    set_epoch(mem, 2)
    core.maybe_auto_bond()
    assert len(mem.submitted) == 1, "should bond once on the gain"
    tx = mem.submitted[0]
    assert tx["recipient"] == "bond" and tx["sender"] == kd["address"]
    assert tx["amount"] == 5 * DENOMINATION, tx["amount"]   # 50% of the +10 gain
    assert core.last_auto_bond_epoch == 2
check("baseline first, then bonds 50% of new earnings", t1)

# ---- 2. throttle: at most one auto-bond per epoch ------------------------------------------------
def t2():
    """Prove auto-bond is throttled to at most one bond tx per epoch."""
    core, mem, kd = make_core(pct=50)             # <100% so the gain also covers the tx fee
    core.maybe_auto_bond()                        # baseline
    add_reward(kd["address"], 4); set_epoch(mem, 2)
    core.maybe_auto_bond()                        # bonds
    add_reward(kd["address"], 4)                  # more reward, SAME epoch
    core.maybe_auto_bond()                        # must NOT bond again this epoch
    assert len(mem.submitted) == 1, f"one bond per epoch, got {len(mem.submitted)}"
check("throttled to one auto-bond per epoch", t2)

# ---- 3. dust floor: a gain whose pct is below AUTO_BOND_MIN_RAW accrues (no tx, no rebaseline) ----
def t3():
    """Prove a gain whose pct share is below AUTO_BOND_MIN_RAW emits no tx and keeps the baseline (accrues)."""
    core, mem, kd = make_core(pct=1)
    core.maybe_auto_bond()                        # baseline = 0
    # 1% of this gain must be < AUTO_BOND_MIN_RAW (0.001 NADO). gain = 0.05 NADO -> 1% = 0.0005 NADO.
    add_reward(kd["address"], 0)                  # noop
    change_balance(kd["address"], AUTO_BOND_MIN_RAW * 50, logger=logger)  # gain = 5e8 raw
    set_epoch(mem, 2)
    base_before = core.auto_bond_baseline
    core.maybe_auto_bond()
    assert mem.submitted == [], "below dust floor must not emit a tx"
    assert core.auto_bond_baseline == base_before, "dust path must NOT rebaseline (keeps accruing)"
check("below dust floor accrues without a tx or rebaseline", t3)

# ---- 4. stops at BOND_CAP (extra bond buys no weight) --------------------------------------------
def t4():
    """Prove no auto-bond is emitted once bonded is already at BOND_CAP."""
    core, mem, kd = make_core(pct=100)
    change_bonded(kd["address"], BOND_CAP, logger=logger)   # already at cap
    core.maybe_auto_bond()                        # baseline
    add_reward(kd["address"], 100); set_epoch(mem, 2)
    core.maybe_auto_bond()
    assert mem.submitted == [], "must not bond once bonded >= BOND_CAP"
check("stops auto-bonding at BOND_CAP", t4)

# ---- 5. pct=0 is fully off --------------------------------------------------------------------
def t5():
    """Prove auto_bond_percent=0 is a complete no-op (no tx, no baseline)."""
    core, mem, kd = make_core(pct=0)
    add_reward(kd["address"], 100); set_epoch(mem, 2)
    core.maybe_auto_bond(); core.maybe_auto_bond()
    assert mem.submitted == [] and core.auto_bond_baseline is None, "pct=0 must be a complete no-op"
check("auto_bond_percent=0 is a no-op", t5)

# ---- 6. realistic round: bond lands (reduces balance); a no-reward epoch then bonds nothing -------
def t6():
    """Prove that after a bond lands (balance drops), a no-reward epoch bonds nothing and bonded stays correct."""
    core, mem, kd = make_core(pct=50)
    core.maybe_auto_bond()                        # baseline 0
    add_reward(kd["address"], 10); set_epoch(mem, 2)
    core.maybe_auto_bond()                        # bonds 5 NADO
    tx = mem.submitted[-1]
    apply_bond(kd["address"], tx["amount"], tx["fee"])   # the bond tx lands in a block
    set_epoch(mem, 3)
    core.maybe_auto_bond()                        # NO new reward this epoch -> no bond
    assert len(mem.submitted) == 1, f"a no-reward epoch must bond nothing, got {len(mem.submitted)}"
    a = get_account(kd["address"])
    assert a["bonded"] == 5 * DENOMINATION, a     # the 5 NADO is now bonded
check("bond lands; a no-reward epoch compounds nothing", t6)

print(f"\n{'ALL AUTO-BOND CHECKS PASSED' if fails==0 else str(fails)+' AUTO-BOND CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
