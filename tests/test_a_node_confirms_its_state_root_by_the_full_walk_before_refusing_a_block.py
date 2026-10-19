"""A node confirms its state root by the full walk before refusing a block over it.

Operator decision 2026-10-19: every node trusts the incremental L1 state root by default (NADO_ROOT_INC=trust, a full
walk cross-check every ROOT_INC_VERIFY_EVERY roots) instead of walking the whole database every block. What makes that
safe is that a wrong incremental root can never make a node REFUSE a valid block: verify_block re-derives the root by
the walk (snapshot_ops.confirm_l1_state_root) before it rejects. This pins:
  1. trust is the default when NADO_ROOT_INC is unset (rule 9: default in the CODE);
  2. a corrupted incremental structure gives a wrong l1_state_root, and confirm_l1_state_root returns the walk's root,
     counts the mismatch, drops the structure and corrects the cache — the next reader gets the right root too;
  3. confirm is memoised per write generation (a diverged node retrying the same parent walks once);
  4. verify_block calls confirm before its refusal (source order), with the regression comment in place.

Run: python3 tests/test_a_node_confirms_its_state_root_by_the_full_walk_before_refusing_a_block.py
"""
import _harness
HOME = _harness.isolate("nado-test-root-confirm-before-refusal-")
import os
os.environ.pop("NADO_ROOT_INC", None)
os.environ["NADO_HOME"] = HOME

from ops import kv_ops, snapshot_ops as so

T = _harness.Report()
T.check("1. trust is the default when NADO_ROOT_INC is unset", so._root_inc_mode() == "trust", so._root_inc_mode())

kv_ops.init_env()
for i in range(30):
    kv_ops.put_account(f"a{i}", {"balance": i + 1})
good = so.l1_state_root()
T.check("setup: the incremental root equals the walk", good == so._root_from_walk())

# corrupt the incremental structure the way a bug would: one leaf digest wrong, then a commit so the root recomputes
kv_ops.put_account("b0", {"balance": 99})
so._root_from_inc()                                       # bring the structure current
st = so._inc
k0 = st["keys"]["accounts"][0]
st["leaves"]["accounts"][k0] = [b"\x00" * 32]
kv_ops.put_account("b1", {"balance": 5})                  # new generation: l1_state_root recomputes from the structure
before = dict(so._inc_stats)
wrong = so.l1_state_root()
walk = so._root_from_walk()
T.check("2a. a corrupted structure yields a WRONG l1_state_root (the hazard trust mode accepts)", wrong != walk)
confirmed = so.confirm_l1_state_root()
T.check("2b. confirm_l1_state_root returns the walk's root", confirmed == walk)
T.check("2c. ...counts the mismatch", so._inc_stats["mismatch"] == before["mismatch"] + 1, so._inc_stats["mismatch"])
T.check("2d. ...drops the incremental structure (rebuilt on the next call)", so._inc is None)
T.check("2e. ...and corrects l1_state_root's cache, so the next reader gets the right root", so.l1_state_root() == walk)

walks = [0]
real = so._root_from_walk
so._root_from_walk = lambda home=None: (walks.__setitem__(0, walks[0] + 1), real(home))[1]
try:
    so.confirm_l1_state_root(); so.confirm_l1_state_root()
finally:
    so._root_from_walk = real
T.check("3. confirm is memoised per write generation (no walk on a repeat)", walks[0] == 0, walks[0])

src = open(os.path.join(_harness.ROOT, "loops", "core_loop.py")).read()
i_conf = src.find("our_state_root = confirm_l1_state_root()")
i_rej = src.find("refusing to extend (would fork state while agreeing on the block body)")
T.check("4. verify_block confirms by the walk before its state-root refusal",
        0 < i_conf < i_rej and "CONFIRM BEFORE REFUSING" in src[i_conf - 900:i_conf], (i_conf, i_rej))
T.done("ALL PASS — a node confirms its state root by the full walk before refusing a block")
