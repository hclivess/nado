"""
reg-difficulty v3 (protocol 4): the register-rate multiplier counts from the recert_by_epoch CONSENSUS
state index — visibility-free (identical on a from-genesis node and a snapshot-booted node with zero
bodies retained). This suite proves the kv-backed count path end-to-end in a throwaway LMDB env:
rows drive chain_register_count, rollback symmetry holds, and the multiplier math consumes them.

Run: python3 tests/test_reg_difficulty_v3.py
"""
import os
import sys
import tempfile
import traceback

_home = tempfile.mkdtemp()
os.environ["HOME"] = _home
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import kv_ops
kv_ops.init_env(_home)
from ops import reg_difficulty as rd
from protocol import POSW_DIFF_WINDOW, POSW_DIFF_FLOOR

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

A = lambda i: f"ndo{i:046d}"

def t_rows_drive_counts():
    for i in range(3):
        kv_ops.recert_put(A(i), 850)
    kv_ops.recert_put(A(9), 851)
    assert rd.chain_register_count(850) == 3
    assert rd.chain_register_count(851) == 1
    assert rd.chain_register_count(849) == 0          # a true zero, not a missing-bodies zero
    assert rd.chain_register_count(-1) == 0

def t_rollback_symmetry():
    kv_ops.recert_del(A(0), 850)
    assert rd.chain_register_count(850) == 2
    kv_ops.recert_put(A(0), 850)
    assert rd.chain_register_count(850) == 3

def t_multiplier_consumes_state():
    # flood one recent window well past the floor baseline; anchor just after it
    e0 = 2000
    n = POSW_DIFF_FLOOR * 3                            # recent = 3x baseline floor -> multiplier 3
    for i in range(n):
        kv_ops.recert_put(A(100 + i), e0 + POSW_DIFF_WINDOW - 1)
    assert rd.difficulty_multiplier(e0 + POSW_DIFF_WINDOW) == 3

def t_window_ends_before_anchor():
    # rows in the anchor's own epoch never count (windows end at anchor_epoch - 1)
    e = 3000
    for i in range(POSW_DIFF_FLOOR * 5):
        kv_ops.recert_put(A(500 + i), e)
    assert rd.difficulty_multiplier(e) == 1

for t in (t_rows_drive_counts, t_rollback_symmetry, t_multiplier_consumes_state, t_window_ends_before_anchor):
    check(t.__name__, t)
print("ALL PASS" if fails == 0 else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
