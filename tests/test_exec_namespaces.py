"""
Per-namespace execution node (multi-rollup): a `blob`'s ns (default when absent) selects which ExecState it
applies to; namespaces are fully isolated; a blob for a namespace this node doesn't run is dropped. This
mirrors the exact routing in execnode.tail_loop, over a plain states dict so it needs no live L1.

Run: python3 tests/test_exec_namespaces.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode import zkvmasm

# minimal fungible-token contract, zkVM-native: balances live at slot = holder's address digest
# (`ctx caller` gives the caller's digest; a string arg is digested at the call boundary).
TOKEN = zkvmasm.assemble_contract({
    "constructor": "ctx r0 caller\n movi r1 1000000\n sstore r0 r1\n ret r0",
    # transfer(to=arg0, amt=arg1): require bal[caller] >= amt, then move it
    "transfer": """
        ctx r2 caller
        sload r3 r2
        mov r4 r3
        lt r4 r1
        notb r4
        require r4
        sub r3 r1
        sstore r2 r3
        sload r5 r0
        add r5 r1
        sstore r0 r5
        ret r0
    """,
    "balanceOf": "sload r1 r0\n ret r1",
})
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


def t5_outbox_emit_commit_and_proof():
    """Prove `emit` commits a cross-domain message in state_root and outbox_proof verifies against it."""
    from execnode import exec_root as ER
    st = _states(["default"])["default"]
    r0 = st.state_root()
    st.apply_blob({"op": "emit", "to_ns": "rollupb", "data": {"hello": 1}}, A, "e1")
    st.apply_blob({"op": "emit", "to_ns": "rollupb", "data": [1, 2, 3]}, B, "e2")
    assert len(st.outbox) == 2, "two messages committed"
    assert st.state_root() != r0, "emitting a message changes the committed root"
    p = st.outbox_proof(0)
    assert p is not None and p["message"]["from"] == A and p["message"]["to_ns"] == "rollupb"
    m = p["message"]
    assert ER.verify_outbox_msg(st.state_root(), m["seq"], m["from"], m["to_ns"], m.get("data"), p["proof"]), \
        "message proves against state_root"
    assert st.outbox_proof(9) is None, "unknown seq -> None"

def t6_outbox_determinism():
    """Prove two nodes emitting the same messages reach the same state_root (message commitment is deterministic)."""
    s1 = _states(["default"])["default"]; s2 = _states(["default"])["default"]
    for s in (s1, s2):
        s.apply_blob({"op": "emit", "to_ns": "x", "data": {"k": "v"}}, A, "e1")
    assert s1.state_root() == s2.state_root(), "same emits -> same root"

def t7_outbox_persists():
    """Prove the outbox survives a save/load round-trip (a restarted exec node keeps its messages)."""
    import tempfile
    from execnode.state import ExecState
    path = tempfile.mktemp(prefix="nado_ob_", suffix=".json")
    s = ExecState(path)
    s.apply_blob({"op": "emit", "to_ns": "y", "data": 7}, A, "e1")
    root = s.state_root(); s.save()
    s2 = ExecState(path)
    assert len(s2.outbox) == 1 and s2.state_root() == root, "outbox reloaded, root identical"


for name, fn in list(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)

print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
