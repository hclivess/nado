"""A settle stash hashes to its own (cursor, root), even after the live state has moved on.

A quorum settle attests the latest EPOCH-BOUNDARY pair (ExecState.boundary_roots), not the live cursor, and it stashed
the LIVE state, serialized after the submit's await: measured 2026-10-27 on the live node, the stash labeled
(4980, root at 4980) held a state at cursor 4981. A joiner verifies a stash against exactly its pair, and the gen-29
settlement prover (execnode/settle_b2.py, tools/settle_b2_shadow.py) starts a span from it, so a stash that does not hash
to its label is worse than none. execnode._record_boundary now serializes the state in the same synchronous step that
records the boundary root, and execnode._stash_payload picks it:
  1. a stash for a boundary pair is the state AT that boundary, though the live state has moved past it;
  2. the live state is used only while it is still exactly at the pair; a pair this node holds no snapshot of stashes
     nothing (None), never a mismatched payload;
  3. a root that is not the recorded one is not served the recorded snapshot;
  4. only boundary cursors record, and the record is bounded.

Run: python3 tests/test_a_settle_stash_hashes_to_its_own_cursor_and_root.py
"""
import os
import sys
import tempfile

_T = tempfile.mkdtemp(prefix="nado-test-stash-pair-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)   # noqa: E401,E702
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json

import _harness
import execnode.execnode as EN
from execnode.state import ExecState
from protocol import EPOCH_LENGTH

T = _harness.Report()
A = "ndo" + "A" * 45


def snap_root(payload):
    d = json.loads(payload)
    v = ExecState.snapshot_view(d["state"])
    return d["cursor"], d["state_root"], v.cursor, v.state_root()


st = ExecState(os.path.join(_T, "st.json"))
B = 3 * EPOCH_LENGTH
st.cursor = B
st.credit_deposit(A, 1000)
EN._record_boundary("default", st)
root_b = st.state_root()
T.check("4a. a boundary cursor records its root and its snapshot", st.boundary_roots.get(B) == root_b
        and EN._boundary_snaps["default"][B][0] == root_b)

# the live state moves on (the next block applies while the settle awaits its submit)
st.cursor = B + 1
st.credit_deposit(A, 5)
live_root = st.state_root()
T.check("the live state really moved: its root is no longer the boundary's", live_root != root_b)

p = EN._stash_payload("default", st, B, root_b)
lc, lr, sc, sr = snap_root(p) if p else (None, None, None, None)
T.check("1. the stash for the boundary pair is the state AT the boundary (it hashes to its own label)",
        p is not None and (lc, lr) == (B, root_b) and (sc, sr) == (B, root_b), (lc, lr, sc, sr))
old = json.dumps({"ns": "default", "cursor": B, "state_root": root_b, "state": st._snapshot()}, sort_keys=True)
T.check("...where the old payload (the live state under the boundary label) did not",
        snap_root(old)[2:] != (B, root_b), snap_root(old))

p2 = EN._stash_payload("default", st, B + 1, live_root)
T.check("2a. the live state is stashed while it is still exactly at the pair", p2 is not None
        and snap_root(p2)[2:] == (B + 1, live_root))
T.check("2b. a pair this node holds no snapshot of stashes nothing", EN._stash_payload("default", st, B - 7, "ab" * 32) is None)
T.check("3. a root other than the recorded one is not served the recorded snapshot",
        EN._stash_payload("default", st, B, "cd" * 32) is None)

n0 = len(EN._boundary_snaps["default"])
st.cursor = B + 2
EN._record_boundary("default", st)
T.check("4b. a cursor that is not a boundary records nothing", len(EN._boundary_snaps["default"]) == n0 and (B + 2) not in st.boundary_roots)
for i in range(1, 9):
    st.cursor = B + i * EPOCH_LENGTH
    EN._record_boundary("default", st)
T.check("4c. the boundary snapshots are bounded", len(EN._boundary_snaps["default"]) == EN._BOUNDARY_SNAPS_KEEP,
        len(EN._boundary_snaps["default"]))
T.done()
