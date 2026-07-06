"""
Relaunch-2 end-to-end (state level): a fresh genesis that CARRIES FORWARD balances/stake must (1) restore
those balances byte-for-byte via the authoritative account_set_field seeding — even for an address that
genesis_open.dat already created as a registered relay (the insert-or-ignore trap), (2) expose the carried
bonded stake to the producer registry, and (3) actually PRODUCE a valid block 1 whose body no longer carries
block_ip / block_producers_hash. This is the check that was missing when snapshot/relaunch "looked done".

Run: python3 tests/test_relaunch.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_relaunch_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("relaunch"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from ops import kv_ops
from ops.account_ops import create_account, get_account, get_bonded_registry, get_open_registry
from ops.block_ops import get_block_candidate
from protocol import B_MIN, CHAIN_ID, GENESIS_TIMESTAMP

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

WHALE = "ndo" + "e" * 46          # a founder relay: registered (open) AND holds coins + bonded stake
BAL = 5_251_313_073_896
BONDED = 8_252_986_467_104

def _seed_genesis_like():
    """Replay genesis order for WHALE: create it as a registered relay first, then carry balance/bonded via account_set_field."""
    # mimic genesis order: genesis_open creates the relay as a REGISTERED identity FIRST (balance 0)...
    create_account(address=WHALE, registered=1)
    kv_ops.recert_put(address=WHALE, epoch=0)
    # ...then the carry-forward runs. create_account here would be IGNORED (already exists) and drop the
    # balance — the relaunch MUST use account_set_field (authoritative) to actually carry it.
    kv_ops.account_set_field(WHALE, "balance", BAL)
    kv_ops.account_set_field(WHALE, "bonded", BONDED)


def t1_carry_forward_survives_registered_relay():
    """Prove carried balance/bonded survive an already-registered relay identity (no insert-or-ignore drop) and registration is kept."""
    _seed_genesis_like()
    acc = get_account(WHALE)
    assert acc["balance"] == BAL, f"carried balance dropped: {acc['balance']}"
    assert acc["bonded"] == BONDED, f"carried bonded dropped: {acc['bonded']}"
    assert acc["registered"] == 1, "registration must be preserved alongside the carried balance"
check("carried balance/stake survives an already-registered relay identity (no insert-or-ignore drop)",
      t1_carry_forward_survives_registered_relay)


def t2_carried_stake_is_an_eligible_producer():
    """Prove the carried bonded stake appears in the producer registry and is fully aged (bond_since unset) at genesis."""
    reg = get_bonded_registry()
    assert WHALE in reg and reg[WHALE]["bonded"] >= B_MIN, "carried bonded stake not in the producer registry"
    # bond_since UNSET -> fully aged -> full producer weight from genesis (no relaunch re-ramp)
    assert kv_ops.bond_since_get_raw(WHALE) is None, "carried stake must be fully-aged (bond_since unset)"
check("carried bonded stake is an eligible, fully-aged producer at genesis", t2_carried_stake_is_an_eligible_producer)


def t3_fresh_chain_produces_a_valid_block_1():
    """Prove the fresh relaunch chain produces a valid block 1 whose body omits block_ip and block_producers_hash."""
    genesis = {"block_number": 0, "block_hash": "0" * 64, "block_timestamp": GENESIS_TIMESTAMP,
               "cumulative_fees": 0, "cumulative_weight": 0}
    cand = get_block_candidate(transaction_pool=[], logger=logger, latest_block=genesis)
    assert cand is not None, "fresh chain could not produce block 1 (no eligible producer?)"
    assert cand["block_number"] == 1 and cand["chain_id"] == CHAIN_ID
    # the relaunch removed these from the block body
    assert "block_ip" not in cand, "block_ip must be gone from the block body"
    assert "block_producers_hash" not in cand, "block_producers_hash must be gone from the block body"
    assert cand["block_creator"], "block must credit a producer address"
    assert cand["block_hash"], "block must have a hash"
check("fresh relaunch chain produces a valid block 1 (no block_ip / block_producers_hash)",
      t3_fresh_chain_produces_a_valid_block_1)


print(f"\n{'ALL RELAUNCH CHECKS PASSED' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
