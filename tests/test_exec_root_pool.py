"""
Exec root pool — the L1 hash-pool pattern for the exec layer (execnode/execnode.py + state.py).

THE GAP THIS CLOSES (user diagnosis, 2026-08-19): the L1 never trusts its own hash in isolation —
it constantly compares against every peer's hash pool and alarms on "outside majority". The exec
layer shipped with NO cross-node comparison at all: each node computed its root in a vacuum, and
three attesters ran divergent for 12k+ cursors with no node ever noticing. Settle cursors are
batch-staggered and never comparable; EPOCH-BOUNDARY cursors are hit identically by every node —
those are the pool's comparison points.

  1. behavioral: boundary_roots ring — record at k*EPOCH_LENGTH, bounded, persisted, root-neutral
  2. pins: recorded after the boundary block applies; /exec/roots serves the ring; the probe
     compares at the newest SHARED boundary and CRITICAL-logs "out of majority"; probe wired+throttled

Run: python3 tests/test_exec_root_pool.py
"""
import os, sys, tempfile, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState

fails = 0
def check(name, fn):
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()

_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "execnode", "execnode.py")).read()


def t1_ring_persisted_and_root_neutral():
    st = ExecState(tempfile.mktemp(prefix="nado_rootpool_", suffix=".json"))
    st.bridge["x"] = 1
    st._touch()
    r0 = st.state_root()
    st.boundary_roots = {60: "aa" * 32, 120: "bb" * 32}
    assert st.state_root() == r0, "boundary_roots must NOT enter the state root (it MIRRORS the root)"
    st.save()
    st2 = ExecState(st.path)
    assert st2.boundary_roots == {60: "aa" * 32, 120: "bb" * 32}
    assert all(isinstance(k, int) for k in st2.boundary_roots)


def t2_pin_recording_site():
    tl = _SRC[_SRC.index("async def tail_loop"):]
    i = tl.index("boundary_roots[_st.cursor] = _st.state_root()")
    assert tl.index("_apply_block(session, states, state, block") < i, \
        "boundary root must be recorded AFTER the boundary block applies"
    seg = tl[max(0, i - 400):i + 400]
    assert "% _EPOCH_LENGTH == 0" in seg and "[:-32]" in seg, "epoch-aligned + bounded ring"


def t3_pin_endpoint_and_probe():
    assert 'web.get("/exec/roots", h_roots)' in _SRC
    h = _SRC[_SRC.index("async def h_roots"):]
    h = h[:h.index("\nasync def ")]
    assert "boundary_roots" in h and "cursor" in h
    p = _SRC[_SRC.index("async def _root_pool_probe"):_SRC.index("async def tail_loop")]
    assert "EXEC ROOT OUT OF MAJORITY" in p and "CRITICAL" in p
    assert "max(shared)" in p, "compare at the NEWEST shared boundary"
    assert "len(best) * 2 > total" in p, "majority = strictly more than half of respondents"
    tl = _SRC[_SRC.index("async def tail_loop"):]
    assert "_root_pool_probe(session)" in tl and "ROOT_POOL_EVERY" in tl, "probe wired + throttled"


check("boundary ring persisted, int keys, root-neutral", t1_ring_persisted_and_root_neutral)
check("pin: recorded after apply, epoch-aligned, bounded", t2_pin_recording_site)
check("pin: /exec/roots + out-of-majority CRITICAL probe wired", t3_pin_endpoint_and_probe)
print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILURE(S)'}")
sys.exit(1 if fails else 0)
