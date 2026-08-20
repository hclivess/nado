"""Foreign-generation veto exemption (2026-08-20): a heavier weight claim from a chain that does
not share OUR block 0 must carry NO veto over the depth-finality floor — fork choice can never
adopt blocks that cannot link to our genesis. Three un-purged reroll stragglers advertising the
old chain's ~9M weight froze betanet-4's floor at 0 from block 1."""
import os

_SRC = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "loops", "core_loop.py")).read()


def t1_veto_loop_filters_foreign_genesis():
    i = _SRC.index("FOREIGN-GENERATION EXEMPTION")
    seg = _SRC[i - 600:i + 900]
    assert "if not self._same_genesis(_peer):" in seg and "continue" in seg, \
        "a foreign-genesis peer must be SKIPPED by the heavier-claim veto"
    k = seg.index("if not self._same_genesis(_peer):")
    assert "self._extends_us(_peer, _budget)" in seg[k:], \
        "the genesis filter must come BEFORE the extends-us veto, not replace it"


def t2_probe_failure_keeps_veto():
    i = _SRC.index("def _same_genesis")
    seg = _SRC[i:i + 1800]
    assert "(_theirs is None) or (_theirs == _ours)" in seg, \
        "an unanswered probe must report SAME genesis (unknown keeps its veto power)"
    assert "same = True" in seg, "an exception must default to same-genesis (freeze-safe)"
    assert "600.0" in seg, "memoized with a TTL so a purged straggler regains standing"


if __name__ == "__main__":
    fails = 0
    for name in ("t1_veto_loop_filters_foreign_genesis", "t2_probe_failure_keeps_veto"):
        try:
            globals()[name]()
            print(f"PASS  {name}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL  {name}: {e}")
    print("ALL PASS" if not fails else f"{fails} FAILURE(S)")
    raise SystemExit(1 if fails else 0)
