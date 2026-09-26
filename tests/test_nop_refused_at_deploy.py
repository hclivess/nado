"""From ZK_HARDEN_HEIGHT a deploy or upgrade carrying NOP is refused — by the exec node AND by the settlement verifier's
event replay, at the same height (execnode/zkvm.py validate_code(height); zk audit 2026-09-26 ZKVM-2).

The interpreter steps over NOP but the AIR halts on it, so a call executing one ran on the exec layer and could never
be proven: every settle span containing it fell back to the quorum. Pins: the rule turns on exactly at the gate for
state.py's deploy and upgrade and for exec_state_bind.apply_event (the two admission paths the settle proof relies on
agreeing), code without NOP is unaffected, and a tool with no height keeps the old rule. The gate is set to 100 here.

Run: python3 tests/test_nop_refused_at_deploy.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-nop-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.environ["HOME"])
import protocol
protocol.ZK_HARDEN_HEIGHT = 100
from execnode import zkvm, zkvmasm
from execnode.code_codec import contract_id
from execnode.state import ExecState
from execnode.stark import exec_state_bind as ESB, calls_commit as CC

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


WITH_NOP = {"go": [["NOP", 0, 0, 0], ["MOVI", 1, 0, 7], ["RET", 0, 1, 0]]}
PLAIN = {"go": zkvmasm.assemble("movi r1 7\n ret r1")}


def refused(code, h):
    try:
        zkvm.validate_code(code, height=h)
        return False
    except zkvm.ZkVMError:
        return True


check("below the gate NOP is admitted (history)", not refused(WITH_NOP, 99))
check("from the gate NOP is refused", refused(WITH_NOP, 100))
check("code without NOP is admitted at the gate", not refused(PLAIN, 100))
check("a tool with no height keeps the old rule", not refused(WITH_NOP, None))

A = "ndoAAAA" + "A" * 41
blk = lambda h, txs: {"block_number": h, "block_hash": "cd" * 32, "block_timestamp": 0, "block_transactions": txs}
dep = lambda code, n: {"recipient": "blob", "sender": A, "txid": "t" + n, "data": {"op": "deploy", "code": code, "nonce": n}}


def exec_deploys(h, code, n):
    from execnode.execnode import _apply_block
    st = ExecState(os.path.join(os.environ["HOME"], f"s{h}{n}.json"))
    asyncio.new_event_loop().run_until_complete(_apply_block(None, {"default": st}, st, blk(h, [dep(code, n)]), verbose=False))
    return contract_id(A, code, n) in st.contracts


def replay_deploys(h, code, n):
    ev = CC.block_calls(blk(h, [dep(code, n)]))[0]
    ok, _cid, _b = ESB.apply_event({}, ev)
    return ok


for h, want in ((99, True), (100, False)):
    e, r = exec_deploys(h, WITH_NOP, f"n{h}"), replay_deploys(h, WITH_NOP, f"n{h}")
    check(f"height {h}: the exec node {'admits' if want else 'refuses'} a NOP deploy", e is want, e)
    check(f"height {h}: the verifier's replay agrees with the exec node", r is e, (r, e))
check("height 100: a plain deploy is admitted by both", exec_deploys(100, PLAIN, "p") and replay_deploys(100, PLAIN, "p"))

print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
