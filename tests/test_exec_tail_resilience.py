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
    seg = _TL[i:i + 8000]   # widened again: peer-batch fallback sits between prefetch and the single-fetch except
    j = seg.index('_get_json(session, f"/get_block?number={h}")')
    assert "try:" in seg[:j], "the batch block-fetch must be exception-wrapped"
    k = seg.index("except", j)
    assert "TimeoutError" in seg[k:k + 200] and "ClientError" in seg[k:k + 200], \
        "timeout/client errors must be caught at the fetch"
    assert "block = None" in seg[k:k + 600], "a failed fetch must degrade to the break path"


def t2_mid_batch_persistence():
    i = _TL.index("applied += 1")
    # up to the per-poll checkpoint call, not a fixed char window (comments between apply and save grew
    # past every width this was widened to)
    seg = _TL[i:_TL.index("_ckpt_maybe_persist(prev_cursor_for_ckpt", i)]
    assert "applied % " in seg and "_st.save()" in seg, \
        "progress must persist periodically INSIDE the apply loop, not only at the epilogue"


def t3_tail_error_names_the_type():
    assert 'tail error: {type(e).__name__}' in _TL, \
        "the tail-error handler must name the exception type (str(TimeoutError) is empty)"


def t4_batch_prefetch_with_single_fetch_fallback():
    # catch-up must amortize round trips (one /get_blocks_after call per ~100 blocks) but the
    # single-block fetch stays the correctness path: any batch problem falls through to it, the
    # buffer is POLL-LOCAL (refilled from the current cursor's own hash -> reorg-safe), and only
    # finalized-bounded blocks enter it.
    i = _TL.index("prefetch = {}")
    seg = _TL[i:i + 9000]   # widened: 20s-timeout rationale + peer-batch-empty logging sit inside
    assert "/get_blocks_after?hash={_ph}&count=" in seg, "batch prefetch must key off our own last hash"
    assert '_b["block_number"] <= finalized' in seg, "prefetch must never admit unfinalized blocks"
    assert 'f"/get_block?number={h}"' in seg, "single-block fetch must remain the fallback"
    assert seg.index("get_blocks_after") < seg.index('f"/get_block?number={h}"'), "batch tried first"


def t5_provisional_guarded_and_named():
    assert "if tip - state.cursor <= 200:" in _TL, "provisional refresh must pause during deep catch-up"
    assert "provisional refresh error: {type(e).__name__}" in _TL, "provisional errors must name the type"


check("batch fetch degrades to break, never kills the poll", t1_batch_fetch_degrades_not_raises)
check("mid-batch persistence", t2_mid_batch_persistence)
check("tail error names the exception type", t3_tail_error_names_the_type)
check("batch prefetch, poll-local, finality-bounded, single-fetch fallback", t4_batch_prefetch_with_single_fetch_fallback)
check("provisional refresh paused while behind; errors named", t5_provisional_guarded_and_named)
print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILURE(S)'}")
sys.exit(1 if fails else 0)


def t6_peer_fallback_fully_verified():
    # peer bodies are only trustable with the anti-fork invariant recomputed per block: own-anchor
    # linkage + block_content_hash == declared hash + own-finality bound. And the ring stores hashes
    # as INTS — the anchor must be hex-formatted or the batch URL silently matches nothing.
    pb = _SRC[_SRC.index("async def _peer_batch"):_SRC.index("async def tail_loop")]
    assert "block_content_hash(b) != b.get" in pb or "block_content_hash(b) == b" in pb.replace("!=","=="), \
        "peer blocks must have their content hash RECOMPUTED"
    assert 'b.get("parent_hash") != expect' in pb, "peer batch must chain from OUR anchor"
    assert '> finalized' in pb, "peer batch must respect our own finality bound"
    tl = _TL
    assert 'format(_ph, "064x")' in tl, "the int-stored ring hash must be hex-formatted for the URL"
    assert "_peer_batch(session, _ph, finalized)" in tl, "peer fallback wired after the local batch"


check("peer fallback: recomputed hashes, own anchor, finality bound, hex anchor", t6_peer_fallback_fully_verified)
