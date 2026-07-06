"""
Execution-layer VM + state (Phase 1): a token contract in the minimal stack VM, applied as blobs.
Checks deploy/constructor, transfer with REQUIRE guard, balanceOf view, revert-on-insufficient-balance,
and DETERMINISM (two execution nodes replaying the same blobs reach the same state_root).

Run: python3 tests/test_execnode_vm.py
"""
import os, sys, tempfile, traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.vm import run, validate_code

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

# A minimal fungible-token contract expressed in the VM's bytecode.
TOKEN = {
    "constructor": [["CALLER"], ["PUSH", 1_000_000], ["MSTORE", "balances"]],   # mint 1e6 to deployer
    "transfer": [                                                               # args=[to, amount]
        ["CALLER"], ["MLOAD", "balances"], ["ARG", 1], ["GTE"], ["REQUIRE"],    # require bal[caller] >= amount
        ["CALLER"], ["CALLER"], ["MLOAD", "balances"], ["ARG", 1], ["SUB"], ["MSTORE", "balances"],
        ["ARG", 0], ["ARG", 0], ["MLOAD", "balances"], ["ARG", 1], ["ADD"], ["MSTORE", "balances"],
        ["HALT"],
    ],
    "balanceOf": [["ARG", 0], ["MLOAD", "balances"], ["RETURN"]],               # args=[addr] -> balance
}
A, B = "ndoalice", "ndobob"


def _state():
    """Return a blank ExecState backed by a throwaway temp file."""
    return ExecState(tempfile.mktemp(prefix="nado_exec_", suffix=".json"))


def t1_validate_token_code():
    """Prove the sample token bytecode passes validate_code."""
    assert validate_code(TOKEN)


def t2_deploy_mints_to_deployer():
    """Prove a deploy blob stores the contract and its constructor mints 1e6 to the deployer only."""
    st = _state()
    cid = st.contract_id(A, TOKEN, "n1")
    st.apply_blob({"op": "deploy", "code": TOKEN, "nonce": "n1"}, sender=A, txid="tx1")
    assert cid in st.contracts, "contract deployed"
    assert st.view(cid, "balanceOf", [A]) == 1_000_000, "deployer minted"
    assert st.view(cid, "balanceOf", [B]) == 0


def t3_transfer_moves_balance():
    """Prove a transfer call debits the sender and credits the recipient by the exact amount."""
    st = _state()
    cid = st.contract_id(A, TOKEN, "n1")
    st.apply_blob({"op": "deploy", "code": TOKEN, "nonce": "n1"}, sender=A, txid="tx1")
    st.apply_blob({"op": "call", "contract": cid, "method": "transfer", "args": [B, 250]}, sender=A, txid="tx2")
    assert st.view(cid, "balanceOf", [A]) == 999_750
    assert st.view(cid, "balanceOf", [B]) == 250


def t4_insufficient_balance_reverts():
    """Prove a transfer exceeding the sender's balance REQUIRE-reverts and leaves state untouched."""
    st = _state()
    cid = st.contract_id(A, TOKEN, "n1")
    st.apply_blob({"op": "deploy", "code": TOKEN, "nonce": "n1"}, sender=A, txid="tx1")
    # B has 0; a transfer from B must REQUIRE-fail and leave state untouched
    r = st.apply_blob({"op": "call", "contract": cid, "method": "transfer", "args": [A, 10]}, sender=B, txid="tx2")
    assert "revert" in r, r
    assert st.view(cid, "balanceOf", [A]) == 1_000_000, "no coins moved on revert"
    assert st.view(cid, "balanceOf", [B]) == 0


def t5_determinism_same_root():
    """Prove two nodes replaying identical blobs reach the same state_root (and the expected final balances)."""
    seq = [
        ({"op": "deploy", "code": TOKEN, "nonce": "n1"}, A, "tx1"),
        ({"op": "call", "contract": None, "method": "transfer", "args": [B, 100]}, A, "tx2"),
        ({"op": "call", "contract": None, "method": "transfer", "args": [A, 40]}, B, "tx3"),
    ]
    roots = []
    for _ in range(2):
        st = _state()
        cid = st.contract_id(A, TOKEN, "n1")
        for payload, sender, txid in seq:
            p = dict(payload)
            if p.get("contract") is None and p["op"] == "call":
                p["contract"] = cid
            st.apply_blob(p, sender=sender, txid=txid)
        roots.append(st.state_root())
    assert roots[0] == roots[1], "two nodes replaying identical blobs must agree on state_root"
    # sanity: final balances
    st = _state(); cid = st.contract_id(A, TOKEN, "n1")
    st.apply_blob({"op": "deploy", "code": TOKEN, "nonce": "n1"}, A, "tx1")
    st.apply_blob({"op": "call", "contract": cid, "method": "transfer", "args": [B, 100]}, A, "tx2")
    st.apply_blob({"op": "call", "contract": cid, "method": "transfer", "args": [A, 40]}, B, "tx3")
    assert st.view(cid, "balanceOf", [A]) == 999_940 and st.view(cid, "balanceOf", [B]) == 60


def t6_bad_bytecode_skipped_not_fatal():
    """Prove deploying invalid bytecode is skipped (not stored) rather than crashing the node."""
    st = _state()
    r = st.apply_blob({"op": "deploy", "code": {"m": [["NOPE"]]}, "nonce": "x"}, sender=A, txid="tx1")
    assert "skip" in r, r
    assert not st.contracts, "invalid contract not stored"


for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
