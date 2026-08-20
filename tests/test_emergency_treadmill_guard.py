"""Source pins for the emergency-loop TREADMILL EXIT (2026-08-20).

The emergency loop's only exit used to require momentarily holding the exact heaviest
ADVERTISED tip; each pass costs a knows_block RTT + fetch + verify, so on a live chain the
check re-fails by 1-2 blocks forever — measured 7h20m continuously in emergency while the
node applied at chain speed, casting NO FFG duty votes and GIL-starving the API event loop
(which froze the exec tail behind it). The guard exits on a clean-prefix BEHIND verdict
within EMERGENCY_EXIT_LAG blocks of the advertised tip and restarts the minority grace
window. Fork evidence must NEVER take this exit."""

import os

_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "loops", "core_loop.py")).read()
_EM = _SRC[_SRC.index("def emergency_mode"):]


def t1_guard_exists_inside_emergency_loop():
    assert "EMERGENCY_EXIT_LAG = 2" in _SRC, "the lag constant must exist (and stay small)"
    i = _EM.index("treadmill guard")
    seg = _EM[max(0, i - 3000):i + 500]
    assert "vstate == fork_resolution.BEHIND" in seg, \
        "ONLY a BEHIND verdict may take the treadmill exit (REORG/DEAD_FORK/UNKNOWN never)"
    assert "int(_anc) >= _ours_n" in seg, \
        "the exit requires our tip ON the majority chain (clean prefix — nothing to roll back)"
    assert "int(_hn) - _ours_n <= EMERGENCY_EXIT_LAG" in seg, \
        "the exit is bounded by the advertised-tip lag"
    assert "force_sync_ip" in seg, "operator force-sync must never be short-circuited"


def t2_guard_restarts_grace_window():
    i = _EM.index("treadmill guard")
    seg = _EM[max(0, i - 3000):i + 500]
    assert "self._minority_since = get_timestamp_seconds()" in seg, \
        "leaving must restart the grace window, or check_mode re-enters emergency on the next pass"
    assert seg.rstrip().endswith("break") or "break" in _EM[i:i + 300], \
        "the guard must BREAK out of the emergency loop"


def t3_guard_sits_before_fork_actions():
    g = _EM.index("treadmill guard")
    assert g < _EM.index("_adopt_branch(_anc)"), \
        "the guard must be evaluated before any adoption/rollback action"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted({k: v for k, v in globals().items() if k.startswith("t")}.items()):
        try:
            fn()
            print(f"PASS  {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL  {name}: {e}")
    print("ALL PASS" if not fails else f"{fails} FAILURE(S)")
    raise SystemExit(1 if fails else 0)
