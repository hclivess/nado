"""The reroll drain brings the exec state to the L1 tip by applying exactly what the exec node would
(tools/exec_drain.py drain; doc/reroll.md step 6).

The exec node applies only finalized blocks, so at a reroll's stop it trails the tip by ~45 blocks that carry real
exec ops (dividend claims, deposits); the carry-forward refuses to run across that gap. The first betanet-8 drain
"finished" having applied nothing, because a block lookup swallowed its error. Pins: the drain applies cursor+1 up to
the tip, stops at the first missing block, saves, and ends in exactly the state the exec node's own _apply_block
reaches over the same blocks; a state already at the tip applies nothing.

Run: python3 tests/test_exec_drain_reaches_the_tip.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-drain-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import sys, asyncio, importlib.util
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(os.environ["HOME"])
from execnode import zkvmasm
from execnode.state import ExecState
from execnode.code_codec import contract_id
import execnode.execnode as EN
spec = importlib.util.spec_from_file_location("exec_drain", os.path.join(ROOT, "tools", "exec_drain.py"))
DR = importlib.util.module_from_spec(spec); spec.loader.exec_module(DR)

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


A = "ndoAAAA" + "A" * 41
CODE = {"bump": zkvmasm.assemble("movi r1 0\n sload r2 r1\n movi r3 1\n add r2 r3\n sstore r1 r2\n ret r2")}
cid = contract_id(A, CODE, "n1")
blk = lambda h, txs: {"block_number": h, "block_hash": "%064x" % h, "block_timestamp": 0, "block_transactions": txs}
call = lambda t: {"recipient": "blob", "sender": A, "txid": t, "data": {"op": "call", "contract": cid, "method": "bump", "args": []}}
CHAIN = {10: blk(10, [{"recipient": "blob", "sender": A, "txid": "d", "data": {"op": "deploy", "code": CODE, "nonce": "n1"}}]),
         11: blk(11, [call("c1")]), 12: blk(12, []), 13: blk(13, [call("c2"), call("c3")])}

# the reference: the exec node's own apply over blocks 10..13
ref = ExecState(os.path.join(os.environ["HOME"], "ref.json"))
loop = asyncio.new_event_loop()
for h in sorted(CHAIN):
    loop.run_until_complete(EN._apply_block(None, {"default": ref}, ref, CHAIN[h], verbose=False))

# a state that stopped after block 10 (the finalized cursor), drained to the tip (13)
path = os.path.join(os.environ["HOME"], "drained.json")
st = ExecState(path)
loop.run_until_complete(EN._apply_block(None, {"default": st}, st, CHAIN[10], verbose=False))
st.save()
first, last = DR.drain(path, CHAIN.get)
back = ExecState(path)
check("the drain applies cursor+1 .. the tip and stops at the first missing block", (first, last) == (11, 13), (first, last))
check("the saved state is at the tip", back.cursor == 13, back.cursor)
check("... and equals what the exec node's own apply reaches", back.state_root() == ref.state_root()
      and back.contracts[cid]["storage"] == ref.contracts[cid]["storage"], (back.contracts[cid]["storage"], ref.contracts[cid]["storage"]))
first, last = DR.drain(path, CHAIN.get)
check("a state already at the tip applies nothing", (first, last) == (14, 13) and ExecState(path).cursor == 13, (first, last))
print("ALL PASS" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
