"""
Committed epoch weights — the presence-dividend's input becomes immutable L1 state
(ops/kv_ops.py + loops/core_loop.py + rollback.py + nado.py, gate: protocol.EPOCH_WEIGHTS_COMMIT_ACTIVATION).

THE DEBT THIS RETIRES (2026-08-19 frozen-quorum post-mortem): weights_at_epoch(E) reconstructs the
fidelity ramp from recert history AT QUERY TIME — "deterministic" only against one code version.
Three historical replays (batch order, per-block order, journal-recorded boundaries) all failed to
reproduce the justified exec root because the day's build no longer answered old epochs the way the
fleet had computed them live. Every fidelity/pool change silently rewrites history for whoever
reconstructs after it. From the activation boundary, the FIRST block of each epoch freezes the
just-completed epoch's weights into a state row — computed once, at one code version, at the same
height, on every node — and the row rides the state ROOT, so a wrong answer is a root split, not a
silent drift.

  1. commit -> get roundtrip; canonical encoding independent of dict insertion order
  2. revert DELETES the key (canonical-absent — the divinflow/h4260 phantom-row lesson)
  3. pins: incorporate commits at (h >= ACT and h % L == 0) for epoch h//L - 1, AFTER the block's
     registers applied; rollback holds the exact inverse under the identical gate;
     /get_open_weights serves committed-first; the activation constant is protocol-level
  4. the committed row shape matches what the exec accrual consumes ({addr: int})

Run: python3 tests/test_epoch_weights_commit.py
"""
import os, sys, tempfile, traceback
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_epochw_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import kv_ops

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CORE = open(os.path.join(_ROOT, "loops", "core_loop.py")).read()
_RB = open(os.path.join(_ROOT, "rollback.py")).read()
_API = open(os.path.join(_ROOT, "nado.py")).read()


def t1_roundtrip_and_canonical():
    kv_ops.epoch_weights_commit(1370, {"b": 2, "a": 1})
    assert kv_ops.epoch_weights_get(1370) == {"a": 1, "b": 2}
    # identical content, reversed insertion order -> identical stored bytes (root-identical)
    def raw(e):
        def _do(txn):
            return bytes(txn.get(f"epochw:{e}".encode(), db=kv_ops._dbs()["meta"]))
        return kv_ops._read(_do)
    kv_ops.epoch_weights_commit(1371, {"a": 1, "b": 2})
    kv_ops.epoch_weights_commit(1372, {"b": 2, "a": 1})
    assert raw(1371) == raw(1372), "encoding must be insertion-order independent (sort_keys)"
    assert kv_ops.epoch_weights_get(9999) is None, "absent epoch must read None"


def t2_revert_deletes():
    kv_ops.epoch_weights_commit(1373, {"m": 7})
    assert kv_ops.epoch_weights_get(1373) == {"m": 7}
    kv_ops.epoch_weights_commit(1373, revert=True)
    assert kv_ops.epoch_weights_get(1373) is None, "revert must DELETE (canonical-absent), not zero"
    def raw_present(e):
        def _do(txn):
            return txn.get(f"epochw:{e}".encode(), db=kv_ops._dbs()["meta"]) is not None
        return kv_ops._read(_do)
    assert not raw_present(1373), "no phantom row may survive the revert"


def t3_pins():
    assert "EPOCH_WEIGHTS_COMMIT_ACTIVATION = 82200" in open(os.path.join(_ROOT, "protocol.py")).read()
    i = _CORE.index("kv_ops.epoch_weights_commit(_E, weights_at_epoch(_E))")
    seg = _CORE[max(0, i - 800):i]
    assert "_bn >= EPOCH_WEIGHTS_COMMIT_ACTIVATION and _bn % EPOCH_LENGTH == 0" in seg, \
        "commit must be activation- and boundary-gated"
    assert "_bn // EPOCH_LENGTH - 1" in seg, "the committed epoch is the JUST-COMPLETED one"
    assert _CORE.index("credit_block_reward(block, logger=self.logger)") < i, \
        "commit runs with the block's other state writes (after this block's txs applied)"
    j = _RB.index("kv_ops.epoch_weights_commit(")
    rseg = _RB[max(0, j - 600):j + 200]
    assert "revert=True" in rseg and "% _EL == 0" in rseg and "EPOCH_WEIGHTS_COMMIT_ACTIVATION" in rseg, \
        "rollback must hold the exact inverse under the identical gate"
    k = _API.index("epoch_weights_get(e)")
    aseg = _API[k:k + 400]
    assert '"committed": True' in aseg, "/get_open_weights must serve the committed row first"
    assert _API.index("epoch_weights_get(e)") < _API.index('return {"epoch": e, "weights": weights_at_epoch(e)}'), \
        "committed row takes precedence over reconstruction"


def t4_exec_shape():
    kv_ops.epoch_weights_commit(1374, {"ab" * 23: 12})
    w = kv_ops.epoch_weights_get(1374)
    assert all(isinstance(a, str) and isinstance(v, int) for a, v in w.items()), \
        "shape must match what the exec accrual consumes"


check("commit/get roundtrip + canonical insertion-order-independent encoding", t1_roundtrip_and_canonical)
check("revert deletes the key — canonical-absent, no phantom", t2_revert_deletes)
check("pins: gated commit, exact rollback inverse, committed-first serving", t3_pins)
check("committed row shape matches the exec consumer", t4_exec_shape)
print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILURE(S)'}")
sys.exit(1 if fails else 0)
