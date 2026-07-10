"""
Execution-layer BRIDGE (Phase 2) end-to-end: L1 deposit locks coins in escrow; the exec node credits the
depositor; a withdrawal is recorded on the exec side and proven (Merkle) against the bonded-quorum SETTLED
root; L1 verifies that ONE proof and releases the escrow, with a nullifier preventing double-claims.
Also unit-tests the shared Merkle primitives.

Run: python3 tests/test_bridge.py
"""
import os, sys, tempfile, traceback, logging
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_bridge_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

logger = logging.getLogger("bridge"); logger.addHandler(logging.NullHandler())
from genesis import create_indexers
create_indexers()

from protocol import B_MIN, MIN_TX_FEE, BRIDGE_ESCROW
from ops import kv_ops
from ops.account_ops import create_account, get_account, reflect_transaction
from ops.transaction_ops import (validate_transaction, construct_settle_tx,
                                  construct_bridge_deposit_tx, construct_bridge_withdraw_tx)
from ops.settlement_ops import latest_settled
from ops.key_ops import generate_keys
from hashing import merkle_root, merkle_proof, verify_merkle_proof, withdrawal_leaf, canonical_bytes
from execnode.state import ExecState

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()
def raises(fn):
    """True if fn raises."""
    try: fn(); return False
    except Exception: return True
def _bal(a):
    """L1 balance of address a."""
    return get_account(a)["balance"]

V = generate_keys(); create_account(V["address"], balance=B_MIN, bonded=4 * B_MIN)   # bonded validator
U = generate_keys(); create_account(U["address"], balance=2_000_000)                 # bridge user

def t1_merkle_primitives():
    """Prove merkle_root/merkle_proof/verify_merkle_proof accept a real leaf and reject an absent one."""
    leaves = [canonical_bytes(["kv", "c1", "m", "k", i]) for i in range(7)]
    target = leaves[3]
    root = merkle_root(leaves)
    proof = merkle_proof(leaves, target)
    assert verify_merkle_proof(target, proof, root), "valid inclusion proof must verify"
    assert not verify_merkle_proof(canonical_bytes(["kv", "c1", "m", "k", 999]), proof, root), "absent leaf must fail"

def t2_full_bridge_roundtrip():
    """Prove the full bridge flow: L1 deposit escrows, exec credits+withdraws, root settles, proven exit releases escrow, nullifier blocks a double-claim."""
    D, W = 500_000, 300_000
    # 1) L1 DEPOSIT -> escrow locks D
    dep = construct_bridge_deposit_tx(U, D, max_block=1, fee=MIN_TX_FEE)
    validate_transaction(dep, logger, 1)
    u0 = _bal(U["address"])
    reflect_transaction(dep, logger, 1)
    assert _bal(BRIDGE_ESCROW) == D, "escrow locked the deposit"
    assert _bal(U["address"]) == u0 - D - MIN_TX_FEE, "user debited deposit + fee"

    # 2) EXEC side: credit the deposit, then withdraw W (records a provable exit)
    st = ExecState(tempfile.mktemp(prefix="nado_exec_", suffix=".json"))
    st.credit_deposit(U["address"], D)
    st.apply_blob({"op": "bridge_withdraw", "amount": W}, sender=U["address"], txid="wd")
    assert st.bridge[U["address"]] == D - W, "exec-side balance burned by W"
    p = st.withdrawal_proof("1")
    assert p and p["addr"] == U["address"] and p["amount"] == W and p["nonce"] == "1"
    root = st.state_root()
    assert verify_merkle_proof(withdrawal_leaf(U["address"], W, "1"), p["proof"], root), "exec proof self-consistent"

    # 3) SETTLE the exec root on L1 (bonded quorum: V alone = 4/4 > 2/3)
    reflect_transaction(construct_settle_tx(V, exec_cursor=7, state_root=root, max_block=1), logger, 1)
    assert latest_settled()[1] == root, "root settled on L1"

    # 4) L1 EXIT: prove the withdrawal against the settled root -> escrow releases W to the user
    wtx = construct_bridge_withdraw_tx(U, U["address"], W, p["nonce"], p["proof"], max_block=1)
    validate_transaction(wtx, logger, 1)
    ub = _bal(U["address"])
    reflect_transaction(wtx, logger, 1)
    assert _bal(U["address"]) == ub + W, "user received the withdrawn coins"
    assert _bal(BRIDGE_ESCROW) == D - W, "escrow reduced by W"

    # 5) double-claim rejected by the nullifier
    assert raises(lambda: validate_transaction(wtx, logger, 1)), "same withdrawal cannot be claimed twice"

def t3_withdraw_without_settlement_rejected():
    """Prove an L1 exit whose exec root was never settled is rejected (proof fails against the settled root)."""
    # a withdrawal whose root is NOT settled must be rejected
    st = ExecState(tempfile.mktemp(prefix="nado_exec_", suffix=".json"))
    st.credit_deposit(U["address"], 100_000)
    st.apply_blob({"op": "bridge_withdraw", "amount": 100_000}, sender=U["address"], txid="wd2")
    p = st.withdrawal_proof("1")
    wtx = construct_bridge_withdraw_tx(U, U["address"], 100_000, "1", p["proof"], max_block=1)
    # this exact (unsettled) root is not the settled one -> proof fails against the settled root
    assert raises(lambda: validate_transaction(wtx, logger, 1)), "unsettled withdrawal must reject"

def t4_forged_amount_rejected():
    """Prove claiming a different amount than the proven withdrawal fails the Merkle check."""
    # claiming a different amount than what was proven must fail the Merkle check
    st = ExecState(tempfile.mktemp(prefix="nado_exec_", suffix=".json"))
    st.credit_deposit(U["address"], 100_000)
    st.apply_blob({"op": "bridge_withdraw", "amount": 40_000}, sender=U["address"], txid="wd3")
    p = st.withdrawal_proof("1")
    root = st.state_root()
    reflect_transaction(construct_settle_tx(V, exec_cursor=99, state_root=root, max_block=1), logger, 1)
    forged = construct_bridge_withdraw_tx(U, U["address"], 99_999, "1", p["proof"], max_block=1)  # wrong amount
    assert raises(lambda: validate_transaction(forged, logger, 1)), "forged amount must fail the proof"

for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
