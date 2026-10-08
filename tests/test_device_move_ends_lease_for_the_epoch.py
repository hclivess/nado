"""A device move ends the previous identity's lease for the whole epoch (protocol.EVICT_VOIDS_EPOCH_HEIGHT).

Through the real apply path (reflect_transaction on register txs; only the certificate parser is stubbed so a fake
statement {"k": key} binds to that key):
  * from the gate, identity X whose device moved to Y in epoch E is absent from present_at_epoch(E) even when X's own
    statement-free renewal is applied after the move at the same height; before the gate the old rule holds;
  * X counts again after a register of its own in a later epoch;
  * reverting the move restores X's eviction list exactly.

Run: python3 tests/test_device_move_ends_lease_for_the_epoch.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_evict_epoch_")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("evict"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

import protocol as P
from ops import kv_ops
from ops import device_attest as DA
from ops.account_ops import create_account, reflect_transaction
from ops.dividend_ops import present_at_epoch
from signatures import generate_keydict

L = P.EPOCH_LENGTH
GATE = 600 * L
P.EVICT_VOIDS_EPOCH_HEIGHT = GATE
DA.device_binding_key = lambda dev, *_a, **_k: dev["k"]
DA.credential_public_key = lambda dev: None

fails = 0


def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def addr():
    a = generate_keydict()["address"]
    create_account(a, balance=0)
    return a


def register(sender, height, device=None, revert=False):
    tx = {"sender": sender, "recipient": "register", "amount": 0, "fee": 0, "txid": f"r-{sender[:8]}-{height}-{device}",
          "max_block": height, "data": ""}
    if device:
        tx["device"] = {"k": device}
    reflect_transaction(tx, logger, block_height=height, revert=revert)


def scenario(base_epoch, key):
    """X binds `key`, then in epoch E (base+400) the device moves to Y and X renews statement-free at the same height,
    the renewal applied after the move. Returns (X, Y, E, move height)."""
    x, y = addr(), addr()
    register(x, base_epoch * L + 3, device=key)
    e = base_epoch + 400
    h = e * L + 7
    register(y, h, device=key)             # the move
    register(x, h)                         # X's statement-free renewal, applied after the move
    return x, y, e, h


def t_before_gate():
    x, y, e, _h = scenario(10, "ledger:before")
    assert x in present_at_epoch(e) and y in present_at_epoch(e), "before the gate the old rule holds"


def t_from_gate():
    x, y, e, _h = scenario(700, "ledger:after")
    pres = present_at_epoch(e)
    assert x not in pres and y in pres, "from the gate the moved-from identity is absent for the epoch"
    assert x not in present_at_epoch(e + 1)


def t_counts_again_after_a_later_register():
    x, y, e, _h = scenario(1400, "ledger:back")
    register(x, (e + 1) * L + 2, device="ledger:other")
    assert x in present_at_epoch(e + 1), "a register in a later epoch counts"


def t_revert_is_exact():
    x, y = addr(), addr()
    register(x, 2100 * L + 3, device="ledger:rev")
    before = kv_ops.devevict_get(x)
    h = 2500 * L + 7
    register(y, h, device="ledger:rev")
    assert kv_ops.devevict_get(x) == before + [(2500, 2500)]
    register(y, h, device="ledger:rev", revert=True)
    assert kv_ops.devevict_get(x) == before, "revert restores the eviction list"


for name, fn in [("before the gate an eviction voids only the latest recert", t_before_gate),
                 ("from the gate the moved-from identity is absent for the whole epoch", t_from_gate),
                 ("a register in a later epoch counts again", t_counts_again_after_a_later_register),
                 ("reverting the move restores the eviction list exactly", t_revert_is_exact)]:
    check(name, fn)
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
