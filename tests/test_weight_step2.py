"""
Fork-choice cumulative_weight unit checks (#16/#17, security step 2).

Covers: total_bonded_shares is pure capped stake (no fidelity ramp); construct_block commits
cumulative_weight = parent + block_weight INSIDE the hash preimage (so it is grind-proof bound to
the block hash). The cross-node agreement of the value is exercised by the 3-node testnet
(verify_block rejects any mismatch, so divergence would break convergence).
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_w2_")
os.environ["NADO_TESTNET"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ops.mining_ops import total_bonded_shares
from ops.block_ops import construct_block
from protocol import B_MIN, BOND_CAP, MAX_SHARES

fails = 0
def check(name, fn):
    global fails
    try:
        fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}")


def t1():
    reg = {
        "a": {"bonded": B_MIN, "fidelity": 0},          # exactly 1 share
        "b": {"bonded": 5 * B_MIN, "fidelity": 0},      # 5 shares
        "c": {"bonded": BOND_CAP * 10, "fidelity": 0},  # whale -> capped at MAX_SHARES
        "d": {"bonded": B_MIN - 1, "fidelity": 99},     # below B_MIN -> 0 (fidelity ignored)
    }
    got = total_bonded_shares(reg)
    assert got == 1 + 5 + MAX_SHARES + 0, got
check("total_bonded_shares = pure capped stake, NO fidelity ramp", t1)

def t2():
    assert total_bonded_shares({}) == 0
check("empty bonded registry -> weight 0", t2)

def t3():
    common = dict(block_timestamp=10, block_number=5, parent_hash="0" * 64, creator="m",
                  transaction_pool=[],
                  block_reward=1_000_000_000, parent_cumulative_fees=0)
    blk = construct_block(parent_cumulative_weight=12, block_weight=3, **common)
    assert blk["cumulative_weight"] == 15, blk["cumulative_weight"]
    # the field is in the hash preimage -> any tampering changes the block hash (grind-proof binding)
    blk2 = construct_block(parent_cumulative_weight=12, block_weight=4, **common)
    assert blk["block_hash"] != blk2["block_hash"], "cumulative_weight must be inside the hash preimage"
check("construct_block commits cumulative_weight into the hash preimage", t3)

print(f"\n{'ALL WEIGHT CHECKS PASSED' if not fails else str(fails) + ' FAILURE(S)'}")
sys.exit(1 if fails else 0)
