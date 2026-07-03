"""
Treasury governance (doc/treasury.md §3.3): stake-quorum spending. A `treasury_spend` proposal pays out only
once BONDED validators voting to approve it (`treasury_vote`) exceed SETTLE_NUM/SETTLE_DEN (2/3) of total
bonded shares — the same quorum as settlement/finality; no multisig. A `treasury_execute` then moves the coins,
capped at TREASURY_MAX_SPEND_BPS of the current treasury balance, one payout per proposal, revert-symmetric.

Covers: below-quorum rejects execute; reaching 2/3 authorizes the payout; double-execute blocked; the
per-proposal cap; only bonded stake may vote; and full revert symmetry of both votes and the payout.

Run: python3 tests/test_treasury.py
"""
import os, sys, tempfile, logging, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_treasury_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)
logger = logging.getLogger("treasury"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import B_MIN, TREASURY_ADDRESS
from ops import kv_ops
from ops.account_ops import create_account, get_account, reflect_transaction, get_bonded_registry
from ops.transaction_ops import validate_transaction, construct_treasury_vote_tx, construct_treasury_execute_tx
from ops.settlement_ops import treasury_justified
from ops.key_ops import generate_keys
from hashing import treasury_proposal_id

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def bal(a):
    acc = get_account(a); return acc["balance"] if acc else 0

# Treasury funded; FOUR equal bonded validators -> 2/4 = 50% (below), 3/4 = 75% (> 2/3).
TREASURY_START = 1000 * B_MIN
create_account(TREASURY_ADDRESS, balance=TREASURY_START)
VS = [generate_keys() for _ in range(4)]
for v in VS:
    create_account(v["address"], bonded=B_MIN)
GRANTEE = generate_keys()["address"]
AMOUNT = TREASURY_START // 10                      # 10% of balance — under the 25% cap
MEMO, NONCE = "core dev grant Q3", "p1"
PID = treasury_proposal_id(GRANTEE, AMOUNT, MEMO, NONCE)

def _vote(v, recipient=GRANTEE, amount=AMOUNT, memo=MEMO, nonce=NONCE):
    tx = construct_treasury_vote_tx(v, recipient, amount, memo, nonce, target_block=1)
    validate_transaction(tx, logger, 1); reflect_transaction(tx, logger, 1)

def _exec_tx(recipient=GRANTEE, amount=AMOUNT, memo=MEMO, nonce=NONCE):
    return construct_treasury_execute_tx(VS[0], recipient, amount, memo, nonce, target_block=1)

def t1_below_quorum_blocks_payout():
    _vote(VS[0]); _vote(VS[1])                      # 2 of 4 = 50%
    assert not treasury_justified(PID, get_bonded_registry()), "2/4 bonded stake is below 2/3"
    try:
        validate_transaction(_exec_tx(), logger, 1); assert False, "execute must fail below quorum"
    except AssertionError as e:
        assert "quorum" in str(e), f"wrong error: {e}"

def t2_reaching_two_thirds_pays_out():
    _vote(VS[2])                                    # 3 of 4 = 75% > 2/3
    assert treasury_justified(PID, get_bonded_registry()), "3/4 bonded stake exceeds 2/3"
    ex = _exec_tx(); validate_transaction(ex, logger, 1)
    t0, g0 = bal(TREASURY_ADDRESS), bal(GRANTEE)
    reflect_transaction(ex, logger, 1)
    assert bal(TREASURY_ADDRESS) == t0 - AMOUNT, "treasury debited by exactly the amount"
    assert bal(GRANTEE) == g0 + AMOUNT, "grantee credited by exactly the amount"
    assert kv_ops.treasury_executed_exists(PID), "proposal marked executed"

def t3_double_execute_blocked():
    try:
        validate_transaction(_exec_tx(), logger, 1); assert False, "a second payout must fail"
    except AssertionError as e:
        assert "already executed" in str(e), f"wrong error: {e}"

def t4_per_proposal_cap_enforced():
    big = bal(TREASURY_ADDRESS)                     # 100% of balance >> 25% cap
    memo, nonce = "drain attempt", "p2"
    pid = treasury_proposal_id(GRANTEE, big, memo, nonce)
    for v in VS:                                    # full quorum
        _vote(v, amount=big, memo=memo, nonce=nonce)
    assert treasury_justified(pid, get_bonded_registry()), "fully voted -> justified"
    try:
        validate_transaction(_exec_tx(amount=big, memo=memo, nonce=nonce), logger, 1)
        assert False, "over-cap payout must fail even with full quorum"
    except AssertionError as e:
        assert "cap" in str(e), f"wrong error: {e}"

def t5_only_bonded_stake_may_vote():
    outsider = generate_keys()
    create_account(outsider["address"], balance=B_MIN)   # has coins but is NOT bonded
    tx = construct_treasury_vote_tx(outsider, GRANTEE, AMOUNT, MEMO, "p3", target_block=1)
    try:
        validate_transaction(tx, logger, 1); assert False, "a non-bonded account cannot vote"
    except AssertionError as e:
        assert "bonded validator" in str(e), f"wrong error: {e}"

def t6_revert_symmetry_votes_and_payout():
    memo, nonce = "grant to revert", "p4"
    pid = treasury_proposal_id(GRANTEE, AMOUNT, memo, nonce)
    for v in VS[:3]:
        _vote(v, memo=memo, nonce=nonce)
    assert treasury_justified(pid, get_bonded_registry())
    # revert one vote -> quorum drops
    rv = construct_treasury_vote_tx(VS[2], GRANTEE, AMOUNT, memo, nonce, target_block=1)
    reflect_transaction(rv, logger, 1, revert=True)
    assert not treasury_justified(pid, get_bonded_registry()), "reverting a vote drops the quorum"
    reflect_transaction(rv, logger, 1)              # re-apply -> justified again
    assert treasury_justified(pid, get_bonded_registry())
    # execute, then revert the payout
    ex = construct_treasury_execute_tx(VS[0], GRANTEE, AMOUNT, memo, nonce, target_block=1)
    validate_transaction(ex, logger, 1)
    t0, g0 = bal(TREASURY_ADDRESS), bal(GRANTEE)
    reflect_transaction(ex, logger, 1)
    assert bal(TREASURY_ADDRESS) == t0 - AMOUNT and kv_ops.treasury_executed_exists(pid)
    reflect_transaction(ex, logger, 1, revert=True)
    assert bal(TREASURY_ADDRESS) == t0, "revert restores the treasury balance"
    assert bal(GRANTEE) == g0, "revert restores the grantee balance"
    assert not kv_ops.treasury_executed_exists(pid), "revert clears the executed nullifier -> re-executable"

for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and len(name) > 1 and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
