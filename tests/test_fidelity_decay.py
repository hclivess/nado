"""
OPEN-lane fidelity with ABSENCE DECAY (continuous-presence, anti-Sybil). apply_heartbeat now decays
fidelity for the gap since the last heartbeat (capped at the current value), +GAIN for this epoch, and
is EXACTLY revert-symmetric (rollback restores fidelity + last_hb_epoch byte-identically via the
hb_revert record). Drives account_ops.apply_heartbeat directly on real KV accounts.

Run: python3 tests/test_fidelity_decay.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_fiddecay_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("fiddecay"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import FIDELITY_GAIN, FIDELITY_DECAY
from ops import kv_ops
from ops.account_ops import create_account, apply_heartbeat
from ops.key_ops import generate_keys

assert FIDELITY_GAIN == 1 and FIDELITY_DECAY == 1, "this test's literals assume GAIN==DECAY==1"

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def _fid(a): return int(kv_ops.get_account(a).get("fidelity", 0))
def _last(a): return int(kv_ops.get_account(a).get("last_hb_epoch", 0))
def _addr():
    kd = generate_keys(); create_account(kd["address"], registered=1); return kd["address"]

def t1_continuous_presence_accrues():
    a = _addr()
    for e in range(1, 6):
        apply_heartbeat(a, e, logger)
        assert _fid(a) == e, f"epoch {e}: fidelity {e} expected, got {_fid(a)}"
        assert _last(a) == e

def t2_absence_decays():
    a = _addr()
    for e in range(1, 6): apply_heartbeat(a, e, logger)      # fidelity 5, last 5
    assert _fid(a) == 5
    apply_heartbeat(a, 10, logger)                           # gap 4 -> decay 4 -> +1 -> 2
    assert _fid(a) == 2, f"expected 2 after decay, got {_fid(a)}"
    assert _last(a) == 10

def t3_decay_capped_never_negative():
    a = _addr()
    apply_heartbeat(a, 1, logger)                            # fidelity 1
    apply_heartbeat(a, 100, logger)                          # gap 98 -> decay capped at 1 -> +1 -> 1
    assert _fid(a) == 1, f"decay must cap at current fidelity; expected 1, got {_fid(a)}"

def t4_first_heartbeat_no_decay():
    a = _addr()
    apply_heartbeat(a, 50, logger)                           # prev 0 -> no gap
    assert _fid(a) == FIDELITY_GAIN and _last(a) == 50

def t5_revert_symmetry_gain():
    a = _addr()
    apply_heartbeat(a, 1, logger)
    f0, l0 = _fid(a), _last(a)
    apply_heartbeat(a, 2, logger)
    apply_heartbeat(a, 2, logger, revert=True)
    assert (_fid(a), _last(a)) == (f0, l0), f"gain revert must restore ({f0},{l0}), got ({_fid(a)},{_last(a)})"

def t6_revert_symmetry_decay():
    a = _addr()
    for e in range(1, 6): apply_heartbeat(a, e, logger)      # fidelity 5, last 5
    f0, l0 = _fid(a), _last(a)
    apply_heartbeat(a, 10, logger)                           # decay case -> fidelity 2, last 10
    assert (_fid(a), _last(a)) == (2, 10)
    apply_heartbeat(a, 10, logger, revert=True)
    assert (_fid(a), _last(a)) == (f0, l0), f"decay revert must restore ({f0},{l0}), got ({_fid(a)},{_last(a)})"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
