"""From block 1 the exec node's wallet endpoints (/exec/field_leaves, /exec/field_shielded) serve the Stwo pool (gen 28's
STWO_POOL_HEIGHT, 1 from gen 29, inlined in G9), and before it — a fresh state, genesis next — the wide pool's.

A wallet builds its Merkle path from /exec/field_leaves and decides which pool it is proving for from the same answer.
With the gate live, the exec layer only accepts `stwo_js` spends against the Stwo pool, so serving the frozen wide pool
there would hand the wallet a tree no spend can anchor to. Pins:
  1. (retired in G9: generation 28's dormant gate);
  2. on a fresh state (tip + 1 == 0) they are still the wide pool's;
  3. from tip + 1 == 1 they are the Stwo pool's: its leaves in order, "pool": "stwo", "wide": False (so a wallet that
     does not know the pool refuses to build a joinsplit3 proof against it), depth 48, and the pool's own root;
  4. (retired in G9: a gate of 0).

Run: python3 tests/test_the_exec_node_serves_the_stwo_pool_to_wallets_from_its_gate.py
"""
import os, sys, tempfile, json, asyncio
_T = tempfile.mkdtemp(prefix="nado-test-stwo-endpoints-")
os.environ["HOME"] = _T
os.environ["NADO_EXEC_STATE"] = os.path.join(_T, "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(_T, "exec_da")
# importing the exec node seeds its state from the exec genesis of the live generation: this test's own (none), never the
# real carried contracts in genesis_data/exec_genesis.json (the gen-29 rehearsal loaded all 27 of them here)
os.environ["NADO_EXEC_GENESIS"] = os.path.join(_T, "no_exec_genesis.json")
import atexit, shutil; atexit.register(shutil.rmtree, _T, ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode.state import ExecState
from execnode import shielded_stwo as SP
import execnode.execnode as EN

import _harness
_report = _harness.Report()
check = _report.check


GATE = 5000                                  # a test height (the Stwo pool holds from block 1)
st = ExecState(os.path.join(_T, "s.json"))
st.cursor = GATE - 1
owner = SP.owner_of("ab" * 32)
for i in range(3):
    st.apply_field_shield(10 + i, owner, i)
check("the fixture: three deposits are Stwo notes", len(st.stwo_pool.commitments) == 3)


def ask(cursor):
    saved, saved_cursor = EN.state, st.cursor
    EN.state, st.cursor = st, cursor
    try:
        loop = asyncio.new_event_loop()
        lv = json.loads(loop.run_until_complete(EN.h_field_leaves(None)).body)

        class _R:
            query = {}
        sh = json.loads(loop.run_until_complete(EN.h_field_shielded(_R())).body)
        return lv, sh
    finally:
        EN.state, st.cursor = saved, saved_cursor


# 1 (generation 28's dormant gate served the wide pool) and 4 (a gate of 0) retired in G9: generation 28's rules.
# STWO_POOL_HEIGHT is inlined as block 1 (execnode._stwo_pool_next: cursor + 1 >= 1).
lv, sh = ask(-1)
check("2. a fresh state (cursor -1, the next block is genesis) still serves the wide pool",
      "pool" not in lv and "pool" not in sh, (lv, sh))
lv, sh = ask(0)
check("3. from tip + 1 == 1 field_leaves serves the Stwo pool's leaves, in order",
      lv.get("pool") == "stwo" and lv.get("leaves") == st.stwo_pool.commitments, lv)
check("...marked not-wide, at depth 48", lv.get("wide") is False and lv.get("depth") == SP.DEPTH == 48, lv)
check("...and field_shielded carries the Stwo pool's own root and counts",
      sh.get("pool") == "stwo" and sh.get("root") == st.stwo_pool.root() and sh.get("notes") == 3
      and sh.get("nullifiers") == 0, sh)
lv, sh = ask(GATE + 10 ** 6)
check("...and at any later height", lv.get("pool") == "stwo" and sh.get("pool") == "stwo", (lv.get("pool"), sh.get("pool")))

print("ALL PASS — the exec node serves the Stwo pool to wallets from its gate" if not _report.fails else f"{_report.fails} FAILURES")
sys.exit(1 if _report.fails else 0)
