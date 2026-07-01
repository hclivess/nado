"""
Execution-layer SETTLEMENT (Phase 2): bonded validators attest an exec-layer (exec_cursor, state_root);
it becomes SETTLED when the attesting bonded shares exceed the 2/3 quorum. Checks the quorum predicate,
latest_settled derivation, one-per-(validator,cursor) uniqueness, and revert-symmetry.

Run: python3 tests/test_settlement.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_settle_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("settle"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import B_MIN, SETTLE_NUM, SETTLE_DEN
from ops import kv_ops
from ops.account_ops import create_account, get_account, reflect_transaction, get_bonded_registry
from ops.transaction_ops import construct_settle_tx, validate_transaction
from ops.settlement_ops import settlement_justified, latest_settled
from ops.key_ops import generate_keys

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()
def raises(fn):
    try: fn(); return False
    except Exception: return True

ROOT_A = "a" * 64
ROOT_B = "b" * 64

def _validator(bonded_shares):
    kd = generate_keys(); create_account(kd["address"], balance=B_MIN, bonded=bonded_shares * B_MIN); return kd

# V1 holds 4 shares, V2 holds 1 share -> total 5 shares; 2/3 quorum needs > 3.33 shares.
V1 = _validator(4)
V2 = _validator(1)

def t1_quorum_predicate():
    reg = get_bonded_registry()
    kv_ops.settlement_put(100, V2["address"], ROOT_A)            # 1 share attesting -> 1/5, not justified
    assert not settlement_justified(100, ROOT_A, reg)
    kv_ops.settlement_put(100, V1["address"], ROOT_A)            # +4 shares -> 5/5 > 2/3, justified
    assert settlement_justified(100, ROOT_A, reg)
    assert not settlement_justified(100, ROOT_B, reg), "a root no one attested is never justified"

def t2_latest_settled_and_reflect():
    tx = construct_settle_tx(V1, exec_cursor=200, state_root=ROOT_A, target_block=1)
    validate_transaction(tx, logger, 1)
    reflect_transaction(tx, logger, 1)                          # V1 alone = 4/5 shares > 2/3 -> settled
    cur, root = latest_settled()
    assert (cur, root) == (200, ROOT_A), f"expected (200,ROOT_A), got {(cur, root)}"

def t3_one_settle_per_validator_per_cursor():
    tx2 = construct_settle_tx(V1, exec_cursor=200, state_root=ROOT_A, target_block=1)
    assert raises(lambda: validate_transaction(tx2, logger, 1)), "second settle from same validator/cursor must reject"

def t4_below_quorum_not_settled():
    # a fresh cursor attested only by V2 (1/5) must NOT settle
    reflect_transaction(construct_settle_tx(V2, exec_cursor=300, state_root=ROOT_B, target_block=1), logger, 1)
    cur, root = latest_settled()
    assert cur != 300, "1/5 stake must not settle"

def t5_revert_unsettles():
    tx = construct_settle_tx(V1, exec_cursor=400, state_root=ROOT_A, target_block=1)
    reflect_transaction(tx, logger, 1)
    assert latest_settled()[0] == 400, "settled after apply"
    reflect_transaction(tx, logger, 1, revert=True)
    assert latest_settled()[0] != 400, "revert removes the settlement (derived, revert-safe)"

def t6_non_bonded_cannot_settle():
    from ops.key_ops import generate_keys as gk
    poor = gk(); create_account(poor["address"], balance=B_MIN)   # no bond
    assert raises(lambda: validate_transaction(construct_settle_tx(poor, 500, ROOT_A, 1), logger, 1)), \
        "a non-bonded sender cannot settle"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
