"""
zkVM as an exec-layer runtime (execnode/runtimes.py _ZkVM + state.py registry wiring): deploy/call/view
through the normal blob path, value escrow + PAY resolution through the digest registry, state_root over
slot storage, persistence, and the DIFFERENTIAL guarantee — the natively-applied call, the interpreter,
and the PROVEN call's replayed I/O log all reach the identical state (doc/nado-dev-approaches: money code
verified 3 ways).

Run: python3 tests/test_zkvm_runtime.py            (~30s: includes one real proof)
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode import runtimes, zkvm, zkvmasm
from execnode.stark import vm_circuit

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


VAULT = {
    "deposit": zkvmasm.assemble("""
        ctx r1 caller
        ctx r2 value
        sload r3 r1
        add r3 r2
        sstore r1 r3
        movi r0 1
        ret r0
    """),
    "withdraw": zkvmasm.assemble("""
        ctx r1 caller
        sload r3 r1
        mov r4 r3
        lt r4 r0
        notb r4
        require r4
        mov r4 r3
        sub r4 r0
        sstore r1 r4
        pay r1 r0
        movi r5 1
        ret r5
    """),
}
ALICE = "ndoALICEALICEALICEALICEALICEALICEALICEALICEALICE"


def _fresh():
    st = ExecState(os.path.join(tempfile.mkdtemp(), "exec_state.json"))
    st.cursor, st.block_ts = 100, 1_700_000_000
    return st

def _deploy(st):
    msg = st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": VAULT, "nonce": "t"}, ALICE, "tx0")
    assert msg.startswith("deploy"), msg
    return next(iter(st.contracts))

def t1_deploy_call_view():
    st = _fresh()
    cid = _deploy(st)
    st.credit_deposit(ALICE, 1000)
    msg = st.apply_blob({"op": "call", "contract": cid, "method": "deposit", "args": [], "value": 300},
                        ALICE, "tx1")
    assert "-> ok" in msg, msg
    dig = str(runtimes.zkvm_addr_digest(ALICE))
    assert st.contracts[cid]["storage"]["slots"] == {dig: 300}
    assert st.bridge == {ALICE: 700, cid: 300}
    assert st.zk_addrs[dig] == ALICE                     # registry learned the caller
    assert st.view(cid, "deposit", []) is None or True    # view path must not crash
    root1 = st.state_root()
    msg = st.apply_blob({"op": "call", "contract": cid, "method": "withdraw", "args": [200]}, ALICE, "tx2")
    assert "-> ok" in msg and "paid=200" in msg, msg
    assert st.contracts[cid]["storage"]["slots"] == {dig: 100}
    assert st.bridge == {ALICE: 900, cid: 100}
    assert st.state_root() != root1                       # slot storage is committed state

def t2_revert_refunds():
    st = _fresh()
    cid = _deploy(st)
    st.credit_deposit(ALICE, 1000)
    st.apply_blob({"op": "call", "contract": cid, "method": "deposit", "args": [], "value": 100}, ALICE, "t")
    msg = st.apply_blob({"op": "call", "contract": cid, "method": "withdraw", "args": [500]}, ALICE, "t2")
    assert "revert" in msg, msg                           # REQUIRE balance >= amount fails
    assert st.bridge == {ALICE: 900, cid: 100}            # nothing moved

def t3_persistence():
    st = _fresh()
    cid = _deploy(st)
    st.credit_deposit(ALICE, 500)
    st.apply_blob({"op": "call", "contract": cid, "method": "deposit", "args": [], "value": 500}, ALICE, "t")
    st.save()
    st2 = ExecState(st.path)
    assert st2.contracts[cid]["storage"] == st.contracts[cid]["storage"]
    assert st2.zk_addrs == st.zk_addrs
    assert st2.state_root() == st.state_root()

def t4_differential_proven_call():
    """The 3-way: (a) native runtime apply, (b) STARK-proven call whose io log is replayed with NO
    execution, (c) the bare interpreter — all reach the same storage + payouts."""
    st = _fresh()
    cid = _deploy(st)
    st.credit_deposit(ALICE, 1000)
    st.apply_blob({"op": "call", "contract": cid, "method": "deposit", "args": [], "value": 300}, ALICE, "t")
    slots_before = {int(k): int(v) for k, v in st.contracts[cid]["storage"]["slots"].items()}
    cf, fargs = runtimes.zkvm_statement(ALICE, [200], {})

    # (b) prove against the pre-state, verify, replay — the skip-execution path
    proof, io, ret, slots_after_proof = vm_circuit.prove_call(VAULT, "withdraw", cf, fargs, slots_before,
                                                              cursor=st.cursor, timestamp=st.block_ts,
                                                              num_queries=8)
    ok, why = vm_circuit.verify_call(proof, VAULT, "withdraw", cf, fargs, io, cursor=st.cursor,
                                     timestamp=st.block_ts, num_queries=8)
    assert ok, f"proven withdraw must verify: {why}"
    ok2, ret2, slots_replayed, payouts, _chain = zkvm.replay_io(io, slots_before)
    assert ok2 and ret2 == ret == 1

    # (c) bare interpreter
    ok3, ret3, slots_interp, io3 = zkvm.run(VAULT, "withdraw", cf, fargs, slots_before,
                                           cursor=st.cursor, timestamp=st.block_ts)
    assert ok3 and io3 == io

    # (a) native runtime apply on the exec state
    msg = st.apply_blob({"op": "call", "contract": cid, "method": "withdraw", "args": [200]}, ALICE, "t2")
    assert "-> ok" in msg
    slots_native = {int(k): int(v) for k, v in st.contracts[cid]["storage"]["slots"].items()}

    assert slots_native == slots_replayed == slots_interp == slots_after_proof, "3-way state divergence"
    dig = runtimes.zkvm_addr_digest(ALICE)
    assert payouts == [(dig, 200)] and st.bridge.get(ALICE) == 900, "payout divergence"

def t5_bad_args_and_zero_pay():
    st = _fresh()
    cid = _deploy(st)
    st.credit_deposit(ALICE, 10)
    msg = st.apply_blob({"op": "call", "contract": cid, "method": "deposit", "args": [1.5], "value": 1},
                        ALICE, "t")
    assert "revert" in msg, msg                           # non-int/str arg -> deterministic revert
    st.apply_blob({"op": "call", "contract": cid, "method": "deposit", "args": [], "value": 10}, ALICE, "t2")
    msg = st.apply_blob({"op": "call", "contract": cid, "method": "withdraw", "args": [0]}, ALICE, "t3")
    assert "-> ok" in msg and "paid" not in msg, msg      # zero PAY filtered — no 0-balance leaf pollution


if __name__ == "__main__":
    check("deploy/call/view + escrow + registry + root", t1_deploy_call_view)
    check("revert refunds escrow", t2_revert_refunds)
    check("persistence round-trip (slots + registry)", t3_persistence)
    check("3-way differential: native == proven+replayed == interpreter", t4_differential_proven_call)
    check("bad args revert; zero payouts filtered", t5_bad_args_and_zero_pay)
    print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
    sys.exit(1 if fails else 0)
