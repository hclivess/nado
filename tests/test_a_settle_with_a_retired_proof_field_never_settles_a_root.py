"""A settle carrying a retired proof field (`proof`, `proof_da`) never settles a root (protocol.SETTLE_FIELDS_HEIGHT).

Validation refused the two retired names by VALUE (`data.get("proof") is None`), while apply marked the root proven by the
key's PRESENCE (`"proof" in data`) and settlement_justified honours that marker with no quorum and no stake floor
(SETTLE_PROOF_TRUSTLESS). So `{"proof": null}` passed validation and still wrote the proven marker. From the gate:
  - validation refuses either key whatever its value, at block validation and at mempool admission (no height);
  - apply never derives `proven` from either name, even for a tx that reached it some other way;
  - an honest bare settle is unchanged.
Below the gate (history) the old reading holds: the tx validates and apply writes the marker, and revert deletes exactly
the marker apply put. Real kv tables and real signed transactions, one bonded account the size of a B_MIN bond.

Run: python3 tests/test_a_settle_with_a_retired_proof_field_never_settles_a_root.py
"""
import os, sys, tempfile, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-settle-fields-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("settle-fields"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

import protocol as P
from protocol import B_MIN, DEFAULT_NS
from ops import kv_ops
from ops import settlement_ops as SO
from ops.account_ops import create_account, reflect_transaction
from ops.transaction_ops import validate_transaction, construct_settle_tx, _seal
from ops.key_ops import generate_keys

fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f"  [{detail}]"))
    if not cond:
        fails.append(name)

def refused(fn):
    try:
        fn()
        return None
    except AssertionError as e:
        return str(e) or "refused"

def fresh():
    SO._latest_settled_cache[0] = None
    SO._recent_settled_cache[0] = None

ATT = generate_keys()
create_account(ATT["address"], balance=B_MIN, bonded=B_MIN)
kv_ops.account_set_field(ATT["address"], "public_key", ATT["public_key"])
for _ in range(15):                                   # stake the attacker is a sliver of, none of it attesting
    kd = generate_keys(); create_account(kd["address"], balance=B_MIN, bonded=10 * B_MIN)
FAKE = "ee" * 32
G = P.SETTLE_FIELDS_HEIGHT


def settle_with(field, cursor, h):
    """A real signed settle whose data carries `field: null` (the retired name present, its value None)."""
    tx = construct_settle_tx(ATT, exec_cursor=cursor, state_root=FAKE, max_block=h)
    tx["data"][field] = None
    for k in ("txid", "signature"):
        tx.pop(k, None)
    _seal(tx, ATT)
    return tx


check("the gate is a live height on generation 29 and block 1 on a fresh chain",
      G == (86400 if P.CHAIN_GENERATION == 29 else 1), G)

for field in ("proof", "proof_da"):
    # FROM THE GATE: refused at validation, at mempool admission, and inert at apply
    h = G + 1
    tx = settle_with(field, h - 1, h)
    why = refused(lambda: validate_transaction(tx, logger, h))
    check(f"from the gate, a settle with `{field}: null` is refused at block validation", why is not None, why)
    why = refused(lambda: validate_transaction(tx, logger, None))
    check(f"a settle with `{field}: null` is refused at mempool admission (no height)", why is not None, why)
    with kv_ops.write_txn():
        reflect_transaction(tx, logger, h)
    fresh()
    check(f"from the gate, apply never marks a root proven from `{field}`",
          not kv_ops.settlement_proven(DEFAULT_NS, h - 1, FAKE))
    check(f"from the gate, the lone `{field}` settler's root is not settled", SO.latest_settled()[1] != FAKE,
          SO.latest_settled())
    with kv_ops.write_txn():
        reflect_transaction(tx, logger, h, revert=True)
    fresh()

    # BELOW THE GATE (history replays): validates, marks, and revert removes exactly that marker
    if G > 2:
        h = G - 1
        tx = settle_with(field, h - 1, h)
        why = refused(lambda: validate_transaction(tx, logger, h))
        check(f"below the gate, the old rule holds: `{field}: null` validates", why is None, why)
        with kv_ops.write_txn():
            reflect_transaction(tx, logger, h)
        check(f"below the gate, apply marks it proven as it always did (history replays)",
              kv_ops.settlement_proven(DEFAULT_NS, h - 1, FAKE))
        with kv_ops.write_txn():
            reflect_transaction(tx, logger, h, revert=True)
        fresh()
        check(f"revert deletes exactly the marker apply put (`{field}`)",
              not kv_ops.settlement_proven(DEFAULT_NS, h - 1, FAKE))

# the honest bare settle is unchanged on both sides
for h in ((G - 1, G + 1) if G > 2 else (G + 1,)):
    tx = construct_settle_tx(ATT, exec_cursor=h - 1, state_root=FAKE, max_block=h)
    why = refused(lambda: validate_transaction(tx, logger, h))
    check(f"a bare settle (no retired field) still validates at {h}", why is None, why)

print("ALL PASS" if not fails else f"{len(fails)} FAILED")
sys.exit(1 if fails else 0)
