import os, sys, tempfile, traceback
home = tempfile.mkdtemp(prefix="nado_s3_")
os.environ["HOME"] = home
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "index/producer_sets", "logs", "peers"):
    os.makedirs(f"{home}/nado/{d}", exist_ok=True)

import logging
logger = logging.getLogger("s3"); logger.addHandler(logging.NullHandler())

from genesis import create_indexers
create_indexers()

from protocol import (split_block_reward, TREASURY_ADDRESS, TREASURY_GENESIS, REWARD_WINDOW,
                      BPS_DENOM, TREASURY_BPS, BASE_SUBSIDY)
from ops.account_ops import (create_account, get_account, change_balance, increase_produced_count,
                             reflect_transaction, get_totals, index_totals, fetch_totals)
from ops.block_ops import get_block_reward, save_block, set_latest_block_info, construct_block

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e: fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

# 1. split is exact + 90/10 for every value (no lost unit, sums to reward)
def t1():
    for r in (0, 1, 5, 9, 10, 99, 1000, 4321, 5_000_000_000):
        p, t = split_block_reward(r)
        assert p + t == r, f"split({r}) sums to {p+t}"
        assert t == r - (r * (BPS_DENOM - TREASURY_BPS) // BPS_DENOM)
        assert p >= t or r < 10, f"producer cut not >= treasury for {r}"
    assert split_block_reward(1000) == (900, 100)
check("split_block_reward exact + 90/10", t1)

# 2. genesis economic model: founder 0, treasury seeded, no personal premine
def t2():
    create_account(address=TREASURY_ADDRESS, balance=TREASURY_GENESIS)
    create_account(address="founder", balance=0)
    assert get_account(TREASURY_ADDRESS)["balance"] == TREASURY_GENESIS
    assert get_account("founder")["balance"] == 0
check("genesis: treasury seeded, founder empty (no premine)", t2)

# 3. emission is now FLAT base subsidy scaled by the bond-elastic multiplier: fee-INDEPENDENT and
#    UNcapped. With no bonded stake the bonded ratio is 0 -> multiplier 1.0 -> exactly BASE_SUBSIDY,
#    regardless of cumulative_fees. BASE_SUBSIDY is the MAX emission/block (m<=1). See bond-elastic-emission.md
def t3():
    assert get_block_reward(parent_block={"block_number": 150, "cumulative_fees": 50_000_000}) == BASE_SUBSIDY
    assert get_block_reward(parent_block={"block_number": 10, "cumulative_fees": 7_000_000}) == BASE_SUBSIDY
    assert get_block_reward(parent_block={"block_number": 10, "cumulative_fees": 10**18}) == BASE_SUBSIDY  # no cap, fee-independent
    assert get_block_reward() == BASE_SUBSIDY  # parent_block optional now
check("get_block_reward: flat base subsidy, fee-independent, no cap", t3)

# 4. construct_block commits cumulative_fees = parent_cumfee + this block's fees, + chain_id
def t4():
    txs = [{"fee": 100, "amount": 1, "txid": "a"}, {"fee": 250, "amount": 1, "txid": "b"}]
    blk = construct_block(block_timestamp=10, block_number=5, parent_hash="0"*64, creator="m",
                          transaction_pool=txs,
                          block_reward=400000, parent_cumulative_fees=1_000_000)
    assert blk["cumulative_fees"] == 1_000_000 + 350, blk["cumulative_fees"]
    assert blk["chain_id"] == "nado-relaunch-2"
check("construct_block commits cumulative_fees + chain_id", t4)

# 5. incorporate vs rollback ECONOMIC round-trip = exact identity (split + fee-from-block-1)
def apply_block(block, txs):
    for tx in txs:
        reflect_transaction(tx, logger=logger, block_height=block["block_number"])
    p, t = split_block_reward(block["block_reward"])
    change_balance(block["block_creator"], p, logger=logger)
    if t: change_balance(TREASURY_ADDRESS, t, logger=logger)
    increase_produced_count(block["block_creator"], p, logger=logger)
    tt = get_totals(block=block)
    index_totals(produced=tt["produced"], fees=tt["fees"])
def rollback_block(block, txs):
    p, t = split_block_reward(block["block_reward"])
    change_balance(block["block_creator"], p, revert=True, logger=logger)
    if t: change_balance(TREASURY_ADDRESS, t, revert=True, logger=logger)
    increase_produced_count(block["block_creator"], p, revert=True, logger=logger)
    tt = get_totals(block=block, revert=True)
    index_totals(produced=tt["produced"], fees=tt["fees"])
    for tx in txs:
        reflect_transaction(tx, logger=logger, block_height=block["block_number"], revert=True)

def t5():
    create_account("alice", 10_000_000); create_account("bob", 0); create_account("miner", 0)
    txs = [{"sender": "alice", "recipient": "bob", "amount": 500, "fee": 100}]
    block = {"block_number": 1, "block_creator": "miner", "block_reward": 1000, "block_transactions": txs}
    before = {a: dict(get_account(a)) for a in ("alice", "bob", "miner", TREASURY_ADDRESS)}
    before_tot = fetch_totals()
    apply_block(block, txs)
    # fee was debited at height 1 (compat gate gone): alice -600, bob +500, fee 100 destroyed
    assert get_account("alice")["balance"] == 10_000_000 - 600
    assert get_account("bob")["balance"] == 500
    assert get_account("miner")["balance"] == 900            # 90% cut
    tre_after = get_account(TREASURY_ADDRESS)["balance"]
    assert tre_after == before[TREASURY_ADDRESS]["balance"] + 100   # 10% cut
    tot = fetch_totals()
    assert tot["produced"] == before_tot["produced"] + 1000 and tot["fees"] == before_tot["fees"] + 100
    rollback_block(block, txs)
    after = {a: dict(get_account(a)) for a in ("alice", "bob", "miner", TREASURY_ADDRESS)}
    assert after == before, f"round-trip not identity:\n{before}\n{after}"
    assert fetch_totals() == before_tot, "totals round-trip not identity"
check("incorporate<->rollback round-trip is exact identity", t5)

# 6. supply formula: no premine, treasury non-circulating
def t6():
    tot = fetch_totals()
    total_supply = TREASURY_GENESIS + tot["produced"] - tot["fees"]
    treasury = get_account(TREASURY_ADDRESS)["balance"]
    circulating = total_supply - treasury
    assert total_supply >= 0 and circulating >= 0
    # after the round-trip, produced/fees are back to 0 and treasury==seed -> circulating 0
    assert total_supply == TREASURY_GENESIS and circulating == 0, (total_supply, treasury, circulating)
check("supply: total = seed + produced - fees; circulating excludes treasury", t6)

print(f"\n{'ALL S3 CHECKS PASSED' if fails==0 else str(fails)+' S3 CHECK(S) FAILED'}")
sys.exit(1 if fails else 0)
