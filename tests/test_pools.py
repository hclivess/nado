"""STAKING POOLS (protocol.POOL_HEIGHT; account_ops.apply_pool_tx; mining_ops.bonded_producer_registry; reward_ops._pool_split;
transaction_ops pool/delegate/undelegate). Pins:
  1. apply/revert: pool terms, delegate, undelegate — fields and member lists restored byte-exactly;
  2. registry: pooled stake counted on the pool, the delegator excluded from the producer draw, the cap over own+pooled;
  3. reward split: pro-rata minus fee, sums to the producer cut, deterministic, journaled and reverted exactly;
  4. validation wiring and uniqueness keys; 5. fork weight unchanged by pooling.
Run: python3 tests/test_pools.py
"""
import os, sys, tempfile, logging
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-pools-")
_fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond: _fails.append(name)

def main():
    import protocol as P
    from ops import kv_ops, mining_ops as M
    from ops.account_ops import apply_pool_tx, get_bonded_registry, get_account
    from ops.reward_ops import credit_block_reward
    kv_ops.close_all(); kv_ops.init_env()
    N = P.DENOMINATION; lg = logging.getLogger("t")
    pool, d1, d2, solo = "a" * 46, "b" * 46, "c" * 46, "d" * 46
    for addr, bonded in ((pool, 200 * N), (d1, 300 * N), (d2, 700 * N), (solo, 50 * N)):
        kv_ops.account_set(addr, "balance", 0); kv_ops.account_set(addr, "bonded", bonded)
    check("gate is a height at/after the cap gate", P.POOL_HEIGHT >= P.BOND_DEVICE_CAP_HEIGHT)
    check("recipients reserved", {"pool", "delegate", "undelegate"} <= P.RESERVED_RECIPIENTS)
    # 1. pool terms
    tx_cfg = {"sender": pool, "recipient": "pool", "txid": "t1", "data": {"fee_bps": 1000, "open": 1, "min": 10 * N, "max": 1000 * N, "label": "Alice pool"}}
    apply_pool_tx(tx_cfg)
    a = get_account(pool)
    check("pool terms written", a.get("pool_fee_bps") == 1000 and a.get("pool_open") == 1 and a.get("pool_label") == "Alice pool" and a.get("pool_max") == 1000 * N)
    tx_d1 = {"sender": d1, "recipient": "delegate", "txid": "t2", "data": {"to": pool}}
    tx_d2 = {"sender": d2, "recipient": "delegate", "txid": "t3", "data": {"to": pool}}
    apply_pool_tx(tx_d1); apply_pool_tx(tx_d2)
    check("delegators point at the pool and the pool lists them (sorted)", get_account(d1).get("pool_to") == pool and get_account(pool).get("pool_members") == sorted([d1, d2]))
    # 2. registry
    reg = get_bonded_registry()
    check("registry: pooled stake on the pool, pool_to on the delegators", reg[pool]["pooled"] == 1000 * N and reg[d1]["pool_to"] == pool and reg[solo]["pooled"] == 0)
    open_reg = {pool: {"fidelity": 1}, d1: {"fidelity": 1}, solo: {"fidelity": 1}}
    pr = M.bonded_producer_registry(reg, open_reg, max(P.POOL_HEIGHT, P.BOND_WEIGHT_CURVE_HEIGHT))
    exp = M.bond_weight(1200 * N, M.bond_knee(1200 * N, 50 * N))       # own 200 + pooled 1000 on a 1,000 knee (others: solo's 50)
    check("producer draw: the pool weighs the curve of own+pooled (1,200 on a 1,000 knee = 1,083)", pr[pool]["bonded"] == exp and 1083 * N <= exp <= 1084 * N, (pr.get(pool), exp))
    check("producer draw: a delegator has no weight of its own, even if attested", d1 not in pr and d2 not in pr)
    check("producer draw: a solo attested staker is unchanged", pr[solo]["bonded"] == 50 * N)
    check("fork weight ignores pooling (each account's own bonded, 10 NADO per share)", M.total_bonded_shares(reg) == (20 + 30 + 70 + 5))
    pr_before = M.bonded_producer_registry(reg, open_reg, P.POOL_HEIGHT - 1)
    check("below the gate pooled stake is ignored and delegators draw on their own", pr_before[pool]["bonded"] == 200 * N and d1 in pr_before)
    # 3. reward split
    from protocol import split_bonded_block_reward
    reward = 1_000_000_000_000
    producer_cut, _, _ = split_bonded_block_reward(reward)
    block = {"block_number": P.POOL_HEIGHT + 7, "block_creator": pool, "block_reward": reward, "block_transactions": []}
    import ops.reward_ops as R
    R.block_lane = lambda b: "bonded"                  # this block is a bonded-lane win
    bal0 = {x: int(get_account(x).get("balance", 0)) for x in (pool, d1, d2, solo)}
    with kv_ops.write_txn(): credit_block_reward(block, logger=lg)
    bal1 = {x: int(get_account(x).get("balance", 0)) for x in (pool, d1, d2, solo)}
    got = {x: bal1[x] - bal0[x] for x in bal1}
    dp = producer_cut * 1000 // 1200; fee = dp * 1000 // 10000; dist = dp - fee
    exp_d1, exp_d2 = dist * 300 // 1000, dist * 700 // 1000
    check("split: delegators get pro-rata minus the 10 % fee", got[d1] == exp_d1 and got[d2] == exp_d2, got)
    check("split: the pool keeps own share + fee + dust; the sum is exactly the producer cut", got[pool] == producer_cut - exp_d1 - exp_d2 and got[pool] + got[d1] + got[d2] == producer_cut)
    check("split: the solo staker gets nothing", got[solo] == 0)
    check("split journaled for the height", kv_ops.pool_revert_pop(f"rw:{block['block_number']}") is not None)
    kv_ops.pool_revert_put(f"rw:{block['block_number']}", [got[pool], [[d1, got[d1]], [d2, got[d2]]]])
    with kv_ops.write_txn(): credit_block_reward(block, logger=lg, revert=True)
    bal2 = {x: int(get_account(x).get("balance", 0)) for x in (pool, d1, d2, solo)}
    check("revert restores every balance exactly", bal2 == bal0, (bal0, bal2))
    # undelegate + reverts
    apply_pool_tx({"sender": d1, "recipient": "undelegate", "txid": "t4", "data": {}})
    check("undelegate clears pool_to and the member list", "pool_to" not in get_account(d1) and get_account(pool).get("pool_members") == [d2])
    apply_pool_tx({"sender": d1, "recipient": "undelegate", "txid": "t4", "data": {}}, revert=True)
    check("reverting undelegate restores both", get_account(d1).get("pool_to") == pool and get_account(pool).get("pool_members") == sorted([d1, d2]))
    # close: terms gone, every delegator released, revert restores all three accounts
    tx_close = {"sender": pool, "recipient": "pool", "txid": "t5", "data": {"close": 1}}
    apply_pool_tx(tx_close)
    check("close removes the terms and releases the delegators", "pool_open" not in get_account(pool) and "pool_members" not in get_account(pool) and "pool_to" not in get_account(d1) and "pool_to" not in get_account(d2))
    apply_pool_tx(tx_close, revert=True)
    check("reverting close restores terms, members and both delegations", get_account(pool).get("pool_fee_bps") == 1000 and get_account(pool).get("pool_members") == sorted([d1, d2]) and get_account(d1).get("pool_to") == pool and get_account(d2).get("pool_to") == pool)
    apply_pool_tx(tx_d2, revert=True); apply_pool_tx(tx_d1, revert=True)
    check("reverting the delegations restores a memberless pool and no pool_to", get_account(pool).get("pool_members") == [] and "pool_to" not in get_account(d1))
    apply_pool_tx(tx_cfg, revert=True)
    check("reverting the terms removes every pool field", not any(f in get_account(pool) for f in ("pool_fee_bps", "pool_open", "pool_label")))
    kv_ops.close_all()
    # 4. wiring
    src = open(os.path.join(ROOT, "ops", "transaction_ops.py")).read()
    check("validation: gated, fee-exempt, terms bounds, open pool, min, room, full, self-delegation refused",
          all(x in src for x in ('"staking pools are not enabled yet"', "pool: fee_bps must be 0..10000", "delegate: that address is not an open pool",
                                  "delegate: the pool has no room for that stake", "delegate: the pool is full", "the pool's weight follows the curve, not a cap", "undelegate: the sender is not delegating", "pool: nothing to close",
                                  '"pool", "delegate", "undelegate"):\n            return (r, tx["sender"])')))
    check("relay: /pools endpoint", '"/pools"' in open(os.path.join(ROOT, "nado.py")).read())
    check("pool_revert is node-local", "pool_revert" in kv_ops._LOCAL_DBS and "pool_revert" not in kv_ops.SNAPSHOT_DBS)

if __name__ == "__main__":
    try: main()
    except Exception:
        import traceback; traceback.print_exc(); _fails.append("exception")
    print("ALL PASS" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    raise SystemExit(1 if _fails else 0)
