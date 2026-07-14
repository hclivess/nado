"""
Pluggable contract runtimes (execnode/runtimes.py): a contract records which runtime it deployed under, and
every call/view dispatches back to THAT runtime — so the execution engine is swappable without touching
state.py. Proven by registering a non-stackvm runtime and driving a contract through it.

Run: python3 tests/test_runtimes.py
"""
import os, sys, copy, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode import runtimes, zkvm_examples as C

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

def _st(): return ExecState(tempfile.mktemp(prefix="nado_rt_", suffix=".json"))


class EchoRuntime:
    """A trivial NON-stackvm runtime: set(k,v) stores v at map 'e'[k], get(k) reads it. Its behavior is driven
    by the runtime, not the bytecode — so if a call reaches it, dispatch is genuinely pluggable."""
    name = "echo"
    def validate_code(self, code):
        if not isinstance(code, dict):
            raise ValueError("code must be an object")
        return True
    def run(self, code, method, caller, args, storage, **kwargs):   # kwargs: value/cursor/beacons/... (echo ignores them)
        st = copy.deepcopy(storage)
        if method == "set":
            st.setdefault("e", {})[str(args[0])] = int(args[1]); return (True, None, st, [])
        if method == "get":
            return (True, st.get("e", {}).get(str(args[0]), 0), st, [])
        return (False, None, storage, [])


def t1_custom_runtime_dispatch():
    """Register 'echo', deploy under it, and confirm calls run on echo (not the stack VM)."""
    runtimes.register(EchoRuntime())
    assert "echo" in runtimes.names(), "registered"
    st = _st()
    code = {"set": [], "get": []}                      # bytecode is ignored by echo; the runtime drives behavior
    cid = st.contract_id("ndoA", code, "n1")
    st.apply_blob({"op": "deploy", "runtime": "echo", "code": code, "nonce": "n1"}, sender="ndoA", txid="d")
    assert cid in st.contracts and st.contracts[cid]["runtime"] == "echo", "recorded the runtime"
    st.apply_blob({"op": "call", "contract": cid, "method": "set", "args": ["k", 42]}, sender="ndoA", txid="c")
    assert st.view(cid, "get", ["k"]) == 42, "call dispatched to the echo runtime"


def t2_unknown_runtime_rejected():
    """A deploy naming an unregistered runtime is a no-op (skip), not a crash."""
    st = _st()
    r = st.apply_blob({"op": "deploy", "runtime": "nope", "code": {"x": []}, "nonce": "n"}, sender="ndoA", txid="d")
    assert "unknown runtime" in r and not st.contracts, r


def t3_default_is_zkvm():
    """A deploy with no explicit runtime uses zkvm — the only runtime NADO ships."""
    st = _st()
    cid = st.contract_id("ndoA", C.COUNTER, "n1")
    st.apply_blob({"op": "deploy", "code": C.COUNTER, "nonce": "n1"}, sender="ndoA", txid="d")
    assert st.contracts[cid]["runtime"] == "zkvm", "default runtime"
    st.apply_blob({"op": "call", "contract": cid, "method": "bump", "args": []}, sender="ndoA", txid="c")
    assert st.view(cid, "get", []) == 1, "zkvm still runs"


for name, fn in sorted(globals().items()):
    if name.startswith("t") and callable(fn) and name[1].isdigit():
        check(name, fn)
print(f"\n{'ALL PASSED' if not fails else str(fails)+' FAILED'}")
sys.exit(1 if fails else 0)
