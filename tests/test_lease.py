"""
Registration PoSW presence LEASE (renewable): a register/recert grants OPEN-lane eligibility for
POSW_LEASE_EPOCHS; it expires unless renewed; renewal restores it; revert is symmetric (removing the last
recert clears `registered`). The PoSW itself is covered by tests/test_posw.py.

Run: python3 tests/test_lease.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_lease_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("lease"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import POSW_LEASE_EPOCHS
from ops import kv_ops
from ops.account_ops import create_account, get_account, apply_register, apply_heartbeat, get_open_registry
from ops.key_ops import generate_keys

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

A = generate_keys()["address"]
create_account(A, registered=0)
E = 10
E2 = E + POSW_LEASE_EPOCHS + 1     # comfortably past the lease

def t1_lease_grants_then_expires():
    apply_heartbeat(A, epoch=E, logger=logger)          # present at E
    apply_register(A, epoch=E, logger=logger)           # register + recert at E
    assert A in get_open_registry(E), "eligible right after registering"
    apply_heartbeat(A, epoch=E2, logger=logger)         # still present at E2 (so presence isn't the reason)
    assert A not in get_open_registry(E2), "lease must expire -> not eligible even though present"

def t2_renewal_restores_eligibility():
    apply_register(A, epoch=E2, logger=logger)          # renew (fresh recert at E2)
    assert A in get_open_registry(E2), "renewed lease -> eligible again"

def t3_revert_renewal_keeps_registered():
    apply_register(A, epoch=E2, logger=logger, revert=True)   # undo the renewal (LIFO)
    assert get_account(A)["registered"] == 1, "still registered: the first recert remains"
    assert A not in get_open_registry(E2), "lease expired again after undoing the renewal"

def t4_revert_last_recert_clears_registered():
    apply_register(A, epoch=E, logger=logger, revert=True)    # undo the only remaining recert
    assert kv_ops.recert_latest(A) < 0, "no recert left"
    assert get_account(A)["registered"] == 0, "registered cleared when no recert remains"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
