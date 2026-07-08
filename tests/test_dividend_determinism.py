"""
Deterministic presence-dividend accrual (audit fix): the exec node distributes each epoch's total
DIVIDEND_POOL inflow (L1, per-epoch) over weights_at_epoch(E) (L1, per-epoch) — a PURE FUNCTION of the
finalized block stream, so batching / poll timing can no longer make honest nodes disagree on the committed
dividend map (which previously broke default-layer settlement).

Run: python3 tests/test_dividend_determinism.py
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_divdet_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
from genesis import create_indexers
create_indexers()
from execnode.state import ExecState
from ops import kv_ops

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def _st():
    return ExecState(tempfile.mktemp(prefix="nado_dd_", suffix=".json"))

SEQ = [(1000, {"a": 2, "b": 1}), (500, {"a": 1, "b": 1}), (0, {"a": 1}), (777, {"a": 3, "b": 2, "c": 1})]


def t1_pure_and_conserving():
    """Same per-epoch sequence → identical dividend map + state_root; and no raw is created or lost."""
    s1, s2 = _st(), _st()
    for i, w in SEQ: s1.accrue_dividend_epoch(i, w)
    for i, w in SEQ: s2.accrue_dividend_epoch(i, w)
    assert s1.dividend == s2.dividend and s1.state_root() == s2.state_root(), "accrual is a pure function"
    total_in = sum(i for i, _ in SEQ)
    total_out = sum(s1.dividend.values()) + s1.div_carry
    assert total_out == total_in, f"conservation: {total_out} != {total_in}"

def t2_batching_independent():
    """THE fix: WHEN you accrue (poll batch size) cannot change the outcome — only the per-epoch sequence does."""
    seq = [(300, {"a": 1, "b": 2}), (0, {}), (900, {"a": 1}), (450, {"b": 1, "c": 1})]
    a = _st()
    for i, w in seq: a.accrue_dividend_epoch(i, w)              # one pass
    b = _st()
    for i, w in seq[:2]: b.accrue_dividend_epoch(i, w)          # split across two "polls"
    for i, w in seq[2:]: b.accrue_dividend_epoch(i, w)
    assert a.dividend == b.dividend and a.div_carry == b.div_carry, "batching must not change the result"

def t3_empty_epoch_carries():
    """An epoch with no present miners carries its whole inflow forward (no raw lost); the next present set gets it."""
    s = _st()
    s.accrue_dividend_epoch(1000, {})
    assert s.dividend == {} and s.div_carry == 1000, "inflow carries when nobody is present"
    s.accrue_dividend_epoch(0, {"a": 1})
    assert s.dividend.get("a") == 1000 and s.div_carry == 0, "carry distributed once a present set exists"

def t4_weighted_split():
    """Shares are proportional to weights, integer floor, remainder carried."""
    s = _st(); s.accrue_dividend_epoch(100, {"a": 3, "b": 1})
    assert s.dividend["a"] == 75 and s.dividend["b"] == 25 and s.div_carry == 0

def t5_persist_watermark():
    """last_div_epoch + dividend + carry survive save/load (a restarted node never re-accrues an epoch)."""
    p = tempfile.mktemp(suffix=".json")
    s = ExecState(p); s.accrue_dividend_epoch(500, {"a": 1}); s.last_div_epoch = 4; root = s.state_root(); s.save()
    s2 = ExecState(p)
    assert s2.last_div_epoch == 4 and s2.dividend.get("a") == 500 and s2.state_root() == root

def t6_inflow_tracking_and_revert():
    """L1 per-epoch inflow accumulates and reverts exactly (revert-symmetric)."""
    kv_ops.dividend_inflow_add(5, 300); kv_ops.dividend_inflow_add(5, 200)
    assert kv_ops.dividend_inflow_get(5) == 500
    kv_ops.dividend_inflow_add(5, 200, revert=True)
    assert kv_ops.dividend_inflow_get(5) == 300
    assert kv_ops.dividend_inflow_get(99) == 0, "unseen epoch -> 0"


for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
