"""A restarted exec node sees the same clock as one that never restarted (review 2026-09-25, reproduced).

block_ts (the TIME opcode's clock) is not in the snapshot, so a restored state kept 0 and the first block it applied
ran every TIME read as 0: a different state root from the nodes that had not restarted, after every /update wave. After
applying block h the node sets block_ts = chain_clock(h), a pure function of the cursor, so ExecState._restore now
derives it the same way. This deploys a contract that stores TIME, restarts one copy, applies the same call to both, and
requires the same stored time and the same root.

Run: python3 tests/test_exec_restart_clock.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-restart-clock-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_L1_URL"] = "http://127.0.0.1:1"          # unreachable: nothing live is touched
import sys, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode import zkvmasm
import execnode.execnode as EN
from protocol import chain_clock

TIMER = {"stamp": zkvmasm.assemble("ctx r1 time\n movi r2 1\n sstore r2 r1\n ret r1")}
blk = lambda h, txs: {"block_number": h, "block_hash": "%064x" % h, "block_transactions": txs}
tx = lambda i, d: {"recipient": "blob", "sender": "A", "txid": f"t{i}", "data": d}
loop = asyncio.new_event_loop()
path = os.path.join(os.environ["HOME"], "a.json")
a = ExecState(path)
loop.run_until_complete(EN._apply_block(None, {"default": a}, a, blk(200000, [tx(0, {"op": "deploy", "code": TIMER, "nonce": 1})]), verbose=False))
a.save()
cid = next(iter(a.contracts))
b = ExecState(path)                                        # the same node after a restart
fails = []
def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond: fails.append(name)
check("a restored state derives its clock from its cursor", b.block_ts == chain_clock(b.cursor) and b.block_ts > 0)
call = blk(200001, [tx(1, {"op": "call", "contract": cid, "method": "stamp", "args": []})])
loop.run_until_complete(EN._apply_block(None, {"default": a}, a, call, verbose=False))
loop.run_until_complete(EN._apply_block(None, {"default": b}, b, call, verbose=False))
ta, tb = a.contracts[cid]["storage"]["slots"].get("1"), b.contracts[cid]["storage"]["slots"].get("1")
check("the restarted node's first call sees the same TIME", ta == tb and int(tb or 0) > 0)
check("...and lands on the same state root", a.state_root() == b.state_root())
print("ALL PASS" if not fails else f"{len(fails)} FAILURES")
sys.exit(1 if fails else 0)
