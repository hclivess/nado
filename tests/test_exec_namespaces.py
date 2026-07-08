"""
Per-namespace execution node (multi-rollup): a `blob`'s ns (default when absent) selects which ExecState it
applies to; namespaces are fully isolated; a blob for a namespace this node doesn't run is dropped. This
mirrors the exact routing in execnode.tail_loop, over a plain states dict so it needs no live L1.

Run: python3 tests/test_exec_namespaces.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState

# minimal fungible-token contract (same bytecode as tests/test_execnode_vm.py)
TOKEN = {
    "constructor": [["CALLER"], ["PUSH", 1_000_000], ["MSTORE", "balances"]],
    "transfer": [
        ["CALLER"], ["MLOAD", "balances"], ["ARG", 1], ["GTE"], ["REQUIRE"],
        ["CALLER"], ["CALLER"], ["MLOAD", "balances"], ["ARG", 1], ["SUB"], ["MSTORE", "balances"],
        ["ARG", 0], ["ARG", 0], ["MLOAD", "balances"], ["ARG", 1], ["ADD"], ["MSTORE", "balances"],
        ["HALT"],
    ],
    "balanceOf": [["ARG", 0], ["MLOAD", "balances"], ["RETURN"]],
}
A, B = "ndoalice", "ndobob"

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


def _states(nslist):
    return {ns: ExecState(tempfile.mktemp(prefix=f"nado_ns_{ns}_", suffix=".json")) for ns in nslist}

def _route_blob(states, data, sender, txid):
    """The exact execnode.tail_loop routing: a blob's ns (default when absent) selects the target state;
    a blob for a namespace this node doesn't run is dropped (returns None)."""
    bns = data.get("ns", "default") if isinstance(data, dict) else "default"
    tgt = states.get(bns)
    return tgt.apply_blob(data, sender, txid) if tgt is not None else None


def t1_blob_ns_routes_to_its_state():
    """A no-ns blob lands in default; an ns=rollupa blob lands in rollupa — never crossed."""
    states = _states(["default", "rollupa"])
    cidD = states["default"].contract_id(A, TOKEN, "nd")
    cidR = states["rollupa"].contract_id(A, TOKEN, "nr")
    _route_blob(states, {"op": "deploy", "code": TOKEN, "nonce": "nd"}, A, "t1")
    _route_blob(states, {"op": "deploy", "code": TOKEN, "nonce": "nr", "ns": "rollupa"}, A, "t2")
    assert cidD in states["default"].contracts and cidD not in states["rollupa"].contracts
    assert cidR in states["rollupa"].contracts and cidR not in states["default"].contracts

def t2_namespaces_isolated_and_roots_differ():
    """A rollup's deploy + transfer never touch the default layer, and distinct states have distinct roots."""
    states = _states(["default", "rollupa"])
    cidR = states["rollupa"].contract_id(A, TOKEN, "nr")
    _route_blob(states, {"op": "deploy", "code": TOKEN, "nonce": "nr", "ns": "rollupa"}, A, "t1")
    assert states["default"].state_root() != states["rollupa"].state_root(), "distinct states, distinct roots"
    _route_blob(states, {"op": "call", "contract": cidR, "method": "transfer", "args": [B, 250], "ns": "rollupa"}, A, "t2")
    assert states["rollupa"].view(cidR, "balanceOf", [B]) == 250
    assert not states["default"].contracts, "default untouched by a rollupa transfer"

def t3_blob_for_unrun_namespace_dropped():
    """A blob for a namespace this node doesn't run is dropped, and nothing leaks into default."""
    states = _states(["default"])
    r = _route_blob(states, {"op": "deploy", "code": TOKEN, "nonce": "n", "ns": "rollupz"}, A, "t1")
    assert r is None, "blob for an unrun namespace is dropped"
    assert not states["default"].contracts, "nothing lands in default"

def t4_default_determinism_preserved():
    """Two nodes replaying the same no-ns blobs still agree — namespacing didn't perturb the default layer."""
    s1 = _states(["default"])["default"]; s2 = _states(["default"])["default"]
    for s in (s1, s2):
        _route_blob({"default": s}, {"op": "deploy", "code": TOKEN, "nonce": "n"}, A, "t1")
        _route_blob({"default": s}, {"op": "call", "contract": s.contract_id(A, TOKEN, "n"),
                                     "method": "transfer", "args": [B, 100]}, A, "t2")
    assert s1.state_root() == s2.state_root(), "default determinism holds"


for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
