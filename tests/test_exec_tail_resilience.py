"""
Exec tail-loop resilience — the all-or-nothing poll epilogue (execnode/execnode.py).

THE BUG CLASS THIS PINS (2026-08-19, "delay behind L1" chronic lag): the tail poll fetches every
catch-up block SEQUENTIALLY, and _get_json RAISES on its 15s timeout. Unhandled, one slow answer
skipped the whole poll epilogue — dividend accrual, the state SAVE, the checkpoint, the settle
spawn. Under a busy L1 EVERY poll died this way (measured: 0 completed epilogues in 100 minutes,
exec_state.json 2h stale while blocks applied in memory, every restart re-replaying hours) — and it
stayed invisible because str(TimeoutError) is "", so the log printed literally "tail error: ".

  1. the batch block-fetch is exception-wrapped and degrades to the `break` path (epilogue reachable)
  2. progress persists MID-BATCH (periodic save inside the apply loop)
  3. the tail-error handler names the exception type (no more empty messages)

Run: python3 tests/test_exec_tail_resilience.py
"""
import os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "execnode", "execnode.py")).read()
_TL = _SRC[_SRC.index("async def tail_loop"):]


def t1_batch_fetch_degrades_not_raises():
    i = _TL.index("while state.cursor < finalized:")
    seg = _TL[i:i + 2500]
    j = seg.index('_get_json(session, f"/get_block_number?number={h}")')
    assert "try:" in seg[:j], "the batch block-fetch must be exception-wrapped"
    k = seg.index("except", j)
    assert "TimeoutError" in seg[k:k + 200] and "ClientError" in seg[k:k + 200], \
        "timeout/client errors must be caught at the fetch"
    assert "block = None" in seg[k:k + 600], "a failed fetch must degrade to the break path"


def t2_mid_batch_persistence():
    i = _TL.index("applied += 1")
    seg = _TL[i:i + 1200]
    assert "applied % " in seg and "_st.save()" in seg, \
        "progress must persist periodically INSIDE the apply loop, not only at the epilogue"


def t3_tail_error_names_the_type():
    assert 'tail error: {type(e).__name__}' in _TL, \
        "the tail-error handler must name the exception type (str(TimeoutError) is empty)"


check("batch fetch degrades to break, never kills the poll", t1_batch_fetch_degrades_not_raises)
check("mid-batch persistence", t2_mid_batch_persistence)
check("tail error names the exception type", t3_tail_error_names_the_type)
print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILURE(S)'}")
sys.exit(1 if fails else 0)
