"""A restarted exec node re-seeds L1's settled root from its stash and serves an exit proof L1 accepts against it.

WHY (G9, 2026-10-27). execnode._seed_root_ring_sync rebuilt the GOLDILOCKS exec root from the stash. A gen-29 settled
root is BLAKE2s, so the rebuilt root never matched and every seed since the reroll was refused: after each restart, a
bridge, dividend or unshield exit against the settled root waited a full settle interval (or got a 409). G9 deleted the
Goldilocks root and the seed now rebuilds the BLAKE2s trees, in the ring shape ExecState.note_root_point records.
Pins, on the real exec-node module (throwaway HOME, state and DA paths):
  1. a stash whose state hashes to the settled root seeds it: the root enters the ring as a ("b2", kv, records) entry;
  2. record_proof_at(settled root) then serves the withdrawal's proof although the live root has moved on, and L1's
     verifier (transaction_ops.exit_root_module -> exec_root_b2.verify_withdrawal) accepts it against the settled root;
  3. the proof does not verify for another amount, and the live root never served it (it is not the settled one);
  4. a stash whose state does not hash to the root it names is refused and seeds nothing.
Run: python3 tests/test_a_restarted_exec_node_serves_exits_against_the_settled_root_from_its_stash.py
"""
import os, sys, json, tempfile
_T = tempfile.mkdtemp(prefix="nado-test-ring-seed-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import execnode.execnode as EN
from execnode import block_apply, exec_root_b2 as R2
from ops import transaction_ops as TO

import _harness
_report = _harness.Report()
check = _report.check

A = "ndo" + "A" * 45
st = EN.states["default"]


def apply(h, txs):
    blk = {"block_number": h, "block_hash": "%064x" % (h + 1), "block_transactions": txs}
    block_apply.begin(EN.states, h)
    block_apply.dispatch(EN.states, st, blk, {}, set(), verbose=False)
    block_apply.close(EN.states, h, blk["block_hash"])


def wd(n, amount):
    return {"recipient": "blob", "sender": A, "txid": n, "data": {"op": "bridge_withdraw", "amount": amount}}


apply(0, [{"recipient": "bridge", "sender": A, "amount": 10_000}])
apply(1, [wd("w1", 700)])
C, R = st.cursor, st.state_root()
nonce = next(n for n, w in st.withdrawals.items() if w == {"addr": A, "amount": 700})
payload = EN._stash_payload("default", st, C, R)
with open(EN._stash_path("default", C), "w") as f:
    f.write(payload)
apply(2, [wd("w2", 50)])                                     # the live state moves on past the settled cursor
live = st.state_root()
st._root_ring, st._ring_stores = {}, {}                      # a restart: the in-memory ring is empty

check("0. the live root has moved past the settled one", live != R and st.cursor == C + 1)
check("1. a stash that hashes to the settled root seeds it", EN._seed_root_ring_sync("default", C, R) is True)
ent = st._root_ring.get(R)
check("1b. ...as note_root_point's BLAKE2s ring entry", isinstance(ent, tuple) and len(ent) == 3 and ent[0] == "b2", ent)
got = st.record_proof_at(R, R2.T_BRIDGE_WD, A, nonce, value=700)
check("2. record_proof_at serves the withdrawal against the SETTLED root", got is not None and got[1] == R)
proof = got[0] if got else None
check("2b. ...and L1's exit verifier accepts it", TO.exit_root_module(C).verify_withdrawal(R, A, 700, nonce, proof))
check("3. the proof is for that amount only", not TO.exit_root_module(C).verify_withdrawal(R, A, 701, nonce, proof))
check("3b. ...and only against the settled root", not R2.verify_withdrawal(live, A, 700, nonce, proof))

bad = json.loads(payload)
bad["state"]["bridge"] = {A: 1}                              # a state that does not hash to the root it names
C2 = C + 5
bad["cursor"] = C2
with open(EN._stash_path("default", C2), "w") as f:
    json.dump(bad, f)
st._root_ring.pop(R, None)
check("4. a stash whose state does not hash to its root is refused", EN._seed_root_ring_sync("default", C2, R) is False
      and R not in st._root_ring)
_report.done()
