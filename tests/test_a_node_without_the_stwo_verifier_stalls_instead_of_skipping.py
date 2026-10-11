"""A node that cannot load the Stwo verifier STALLS a block carrying a Stwo spend; it never skips the spend
(execnode._apply_block's pre-check, stwo_js_native.ensure_loaded).

apply_blob turns any exception into a "skip". A node missing native/stwo_js would therefore skip a spend every other
node applies and fork its exec state without a word — the crate is optional until STWO_POOL_HEIGHT is set, so this is
exactly the node to expect. Pins, driving the real _apply_block with the library pointed at a path that does not exist:
  1. a block carrying a stwo_js field_transfer, at or above the gate, returns False and moves NOTHING (cursor, pool);
  2. the same block below the gate applies (the bundle is refused there as not live, deterministically);
  3. a block with no Stwo spend applies above the gate as before.

Run: python3 tests/test_a_node_without_the_stwo_verifier_stalls_instead_of_skipping.py
"""
import os, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-stwo-stall-")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
os.environ["NADO_STWO_JS_LIB"] = os.path.join(os.environ["HOME"], "no-such-libnado_stwo_js.so")
import sys, json, copy, asyncio
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.environ["HOME"])
import protocol as P
from execnode.state import ExecState
from execnode.execnode import _apply_block

fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


GATE = 500
P.STWO_POOL_HEIGHT = GATE
loop = asyncio.new_event_loop()
blk = lambda h, txs: {"block_number": h, "block_hash": "%064x" % (h * 7919), "block_timestamp": 0, "block_transactions": txs}
SPEND = {"stark": {"stwo_js": {"proof": "00", "root": "00" * 32, "nf": "11" * 32, "cm_out1": "22" * 32,
                               "cm_out2": "33" * 32, "unshield": 0, "fee": 0}}}
spend_tx = lambda t: {"recipient": "blob", "sender": "ndoA" + "a" * 44, "txid": t,
                      "data": {"op": "field_transfer", "bundle_json": json.dumps(SPEND)}}
run = lambda st, b: loop.run_until_complete(_apply_block(None, {"default": st}, st, b, verbose=False))


def state_at(cursor):
    st = ExecState(os.path.join(tempfile.mkdtemp(dir=os.environ["HOME"]), "s.json"))
    st.cursor = cursor
    return st


st = state_at(GATE - 1)
before = copy.deepcopy(st._snapshot())
ok = run(st, blk(GATE, [spend_tx("s1")]))
check("1. at the gate a block carrying a Stwo spend STALLS on a node without the verifier", ok is False, ok)
check("...and moves nothing (cursor and every pool as before)", st.cursor == GATE - 1 and st._snapshot() == before)

st = state_at(GATE - 3)
ok = run(st, blk(GATE - 2, [spend_tx("s2")]))
check("2. below the gate the same block applies (the bundle is refused as not live, identically everywhere)",
      ok is not False and st.cursor == GATE - 2, ok)

st = state_at(GATE + 4)
ok = run(st, blk(GATE + 5, [{"recipient": "blob", "sender": "ndoA" + "a" * 44, "txid": "n1",
                             "data": {"op": "deploy", "code": {"x": []}, "nonce": "z"}}]))
check("3. above the gate a block with no Stwo spend applies as before", ok is not False and st.cursor == GATE + 5, ok)

print("ALL PASS — a node without the Stwo verifier stalls instead of skipping" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
