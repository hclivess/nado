"""
Lagging-prefix corroboration for the depth-finality floor (loops/core_loop.py).

THE FREEZE (2026-08-19, 2.5 h live): _depth_floor_corroborated requires holding a peer's advertised
tip block, but a node that is merely SLOW on the canonical chain never holds anyone's current tip —
every peer is ahead. Every heavier claim became an "unanswerable" veto, no advertised hash was held,
and the floor froze at 81242 across restarts while the tip followed the fleet — starving the exec
layer (which caps at finalized) and blocking the settlement healing. Fix: a SIGNED peer claim that
its hash at OUR height equals OUR tip hash proves our chain is a strict prefix of the peer's heavier
one. A forker's hash at our height differs, so nothing a minority fork or clique could not already
do is newly possible.

  1. pins: veto path consults _extends_us before freezing; the lagging fallback probes the heaviest
     few; probes are budget-capped per pass and ride the 90s memo (the 2026-08-18 probe-storm lesson)
  2. behavioral: _extends_us matches/rejects/budget-stops on a stub (no network, no full node)

Run: python3 tests/test_depth_floor_prefix_corroboration.py
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
                         "loops", "core_loop.py")).read()


def t1_pins():
    fn = _SRC[_SRC.index("def _depth_floor_corroborated"):_SRC.index("def _fork_state")]
    v = fn.index("_t is None or not majority_on_our_canonical")
    assert "_extends_us(_peer, _budget)" in fn[v:v + 300], \
        "an unanswerable heavier claim must consult the prefix probe before vetoing"
    assert fn.index("_budget = [4]") < v, "probe budget must exist before the veto loop"
    assert fn.rindex("_extends_us(_peer, _budget)") > fn.index("return True"), \
        "the lagging fallback must probe after the held-hash loop fails"
    ex = _SRC[_SRC.index("def _extends_us"):]
    ex = ex[:ex.index("\n    def ")]
    assert "_memo_probe(peer, our_h, our_h)" in ex, "must ride the 90s fork-verdict memo"
    assert "budget[0] <= 0" in ex and "budget[0] -= 1" in ex, "new probes must be budget-capped"
    assert "h == our_hash" in ex, "corroboration = the peer's signed hash at OUR height equals OUR tip"


def t2_behavioral():
    from loops.core_loop import CoreClient
    class Stub:
        _extends_us = CoreClient._extends_us
        def __init__(self, answers):
            self.memserver = type("M", (), {"latest_block": {"block_number": 100, "block_hash": "H100"}})()
            self._answers = answers
            self._probe_memo = (0.0, {})
            self.probes = 0
        def _memo_probe(self, peer, h, tip):
            self.probes += 1
            return self._answers.get(peer, (None, 0))
    s = Stub({"a": ("H100", 3), "b": ("FORK", 0)})
    assert s._extends_us("a", [4]) is True, "matching signed hash at our height corroborates"
    assert s._extends_us("b", [4]) is False, "a forker's hash at our height must not corroborate"
    assert s._extends_us("c", [4]) is False, "no/failed claim must not corroborate"
    b = [0]
    assert s._extends_us("a", b) is False, "exhausted budget answers False (freeze one pass, safe)"
    # cached memo entries bypass the budget
    s2 = Stub({"a": ("H100", 3)})
    s2._probe_memo = (0.0, {("a", 100): ("H100", 3)})
    assert s2._extends_us("a", [0]) is True, "memoized answers are free — no budget needed"


check("pins: veto consults prefix probe; fallback probes heaviest; budgeted + memoized", t1_pins)
check("behavioral: match / fork-reject / budget-stop / memo-free", t2_behavioral)
print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILURE(S)'}")
sys.exit(1 if fails else 0)
